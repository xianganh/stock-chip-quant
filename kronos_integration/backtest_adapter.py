"""
Kronos × 筹码峰演化分析 — 批量回测对比适配器

直接嵌入你现有工作流：
    1. 拉取某只股票的完整筹码+K线数据（你已有 chip_data_fetcher）
    2. 逐交易日计算：Kronos预测 + 筹码健康度 → 融合信号
    3. 对比：纯筹码策略 vs 融合策略 的收益率
    4. 把结果回写给 EvolutionEngine 作为新型 signal_type
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime

_sys_path_fix = os.path.join(os.path.dirname(__file__), "..")
if _sys_path_fix not in sys.path:
    sys.path.insert(0, _sys_path_fix)

from kronos_integration import KronosChipFuser


class KronosChipBacktestAdapter:
    """
    把 Kronos 融合器嵌入到你现有回测管线的适配器

    典型用法:
        adapter = KronosChipBacktestAdapter("603002.SH")
        result = adapter.run_comparison(start_date="20260302", end_date="20260624")
        print("纯筹码策略收益:", result["chip_only_return"])
        print("融合策略收益:  ", result["fused_return"])
    """

    def __init__(self, ts_code: str, model_name: str = "NeoQuasar/Kronos-mini"):
        self.ts_code = ts_code
        self.fuser = KronosChipFuser(model_name=model_name, chip_weight=0.70, kronos_weight=0.30)
        self.df_complete = None  # 会在 prepare() 中填充

    # ------------------------------------------------------------------
    # 数据准备 — 直接复用你已写好的模块
    # ------------------------------------------------------------------
    def prepare(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        拉取完整数据：K线 + 筹码指标 + 筹码健康度评分
        完全复用你的现有模块，不需要重复发明轮子
        """
        from chip_data_fetcher import fetch_complete_data
        from chip_indicators import analyze_chip_health, compute_chip_metrics

        print(f"[Adapter] 正在拉取 {self.ts_code} 数据: {start_date} ~ {end_date} ...")

        # 1) 你的数据获取模块（已验证可用）
        data = fetch_complete_data(self.ts_code, start_date, end_date)
        if data is None or len(data) == 0:
            raise RuntimeError(f"无法获取 {self.ts_code} 数据")

        rows = []
        trade_dates = sorted(data.keys())

        for i, date in enumerate(trade_dates):
            day = data[date]
            close = day["daily"]["close"] if "daily" in day else None

            # 2) 你的筹码指标计算（23+项）
            metrics = compute_chip_metrics(day.get("chip_df"), close)
            if metrics is None:
                continue

            # 3) 你的健康度评分（-4 ~ +9）
            prev_metrics = None
            if i >= 3:
                prev_date = trade_dates[i - 3]
                prev_day = data.get(prev_date, {})
                prev_close = prev_day.get("daily", {}).get("close")
                prev_chip = prev_day.get("chip_df")
                if prev_close and prev_chip is not None:
                    prev_metrics = compute_chip_metrics(prev_chip, prev_close)

            health = analyze_chip_health(metrics, prev_metrics)
            chip_score = health.get("score", 0) if health else 0

            # 4) 计算未来10日收益率（用于回测评估）
            future_ret = None
            if i + 10 < len(trade_dates):
                future_close = data[trade_dates[i + 10]]["daily"]["close"]
                if close and close > 0:
                    future_ret = round((future_close - close) / close * 100, 2)

            rows.append({
                "trade_date": date,
                "open": day["daily"].get("open"),
                "high": day["daily"].get("high"),
                "low": day["daily"].get("low"),
                "close": close,
                "volume": day["daily"].get("vol"),
                **metrics,                 # 23+ 项筹码指标
                "chip_score": chip_score,  # 你的筹码健康度 -4~9
                "future_10d_return": future_ret,
            })

        self.df_complete = pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)
        print(f"[Adapter] 数据准备完成 ✓ 共 {len(self.df_complete)} 个交易日")
        return self.df_complete

    # ------------------------------------------------------------------
    # 对比回测 — 核心逻辑
    # ------------------------------------------------------------------
    def run_comparison(self, start_date: str, end_date: str,
                       initial_capital: float = 100000.0) -> Dict:
        """
        对比两种策略：
            A) 纯筹码策略：仅用 chip_score 判断买卖
            B) 融合策略：筹码 + Kronos 贝叶斯融合

        规则（与你现有持仓管理兼容）：
            买入：chip_score >= 5  或  fused_score >= 68
            卖出：chip_score <= -2 或  fused_score <= 30
            持仓：否则持有现金或股票
            最大持仓天数：30
        """
        df = self.prepare(start_date, end_date)

        # --- 逐交易日计算 Kronos 预测 + 融合信号 ---
        fused_scores = []
        signals = []
        kronos_preds = []

        OHLCV_COLS = ['open', 'high', 'low', 'close', 'volume']
        for i, row in df.iterrows():
            # 取 i 天之前（含i）的历史给 Kronos（不能用未来数据！）
            hist_df = df.loc[:i, OHLCV_COLS].copy()
            kr = self.fuser.kronos_predict(
                hist_df, horizon=10, sample_count=5
            )
            kronos_preds.append(kr)

            fused = self.fuser.bayesian_fusion(row["chip_score"], kr)
            fused_scores.append(fused["fused_score"])
            signals.append(fused["signal"])

        df = df.assign(
            kronos_bull_prob=[p["bull_prob"] if p else None for p in kronos_preds],
            kronos_mean_ret=[p["mean_10d_return"] if p else None for p in kronos_preds],
            fused_score=fused_scores,
            fused_signal=signals,
        )

        # --- 模拟交易：策略A 纯筹码 vs 策略B 融合 ---
        def simulate(strategy_name: str, buy_cond, sell_cond):
            capital = initial_capital
            shares = 0
            position = 0  # 0 空仓 / 1 持仓
            cost = 0
            trades = []
            equity_curve = []
            hold_days = 0

            for i, (_, row) in enumerate(df.iterrows()):
                price = float(row["close"])
                if position == 0 and buy_cond(row, i):
                    # 全仓买入
                    shares = int(capital / price / 100) * 100  # 整手
                    if shares > 0:
                        cost = price * shares
                        capital -= cost
                        position = 1
                        hold_days = 0
                        trades.append({
                            "date": row["trade_date"],
                            "action": "BUY",
                            "price": price,
                            "shares": shares,
                            strategy: strategy_name,
                        })
                elif position == 1:
                    hold_days += 1
                    force_sell = sell_cond(row) or hold_days >= 30
                    stop_loss = (price * shares / cost - 1) < -0.08
                    if force_sell or stop_loss:
                        capital += price * shares
                        trades.append({
                            "date": row["trade_date"],
                            "action": "SELL",
                            "price": price,
                            "shares": shares,
                            "profit_pct": round((price / (cost / shares) - 1) * 100, 2),
                            "hold_days": hold_days,
                        })
                        shares = 0
                        position = 0
                        cost = 0
                        hold_days = 0

                total_val = capital + shares * price
                equity_curve.append(total_val)

            # 清算
            if position == 1 and shares > 0:
                capital += shares * df.iloc[-1]["close"]
                shares = 0
                position = 0

            total_return = round((capital - initial_capital) / initial_capital * 100, 2)
            win_trades = [t for t in trades if t.get("profit_pct", 0) > 0]
            win_rate = round(len(win_trades) / max(1, len([t for t in trades if t["action"] == "SELL"])) * 100, 1) if trades else 0

            return {
                "final_capital": round(capital, 2),
                "total_return": total_return,
                "win_rate": win_rate,
                "trade_count": len([t for t in trades if t["action"] == "BUY"]),
                "trades": trades[-10:],  # 最后10笔
                "equity_curve": equity_curve,
            }

        # 策略A：纯筹码
        strat_a = simulate(
            "CHIP_ONLY",
            buy_cond=lambda r, i: r["chip_score"] >= 5,
            sell_cond=lambda r: r["chip_score"] <= -2,
        )

        # 策略B：融合（多了一个 Kronos 过滤）
        strat_b = simulate(
            "FUSED",
            buy_cond=lambda r, i: (
                # 融合信号要求更高：筹码≥3 且 融合分≥68，
                # 或者融合≥80 即使筹码稍弱也买（捕捉 Kronos 提前发现的机会）
                (r["chip_score"] >= 3 and r["fused_score"] >= 68)
                or (r["fused_score"] >= 80)
            ),
            sell_cond=lambda r: (
                # 任何一方发出卖出信号就减仓（严格风控）
                r["chip_score"] <= -1
                or r["fused_score"] <= 35
            ),
        )

        # --- 买入持有基准 ---
        if len(df) >= 2:
            first_p = float(df.iloc[0]["close"])
            last_p = float(df.iloc[-1]["close"])
            buy_hold = round((last_p - first_p) / first_p * 100, 2)
        else:
            buy_hold = 0.0

        return {
            "ts_code": self.ts_code,
            "period": f"{start_date} ~ {end_date}",
            "trading_days": len(df),
            "buy_hold_return": buy_hold,
            "chip_only": strat_a,
            "fused": strat_b,
            "excess_return": round(strat_b["total_return"] - strat_a["total_return"], 2),
            "df_annotated": df,  # 带融合信号的完整DataFrame，供画图用
        }

    # ------------------------------------------------------------------
    # 辅助：把结果导出给你的 EvolutionEngine 作为新信号类型
    # ------------------------------------------------------------------
    def register_signal_to_evolution_engine(self, result: Dict):
        """
        把融合信号的 df_annotated 转成 EvolutionEngine 支持的 signal_type='kronos_fused'
        这样你的参数进化框架就可以自动优化：
            - chip_weight / kronos_weight 权重组合
            - 买入阈值 fused_score >= X
            - 卖出阈值 fused_score <= Y
        """
        df = result["df_annotated"]
        # 给 df 加上一个列作为新信号，供 engine 使用
        df["kronos_fused_buy"] = df["fused_score"] >= 68
        df["kronos_fused_sell"] = df["fused_score"] <= 30
        return df


# ----------------------------------------------------------------------
# 命令行入口：直接对宏昌电子跑一次对比
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print(f"Kronos×筹码峰 策略对比 — 宏昌电子 603002.SH")
    print("=" * 70)

    adapter = KronosChipBacktestAdapter("603002.SH", model_name="NeoQuasar/Kronos-mini")
    result = adapter.run_comparison(start_date="20260302", end_date="20260624")

    print(f"\n回测区间: {result['period']}  ({result['trading_days']}个交易日)")
    print(f"买入持有基准收益: {result['buy_hold_return']:+.2f}%")
    print("-" * 50)
    print("策略A: 纯筹码信号")
    print(f"  最终资金: ¥{result['chip_only']['final_capital']:,.2f}")
    print(f"  总收益:   {result['chip_only']['total_return']:+.2f}%")
    print(f"  胜率:     {result['chip_only']['win_rate']:.1f}%")
    print(f"  交易次数: {result['chip_only']['trade_count']} 次")
    print("-" * 50)
    print("策略B: 筹码 + Kronos 融合")
    print(f"  最终资金: ¥{result['fused']['final_capital']:,.2f}")
    print(f"  总收益:   {result['fused']['total_return']:+.2f}%")
    print(f"  胜率:     {result['fused']['win_rate']:.1f}%")
    print(f"  交易次数: {result['fused']['trade_count']} 次")
    print("-" * 50)
    print(f"融合策略超额收益: {result['excess_return']:+.2f}%")
    if result['excess_return'] > 0:
        print("✅ Kronos 融合产生了正向增强效果！")
    else:
        print("⚠️  融合效果不佳或等于纯筹码，建议：")
        print("   - 降低 kronos_weight（比如 0.15）")
        print("   - 提高 chip_weight（比如 0.85）")
        print("   - 或者等后续用 A 股数据微调 Kronos 后再启用")

    # 保存结果
    save_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "kronos_chip_comparison.json"
    )
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    # 去掉巨大的 df 只存统计
    export = {k: v for k, v in result.items() if k != "df_annotated"}
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n详细结果已保存: {save_path}")
