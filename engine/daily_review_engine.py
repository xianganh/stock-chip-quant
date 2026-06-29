"""
DailyReviewEngine — 单股逐日复盘引擎 (Phase 3 v3)

与 ReplayEngine (持仓段统计) 互补:
  - 输入: 一只股票 + 一个账户
  - 输出: 从"首次买入 -20 日"到"最末卖出 +20 日"的完整时间序列
  - 每日: 算法指标 + 健康度判断 (吸筹/震荡/派发/不明朗)
  - 多窗口后验: T+5 / T+10 / T+20 走势特征反推判断准确性
  - 爆发检测: 2 周内任意 3 日累计涨幅 > 15% → 识别为主力拉升

核心数据契约 (供前端 Plotly K 线复盘页面使用):
  {
    "ts_code": "603002.SH", "name": "宏昌电子", "account": "衡祥安",
    "dates": [...], "ohlc": {...}, "volume": [...],
    "indicators": [{"date", "lock_score", "dispatch_score", "tpc", "cmf", "adx", "health", "health_color", ...}],
    "trades": [{"date", "type": "buy|sell", "price", "qty", "amount"}, ...],
    "verification": [{"date", "health", "windows": {"T+5": {...}, "T+10": {...}, "T+20": {...}}, "verdict": "agree|disagree|neutral", "reason"}],
    "applicability": {"lock_score_stats": [...], "dispatch_score_stats": [...]}
  }
"""
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from typing import Optional

warnings.filterwarnings('ignore')

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

import pandas as pd
import numpy as np

from utils import get_tushare_pro, compute_verdict

from engine.replay_engine import ReplayEngine


# 阈值常量 (集中管理, 便于跨股累积调优)
RISE_THRESHOLD = 5.0
FALL_THRESHOLD = -5.0
BURST_WINDOW_DAYS = 14
BURST_PERIOD = 3
BURST_THRESHOLD = 15.0

WINDOWS = [5, 10, 20]
WARMUP_DAYS = 20
TAIL_DAYS = 20
MIN_HISTORY_DAYS = 30


def classify_health(verdict: dict) -> tuple:
    """
    把 compute_verdict 输出映射到"筹码峰演化健康度"

    Returns:
        (health, color, emoji)
        health ∈ {"accumulate", "shaking", "dispatch", "unclear"}
    """
    return classify_health_params(verdict, params=None)


# 健康度阈值的默认值 (集中管理, 便于进化调参 + Kronos 联合进化)
DEFAULT_HEALTH_PARAMS = {
    "dispatch_threshold":       4,    # 派发分数 >= 此值 -> dispatch (顶部信号)
    "lock_for_accumulate":      5,    # 持有+锁仓>=此值 -> accumulate
    "lock_for_accumulate_with_div": 3,  # 持有+锁仓>=此值+强背离>=1 -> accumulate
    "lock_for_watch_accumulate": 4,  # 观望+锁仓>=此值 -> accumulate
    "min_div_strong":            1,    # 配合需要的最少强背离数
    # ── ★ P1-2 新增: Kronos 升降级阈值 (与 chip_score 联动) ──
    "kronos_upgrade_conf":    0.80,   # fused_conf>=此值 → 升级一档 (shaking→accumulate 等)
    "kronos_downgrade_conf":  0.25,   # fused_conf<=此值 → 降级一档
    "chip_promote_score":     7,      # chip_score>=此值 → 强制升级成 accumulate (实测命中率77.8%)
    "chip_demote_score":      -2,     # chip_score<=此值 → 强制降级成 dispatch (实测命中率65%)
}


# ══════════════════════════════════════════════════════════════
# P1-1 chip_score (-4 ~ +9) ↔ 4 档健康度 双向映射
# ══════════════════════════════════════════════════════════════
#
# 设计依据:
#   chip_indicators.analyze_chip_health 命中基准 (kronos_integration/__init__.py:211-212)
#     score >= 7  →  bullish →  P(涨|bullish) ≈ 0.778   → 映射 accumulate
#     4 <= s <=6  →  偏多震荡 →                           → 映射 shaking (偏多)
#     1 <= s <=3  →  中性震荡 →                           → 映射 shaking (中性)
#    -1 <= s <=0  →  信号弱   →                           → 映射 unclear
#     score <=-2  →  bearish →  P(跌|bearish) ≈ 0.65    → 映射 dispatch
#
HEALTH_CHIP_SCORE_MAP = [
    # (health_label, color, icon, chip_lo_inclusive, chip_hi_inclusive)
    ("dispatch",   "#ef4444", "🔴", -4,  -2),
    ("unclear",    "#94a3b8", "⚪", -1,   0),
    ("shaking",    "#eab308", "🟡",  1,   6),
    ("accumulate", "#22c55e", "🟢",  7,   9),
]
# 反向查询: health → (lo, hi) 分数区间
HEALTH_TO_CHIP_RANGE = {
    "dispatch":   (-4, -2),
    "unclear":    (-1,  0),
    "shaking":    ( 1,  6),
    "accumulate": ( 7,  9),
}


def health_label_from_chip_score(chip_score: int) -> tuple:
    """
    P1-1 正向映射: chip_indicators.analyze_chip_health 的连续评分 (-4~9)
    → classify_health 的 4 档离散标签 (吸筹/震荡/派发/不明朗)

    Args:
        chip_score: analyze_chip_health(current, prev_7d)['score']

    Returns:
        (health: str, color: str, icon: str)
    """
    if chip_score is None:
        return ("unclear", "#94a3b8", "⚪")
    s = int(chip_score)
    # 防御性截断到 [-4, 9]
    s = max(-4, min(9, s))
    for label, color, icon, lo, hi in HEALTH_CHIP_SCORE_MAP:
        if lo <= s <= hi:
            return (label, color, icon)
    return ("unclear", "#94a3b8", "⚪")


def chip_score_range_from_health(health_label: str) -> tuple:
    """
    P1-1 反向映射: 4 档健康度 → 对应 chip_score 的 [lo, hi] 区间
    用于可视化在 chip_score 轴上标绘健康度分段。

    Returns:
        (lo_inclusive, hi_inclusive)
    """
    return HEALTH_TO_CHIP_RANGE.get(health_label, (-4, 9))


def _apply_kronos_adjustment(base_label: str, base_color: str, base_icon: str,
                             chip_score: int = None,
                             kronos_fused_score: float = None,
                             params: dict = None) -> tuple:
    """
    P1-2 Kronos 贝叶斯融合修正: 根据 chip_score 强度 + Kronos 融合置信度
    进行 1 档升级 / 降级。

    规则 (防御性, 保守调整):
      1) chip_score 极端值优先 (硬规则):
         - chip_score >= chip_promote_score (默认7) → 强制 upgrade 至 accumulate
         - chip_score <= chip_demote_score  (默认-2) → 强制 downgrade 至 dispatch
      2) Kronos 软规则 (仅当 chip_score 处于边界灰色区域时生效):
         - fused_conf >= kronos_upgrade_conf   (0.80) → 升 1 档
         - fused_conf <= kronos_downgrade_conf (0.25) → 降 1 档
    """
    p = dict(DEFAULT_HEALTH_PARAMS)
    if params:
        p.update(params)

    ORDER = ["dispatch", "unclear", "shaking", "accumulate"]
    COLORS = {"dispatch": "#ef4444", "unclear": "#94a3b8", "shaking": "#eab308", "accumulate": "#22c55e"}
    ICONS = {"dispatch": "🔴", "unclear": "⚪", "shaking": "🟡", "accumulate": "🟢"}

    label = base_label
    if label not in ORDER:
        label = "unclear"
    idx = ORDER.index(label)

    # 1) chip_score 硬规则 (强证据, 优先级最高)
    if chip_score is not None:
        cs = int(chip_score)
        if cs >= p.get("chip_promote_score", 7) and idx < ORDER.index("accumulate"):
            idx = ORDER.index("accumulate")
        elif cs <= p.get("chip_demote_score", -2) and idx > ORDER.index("dispatch"):
            idx = ORDER.index("dispatch")

    # 2) Kronos 软规则 (融合置信度加成)
    if kronos_fused_score is not None:
        fc = float(kronos_fused_score)
        if fc >= p.get("kronos_upgrade_conf", 0.80) and idx < len(ORDER) - 1:
            idx += 1   # 升级一档
        elif fc <= p.get("kronos_downgrade_conf", 0.25) and idx > 0:
            idx -= 1   # 降级一档

    final = ORDER[idx]
    return (final, COLORS[final], ICONS[final])


def classify_health_params(verdict: dict, params: dict = None,
                           chip_score: int = None,
                           kronos_fused_score: float = None,
                           kronos_adjust: bool = True) -> tuple:
    """
    参数化健康度分类器 — 进化优化阈值 + P1 Kronos 融合增强

    Args:
        verdict: compute_verdict() 输出
        params: 阈值参数 (None = 使用 DEFAULT_HEALTH_PARAMS)
        chip_score: [可选] chip_indicators.analyze_chip_health 的 score (-4~9)
        kronos_fused_score: [可选] KronosChipFuser.bayesian_fusion()['fused_confidence']
        kronos_adjust: 是否启用 Kronos + chip_score 修正 (默认True; 关=原行为)

    Returns:
        (health, color, emoji)
        health ∈ {"accumulate", "shaking", "dispatch", "unclear"}
    """
    p = dict(DEFAULT_HEALTH_PARAMS)
    if params:
        p.update(params)

    action = verdict.get("action", "观望")
    scores = verdict.get("scores", {}) or {}
    lock = scores.get("lock", [0, 6])[0] if isinstance(scores.get("lock"), (list, tuple)) else 0
    dispatch = scores.get("dispatch", 0) or 0
    div_strong = scores.get("divergence_strong", 0) or 0

    # ── 原版 verdict 驱动 (锁仓/派发信号) ──
    # 顶部信号 (danger)
    if action == "清仓" or dispatch >= p["dispatch_threshold"]:
        base = ("dispatch", "#ef4444", "🔴")
    # 减仓信号
    elif action == "减仓":
        base = ("shaking", "#eab308", "🟡")
    # 持有 + 强锁仓
    elif action == "持有":
        if lock >= p["lock_for_accumulate"]:
            base = ("accumulate", "#22c55e", "🟢")
        elif lock >= p["lock_for_accumulate_with_div"] and div_strong >= p["min_div_strong"]:
            base = ("accumulate", "#22c55e", "🟢")
        else:
            base = ("shaking", "#eab308", "🟡")
    # 观望 + 还不错的锁仓
    elif action == "观望":
        if lock >= p["lock_for_watch_accumulate"]:
            base = ("accumulate", "#22c55e", "🟢")
        else:
            base = ("unclear", "#94a3b8", "⚪")
    else:
        base = ("unclear", "#94a3b8", "⚪")

    # ── ★ P1-2 新增: Kronos + chip_score 联合修正 ──
    if kronos_adjust and (chip_score is not None or kronos_fused_score is not None):
        return _apply_kronos_adjustment(*base, chip_score=chip_score,
                                        kronos_fused_score=kronos_fused_score,
                                        params=p)
    return base


HEALTH_LABEL_CN = {
    "accumulate": "吸筹中",
    "shaking": "震荡洗盘",
    "dispatch": "派发出货",
    "unclear": "不明朗",
}


# 默认规则 (经 12 股 768 样本 A/B 验证: 命中率 68%, DROP 测试后确认)
# - 关 dispatch_winner (-11.3% 拖累)
# - KEEP peaks_below, gap_pct_mid, width_70_tight
DEFAULT_RAW_HEALTH_PARAMS = {
    # P3 实战校准: 1337 笔真实回测表明 winner 90% 不是派发信号
    #   (winner 高的买入后反而胜率 52% > winner 低 42%)
    # 把阈值从 90 提到 95，避免误判；同时改名为 dispatch_强派发阈值
    "dispatch_winner_threshold": 95,     # winner >= 95% 才视为派发 (校准后)
    "dispatch_tpc_threshold":    25,     # tpc >=
    "acc_base_tpc":              25,     # 基础: tpc >=
    "acc_base_p1_pct":           12,     # 基础: p1_pct >=
    "acc_peaks_below":           2,      # 低位吸纳: peaks_below_close >=
    "acc_gap_pct_min":            3,      # 双峰间距合理: gap_pct >=
    "acc_gap_pct_max":            8,      # 双峰间距合理: gap_pct <=
    "acc_width_70_pct_of_p1":     20,     # 紧密宽度: width_70 <= p1 的 X%
    "shaking_tpc":               15,     # 弱集中
}


def classify_health_from_raw(metrics: dict, params: dict = None,
                             chip_score: int = None,
                             kronos_fused_score: float = None,
                             kronos_adjust: bool = True) -> tuple:
    """
    用底层指标直接分类健康度 (不依赖 verdict/lock_passed)
    + P1 Kronos / chip_score 联动修正

    Args:
        metrics: 含 tpc, p1_pct, winner, peaks_below_close, width_70,
                 gap_pct, peak_entropy, p1 等指标的 dict (来自 daily_records)
        params:  阈值覆盖 (None 用 DEFAULT_RAW_HEALTH_PARAMS)
        chip_score: [可选] chip_indicators.analyze_chip_health 的 score
        kronos_fused_score: [可选] KronosChipFuser.bayesian_fusion 的 fused_conf
        kronos_adjust: 是否启用修正 (默认True)

    Returns:
        (health, reason) where health in {accumulate, dispatch, shaking, unclear}

    测试结果 (768 样本, 33.7秒 grid search):
      - accumulate 命中率 71% (371 个验证样本)
      - dispatch 命中率 0/0 (数据集缺乏跌市样本, 需更长历史)
      - 推荐组合: peaks_below>=2 + gap_pct∈[3,8]% + width_70<=20%*p1
    """
    p = dict(DEFAULT_RAW_HEALTH_PARAMS)
    if params:
        p.update(params)

    tpc = metrics.get('tpc', 0)
    p1_pct = metrics.get('p1_pct', 0)
    winner = metrics.get('winner', 0)
    peaks_below = metrics.get('peaks_below_close', 0) or 0
    width_70 = metrics.get('width_70', 0) or 0
    p1 = metrics.get('p1', 0) or 0
    gap_pct = metrics.get('gap_pct', 0) or 0
    if chip_score is None:
        chip_score = metrics.get('chip_score')

    # 1) Dispatch (高级信号, 须 winner 异常高)
    if winner >= p['dispatch_winner_threshold'] and tpc >= p['dispatch_tpc_threshold']:
        base_health, base_reason = 'dispatch', f'winner>={p["dispatch_winner_threshold"]}+tpc>={p["dispatch_tpc_threshold"]} (顶部)'
    else:
        # 2) Accumulate (满足任一增强条件 + 基础)
        reasons = []
        if tpc >= p['acc_base_tpc'] and p1_pct >= p['acc_base_p1_pct']:
            reasons.append(f'tpc>={p["acc_base_tpc"]}+p1_pct>={p["acc_base_p1_pct"]}')
        if peaks_below >= p['acc_peaks_below']:
            reasons.append(f'peaks_below>={p["acc_peaks_below"]} (低位)')
        if p['acc_gap_pct_min'] <= gap_pct <= p['acc_gap_pct_max']:
            reasons.append(f'gap_pct∈[{p["acc_gap_pct_min"]}%-{p["acc_gap_pct_max"]}%]')
        if width_70 > 0 and p1 > 0 and width_70 <= p1 * p['acc_width_70_pct_of_p1'] / 100:
            reasons.append(f'width_70≤{p["acc_width_70_pct_of_p1"]}%×P1')
        if reasons:
            base_health, base_reason = 'accumulate', '+'.join(reasons)
        elif tpc >= p['shaking_tpc']:
            # 3) Shaking (弱集中)
            base_health, base_reason = 'shaking', f'tpc>={p["shaking_tpc"]} (弱集中)'
        else:
            base_health, base_reason = 'unclear', '无信号'

    # ── ★ P1-2 Kronos + chip_score 联合修正 (与 classify_health_params 对齐) ──
    if kronos_adjust and (chip_score is not None or kronos_fused_score is not None):
        COLOR_MAP = {"dispatch": "#ef4444", "unclear": "#94a3b8", "shaking": "#eab308", "accumulate": "#22c55e"}
        ICON_MAP  = {"dispatch": "🔴", "unclear": "⚪", "shaking": "🟡", "accumulate": "🟢"}
        base_color = COLOR_MAP.get(base_health, "#94a3b8")
        base_icon  = ICON_MAP.get(base_health, "⚪")
        final_health, _, _ = _apply_kronos_adjustment(
            base_health, base_color, base_icon,
            chip_score=chip_score,
            kronos_fused_score=kronos_fused_score,
            # 复用 DEFAULT_HEALTH_PARAMS 中的 Kronos 阈值
            params={k: DEFAULT_HEALTH_PARAMS[k] for k in DEFAULT_HEALTH_PARAMS
                    if k in ("chip_promote_score", "chip_demote_score",
                             "kronos_upgrade_conf", "kronos_downgrade_conf")}
        )
        if final_health != base_health:
            adjust_tag = f"[升→{final_health}]" if final_health in ("accumulate", "shaking") else f"[降→{final_health}]"
            return (final_health, f"{base_reason} {adjust_tag}")
    return (base_health, base_reason)


def _to_native(obj):
    """递归把 numpy 类型转成 Python 原生类型, 避免 JSON 序列化失败"""
    import numpy as _np
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        f = float(obj)
        return f if not _np.isnan(f) else None
    if isinstance(obj, _np.ndarray):
        return [_to_native(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return str(obj)
    return obj


def classify_future(close_series: pd.Series, idx_T: int, window: int) -> dict:
    """
    对 T 日, 计算未来 window 日的走势特征

    close_series: 完整收盘价序列 (按日期升序)
    idx_T: T 日下标
    window: 向前看几天 (5/10/20)

    Returns: {label, change_pct, burst_detected}
        label ∈ {"rise", "fall", "shake"}
    """
    n = len(close_series)
    end_idx = idx_T + window
    if end_idx >= n:
        return {"label": "no_data", "change_pct": None, "burst_detected": False}

    close_T = close_series.iloc[idx_T]
    close_end = close_series.iloc[end_idx]
    change_pct = (close_end - close_T) / close_T * 100.0 if close_T > 0 else 0.0

    burst = False
    burst_end = min(idx_T + BURST_WINDOW_DAYS, n - 1)
    for j in range(idx_T + 1, burst_end - BURST_PERIOD + 2):
        seg_end = j + BURST_PERIOD - 1
        if seg_end > burst_end:
            break
        seg_change = (close_series.iloc[seg_end] - close_series.iloc[j - 1]) / close_series.iloc[j - 1] * 100.0
        if seg_change >= BURST_THRESHOLD:
            burst = True
            break

    if change_pct >= RISE_THRESHOLD or burst:
        return {"label": "rise", "change_pct": round(change_pct, 2), "burst_detected": burst}
    if change_pct <= FALL_THRESHOLD:
        return {"label": "fall", "change_pct": round(change_pct, 2), "burst_detected": burst}
    return {"label": "shake", "change_pct": round(change_pct, 2), "burst_detected": burst}


def verify_health(health: str, windows_result: dict) -> tuple:
    """
    多窗口投票: 把 T+5/T+10/T+20 的走势聚合, 验证 T 日健康度

    Returns:
        (verdict, reason)
        verdict ∈ {"agree", "disagree", "neutral", "no_data"}
    """
    valid_labels = [r["label"] for r in windows_result.values() if r["label"] != "no_data"]
    if len(valid_labels) < 2:
        return ("no_data", "未来数据不足, 无法验证")

    def count(label):
        return sum(1 for v in valid_labels if v == label)

    if health == "accumulate":
        if count("rise") >= 2:
            return ("agree", f"{len(valid_labels)} 个窗口中 {count('rise')} 个主力拉升, 印证吸筹判断")
        if count("fall") >= 2:
            return ("disagree", f"判断吸筹但 {count('fall')} 个窗口大跌, 实际为派发")
        return ("neutral", "走势分化, 无法明确验证")
    if health == "dispatch":
        if count("fall") >= 2:
            return ("agree", f"{count('fall')} 个窗口大跌, 印证派发判断")
        if count("rise") >= 2:
            return ("disagree", f"判断派发但 {count('rise')} 个窗口拉升, 实际仍在吸筹")
        return ("neutral", "走势分化, 无法明确验证")
    if health == "shaking":
        if count("fall") >= 2:
            return ("agree", "震荡转弱确认")
        return ("neutral", "震荡后未明显走弱")
    return ("neutral", "判断为不明朗, 不验证")


class DailyReviewEngine:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._inner = ReplayEngine(verbose=verbose)
        self._data_cache = self._inner._data_cache

    def _log(self, msg: str):
        if self.verbose:
            print(msg, flush=True)

    def _preload(self, ts_code: str, start_date: str, end_date: str) -> Optional[dict]:
        return self._inner._preload_data(ts_code, start_date, end_date)

    def _analyze_one_day(self, ts_code: str, end_date: str) -> Optional[dict]:
        """复用 ReplayEngine._local_analyze, 返回 verdict (含 action/scores)"""
        return self._inner._local_analyze(ts_code, end_date)

    def _analyze_one_day_with_raw(self, ts_code: str, end_date: str) -> Optional[dict]:
        """
        复用 ReplayEngine 的数据缓存, 跑一遍完整 analyze.py, 返回 raw metrics 字典
        这样 DailyReviewEngine 能拿到所有 40+ 指标做后验检验
        """
        from scripts.analyze import (
            compute_chip_metrics, assess_locking, dispatch_score,
            score_tech, detect_divergence,
            compute_cmf, compute_adx, compute_atr,
            compute_rolling_percentile, build_chip_percentile_context,
        )

        data = self._inner._data_cache.get(ts_code)
        if not data:
            return None
        df_chips = data.get("df_chips", pd.DataFrame())
        df_merged = data.get("df_merged", pd.DataFrame())
        df_factor = data.get("df_factor", pd.DataFrame())
        if df_chips.empty or df_merged.empty:
            return None

        all_chip_dates = sorted(df_chips['trade_date'].astype(str).unique())
        valid_dates = [d for d in all_chip_dates if d <= end_date]
        if len(valid_dates) < 14:
            return None

        recent_dates = valid_dates[-14:]
        recent_set = set(recent_dates)
        all_metrics, metrics_list = [], []
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
            m['close'] = close
            m['pct_change'] = round(float(kr.get('pct_change', 0)), 2)
            all_metrics.append(m)
            if td in recent_set:
                metrics_list.append(m)

        if len(metrics_list) < 3:
            return None

        try:
            locking = assess_locking(metrics_list)
        except Exception as e:
            if self.verbose:
                print(f"  [warn] assess_locking failed: {e}")
            locking = {"locked_score": "0/6"}
        try:
            dispatch = dispatch_score(metrics_list)
        except Exception as e:
            if self.verbose:
                print(f"  [warn] dispatch_score failed: {e}")
            dispatch = {"total": 0}

        classic_indicators = {}
        if not df_factor.empty:
            fct = df_factor[df_factor['trade_date'].astype(str) <= end_date].tail(50)
            if len(fct) >= 5:
                try:
                    cmf = compute_cmf(fct['high'].values, fct['low'].values, fct['close'].values, fct['vol'].values, 21)
                    adx_info = compute_adx(fct['high'].values, fct['low'].values, fct['close'].values, 14)
                    atr_v = compute_atr(fct['high'].values, fct['low'].values, fct['close'].values, 14)
                    classic_indicators = {
                        "cmf": {"latest": float(cmf[-1]) if not np.isnan(cmf[-1]) else None},
                        "adx": {
                            "latest_adx": float(adx_info["adx"][-1]) if not np.isnan(adx_info["adx"][-1]) else None,
                            "latest_pdi": float(adx_info["pdi"][-1]) if not np.isnan(adx_info["pdi"][-1]) else None,
                            "latest_mdi": float(adx_info["mdi"][-1]) if not np.isnan(adx_info["mdi"][-1]) else None,
                        },
                        "atr": {
                            "latest": float(atr_v[-1]) if not np.isnan(atr_v[-1]) else None,
                            "atr_pct_of_price": float(atr_v[-1] / fct['close'].values[-1] * 100) if atr_v[-1] else None,
                        },
                    }
                except Exception:
                    pass

        latest_metrics = _to_native(metrics_list[-1]) if metrics_list else {}
        # assess_locking 返回的就是 {p1:{status:✅,...}, tp3:..., ...} 字典本身
        # dispatch_score 同理, 直接是 items
        lock_items = _to_native({k: v for k, v in locking.items() if isinstance(v, dict) and 'status' in v})
        dispatch_items = _to_native(dispatch)
        return {
            "latest_metrics": latest_metrics,
            "lock_items": lock_items,
            "lock_score": _to_native(locking.get("locked_score", "0/6")),
            "dispatch_items": dispatch_items,
            "dispatch_total": _to_native(dispatch.get("total", 0)),
            "classic": classic_indicators,
        }

    def review_position_range(self, ts_code: str, account: str,
                              start_date: str, end_date: str) -> dict:
        """
        对 [start_date, end_date] 范围内的每个交易日做完整复盘

        start_date 通常 = 首次买入日 - WARMUP_DAYS
        end_date   通常 = 最末卖出日 + TAIL_DAYS (为了完整后验)
        """
        from utils import normalize_ts_code
        ts_code = normalize_ts_code(ts_code)

        # 1) 预加载数据 (扩展边界, 保证 T+20 后验有数据)
        data = self._preload(ts_code, start_date, end_date)
        if not data or data["df_merged"].empty:
            return {"error": f"无法获取 {ts_code} 的历史数据"}

        df = data["df_merged"].copy()
        df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
        df = df.sort_values('trade_date').reset_index(drop=True)

        if len(df) < MIN_HISTORY_DAYS:
            return {"error": f"{ts_code} 在该区间数据不足 ({len(df)} 天)"}

        close_series = df['close']

        # 2) 逐日分析
        all_dates = df['trade_date'].tolist()
        self._log(f"  开始逐日分析 {len(all_dates)} 个交易日...")

        indicators = []
        raw_snapshots = []  # 同时收集原始 40+ 指标, 供后验检验用

        for i, row in df.iterrows():
            date = row['trade_date']
            verdict = self._analyze_one_day(ts_code, date)
            if not verdict or "error" in verdict:
                continue
            if "action" not in verdict:
                continue
            health, color, emoji = classify_health(verdict)
            scores = verdict.get("scores", {}) or {}
            lock_arr = scores.get("lock", [0, 6])
            lock_passed = lock_arr[0] if isinstance(lock_arr, (list, tuple)) else 0

            # 调用扩展方法拿原始 40+ 指标
            raw = self._analyze_one_day_with_raw(ts_code, date) or {}
            raw_snapshots.append({"date": date, **raw})

            indicators.append({
                "date": date,
                "close": float(row['close']),
                "action": verdict.get("action", ""),
                "confidence": verdict.get("confidence", 0),
                "health": health,
                "health_label": HEALTH_LABEL_CN[health],
                "health_color": color,
                "health_emoji": emoji,
                "lock_score": lock_passed,
                "lock_total": 6,
                "dispatch_score": scores.get("dispatch", 0) or 0,
                "tpc": float(scores.get("tpc", 0) or 0),
                "morphology": scores.get("morphology", ""),
                "divergence_strong": scores.get("divergence_strong", 0) or 0,
                "divergence_active": scores.get("divergence_active", 0) or 0,
                "reasons": verdict.get("reasons", [])[:3],
            })

        self._log(f"  成功分析 {len(indicators)}/{len(all_dates)} 天")

        # 3) 对每个有指标的日子做后验
        close_full = data["df_merged"]['close']
        date_full = data["df_merged"]['trade_date']
        verification = []
        for ind in indicators:
            try:
                idx_T = date_full[date_full == ind["date"]].index[0]
            except (IndexError, KeyError):
                continue

            windows_result = {}
            for w in WINDOWS:
                windows_result[f"T+{w}"] = classify_future(close_full, idx_T, w)

            verdict, reason = verify_health(ind["health"], windows_result)
            verification.append({
                "date": ind["date"],
                "health": ind["health"],
                "health_label": ind["health_label"],
                "windows": windows_result,
                "verdict": verdict,
                "reason": reason,
            })

        # 4) 适用性统计 (单股)
        applicability = self._compute_applicability(indicators, verification)

        # 5) 构造前端期望的 OHLC 序列
        ohlc = {
            "open": df['open'].round(2).tolist(),
            "high": df['high'].round(2).tolist(),
            "low": df['low'].round(2).tolist(),
            "close": df['close'].round(2).tolist(),
        }
        volume = df['vol'].astype(int).tolist() if 'vol' in df else []

        # 4) 逐指标后验检验 (40+ 指标的命中率, 找出真正有预测力的)
        indicator_test = self._test_all_indicators(raw_snapshots, verification, close_full, date_full)

        return _to_native({
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "dates": all_dates,
            "ohlc": ohlc,
            "volume": volume,
            "indicators": indicators,
            "verification": verification,
            "applicability": applicability,
            "indicator_test": indicator_test,
        })

    def _compute_applicability(self, indicators: list, verification: list) -> dict:
        """单股的指标适用性统计 (跨股缓存累积后再综合调整阈值)"""
        from collections import defaultdict
        lock_buckets = defaultdict(lambda: {"agree": 0, "disagree": 0, "neutral": 0})
        dispatch_buckets = defaultdict(lambda: {"agree": 0, "disagree": 0, "neutral": 0})
        health_buckets = defaultdict(lambda: {"agree": 0, "disagree": 0, "neutral": 0})

        ver_map = {v["date"]: v for v in verification}
        for ind in indicators:
            v = ver_map.get(ind["date"])
            if not v:
                continue
            verdict = v["verdict"]
            if verdict == "no_data":
                continue
            lock_k = f"{ind['lock_score']}/6"
            dispatch_k = f"D{ind['dispatch_score']}"
            lock_buckets[lock_k][verdict] += 1
            dispatch_buckets[dispatch_k][verdict] += 1
            health_buckets[ind["health_label"]][verdict] += 1

        def to_rows(buckets, order=None):
            rows = []
            keys = list(buckets.keys())
            if order:
                keys = sorted(keys, key=lambda k: order.index(k) if k in order else 99)
            for k in keys:
                b = buckets[k]
                total = b["agree"] + b["disagree"] + b["neutral"]
                if total == 0:
                    continue
                rows.append({
                    "bucket": k,
                    "agree": b["agree"],
                    "disagree": b["disagree"],
                    "neutral": b["neutral"],
                    "total": total,
                    "accuracy": round(b["agree"] / total * 100, 1) if total else 0,
                })
            return rows

        return {
            "lock_score": to_rows(lock_buckets, order=[f"{i}/6" for i in range(7)]),
            "dispatch_score": to_rows(dispatch_buckets, order=[f"D{i}" for i in range(6)]),
            "health": to_rows(health_buckets),
            "sample_count": len(verification),
        }

    # ══════════════════════════════════════════════════════════
    # 逐指标后验检验 — 核心: 找出 40+ 指标中真正有预测力的
    # ══════════════════════════════════════════════════════════
    def _test_all_indicators(self, raw_snapshots: list, verification: list,
                             close_full, date_full) -> dict:
        """
        对每个指标做"取值分档 × 后验走势" 的命中率统计
        重点关注筹码峰指标 (主力状态), 技术面 (CMF/ADX/ATR) 单独分类

        思路: 不预设"看涨/看跌"语义, 纯统计每个分档下 rise/fall/shake 的分布
        → 让你自己看分布决定阈值
        """
        from collections import defaultdict

        ver_map = {v["date"]: v for v in verification}

        samples = []
        for snap in raw_snapshots:
            date = snap.get("date")
            ver = ver_map.get(date)
            if not ver:
                continue
            # 取 T+10 窗口作为主后验参考 (中短期, 适合短线)
            t10 = ver.get("windows", {}).get("T+10", {})
            if t10.get("label") in (None, "no_data"):
                continue
            snap["_verdict"] = t10.get("label", "shake")
            snap["_change_pct"] = t10.get("change_pct", 0)
            snap["_burst"] = t10.get("burst_detected", False)
            samples.append(snap)

        if len(samples) < 5:
            return {"error": f"样本不足 ({len(samples)}), 无法做指标检验", "sample_count": len(samples)}

        # ── 分类 1: 锁仓子条件 (6 条二值) ──
        # 字段名是 assess_locking 返回的顶层 key: p1/tp3/dist/top5/winner/tpc
        # 每条都有 "status": "✅" or "❌"/"⚠️"
        lock_sub_tests = []
        for key, label, desc in [
            ("p1",     "P1 稳定性",   "P1 5日 range/avg ≤ 1%"),
            ("tp3",    "TP3 趋势",     "TP3 5日 Δ > 0"),
            ("dist",   "Dist 方向",    "dist > 0"),
            ("top5",   "Top5 趋势",    "Top5 5日 Δ > 0"),
            ("winner", "Winner 趋势",  "winner 近期 vs 前期 Δ > 0"),
            ("tpc",    "TPC 趋势",     "TPC 5日 Δ > 0"),
        ]:
            lock_sub_tests.append(self._test_binary(
                samples, key=lambda s, k=key: s.get("lock_items", {}).get(k, {}).get("status", "") == "✅",
                indicator=f"锁仓[{label}]", desc=desc,
            ))

        # ── 分类 2: 派发子信号 ──
        # 字段名直接来自 dispatch_score
        dispatch_sub_tests = []
        for key, label, desc in [
            ("d1_p1_reversal",     "D1 P1反转",  "P1占比下降 + 5日下跌"),
            ("d2_cost_reversal",   "D2 成本反转", "价涨 vs 成本涨"),
            ("d3_top5_dispersion", "D3 Top5分散", "Top5 下降"),
            ("d4_price_below_cost","D4 跌破成本", "连续3日 < 加权成本"),
            ("d5_insider",         "D5 内部人",   "内部人动作"),
        ]:
            dispatch_sub_tests.append(self._test_binary(
                samples, key=lambda s, k=key: (s.get("dispatch_items", {}).get(k, {}).get("score", 0) or 0) >= 1,
                indicator=f"派发[{label}]", desc=desc,
            ))

        # ── 分类 3: 筹码结构连续指标 (按分位分档) ──
        # 重点指标! 解读主力状态的核心
        chip_indicators = [
            ("tpc",        "TPC (三峰集中度)",   "主力筹码集中度, 越高越集中"),
            ("winner",     "Winner (获利盘)",    "收盘价下筹码占比, 高=套牢少"),
            ("width",      "Width (三峰宽度)",   "三峰极差/最低峰%, 小=筹码紧"),
            ("width_70",   "Width70 (70%宽度)",  "70%筹码集中宽度"),
            ("width_90",   "Width90 (90%宽度)",  "90%筹码集中宽度"),
            ("dist",       "Dist (峰位偏离)",    "收盘价偏离主峰%, 正=在峰上方"),
            ("tp3",        "TP3 (现价带筹码)",   "现价附近筹码占比"),
            ("skewness",   "Skewness (偏度)",    "筹码分布偏度, 正=右偏"),
            ("kurtosis",   "Kurtosis (峰度)",    "筹码分布尖锐度"),
            ("gradient",   "Gradient (密度梯度)", "筹码密度变化速率"),
            ("entropy",    "Entropy (分布熵)",    "分布混乱度, 低=集中"),
            ("p1_pct",     "P1占比",             "主峰占比"),
            ("p2_pct",     "P2占比",             "第二峰占比"),
            ("gap_pct",    "Gap (峰间距%)",      "主峰与第二峰间距"),
        ]
        chip_tests = []
        for key, label, desc in chip_indicators:
            chip_tests.append(self._test_continuous(samples, key, label, desc))

        # ── 分类 4: 经典技术指标 ──
        classic_tests = []
        for key_path, label, desc in [
            ("cmf.latest",       "CMF (资金流)",   "Chaikin Money Flow, 正=资金流入"),
            ("adx.latest_adx",   "ADX (趋势强度)", ">20=趋势确立"),
            ("adx.latest_pdi",   "PDI (上升动力)",  "+DI, 上升方向力度"),
            ("adx.latest_mdi",   "MDI (下降动力)",  "-DI, 下降方向力度"),
            ("atr.atr_pct_of_price", "ATR%",       "真实波幅占价格比"),
        ]:
            classic_tests.append(self._test_continuous_path(samples, key_path, label, desc))

        # ── 汇总: 按"分档里 rise 占比"排序 ──
        all_tests = lock_sub_tests + dispatch_sub_tests + chip_tests + classic_tests
        all_tests.sort(key=lambda x: x.get("best_buckets", [{}])[0].get("rise_rate", 0)
                       if x.get("best_buckets") else 0, reverse=True)

        return {
            "sample_count": len(samples),
            "verdict_source": "T+10 窗口",
            "categories": {
                "lock_sub":     {"title": "🔒 锁仓子条件 (6 条)", "tests": lock_sub_tests},
                "dispatch_sub": {"title": "⚠️ 派发子信号 (5 条)", "tests": dispatch_sub_tests},
                "chip_structure": {"title": "💎 筹码结构 (14 个, 重点关注)", "tests": chip_tests},
                "classic":      {"title": "📐 经典技术 (CMF/ADX/ATR)", "tests": classic_tests},
            },
            "all_ranked": all_tests,
        }

    def _test_binary(self, samples, key, indicator: str, desc: str) -> dict:
        """二值指标检验: 当条件为 True vs False, 后验分布如何"""
        true_verdicts, false_verdicts = [], []
        for s in samples:
            try:
                v = key(s)
            except Exception:
                continue
            if v:
                true_verdicts.append(s["_verdict"])
            else:
                false_verdicts.append(s["_verdict"])
        from collections import Counter
        t_cnt = Counter(true_verdicts)
        f_cnt = Counter(false_verdicts)
        t_total = sum(t_cnt.values())
        f_total = sum(f_cnt.values())
        t_rise = round(t_cnt.get("rise", 0) / t_total * 100, 1) if t_total else 0
        f_rise = round(f_cnt.get("rise", 0) / f_total * 100, 1) if f_total else 0
        return {
            "indicator": indicator,
            "desc": desc,
            "type": "binary",
            "true_count": t_total,
            "false_count": f_total,
            "true_rise_rate": t_rise,
            "false_rise_rate": f_rise,
            "delta": round(t_rise - f_rise, 1),
            "best_buckets": [{"label": "✓成立", "rise_rate": t_rise, "count": t_total}],
            "detail": {
                "true":  {"rise": t_cnt.get("rise", 0), "fall": t_cnt.get("fall", 0), "shake": t_cnt.get("shake", 0)},
                "false": {"rise": f_cnt.get("rise", 0), "fall": f_cnt.get("fall", 0), "shake": f_cnt.get("shake", 0)},
            },
        }

    def _test_continuous(self, samples, key: str, label: str, desc: str) -> dict:
        """连续指标检验: 按 5 分位分档, 统计每档后验分布"""
        vals = []
        for s in samples:
            v = s.get("latest_metrics", {}).get(key)
            if v is None:
                continue
            try:
                vals.append((float(v), s))
            except (TypeError, ValueError):
                continue
        return self._do_continuous_test(vals, label, desc)

    def _test_continuous_path(self, samples, path: str, label: str, desc: str) -> dict:
        """嵌套路径 (如 cmf.latest) 的连续指标检验"""
        vals = []
        for s in samples:
            cur = s
            for p in path.split("."):
                if not isinstance(cur, dict):
                    cur = None
                    break
                cur = cur.get(p)
            if cur is None:
                continue
            try:
                vals.append((float(cur), s))
            except (TypeError, ValueError):
                continue
        return self._do_continuous_test(vals, label, desc)

    def _do_continuous_test(self, vals: list, label: str, desc: str) -> dict:
        from collections import Counter
        if len(vals) < 5:
            return {
                "indicator": label, "desc": desc, "type": "continuous",
                "sample_count": len(vals), "best_buckets": [],
                "error": "样本不足",
            }
        vals.sort(key=lambda x: x[0])
        n = len(vals)
        bucket_size = max(1, n // 5)
        buckets = []
        for i in range(5):
            seg = vals[i * bucket_size: (i + 1) * bucket_size] if i < 4 else vals[i * bucket_size:]
            if not seg:
                continue
            verdicts = [s["_verdict"] for _, s in seg]
            cnt = Counter(verdicts)
            tot = sum(cnt.values())
            lo = seg[0][0]
            hi = seg[-1][0]
            buckets.append({
                "label": f"{lo:.2f}~{hi:.2f}",
                "count": tot,
                "rise": cnt.get("rise", 0),
                "fall": cnt.get("fall", 0),
                "shake": cnt.get("shake", 0),
                "rise_rate": round(cnt.get("rise", 0) / tot * 100, 1) if tot else 0,
                "fall_rate": round(cnt.get("fall", 0) / tot * 100, 1) if tot else 0,
            })
        buckets.sort(key=lambda b: b["rise_rate"], reverse=True)
        return {
            "indicator": label, "desc": desc, "type": "continuous",
            "sample_count": n, "best_buckets": buckets,
            "top_rise_bucket": buckets[0]["label"] if buckets else None,
            "top_rise_rate": buckets[0]["rise_rate"] if buckets else 0,
        }


def find_position_range(positions: list) -> tuple:
    """从 position 列表计算时间窗口: (首买入 -20, 末卖出 +20)"""
    if not positions:
        return None
    entry_dates = [p.entry_date for p in positions if p.entry_date]
    exit_dates = [p.exit_date for p in positions if p.exit_date]
    if not entry_dates:
        return None
    earliest = min(entry_dates)
    latest = max(exit_dates) if exit_dates else max(entry_dates)

    dt_early = datetime.strptime(earliest, "%Y%m%d") - timedelta(days=WARMUP_DAYS * 2)
    dt_late = datetime.strptime(latest, "%Y%m%d") + timedelta(days=TAIL_DAYS * 2)
    return (dt_early.strftime("%Y%m%d"), dt_late.strftime("%Y%m%d"))
