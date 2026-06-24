"""
ReplayEngine — 算法信号回放引擎 (Phase 3 v2 - 性能优化版)

性能优化：
- 每只股票只拉一次 Tushare 全量数据
- 内存切片 + 离线计算每日信号
- 缓存避免重复计算
- 性能：~3s/position（vs 旧版 ~30s/position）

对历史 position 逐日重算算法判断，存到 Position.algorithm_signal / trade_log.algorithm_signal
用于验证算法在历史数据上的有效性，找出不适用的指标和需要调整的阈值。

用法:
    from engine.replay_engine import ReplayEngine
    engine = ReplayEngine()
    result = engine.replay_position(ts_code="603773.SH", entry_date="20260522", exit_date="20260612")
    print(result.summary())
"""
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from typing import Optional

warnings.filterwarnings('ignore')

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

import pandas as pd
import numpy as np

from utils import get_tushare_pro, compute_verdict

# 复用 analyze.py 中的纯计算函数（不调 API）
from scripts.analyze import (
    compute_chip_metrics,
    compute_rolling_percentile,
    build_chip_percentile_context,
    assess_locking,
    dispatch_score,
    score_tech,
    detect_divergence,
    compute_cmf, compute_adx, compute_atr,
    _build_narrative,
)


class ReplayResult:
    """单笔回放的结果"""

    def __init__(self, ts_code, entry_date, exit_date=None, account="", name=""):
        self.ts_code = ts_code
        self.name = name or ts_code
        self.account = account
        self.entry_date = entry_date
        self.exit_date = exit_date or ""
        # 逐日信号: {date: {verdict, confidence, ...}}
        self.daily_signals = {}
        # 整体结果
        self.entry_signal = None
        self.exit_signal = None
        # 偏差统计
        self.actual_pnl_pct = None  # 实际盈亏（需要从外部注入）
        # 性能
        self.preload_seconds = 0
        self.calc_seconds = 0
        # 错误
        self.errors = []

    def add_daily_signal(self, date, signal):
        self.daily_signals[date] = signal
        if date == self.entry_date:
            self.entry_signal = signal
        if self.exit_date and date == self.exit_date:
            self.exit_signal = signal

    def set_actual_pnl(self, pnl_pct):
        """注入实际盈亏，用于偏差分析"""
        self.actual_pnl_pct = pnl_pct

    @property
    def holding_days(self):
        return len(self.daily_signals)

    def get_action_distribution(self):
        """统计每日 action 分布"""
        dist = {}
        for sig in self.daily_signals.values():
            if "action" in sig:
                action = sig["action"]
                dist[action] = dist.get(action, 0) + 1
        return dist

    def compute_deviation(self):
        """
        计算算法 vs 实际的偏差

        Returns:
            {
              "actual_pnl_pct": float,
              "entry_action": str,
              "entry_confidence": int,
              "action_distribution": dict,
              "verdict": "algorithmic_agree" | "algorithmic_warn" | "data_insufficient"
            }
        """
        if self.actual_pnl_pct is None:
            return {"verdict": "no_actual_data"}

        dist = self.get_action_distribution()
        entry_action = self.entry_signal.get("action", "?") if self.entry_signal else "?"

        # 算法预测 vs 实际结果
        pnl = self.actual_pnl_pct
        if pnl > 2:
            actual_outcome = "盈利"
        elif pnl < -2:
            actual_outcome = "亏损"
        else:
            actual_outcome = "持平"

        # 算法是否一致
        if entry_action == "持有" and actual_outcome == "盈利":
            verdict = "algorithmic_agree"
        elif entry_action in ("减仓", "清仓") and actual_outcome == "亏损":
            verdict = "algorithmic_warn"
        elif entry_action == "观望" and self.holding_days < 3:
            verdict = "data_insufficient"
        else:
            verdict = "algorithmic_disagree"

        return {
            "actual_pnl_pct": pnl,
            "actual_outcome": actual_outcome,
            "entry_action": entry_action,
            "entry_confidence": self.entry_signal.get("confidence", 0) if self.entry_signal else 0,
            "action_distribution": dist,
            "verdict": verdict,
        }

    def summary(self):
        """生成可读的总结"""
        lines = [
            f"=== Replay Result ===",
            f"Position: {self.ts_code} ({self.name}) | {self.account}",
            f"Period:   {self.entry_date} ~ {self.exit_date or '(active)'}",
            f"Days:     {self.holding_days} | preload: {self.preload_seconds:.1f}s | calc: {self.calc_seconds:.1f}s",
        ]
        if self.entry_signal:
            lines.append(f"\n[Entry Day Signal: {self.entry_date}]")
            lines.append(f"  Action:     {self.entry_signal.get('action')}")
            lines.append(f"  Confidence: {self.entry_signal.get('confidence')}%")
            lines.append(f"  Color:      {self.entry_signal.get('color')}")
            for r in self.entry_signal.get("reasons", [])[:3]:
                lines.append(f"  - {r}")

        if self.exit_signal:
            lines.append(f"\n[Exit Day Signal: {self.exit_date}]")
            lines.append(f"  Action:     {self.exit_signal.get('action')}")
            lines.append(f"  Confidence: {self.exit_signal.get('confidence')}%")
            for r in self.exit_signal.get("reasons", [])[:3]:
                lines.append(f"  - {r}")

        # 持有期间的逐日信号表
        valid_sigs = [(d, s) for d, s in self.daily_signals.items()
                      if "action" in s and d != self.entry_date and d != self.exit_date]
        if valid_sigs:
            lines.append(f"\n[Holding Period Signals ({len(valid_sigs)} days)]")
            lines.append(f"  {'Date':<10} {'Action':<8} {'Conf':<5} {'Lock':<7} {'Disp':<5} {'TPC':<6} {'Color'}")
            for date, sig in sorted(valid_sigs):
                scores = sig.get("scores", {})
                lock_tuple = scores.get("lock", [0, 6])
                lock = f"{lock_tuple[0]}/{lock_tuple[1]}"
                disp = scores.get("dispatch", 0)
                tpc = scores.get("tpc", 0)
                color = sig.get("color", "?")
                lines.append(
                    f"  {date:<10} {sig['action']:<8} {sig['confidence']:<5} "
                    f"{lock:<7} {disp:<5} {tpc:<6.1f} {color}"
                )

        # 偏差分析
        deviation = self.compute_deviation()
        if deviation.get("verdict") not in (None, "no_actual_data"):
            lines.append(f"\n[Deviation Analysis]")
            lines.append(f"  Actual PnL:     {self.actual_pnl_pct:+.2f}%")
            lines.append(f"  Outcome:        {deviation.get('actual_outcome')}")
            lines.append(f"  Entry Action:   {deviation.get('entry_action')}")
            lines.append(f"  Algorithm:      {deviation.get('verdict')}")
            lines.append(f"  Action Dist:    {deviation.get('action_distribution')}")

        if self.errors:
            lines.append(f"\n[Errors ({len(self.errors)})]")
            for e in self.errors[:5]:
                lines.append(f"  - {e}")

        return "\n".join(lines)


class ReplayEngine:
    """算法信号回放引擎 (v2 性能优化版)"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        # 缓存: ts_code -> {df_chips, df_factor, df_mf, df_basic, df_merged, ts_code}
        self._data_cache = {}
        # 性能统计
        self.stats = {"preload_count": 0, "signal_count": 0, "cache_hits": 0}

    def _log(self, msg):
        if self.verbose:
            print(f"[replay] {msg}", file=sys.stderr)

    def _preload_data(self, ts_code: str, start_date: str, end_date: str):
        """
        预加载一只股票的全量历史数据（一次性拉取）

        Returns:
            dict: {df_chips, df_factor, df_mf, df_basic, df_merged}
        """
        if ts_code in self._data_cache:
            self.stats["cache_hits"] += 1
            return self._data_cache[ts_code]

        t0 = time.time()
        pro = get_tushare_pro()

        # 拉全量筹码分布（不限日期范围）
        df_chips = pro.cyq_chips(ts_code=ts_code, fields='ts_code,trade_date,price,percent')
        self._log(f"  [{ts_code}] cyq_chips: {len(df_chips)} rows")

        # 拉技术指标 + 资金流 + 基本面（限定窗口）
        try:
            df_factor = pro.stk_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception as e:
            self._log(f"  stk_factor failed: {e}")
            df_factor = pd.DataFrame()
        try:
            df_mf = pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            df_mf = pd.DataFrame()
        try:
            df_basic = pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            df_basic = pd.DataFrame()

        # 合并（与 analyze.py 一致）
        df_merged = df_factor.copy() if not df_factor.empty else pd.DataFrame()
        if not df_mf.empty and not df_merged.empty:
            df_merged = df_merged.merge(
                df_mf[['ts_code', 'trade_date', 'net_mf_amount']],
                on=['ts_code', 'trade_date'], how='left', suffixes=('', '_mf')
            )
        if not df_basic.empty and not df_merged.empty:
            df_merged = df_merged.merge(
                df_basic[['ts_code', 'trade_date', 'turnover_rate', 'volume_ratio', 'pe_ttm', 'pb']],
                on=['ts_code', 'trade_date'], how='left', suffixes=('', '_db')
            )
        for col in ['net_mf_amount', 'turnover_rate', 'volume_ratio']:
            if col in df_merged.columns:
                df_merged[col] = df_merged[col].fillna(0)
        if not df_merged.empty:
            df_merged = df_merged.sort_values('trade_date').reset_index(drop=True)

        data = {
            "df_chips": df_chips,
            "df_factor": df_factor,
            "df_mf": df_mf,
            "df_basic": df_basic,
            "df_merged": df_merged,
        }
        self._data_cache[ts_code] = data
        self.stats["preload_count"] += 1
        elapsed = time.time() - t0
        self._log(f"  [{ts_code}] preload done in {elapsed:.2f}s")
        return data

    def _local_analyze(self, ts_code: str, end_date: str, days: int = 14) -> Optional[dict]:
        """
        基于预加载数据，离线计算某日的完整分析结果

        复用 analyze.py 的所有核心计算函数，但跳过 Tushare 调用
        """
        data = self._data_cache.get(ts_code)
        if not data:
            return None

        df_chips = data["df_chips"]
        df_merged = data["df_merged"]
        df_factor = data["df_factor"]

        if df_chips.empty or df_merged.empty:
            return None

        # 确定 chip_dates
        all_chip_dates = sorted(df_chips['trade_date'].astype(str).unique())
        if not all_chip_dates:
            return None

        # 找 <= end_date 的所有 chip_dates
        valid_dates = [d for d in all_chip_dates if d <= end_date]
        if len(valid_dates) < days:
            return {"error": f"数据不足: 需要{days}天，只有{len(valid_dates)}天"}

        recent_dates = valid_dates[-days:]
        recent_set = set(recent_dates)

        # 逐日计算筹码指标（复用 analyze.py 逻辑）
        all_metrics = []
        metrics_list = []
        prev_metrics = None

        for td in valid_dates:
            chip_today = df_chips[df_chips['trade_date'].astype(str) == td]
            kline_row = df_merged[df_merged['trade_date'].astype(str) == td]
            if len(chip_today) < 3 or len(kline_row) == 0:
                continue

            close = float(kline_row.iloc[0]['close'])
            m = compute_chip_metrics(chip_today, close)
            if m is None:
                continue

            kr = kline_row.iloc[0]
            m['date'] = str(td)
            m['open'] = round(float(kr.get('open', 0)), 2)
            m['high'] = round(float(kr.get('high', 0)), 2)
            m['low'] = round(float(kr.get('low', 0)), 2)
            m['close'] = close
            m['pct_change'] = round(float(kr.get('pct_change', 0)), 2)
            m['volume'] = int(kr.get('vol', 0) or 0)
            m['amount'] = round(float(kr.get('amount', 0) or 0), 0)
            m['turnover_rate'] = round(float(kr.get('turnover_rate', 0) or 0), 2)
            m['volume_ratio'] = round(float(kr.get('volume_ratio', 1) or 1), 2)
            m['net_mf_amount'] = round(float(kr.get('net_mf_amount', 0) or 0), 0)
            m['pe_ttm'] = float(kr.get('pe_ttm', 0) or 0)
            m['pb'] = float(kr.get('pb', 0) or 0)

            all_metrics.append(m)
            if td in recent_set:
                # 加 emoji 标注（简化版，跳过以提速）
                metrics_list.append(m)
                prev_metrics = m

        if len(metrics_list) < 3:
            return {"error": "有效筹码数据不足"}

        # 8 大引擎（简化版只算 verdict 必需的）
        # 1. 经典量化指标
        if not df_factor.empty:
            fct = df_factor[df_factor['trade_date'].astype(str) <= end_date].tail(50)
            if len(fct) >= 5:
                arr_h = fct['high'].values
                arr_l = fct['low'].values
                arr_c = fct['close'].values
                arr_v = fct['vol'].values
                cmf_vals = compute_cmf(arr_h, arr_l, arr_c, arr_v, period=21)
                adx_info = compute_adx(arr_h, arr_l, arr_c, period=14)
                atr_vals = compute_atr(arr_h, arr_l, arr_c, period=14)
                latest_cmf = round(float(cmf_vals[-1]), 3) if not np.isnan(cmf_vals[-1]) else None
                latest_adx = round(float(adx_info["adx"][-1]), 2) if not np.isnan(adx_info["adx"][-1]) else None
                latest_pdi = round(float(adx_info["pdi"][-1]), 2) if not np.isnan(adx_info["pdi"][-1]) else None
                latest_mdi = round(float(adx_info["mdi"][-1]), 2) if not np.isnan(adx_info["mdi"][-1]) else None
                latest_atr = round(float(atr_vals[-1]), 2) if not np.isnan(atr_vals[-1]) else None
                atr_pct = round(latest_atr / float(arr_c[-1]) * 100, 2) if latest_atr else None
            else:
                latest_cmf = latest_adx = latest_pdi = latest_mdi = latest_atr = atr_pct = None
        else:
            latest_cmf = latest_adx = latest_pdi = latest_mdi = latest_atr = atr_pct = None

        classic_indicators = {
            "cmf": {"latest": latest_cmf},
            "adx": {"latest_adx": latest_adx, "latest_pdi": latest_pdi, "latest_mdi": latest_mdi},
            "atr": {"latest": latest_atr, "atr_pct_of_price": atr_pct},
        }

        # 2. 分位数
        try:
            pct_context = build_chip_percentile_context(all_metrics, metrics_list)
        except Exception:
            pct_context = {"metrics_percentiles": {}, "latest_z_scores": {}}

        # 3. 锁仓
        try:
            locking = assess_locking(metrics_list)
        except Exception as e:
            locking = {"locked_score": "0/6", "overall": "数据不足", "verdict": ""}

        # 4. 派发
        try:
            dispatch = dispatch_score(metrics_list)
        except Exception:
            dispatch = {"total": 0, "verdict": "数据不足"}

        # 5. 背离
        try:
            divergence = detect_divergence(metrics_list, pct_context, classic_indicators)
        except Exception:
            divergence = {"active_count": 0, "strong_count": 0, "total_score": 0, "verdict": "无"}

        # 6. 计算 verdict
        result = {
            "meta": {
                "ts_code": ts_code,
                "trade_days": len(metrics_list),
                "date_range": f"{metrics_list[0]['date']} ~ {metrics_list[-1]['date']}",
                "end_date": end_date,
            },
            "chip_evolution": {
                "daily_records": metrics_list,
                "locking_assessment": locking,
                "dispatch_score": dispatch,
            },
            "classic_indicators": classic_indicators,
            "chip_factor_ranks": pct_context,
            "divergence_signals": divergence,
        }

        try:
            verdict = compute_verdict(result)
            return verdict
        except Exception as e:
            return {"error": f"compute_verdict failed: {e}"}

    def replay_position(self, ts_code: str, entry_date: str,
                        exit_date: str = None, days_window: int = 14,
                        skip_weekends: bool = True) -> ReplayResult:
        """
        对单个 position 逐日重算算法判断

        性能优化：每只股票只拉一次数据
        """
        result = ReplayResult(ts_code, entry_date, exit_date)

        # 确定时间窗口（向前往前推 60 天以确保有足够数据）
        start_dt = datetime.strptime(entry_date, "%Y%m%d") - timedelta(days=60)
        end_dt_str = exit_date if exit_date else datetime.now().strftime("%Y%m%d")
        start_date = start_dt.strftime("%Y%m%d")

        self._log(f"Replaying {ts_code} [{entry_date} ~ {exit_date or 'now'}]")

        # 1. 预加载数据（一次性 Tushare 调用）
        t0 = time.time()
        data = self._preload_data(ts_code, start_date, end_dt_str)
        result.preload_seconds = time.time() - t0

        if not data or data["df_chips"].empty:
            result.errors.append("数据加载失败")
            return result

        # 2. 逐日计算
        t0 = time.time()
        start = datetime.strptime(entry_date, "%Y%m%d")
        if exit_date:
            end = datetime.strptime(exit_date, "%Y%m%d")
        else:
            end = datetime.now()

        current = start
        while current <= end:
            date_str = current.strftime("%Y%m%d")

            # 跳过周末
            if skip_weekends and current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            verdict = self._local_analyze(ts_code, date_str, days_window)
            self.stats["signal_count"] += 1

            if not verdict or "error" in verdict:
                result.errors.append(f"{date_str}: {verdict.get('error', 'no signal') if verdict else 'None'}")
            else:
                # 简化存储：只保留关键字段
                signal = {
                    "date": date_str,
                    "action": verdict.get("action"),
                    "confidence": int(verdict.get("confidence", 0)),
                    "color": verdict.get("color"),
                    "reasons": verdict.get("reasons", [])[:3],
                    "scores": verdict.get("scores", {}),
                }
                result.add_daily_signal(date_str, signal)

            current += timedelta(days=1)

        result.calc_seconds = time.time() - t0
        self._log(f"Done: {result.holding_days} days, {len(result.errors)} errors, "
                  f"total {result.preload_seconds + result.calc_seconds:.1f}s")
        return result


def main_poc_v2():
    """POC v2: 性能优化版 + 偏差对比 + 多样本"""
    print("=" * 70)
    print("Phase 3 POC v2: 性能优化版 + 偏差对比")
    print("=" * 70)
    print()

    engine = ReplayEngine(verbose=True)

    # POC 样本: 4 只股票，覆盖不同场景
    samples = [
        {"ts_code": "603773.SH", "name": "沃格光电", "entry": "20260522", "exit": "20260612",
         "actual_pnl": 9.12, "scenario": "WIN 案例（中等盈利）"},
        {"ts_code": "603039.SH", "name": "泛微网络", "entry": "20260608", "exit": None,
         "actual_pnl": None, "scenario": "活跃持仓（当前仍持有）"},
        {"ts_code": "002602.SZ", "name": "世纪华通", "entry": "20260605", "exit": "20260615",
         "actual_pnl": -2.93, "scenario": "LOSS 案例（小亏）"},
        {"ts_code": "002407.SZ", "name": "多氟多", "entry": "20260612", "exit": "20260615",
         "actual_pnl": -3.05, "scenario": "LOSS 案例（小亏）"},
    ]

    for s in samples:
        print(f"\n{'='*70}")
        print(f"[Sample] {s['name']} ({s['ts_code']}) - {s['scenario']}")
        print(f"{'='*70}")

        result = engine.replay_position(
            ts_code=s["ts_code"],
            entry_date=s["entry"],
            exit_date=s["exit"],
        )
        if s["actual_pnl"] is not None:
            result.set_actual_pnl(s["actual_pnl"])

        print(result.summary())
        print()

    # 输出整体统计
    print("\n" + "=" * 70)
    print("性能统计")
    print("=" * 70)
    print(f"  Preload count: {engine.stats['preload_count']}")
    print(f"  Cache hits:    {engine.stats['cache_hits']}")
    print(f"  Signal count:  {engine.stats['signal_count']}")
    print()


if __name__ == "__main__":
    main_poc_v2()