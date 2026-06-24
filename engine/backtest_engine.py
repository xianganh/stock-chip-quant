"""
回测引擎 — 事件驱动时序回测
基于筹码快照数据库，对单只股票的历史信号进行回测验证
"""
import json
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

# 添加项目根目录和 scripts 路径
_PROJ_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _PROJ_ROOT)
sys.path.insert(0, os.path.join(_PROJ_ROOT, "scripts"))
from analyze import analyze as chip_analyze
from utils import get_tushare_pro


class BacktestEngine:
    """
    时序事件驱动回测引擎

    用法:
        engine = BacktestEngine(ts_code="000066.SZ", start_date="20250101", end_date="20250622")
        result = engine.run(signal_type="locking", params={"tpc_pctile": 75, "entropy_pctile": 35})
    """

    def __init__(self, ts_code: str, start_date: str = None, end_date: str = None):
        self.ts_code = ts_code
        self.start_date = start_date or "20200101"
        self.end_date = end_date or datetime.now().strftime("%Y%m%d")
        self.price_data = None
        self.signal_cache = {}

    def load_price_data(self):
        """从 Tushare 拉取历史价格数据"""
        pro = get_tushare_pro()

        df = pro.daily(ts_code=self.ts_code, start_date=self.start_date, end_date=self.end_date,
                       fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg")
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["close"] = df["close"].astype(float)
        self.price_data = df
        return df

    def _compute_signal_daily(self, date: str, window_days: int = 14,
                               signal_type: str = "locking",
                               params: dict = None) -> Optional[dict]:
        """
        对指定日期运行筹码分析并提取信号

        signal_type: "locking" | "divergence" | "dispatch" | "build_divergence"
        """
        cache_key = f"{date}_{signal_type}_{json.dumps(params or {})}"
        if cache_key in self.signal_cache:
            return self.signal_cache[cache_key]

        try:
            result = chip_analyze(self.ts_code, days=window_days, end_date=date)
        except Exception as e:
            self.signal_cache[cache_key] = None
            return None

        signal = {"date": date, "close": 0, "signal": False, "strength": 0}

        # 获取当日价格
        if self.price_data is not None:
            row = self.price_data[self.price_data["trade_date"] == date]
            if len(row) > 0:
                signal["close"] = float(row.iloc[0]["close"])

        params = params or {}

        if signal_type == "locking":
            # 锁仓信号: 强锁仓 (>=5/6)
            locking = result.get("chip_evolution", {}).get("locking_assessment", {})
            score_str = locking.get("locked_score", "0/6")
            passed = int(score_str.split("/")[0]) if "/" in score_str else 0
            signal["signal"] = passed >= (params.get("min_conditions", 5))
            signal["strength"] = passed / 6

        elif signal_type == "divergence":
            # 背离信号
            div = result.get("divergence_signals", {})
            total_score = div.get("total_score", 0)
            threshold = params.get("divergence_threshold", 40)
            signal["signal"] = total_score >= threshold
            signal["strength"] = total_score / 100

        elif signal_type == "build_divergence":
            # 暗中建仓: 价格-筹码背离
            div = result.get("divergence_signals", {})
            pc_div = div.get("signals", {}).get("price_chip_divergence", {})
            signal["signal"] = pc_div.get("active", False)
            signal["strength"] = pc_div.get("score", 0) / 100

        elif signal_type == "dispatch":
            # 派发预警
            dispatch = result.get("chip_evolution", {}).get("dispatch_score", {})
            total = dispatch.get("total", 0)
            signal["signal"] = total >= (params.get("min_dispatch_score", 3))
            signal["strength"] = total / 5

        self.signal_cache[cache_key] = signal
        return signal

    def run(self, signal_type: str = "locking", params: dict = None,
            max_holding_days: int = 20, stop_loss_pct: float = -8,
            take_profit_pct: float = 20, window_days: int = 14,
            signal_check_interval: int = 5) -> dict:
        """
        运行回测

        Returns:
            dict with keys: total_trades, win_rate, avg_return, sharpe, max_drawdown,
                            total_return, trades (list)
        """
        if self.price_data is None:
            self.load_price_data()

        df = self.price_data
        if df is None or len(df) < window_days + 5:
            return {"error": "价格数据不足"}

        # ★ 每次 run 清空缓存, 避免进化引擎多轮参数搜索时无限增长
        self.signal_cache.clear()

        trades = []
        holding_until = None  # 持仓到哪一天
        entry_info = None

        for i in range(window_days, len(df)):
            date = str(df.iloc[i]["trade_date"])
            close = float(df.iloc[i]["close"])

            # 如果已持仓，检查是否出场
            if entry_info is not None:
                holding_days = i - entry_info["idx"]
                return_pct = (close - entry_info["price"]) / entry_info["price"] * 100

                # 止损
                if return_pct <= stop_loss_pct:
                    trades.append({
                        "entry_date": entry_info["date"],
                        "exit_date": date,
                        "entry_price": entry_info["price"],
                        "exit_price": close,
                        "return_pct": round(return_pct, 2),
                        "holding_days": holding_days,
                        "signal_type": signal_type,
                        "exit_reason": "stop_loss",
                    })
                    entry_info = None
                    continue

                # 止盈
                if return_pct >= take_profit_pct:
                    trades.append({
                        "entry_date": entry_info["date"],
                        "exit_date": date,
                        "entry_price": entry_info["price"],
                        "exit_price": close,
                        "return_pct": round(return_pct, 2),
                        "holding_days": holding_days,
                        "signal_type": signal_type,
                        "exit_reason": "take_profit",
                    })
                    entry_info = None
                    continue

                # 时间出场
                if holding_days >= max_holding_days:
                    trades.append({
                        "entry_date": entry_info["date"],
                        "exit_date": date,
                        "entry_price": entry_info["price"],
                        "exit_price": close,
                        "return_pct": round(return_pct, 2),
                        "holding_days": holding_days,
                        "signal_type": signal_type,
                        "exit_reason": "time_exit",
                    })
                    entry_info = None
                    continue

                continue  # 继续持仓

            # 未持仓，检测入场信号
            # 按 signal_check_interval 间隔检测（避免过度交易+节省API调用）
            if i % signal_check_interval != 0:
                continue

            signal = self._compute_signal_daily(date, window_days, signal_type, params)
            if signal and signal.get("signal"):
                entry_info = {
                    "idx": i,
                    "date": date,
                    "price": close,
                }

        # 如果在回测结束时仍持仓，强制平仓
        if entry_info is not None:
            last_date  = str(df.iloc[-1]["trade_date"])
            last_close = float(df.iloc[-1]["close"])
            holding_days = len(df) - 1 - entry_info["idx"]
            return_pct = (last_close - entry_info["price"]) / entry_info["price"] * 100
            trades.append({
                "entry_date": entry_info["date"],
                "exit_date": last_date,
                "entry_price": entry_info["price"],
                "exit_price": last_close,
                "return_pct": round(return_pct, 2),
                "holding_days": holding_days,
                "signal_type": signal_type,
                "exit_reason": "force_close",
            })

        # ── 统计 ──
        if not trades:
            return {
                "total_trades": 0, "win_rate": 0, "avg_return": 0,
                "max_return": 0, "min_return": 0, "sharpe": 0,
                "max_drawdown": 0, "total_return": 0, "trades": []
            }

        returns = [t["return_pct"] for t in trades]
        wins   = [r for r in returns if r > 0]
        total_trades = len(trades)
        win_rate     = round(len(wins) / total_trades * 100, 1)
        avg_return   = round(np.mean(returns), 2)
        max_return   = round(max(returns), 2)
        min_return   = round(min(returns), 2)
        total_return = round(sum(returns), 2)

        # Sharpe (简化: 无风险利率=0)
        std_ret = np.std(returns) if len(returns) > 1 else 1
        sharpe = round(avg_return / std_ret * np.sqrt(252 / max_holding_days), 2) if std_ret > 0 else 0

        # Max drawdown (基于逐笔收益的累计)
        cum_returns = np.cumsum(returns)
        peak = np.maximum.accumulate(cum_returns)
        drawdown = peak - cum_returns
        max_drawdown = round(float(np.max(drawdown)), 2)

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_return": avg_return,
            "max_return": max_return,
            "min_return": min_return,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "total_return": total_return,
            "trades": trades,
        }
