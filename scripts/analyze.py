#!/usr/bin/env python3
"""
筹码峰演化 + 技术面参考分析 — 统一数据脚本 (v2.5)
==================================================
基于 cyq_chips 全量筹码分布直方图 + 经典量化指标 + 滚动分位数归一化

用法:
  python analyze.py <stock_code> [--days 14] [--output result.json]

核心指标 (v2.2):
  ── 筹码分布统计 (逐日) ──
  - 加权偏度 (skewness) / 峰度 (kurtosis) / 梯度 (gradient) / 熵 (entropy)
  - 70%/90% 集中宽度 / 局部极大值峰值检测 / 形态分类
  - 阻力位/支撑位 / P1支配度/峰熵

  ── 经典量化辅助指标 (新增 v2.2) ──
  - CMF (蔡金资金流) — 替代裸 net_mf_amount, 归一化到 [-1,+1]
  - ADX (平均趋向指数) — 趋势强度 + 方向 (+DI/-DI)
  - ATR (平均真实波幅) — 波动率分位, 环境分类

  ── 筹码因子滚动分位数归一化 (新增 v2.2) ──
  - 所有筹码指标基于全量历史 (60日窗口) 计算滚动分位数
  - 消除硬编码阈值, 跨股票可比
  - Z-score 标准化输出

数据源: Tushare Pro
  - cyq_chips     → 全量筹码分布直方图 (price, percent)
  - stk_factor     → K线 + MACD/KDJ/RSI/BOLL
  - moneyflow      → 资金流向
  - daily_basic    → 换手率 / 量比 / PE/PB
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Optional
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np

# ── 配置 ──────────────────────────────────────────────
# 将项目根目录加入 sys.path 以便导入 utils
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from utils import get_tushare_pro


def safe_div(a, b, default=0.0):
    return a / b if b else default


# ══════════════════════════════════════════════════════
# 引擎①: 筹码峰单日指标计算 (基于 cyq_chips 真实分布)
# ══════════════════════════════════════════════════════

def _detect_local_peaks(prices: np.ndarray, percents: np.ndarray,
                        min_height: float = 0.5, min_distance: float = 0.02) -> dict:
    """
    局部极大值峰值检测 (不依赖 scipy)

    Args:
        prices: 价格数组 (按价格升序)
        percents: 筹码占比数组 (%)
        min_height: 最低峰值高度 (占比%), 低于此值忽略
        min_distance: 最小峰间距 (价格相对距离), 过近则合并

    Returns:
        {"positions": [价格], "heights": [占比%], "indices": [索引]}
    """
    n = len(prices)
    if n < 3:
        return {"positions": [], "heights": [], "indices": []}

    # 第一步: 找所有局部极大值
    raw_peaks = []
    for i in range(1, n - 1):
        # 左右各看2个邻居去噪
        left_vals  = percents[max(0, i-2):i]
        right_vals = percents[i+1:min(n, i+3)]
        # ★ 修复: 左右严格度统一 (原来 `>` vs `>=` 不对称会右偏置)
        if left_vals.size > 0 and right_vals.size > 0:
            if percents[i] > max(left_vals) and percents[i] > max(right_vals):
                if percents[i] >= min_height:
                    raw_peaks.append((i, float(prices[i]), float(percents[i])))

    if not raw_peaks:
        return {"positions": [], "heights": [], "indices": []}

    # 第二步: 合并过近的峰 (保留更高的)
    merged = [raw_peaks[0]]
    for idx, price, h in raw_peaks[1:]:
        last_idx, last_price, last_h = merged[-1]
        rel_dist = abs(price - last_price) / last_price if last_price > 0 else 1
        if rel_dist < min_distance:
            # 合并: 保留更高的
            if h > last_h:
                merged[-1] = (idx, price, h)
        else:
            merged.append((idx, price, h))

    return {
        "positions": [m[1] for m in merged],
        "heights":   [m[2] for m in merged],
        "indices":   [m[0] for m in merged],
    }


def _classify_morphology(peak_info: dict, tpc: float, width: float) -> str:
    """根据检测到的峰值数量和分布特征，分类筹码形态"""
    n = len(peak_info["positions"])
    positions = peak_info["positions"]
    heights   = peak_info["heights"]

    if n == 0:
        return "无峰(极度分散)"
    elif n == 1:
        return "单峰密集" if tpc > 15 else "单峰(弱)"
    elif n == 2:
        gap_ratio = abs(positions[0] - positions[1]) / min(positions[0], positions[1])
        if gap_ratio < 0.05:
            return "双峰密集(窄)"
        elif gap_ratio < 0.15:
            return "双峰对峙"
        else:
            return "双峰发散(宽)"
    elif n == 3:
        # 分析三峰的均匀程度
        h_ratios = [h / max(heights) for h in heights]
        if min(h_ratios) > 0.5:
            return "三峰均衡"
        elif h_ratios[0] > 0.6:
            return "三峰(主峰突出)"
        else:
            return "三峰分布"
    else:
        return "多峰发散"


def _find_resistance_support(peak_info: dict, close: float) -> dict:
    """在检测到的峰值中找最近的阻力位和支撑位"""
    positions = peak_info["positions"]
    heights   = peak_info["heights"]

    resistance = None
    support    = None

    for price, h in zip(positions, heights):
        if price > close:
            if resistance is None or h > resistance["percent"]:
                resistance = {"price": round(price, 2), "percent": round(h, 2)}
        else:
            if support is None or h > support["percent"]:
                support = {"price": round(price, 2), "percent": round(h, 2)}

    return {
        "resistance": resistance,
        "support": support,
        "resistance_distance_pct": round((resistance["price"] - close) / close * 100, 2) if resistance else None,
        "support_distance_pct": round((close - support["price"]) / close * 100, 2) if support else None,
    }


def _compute_weighted_skewness(prices: np.ndarray, percents: np.ndarray) -> float:
    """加权偏度 (Fisher-Pearson 标准化矩系数)"""
    w = np.maximum(percents, 1e-9)
    mu = np.average(prices, weights=w)
    sigma = np.sqrt(np.average((prices - mu) ** 2, weights=w))
    if sigma < 1e-9:
        return 0.0
    skew = np.average((prices - mu) ** 3, weights=w) / (sigma ** 3)
    return round(float(skew), 3)


def _compute_weighted_kurtosis(prices: np.ndarray, percents: np.ndarray) -> float:
    """加权超额峰度 (excess kurtosis)"""
    w = np.maximum(percents, 1e-9)
    mu = np.average(prices, weights=w)
    sigma = np.sqrt(np.average((prices - mu) ** 2, weights=w))
    if sigma < 1e-9:
        return 0.0
    kurt = np.average((prices - mu) ** 4, weights=w) / (sigma ** 4) - 3.0
    return round(float(kurt), 3)


def _compute_gradient(prices: np.ndarray, percents: np.ndarray) -> float:
    """
    筹码密度梯度: 相邻价位筹码占比的平均变化率
    高梯度 = 筹码分布有明显断层 (sharp transitions)
    低梯度 = 筹码分布平滑渐变
    """
    if len(percents) < 2:
        return 0.0
    diffs = np.abs(np.diff(percents))
    # 归一化: 平均价差变化 / 平均筹码占比
    avg_diff  = float(np.mean(diffs))
    avg_pct   = float(np.mean(percents)) if np.mean(percents) > 0 else 1.0
    gradient  = round(avg_diff / avg_pct, 3)
    return gradient


def _compute_concentration_width(prices: np.ndarray, percents: np.ndarray,
                                  pct_level: float = 90) -> float:
    """
    计算包含 pct_level% 筹码的价格宽度 (相对于加权平均成本的百分比)

    Args:
        pct_level: 如 70 表示找到包含70%筹码的最窄价格区间
    """
    if len(prices) < 3:
        return 0.0

    sorted_idx = np.argsort(prices)
    sorted_prices  = prices[sorted_idx]
    sorted_percents = percents[sorted_idx]

    total = float(sorted_percents.sum())
    if total < 1e-9:
        return 0.0

    target = total * pct_level / 100.0
    cum = 0.0
    best_width = float('inf')
    best_range = None

    # 滑动窗口寻找包含target筹码的最窄区间
    left = 0
    for right in range(len(sorted_prices)):
        cum += float(sorted_percents[right])
        while cum - float(sorted_percents[left]) >= target:
            cum -= float(sorted_percents[left])
            left += 1
        if cum >= target:
            w = float(sorted_prices[right] - sorted_prices[left])
            if w < best_width:
                best_width = w
                best_range = (float(sorted_prices[left]), float(sorted_prices[right]))

    if best_range is None:
        return 0.0

    # 返回相对宽度 (%)
    mid_price = (best_range[0] + best_range[1]) / 2
    width_pct = round(best_width / mid_price * 100, 2) if mid_price > 0 else 0
    # 极小宽度(筹码高度集中在单一价位)标注为 0.01 避免输出 0.0 引起误解
    return max(0.01, width_pct) if best_width < 0.001 else width_pct


def _compute_chip_entropy(percents: np.ndarray) -> float:
    """筹码分布的信息熵 (bits)，值越大分布越分散"""
    p = np.maximum(percents, 1e-9)
    p = p / p.sum()
    entropy = -np.sum(p * np.log2(p))
    return round(float(entropy), 3)


def compute_chip_metrics(df_cyq: pd.DataFrame, close: float) -> Optional[dict]:
    """
    从 cyq_chips 单日数据计算全量筹码指标 (v2.1 增强版)

    新增:
      - 局部极大值峰值检测 (morphology / resistance / support)
      - 加权偏度 (skewness) / 峰度 (kurtosis)
      - 筹码密度梯度 (gradient)
      - 70%/90% 集中宽度 (width_70 / width_90)
      - 分布熵 (entropy)
      - 三峰支配度 / 峰熵 (triple_peak_dominance / peak_entropy)
    """
    if len(df_cyq) < 3:
        return None

    # ── 基础数据 ──
    df = df_cyq.sort_values('percent', ascending=False).copy()
    arr_price   = df['price'].values.astype(float)
    arr_percent = df['percent'].values.astype(float)

    # 同时维护按价格排序的数组 (给梯度/宽度/峰值用)
    df_sorted = df_cyq.sort_values('price').copy()
    arr_p_sorted = df_sorted['price'].values.astype(float)
    arr_pt_sorted = df_sorted['percent'].values.astype(float)

    # ── ★ 局部极大值峰值检测 (先算，用于统一P1/P2/P3) ──
    peak_info = _detect_local_peaks(arr_p_sorted, arr_pt_sorted,
                                    min_height=0.5, min_distance=0.02)

    # ── 三峰: 优先用局部极大值，不足3个则从df.head()补 ──
    detected_positions = peak_info["positions"]
    detected_heights   = peak_info["heights"]
    n_detected = len(detected_positions)

    # 构建 (price, percent, source) 三元组
    peak_triplets = []
    for i in range(n_detected):
        peak_triplets.append((detected_positions[i], detected_heights[i], "peak"))

    # 若不足3个，从 df 中补充 (排除已检测到的峰附近 ±5% 区间的)
    if n_detected < 3:
        exclude_mask = np.zeros(len(df), dtype=bool)
        for dp in detected_positions:
            exclude_mask |= ((df['price'] >= dp * 0.95) & (df['price'] <= dp * 1.05))
        supplement = df[~exclude_mask].head(3 - n_detected)
        for _, row in supplement.iterrows():
            peak_triplets.append((float(row['price']), float(row['percent']), "supplement"))

    # 按 percent 降序取前3
    peak_triplets.sort(key=lambda x: x[1], reverse=True)
    peak_triplets = peak_triplets[:3]

    # ★ 防御: 不足 3 个用 (0, 0, "missing") 占位, 避免 IndexError
    while len(peak_triplets) < 3:
        peak_triplets.append((0.0, 0.0, "missing"))

    p1, p1_pct = peak_triplets[0][0], peak_triplets[0][1]
    p2, p2_pct = peak_triplets[1][0], peak_triplets[1][1]
    p3, p3_pct = peak_triplets[2][0], peak_triplets[2][1]
    peak_sources = [peak_triplets[0][2], peak_triplets[1][2], peak_triplets[2][2]]

    # ── 集中度 ──
    tpc  = round(p1_pct + p2_pct + p3_pct, 2)
    top3 = tpc
    top5 = round(float(df.head(5)['percent'].sum()), 2)
    top10 = round(float(df.head(10)['percent'].sum()), 2)

    # ── 宽度: 三峰价格极差 / 最低峰价 × 100 ──
    mn_peak, mx_peak = min(p1, p2, p3), max(p1, p2, p3)
    width = round((mx_peak - mn_peak) / mn_peak * 100, 2) if mn_peak > 0 else 0

    # ── dist / tp3 / gap / winner / weight_avg ──
    dist = round((close - p1) / p1 * 100, 2) if p1 > 0 else 0
    band = 0.03
    lo, hi = close * (1 - band), close * (1 + band)
    tp3 = round(float(df[(df['price'] >= lo) & (df['price'] <= hi)]['percent'].sum()), 2)
    gap_pct = round(abs(p1 - p2) / p1 * 100, 2) if p1 > 0 else 0
    winner = round(float(df[df['price'] <= close]['percent'].sum()), 2)
    total_pct = float(df['percent'].sum())
    weight_avg = round(float((df['price'] * df['percent']).sum() / total_pct), 2) if total_pct > 0 else 0
    # ★ 修复: 中位成本价必须按价格升序找 cumsum 50% 处的价格 (用 arr_p_sorted)
    if len(arr_p_sorted) > 0 and arr_pt_sorted.sum() > 0:
        cumsum_sorted = np.cumsum(arr_pt_sorted)
        half_total = cumsum_sorted[-1] / 2.0
        median_idx = int(np.searchsorted(cumsum_sorted, half_total))
        median_idx = min(median_idx, len(arr_p_sorted) - 1)
        median_price = round(float(arr_p_sorted[median_idx]), 2)
    else:
        median_price = weight_avg if weight_avg > 0 else close
    gap_12 = round(abs(p1 - p2), 2)
    gap_23 = round(abs(p2 - p3), 2)
    peaks_below = len([p for p in [p1, p2, p3] if p <= close])

    # ── 形态分类 (基于局部极大值) ──
    morphology = _classify_morphology(peak_info, tpc, width)
    n_peaks = len(peak_info["positions"])

    # ── ★ 新增: 阻力位 / 支撑位 ──
    rs = _find_resistance_support(peak_info, close)

    # ── ★ 新增: 加权偏度 / 峰度 ──
    skewness = _compute_weighted_skewness(arr_price, arr_percent)
    kurtosis = _compute_weighted_kurtosis(arr_price, arr_percent)

    # ── ★ 新增: 筹码密度梯度 ──
    gradient = _compute_gradient(arr_p_sorted, arr_pt_sorted)

    # ── ★ 新增: 70% / 90% 集中宽度 ──
    width_70 = _compute_concentration_width(arr_p_sorted, arr_pt_sorted, 70)
    width_90 = _compute_concentration_width(arr_p_sorted, arr_pt_sorted, 90)

    # ── ★ 新增: 分布熵 ──
    entropy = _compute_chip_entropy(arr_percent)

    # ── ★ 新增: 三峰集中度细化 ──
    # P1 支配度: P1占比 / 三峰总占比 (值越高 P1越主导)
    p1_dominance = round(p1_pct / tpc, 3) if tpc > 0 else 0
    # 峰熵: 三峰之间分布的均匀程度 (越小越不均匀 = P1越突出)
    peak_weights = np.array([p1_pct, p2_pct, p3_pct])
    peak_weights = np.maximum(peak_weights, 1e-9)
    peak_weights = peak_weights / peak_weights.sum()
    peak_entropy = round(float(-np.sum(peak_weights * np.log2(peak_weights))), 3)

    # ── 偏度方向提示 ──
    if skewness > 0.3:
        skew_hint = f"右偏+{skewness} (套牢盘重)"
    elif skewness < -0.3:
        skew_hint = f"左偏{skewness} (获利盘重)"
    else:
        skew_hint = f"近似对称{skewness}"

    # ── 峰度解读 ──
    if kurtosis > 2:
        kurt_hint = f"尖峰{kurtosis} (筹码高度集中)"
    elif kurtosis > 0:
        kurt_hint = f"略尖{kurtosis} (偏集中)"
    elif kurtosis > -1:
        kurt_hint = f"近正态{kurtosis}"
    else:
        kurt_hint = f"扁平{kurtosis} (筹码分散)"

    # ── 梯度解读 ──
    if gradient > 0.5:
        grad_hint = "断层明显(有筹码真空区)"
    elif gradient > 0.2:
        grad_hint = "中等过渡"
    else:
        grad_hint = "平滑分布"

    return {
        # 原有指标
        "p1": p1, "p1_pct": p1_pct,
        "p2": p2, "p2_pct": p2_pct,
        "p3": p3, "p3_pct": p3_pct,
        "tpc": tpc, "top3": top3, "top5": top5, "top10": top10,
        "width": width,
        "dist": dist,
        "tp3": tp3,
        "gap_pct": gap_pct,
        "gap_12": gap_12, "gap_23": gap_23,
        "winner": winner,
        "weight_avg": weight_avg,
        "median_price": median_price,
        "skew_hint": skew_hint,
        "peaks_below_close": peaks_below,

        # ★ 新增: 形态识别
        "morphology": morphology,
        "n_peaks": n_peaks,
        "peak_positions": [round(p, 2) for p in peak_info["positions"]],
        "peak_heights":   [round(h, 2) for h in peak_info["heights"]],

        # ★ 新增: 阻力支撑
        "resistance": rs["resistance"],
        "support": rs["support"],
        "resistance_distance_pct": rs["resistance_distance_pct"],
        "support_distance_pct": rs["support_distance_pct"],

        # ★ 新增: 分布统计
        "skewness": skewness,
        "kurtosis": kurtosis,
        "kurt_hint": kurt_hint,
        "gradient": gradient,
        "grad_hint": grad_hint,
        "entropy": entropy,

        # ★ 新增: 集中宽度
        "width_70": width_70,
        "width_90": width_90,

        # ★ 新增: 三峰结构
        "p1_dominance": p1_dominance,
        "peak_entropy": peak_entropy,
    }


# ══════════════════════════════════════════════════════
# 引擎②: emoji 行为标注 (基于 ΔP1 + ΔTop5 双向判定)
# ══════════════════════════════════════════════════════

def judge_emoji(prev: Optional[dict], curr: dict) -> tuple:
    """
    旧版 emoji 引擎 (与 v5.6.6 chip_evolution.py 对齐)
    基于 ΔP1 (峰位漂移) + ΔTop5 (集中度变化) 的双向判定
    """
    if prev is None:
        return ("🏗️", "建仓(初始)", {"note": "首日"})

    d_p1   = curr['p1']   - prev['p1']
    d_top5 = curr['top5'] - prev['top5']
    d_p1_pct    = curr['p1_pct'] - prev['p1_pct']
    d_dist      = curr['dist'] - prev['dist']
    d_winner    = curr['winner'] - prev['winner']

    # 派发: P1 大幅下移 + 集中度崩溃
    if d_p1 < -2 and d_top5 < -3:
        return ("🔴", "派发", {"dP1": d_p1, "dTop5": d_top5, "note": "P1下移+集中度崩溃"})

    # 预警: 集中度骤降 (多头力竭信号)
    if d_top5 < -10:
        return ("⚠️", "预警", {"dTop5": d_top5, "note": "Top5骤降>10%"})

    # 建仓: P1 大幅上移 + 集中度快速提升
    if d_p1 > 2 and d_top5 > 3:
        return ("🏗️", "建仓", {"dP1": d_p1, "dTop5": d_top5})

    # 锁仓: P1 几乎不动 + 集中度小幅提升
    if abs(d_p1) < 0.5 and d_top5 > 1:
        return ("🔒", "锁仓", {"dP1": d_p1, "dTop5": d_top5, "note": "P1稳定+集中度抬升"})

    # 震仓: P1 几乎不动 + 集中度小幅下降 (洗出不坚定筹码)
    if abs(d_p1) < 0.5 and d_top5 < -1:
        return ("🌊", "震仓", {"dP1": d_p1, "dTop5": d_top5, "note": "P1稳定+集中度小幅下降"})

    # 推升: P1 温和上移 + 集中度稳定
    if d_p1 > 1 and abs(d_top5) < 2:
        return ("📈", "推升", {"dP1": d_p1, "dTop5": d_top5})

    # 推升 (弱)
    if d_p1 > 0.5:
        return ("📈", "推升(弱)", {"dP1": d_p1})

    # 震仓 (弱)
    if d_p1 < -0.5:
        return ("🌊", "震仓(弱)", {"dP1": d_p1})

    return ("🔒", "锁仓(弱)", {"dP1": d_p1, "note": "无明显行为"})


# ══════════════════════════════════════════════════════
# 引擎③: 锁仓三条件判定
# ══════════════════════════════════════════════════════

def assess_locking(metrics_list: list) -> dict:
    """
    锁仓三条件 (v5.6.6 标准):
    ① P1 稳定: 最近 5 日 P1 range/avg < 1%
    ② tp3 提升: 最新 tp3 > 5 日前
    ③ dist 转正: 最新 dist > 0

    以及新增:
    ④ Top5 集中度: 最近日 vs 5日前
    ⑤ winner 趋势: 最近5日均值 vs 前5日
    """
    n = len(metrics_list)
    if n < 6:
        return {"error": "数据不足，至少需要 6 个交易日"}
    
    recent5 = metrics_list[-5:]
    early5  = metrics_list[-min(10, n):-5] if n >= 10 else metrics_list[:n//2]
    
    # ① P1 稳定性
    p1s = [m['p1'] for m in recent5]
    p1_range = max(p1s) - min(p1s)
    p1_avg = sum(p1s) / len(p1s)
    p1_stab = round(p1_range / p1_avg * 100, 3) if p1_avg > 0 else 999
    p1_ok = p1_stab < 1.0
    
    # ② tp3 提升
    tp3_now  = metrics_list[-1]['tp3']
    tp3_5ago = metrics_list[-5]['tp3'] if n >= 5 else tp3_now
    tp3_ok = tp3_now > tp3_5ago
    
    # ③ dist 转正
    dist_now = metrics_list[-1]['dist']
    dist_ok = dist_now > 0
    
    # ④ Top5 集中度变化
    top5_now  = metrics_list[-1]['top5']
    top5_5ago = metrics_list[-5]['top5'] if n >= 5 else top5_now
    top5_delta = round(top5_now - top5_5ago, 2)
    top5_ok = top5_delta > 0
    
    # ⑤ winner 趋势
    winner_recent = sum(m['winner'] for m in recent5) / len(recent5)
    winner_early  = sum(m['winner'] for m in early5) / len(early5) if early5 else winner_recent
    winner_delta  = round(winner_recent - winner_early, 2)
    winner_ok = winner_delta > 0
    
    # ⑥ tpc 趋势
    tpc_now  = metrics_list[-1]['tpc']
    tpc_5ago = metrics_list[-5]['tpc'] if n >= 5 else tpc_now
    tpc_delta = round(tpc_now - tpc_5ago, 2)
    tpc_ok = tpc_delta > 0
    
    # ── 综合 ──
    conditions = {
        "p1_stability": p1_ok,
        "tp3_improvement": tp3_ok,
        "dist_positive": dist_ok,
        "top5_trend": top5_ok,
        "winner_trend": winner_ok,
        "tpc_trend": tpc_ok,
    }
    passed = sum(conditions.values())
    total  = len(conditions)
    
    if passed >= 5:
        overall = "强锁仓"
    elif passed >= 4:
        overall = "中等锁仓"
    elif passed >= 3:
        overall = "弱锁仓"
    else:
        overall = "未锁仓"
    
    return {
        "p1": {
            "status": "✅" if p1_ok else "❌",
            "stab_pct": p1_stab,
            "threshold": "<1.0%",
            "verdict": f"P1 5日 range/avg={p1_stab:.3f}% {'≤' if p1_ok else '>'} 1%"
        },
        "tp3": {
            "status": "✅" if tp3_ok else "❌",
            "current": tp3_now,
            "5days_ago": tp3_5ago,
            "delta": round(tp3_now - tp3_5ago, 2),
            "verdict": f"tp3 {tp3_5ago}%→{tp3_now}% (Δ{tp3_now-tp3_5ago:+.2f})"
        },
        "dist": {
            "status": "✅" if dist_ok else "❌",
            "value": dist_now,
            "verdict": f"dist={dist_now:+.2f}% {'>0' if dist_ok else '≤0'}"
        },
        "top5": {
            "status": "✅" if top5_ok else "⚠️",
            "current": top5_now,
            "5days_ago": top5_5ago,
            "delta": top5_delta,
            "verdict": f"Top5 {top5_5ago}%→{top5_now}% (Δ{top5_delta:+.2f})"
        },
        "winner": {
            "status": "✅" if winner_ok else "⚠️",
            "recent_avg": round(winner_recent, 1),
            "early_avg": round(winner_early, 1),
            "delta": winner_delta,
            "verdict": f"winner {winner_early:.1f}%→{winner_recent:.1f}% (Δ{winner_delta:+.1f})"
        },
        "tpc": {
            "status": "✅" if tpc_ok else "⚠️",
            "current": tpc_now,
            "5days_ago": tpc_5ago,
            "delta": tpc_delta,
            "verdict": f"TPC {tpc_5ago}%→{tpc_now}% (Δ{tpc_delta:+.2f})"
        },
        "overall": f"{overall} ({passed}/{total})",
        "locked_score": f"{passed}/{total}",
    }


# ══════════════════════════════════════════════════════
# 引擎④: 派发5维量化评分
# ══════════════════════════════════════════════════════

def dispatch_score(metrics_list: list) -> dict:
    """派发5维量化评分 (v5.6.6)"""
    n = len(metrics_list)
    if n < 10:
        return {"total": 0, "verdict": "数据不足"}
    
    mid = n // 2
    m_now  = metrics_list[-1]
    m_5ago = metrics_list[-5]
    m_first_half = metrics_list[:mid]
    m_second_half = metrics_list[mid:]
    
    # D1: P1占比与价格方向反向 (价格上涨但 P1 占比下降 = 主力出货)
    chg5 = (m_now['close'] - m_5ago['close']) / m_5ago['close'] * 100
    # ★ 修复命名: 这是"前半/后半窗口"均值 (n//2 天), 不是 5 日
    prev_half_p1_avg = sum(x['p1_pct'] for x in m_first_half) / len(m_first_half)
    last_half_p1_avg = sum(x['p1_pct'] for x in m_second_half) / len(m_second_half)
    d1 = 1 if chg5 < -7 and (last_half_p1_avg - prev_half_p1_avg) > 30 else 0
    
    # D2: 加权成本与价格方向反向
    prev_wavg = m_5ago['weight_avg']
    wavg_chg = (m_now['weight_avg'] - prev_wavg) / prev_wavg * 100 if prev_wavg > 0 else 0
    price_chg = (m_now['close'] / m_5ago['close'] - 1) * 100
    d2 = 1 if price_chg >= 5 and wavg_chg < 2 else 0
    
    # D3: Top5 两阶段对比 (集中度从高→低 = 分散 = 出货信号)
    top5_early = sum(x['top5'] for x in m_first_half) / len(m_first_half)
    top5_late  = sum(x['top5'] for x in m_second_half) / len(m_second_half)
    d3 = 1 if top5_early >= 35 and top5_late <= top5_early * 0.7 else 0
    
    # D4: 连续3日 close < 加权成本
    below_count = sum(1 for m in metrics_list[-3:] if m['close'] < m['weight_avg'])
    d4 = 1 if below_count >= 3 else 0
    
    # D5: 内部人动作 (暂不支持)
    d5 = 0
    
    total = d1 + d2 + d3 + d4 + d5
    
    dispatch = "派发（清仓）" if total >= 4 else ("警惕（减仓1/3）" if total == 3 else "健康（按计划持有/建仓）")
    
    return {
        "d1_p1_reversal": {
            "score": d1,
            "detail": f"5日跌幅{chg5:+.2f}%, 前期P1占比{prev_half_p1_avg:.1f}%→后期{last_half_p1_avg:.1f}%",
        },
        "d2_cost_reversal": {
            "score": d2,
            "detail": f"价涨{price_chg:+.2f}% vs 成本涨{wavg_chg:+.2f}%",
        },
        "d3_top5_dispersion": {
            "score": d3,
            "detail": f"前期Top5={top5_early:.1f}% → 后期={top5_late:.1f}%",
        },
        "d4_price_below_cost": {
            "score": d4,
            "detail": f"连续{below_count}/3日收盘 < 加权成本",
        },
        "d5_insider": {
            "score": d5,
            "detail": "内部人动作暂未量化",
        },
        "total": total,
        "verdict": dispatch,
    }


# ══════════════════════════════════════════════════════
# 引擎⑤: 技术面三策略打分 (复用 v1.0 逻辑，改进)
# ══════════════════════════════════════════════════════

def score_tech(df_factor: pd.DataFrame) -> dict:
    """动量/趋势/反转 三策略独立打分 + 反对票"""
    if len(df_factor) < 5:
        return {"error": "技术指标数据不足"}
    
    latest = df_factor.iloc[-1].to_dict()
    
    rsi6  = latest.get("rsi_6", 50) or 50
    rsi12 = latest.get("rsi_12", 50) or 50
    kdj_k = latest.get("kdj_k", 50) or 50
    kdj_j = latest.get("kdj_j", 50) or 50
    macd_dif = latest.get("macd_dif", 0) or 0
    macd_dea = latest.get("macd_dea", 0) or 0
    macd_bar = latest.get("macd", 0) or 0
    close_p  = latest.get("close", 0)
    boll_u   = latest.get("boll_upper", 0)
    boll_m   = latest.get("boll_mid", 0)
    boll_l   = latest.get("boll_lower", 0)
    cci      = latest.get("cci", 0) or 0
    
    # ── 动量策略 (RSI + KDJ) ──
    if 40 <= rsi6 <= 60:
        momentum_score, momentum_label = 4, "RSI中性偏强"
    elif 60 < rsi6 < 75:
        momentum_score, momentum_label = 5, "RSI偏强"
    elif rsi6 >= 75:
        momentum_score, momentum_label = 2, "RSI超买→扣分"
    else:
        momentum_score, momentum_label = 2, "RSI偏弱"
    
    if kdj_j > 100:
        momentum_score = max(momentum_score - 1, 1)
    elif kdj_j < 0:
        momentum_score = max(momentum_score - 1, 1)
    momentum_score = max(1, min(5, momentum_score))
    
    # ── 趋势策略 (MACD + BOLL) ──
    if macd_dif > macd_dea and macd_bar > 0:
        trend_score, trend_label = 5, "MACD多头"
    elif macd_dif > macd_dea and macd_bar < 0:
        trend_score, trend_label = 4, "MACD金叉待放"
    else:
        trend_score, trend_label = 2, "MACD空头"
    
    if boll_u and close_p:
        boll_pos = (close_p - boll_l) / (boll_u - boll_l) * 100
        if boll_pos > 90:
            trend_score = max(trend_score - 1, 1)
        elif boll_pos < 15:
            trend_score = max(trend_score - 1, 1)
    trend_score = max(1, min(5, trend_score))
    
    # ── 反转策略 (顶背离 + KDJ超买 + RSI超买) ──
    reversal_score = 2
    reversal_factors = {}
    
    prices = df_factor["close"].values[-10:]
    rsis   = df_factor["rsi_6"].values[-10:]
    if len(prices) >= 5:
        p_peak = int(prices.argmax())
        r_peak = int(rsis.argmax())
        if p_peak != r_peak and prices[p_peak] > prices[-1]:
            reversal_factors["顶背离"] = f"价峰在{df_factor.iloc[-(10-p_peak)]['trade_date']} RSI峰在{df_factor.iloc[-(10-r_peak)]['trade_date']}"
            reversal_score = 4
    
    if kdj_j > 90:
        reversal_factors["KDJ超买"] = f"J={kdj_j:.1f}>90"
        reversal_score = max(reversal_score, 4)
    if rsi6 > 70:
        reversal_factors["RSI超买"] = f"RSI6={rsi6:.1f}>70"
        reversal_score = max(reversal_score, 4)
    if cci > 200:
        reversal_factors["CCI极端"] = f"CCI={cci:.0f}>200"
        reversal_score = max(reversal_score, 4)
    
    reversal_score = max(1, min(5, reversal_score))
    
    # ── 加权 ──
    weighted = round(momentum_score * 0.35 + trend_score * 0.40 + reversal_score * 0.25, 2)
    resonance = sum([momentum_score >= 4, trend_score >= 4, reversal_score <= 2])
    stars = "⭐" * resonance + ("☆" * (3 - resonance)) if resonance >= 1 else "⭐"
    
    # ── 反对票 ──
    opposition = []
    if kdj_j > 80:
        opposition.append(f"KDJ-J={kdj_j:.1f}>80 超买区")
    if rsi6 > 65:
        opposition.append(f"RSI(6)={rsi6:.1f} 接近超买")
    if boll_u and close_p and (boll_u - boll_l) > 1e-6:
        boll_pos = (close_p - boll_l) / (boll_u - boll_l) * 100
        if boll_pos > 85:
            opposition.append(f"距BOLL上轨仅{100-boll_pos:.1f}%")
    if macd_dif < macd_dea:
        opposition.append("MACD 空头排列")
    if cci > 150:
        opposition.append(f"CCI={cci:.0f} 超买")
    
    return {
        "momentum": {"score": momentum_score, "label": momentum_label,
                     "rsi6": rsi6, "rsi12": rsi12, "kdj_k": kdj_k, "kdj_j": kdj_j},
        "trend": {"score": trend_score, "label": trend_label,
                  "macd_dif": macd_dif, "macd_dea": macd_dea, "macd_bar": macd_bar,
                  "boll_u": boll_u, "boll_m": boll_m, "boll_l": boll_l, "cci": cci},
        "reversal": {"score": reversal_score, "factors": reversal_factors},
        "weighted": weighted,
        "resonance_level": resonance,
        "stars": stars,
        "opposition_votes": opposition if opposition else ["无"]
    }


# ══════════════════════════════════════════════════════
# 引擎⑥: 经典量化辅助指标 (CMF / ADX / ATR / VWAP)
# ══════════════════════════════════════════════════════

def compute_cmf(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                volume: np.ndarray, period: int = 21) -> np.ndarray:
    """
    Chaikin Money Flow — 蔡金资金流向指标
    结合价格在日内位置 + 成交量, 归一化到 [-1, +1]
    正值 = 收盘偏高位 + 放量 (吸筹/推升)
    负值 = 收盘偏低位 + 放量 (出货/打压)
    """
    n = len(close)
    if n < period + 1:
        return np.full(n, np.nan)

    hl_diff = high - low
    hl_diff = np.where(hl_diff < 1e-9, 1.0, hl_diff)
    mfm = ((close - low) - (high - close)) / hl_diff
    mfv = mfm * volume

    cmf = np.full(n, np.nan)
    for i in range(period - 1, n):
        cmf[i] = np.sum(mfv[i - period + 1:i + 1]) / max(np.sum(volume[i - period + 1:i + 1]), 1)
    return cmf


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                period: int = 14) -> dict:
    """
    Average Directional Index — 平均趋向指数
    返回: adx, plus_di, minus_di
    ADX > 25 → 趋势市, ADX < 20 → 震荡市
    +DI > -DI → 多头主导, 反之为空头
    """
    n = len(close)
    nan_arr = np.full(n, np.nan)

    if n < period * 2:
        return {"adx": nan_arr, "pdi": nan_arr, "mdi": nan_arr}

    # True Range
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]

    # Directional Movement
    up_move = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    up_move[0] = down_move[0] = 0

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # Wilder's smoothing (first valid SMA, then EMA-like)
    def wilder_smooth(arr, period):
        smoothed = arr.copy().astype(float)
        # 找第一个包含 >= period 个非 NaN 的窗口
        valid_mask = ~np.isnan(arr)
        cum_valid = np.cumsum(valid_mask)
        first_idx = None
        for i in range(period - 1, n):
            win_valid = cum_valid[i] - (cum_valid[i - period] if i >= period else 0)
            if win_valid >= period:
                first_idx = i
                break
        if first_idx is None:
            return np.full(n, np.nan)

        smoothed[first_idx] = np.nanmean(arr[first_idx - period + 1:first_idx + 1])
        start = first_idx + 1
        for i in range(start, n):
            prev = smoothed[i - 1]
            if np.isnan(prev):
                smoothed[i] = np.nan
            else:
                val = arr[i] if not np.isnan(arr[i]) else prev
                smoothed[i] = (prev * (period - 1) + val) / period
        return smoothed

    tr_smooth  = wilder_smooth(tr, period)
    pdi_smooth = wilder_smooth(plus_dm, period)
    mdi_smooth = wilder_smooth(minus_dm, period)

    pdi = 100 * pdi_smooth / np.maximum(tr_smooth, 1e-9)
    mdi = 100 * mdi_smooth / np.maximum(tr_smooth, 1e-9)
    dx = 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9)

    adx = wilder_smooth(dx, period)

    return {"adx": np.round(adx, 1), "pdi": np.round(pdi, 1), "mdi": np.round(mdi, 1)}


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                period: int = 14) -> np.ndarray:
    """Average True Range — 平均真实波幅"""
    n = len(close)
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]

    atr = np.full(n, np.nan)
    for i in range(period - 1, n):
        if i == period - 1:
            atr[i] = np.mean(tr[:period])
        else:
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return np.round(atr, 2)


# ══════════════════════════════════════════════════════
# 引擎⑦: 滚动分位数归一化 (自适应阈值，跨股票可比)
# ══════════════════════════════════════════════════════

def compute_rolling_percentile(series: np.ndarray, window: int = 60,
                               min_periods: int = 20) -> np.ndarray:
    """
    滚动分位数排名: 每个值在其过去 window 天中的百分位 (0~100)

    例: 今天的 TPC=30.67%，在过去60天排在第 85 百分位 → TPC 偏高
    这替代了硬编码的 "TPC > 35 算集中" 之类的主观阈值
    """
    n = len(series)
    ranks = np.full(n, np.nan)
    for i in range(min_periods - 1, n):
        start = max(0, i - window + 1)
        lookback = series[start:i + 1]
        ranks[i] = np.searchsorted(np.sort(lookback), series[i]) / len(lookback) * 100
    return np.round(ranks, 1)


def build_chip_percentile_context(all_metrics: list, analysis_list: list) -> dict:
    """
    基于全量历史数据, 为分析窗口中的每项筹码指标计算滚动分位数

    Args:
        all_metrics: 全量历史指标列表 (>60项)
        analysis_list: 分析窗口的指标列表 (14项)

    Returns:
        dict: 包含各指标的最新区间统计和最新分位数排名
    """
    n_all = len(all_metrics)
    n_win = len(analysis_list)
    if n_all < 30:
        return {"warning": "历史数据不足30日，无法计算可靠分位数"}

    window = min(60, n_all)

    metric_names = [
        "tpc", "top3", "top5", "top10", "p1_pct", "p2_pct", "p3_pct",
        "width", "width_70", "width_90", "dist", "tp3", "gap_pct",
        "winner", "weight_avg", "skewness", "kurtosis", "gradient",
        "entropy", "p1_dominance", "peak_entropy"
    ]

    result = {}
    last_full_series_len = 0  # ★ 防御: 避免 baseline_days 依赖 locals() 探测
    for metric in metric_names:
        # 从全量历史抽取该指标的时间序列
        full_series = []
        for m in all_metrics:
            val = m.get(metric)
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                full_series.append(float(val))

        if len(full_series) < 30:
            continue

        arr = np.array(full_series)
        pct_ranks = compute_rolling_percentile(arr, window=window)

        # 取分析窗口内的值
        if n_win > 0 and len(pct_ranks) >= n_win:
            win_ranks = pct_ranks[-n_win:]
            latest_val = full_series[-1]
            latest_pct = pct_ranks[-1]
        else:
            win_ranks = pct_ranks[-min(n_win, len(pct_ranks)):] if len(pct_ranks) > 0 else np.array([])
            latest_val = full_series[-1] if full_series else 0
            latest_pct = pct_ranks[-1] if len(pct_ranks) > 0 else 50

        # 分位水平标签
        if np.isnan(latest_pct):
            level = "无数据"
        elif latest_pct >= 85:
            level = "极高(>85%分位)"
        elif latest_pct >= 70:
            level = "偏高(70-85%分位)"
        elif latest_pct >= 30:
            level = "中等(30-70%分位)"
        elif latest_pct >= 15:
            level = "偏低(15-30%分位)"
        else:
            level = "极低(<15%分位)"

        result[metric] = {
            "latest_value": round(latest_val, 4) if isinstance(latest_val, float) else latest_val,
            "latest_percentile": latest_pct if not np.isnan(latest_pct) else None,
            "level": level,
            "window_percentiles": {
                "min": round(float(np.nanmin(win_ranks)), 1) if len(win_ranks) > 0 else None,
                "max": round(float(np.nanmax(win_ranks)), 1) if len(win_ranks) > 0 else None,
                "median": round(float(np.nanmedian(win_ranks)), 1) if len(win_ranks) > 0 else None,
                "days_extreme": int(np.sum((~np.isnan(win_ranks)) &
                                     ((win_ranks >= 85) | (win_ranks <= 15)))) if len(win_ranks) > 0 else 0,
            },
            "history_range": {
                "min": round(float(np.min(arr)), 4) if len(arr) > 0 else 0,
                "max": round(float(np.max(arr)), 4) if len(arr) > 0 else 0,
                "mean": round(float(np.mean(arr)), 4) if len(arr) > 0 else 0,
                "std": round(float(np.std(arr)), 4) if len(arr) > 0 else 0,
            }
        }

    # 标准化 z-score (用于跨股票比较)
    latest_z = {}
    for metric in metric_names:
        if metric in result:
            info = result[metric]
            if info["history_range"]["std"] > 1e-9:
                z = (info["latest_value"] - info["history_range"]["mean"]) / info["history_range"]["std"]
                latest_z[metric] = round(z, 2)
            else:
                latest_z[metric] = 0.0

    return {
        "metrics_percentiles": result,
        "latest_z_scores": latest_z,
        "baseline_days": last_full_series_len if last_full_series_len >= 30 else n_all,
    }


# ══════════════════════════════════════════════════════
# 引擎⑧: 价格-筹码背离检测 (辅助验证「逻辑预期差」正在被资金兑现)
# ══════════════════════════════════════════════════════

def detect_divergence(metrics_list: list, pct_context: dict,
                      classic_indicators: dict) -> dict:
    """
    检测四类价格-筹码背离, 为 Layer1 逻辑预期差提供 Layer2.5 验证:
      - 如果逻辑面找到好标的, 且这里检测到背离 → 主力也在暗中行动
      - 如果逻辑面找到好标的, 但这里无背离 → 逻辑尚未被市场认知, 需等待

    背离①: 价格-筹码背离 (暗中建仓)  [权重 35%]
      价格弱势横盘/微跌 + 筹码暗中集中(TPC↑/width_90↓/entropy↓)
      ★ ATR 自适应阈值: 改用近期价格振幅分位替代硬编码 2%

    背离②: 资金-价格背离 (压盘吸筹)  [权重 30%]
      CMF资金持续流入 + 价格不涨或微跌

    背离③: 形态-认知背离 (表散实聚)  [权重 20%]
      表面多峰发散(n_peaks≥3) + 实际P1在暗中增强(P1↑/p1_pct↑)

    背离④: 时间-认知背离 (筹码领先价格) [权重 15%] ★ 新增
      筹码在3~5天前就已高度集中, 但价格至今未反应
      → 主力布局已完成, 只差催化 → 最有操作价值的信号

    每个背离增加 5 日回看窗口 (时序先行性检测)。
    """
    latest = metrics_list[-1]
    mp = pct_context.get("metrics_percentiles", {})
    ci  = classic_indicators

    # ── ATR 自适应价格阈值 (替代硬编码) ──
    atr_info = ci.get("atr", {})
    atr_pct  = atr_info.get("atr_pct_of_price", 2.0) or 2.0

    # 基于近期 price pct_change 计算振幅分位 (用于判断"价格弱")
    if len(metrics_list) >= 10:
        recent_abs_chg = [abs(m.get("pct_change", 0)) for m in metrics_list[-10:]]
        recent_abs_chg.sort()
        # 使用近期振幅的 30 分位作为 "弱势" 阈值
        weak_threshold = max(recent_abs_chg[int(len(recent_abs_chg) * 0.3)], 0.5)
        strong_threshold = max(recent_abs_chg[int(len(recent_abs_chg) * 0.7)], 2.0)
    else:
        weak_threshold = atr_pct * 0.7
        strong_threshold = atr_pct * 1.5

    signals = {}
    scores  = {}
    lookback_signals = {}  # 5日回看窗口

    # ── 背离①: 价格-筹码背离 (ATR自适应阈值) ──
    price_weak  = abs(latest.get("pct_change", 0)) < weak_threshold
    price_down  = latest.get("pct_change", 0) < 0
    tpc_pct  = mp.get("tpc", {}).get("latest_percentile", 50) or 50
    ent_pct  = mp.get("entropy", {}).get("latest_percentile", 50) or 50
    w90_pct  = mp.get("width_90", {}).get("latest_percentile", 50) or 50
    p1p_pct  = mp.get("p1_pct", {}).get("latest_percentile", 50) or 50

    chip_tightening = (tpc_pct > 60 and ent_pct < 50 and w90_pct < 50)
    chip_strong_tight = (tpc_pct > 75 and ent_pct < 35 and w90_pct < 35)

    d1_active = price_weak and chip_tightening
    d1_strong = price_down and chip_strong_tight

    # 背离强度: 价格弱 * 筹码集中度 归一化
    price_factor = max(0, (weak_threshold * 2 - abs(latest.get("pct_change", 0))) / (weak_threshold * 2))
    chip_factor  = min(tpc_pct / 80, 1.0)
    d1_score = round(min(price_factor * chip_factor * 100, 100), 0)

    # 5日回看: 筹码是否在3-5天前就已经集中
    if len(metrics_list) >= 6:
        mid_metrics = metrics_list[-6:-2]  # t-5 ~ t-3
        mid_tpc_avg = np.mean([m.get("p1_pct", 0) for m in mid_metrics])
        mid_ent_avg = np.mean([m.get("entropy", 0) for m in mid_metrics])
        d1_lookback = mid_tpc_avg > metrics_list[0].get("p1_pct", 0) * 1.2 and mid_ent_avg < metrics_list[0].get("entropy", 999)
    else:
        d1_lookback = False

    signals["price_chip_divergence"] = {
        "active": d1_active,
        "strong": d1_strong,
        "score": d1_score,
        "details": {
            "price_weak": price_weak,
            "weak_threshold": round(weak_threshold, 2),
            "atr_pct_of_price": round(atr_pct, 2),
            "tpc_percentile": tpc_pct,
            "entropy_percentile": ent_pct,
            "width_90_percentile": w90_pct,
            "p1_pct_percentile": p1p_pct,
        },
        "lookback_5d_signaled": d1_lookback,
        "interpretation": (
            "强背离+筹码领先: 价格弱势但筹码早已暗中快速集中, 主力压盘建仓已近完成"
            if d1_strong and d1_lookback else
            "强背离: 价格弱势但筹码暗中快速集中, 主力可能在压盘建仓"
            if d1_strong else
            "弱背离: 价格横盘、筹码有集中趋势, 值得跟踪"
            if d1_active else
            "无背离: 价格与筹码方向一致, 未检测到暗中建仓信号"
        ),
    }
    scores["price_chip"] = d1_score
    lookback_signals["d1"] = d1_lookback

    # ── 背离②: 资金-价格背离 ──
    cmf_val  = ci["cmf"]["latest"]
    cmf_valid = cmf_val is not None
    money_in  = cmf_valid and cmf_val > 0.05

    if len(metrics_list) >= 5:
        price_5d_chg = (metrics_list[-1]["close"] - metrics_list[-5]["close"]) / abs(metrics_list[-5]["close"]) * 100
    else:
        price_5d_chg = 0

    price_stagnant = abs(price_5d_chg) < weak_threshold * 5
    price_declining = price_5d_chg < 0

    d2_active = money_in and price_stagnant
    d2_strong = money_in and price_declining and cmf_valid and cmf_val > 0.1

    cmf_factor = min(max(cmf_val, 0) / 0.2, 1.0) if cmf_valid else 0
    d2_score = round(min(cmf_factor * (1 - min(max(price_5d_chg, 0) / (weak_threshold * 5), 1)) * 100, 100), 0)

    # 5日回看: CMF 是否在过去5天持续为正
    if ci["cmf"].get("recent_5d_positive_ratio", 0) > 0.6:
        d2_lookback = True
    else:
        d2_lookback = False

    signals["capital_price_divergence"] = {
        "active": d2_active,
        "strong": d2_strong,
        "score": d2_score,
        "details": {
            "cmf": cmf_val,
            "price_5d_chg_pct": round(price_5d_chg, 2),
            "money_inflow": money_in,
            "stagnant_threshold": round(weak_threshold * 5, 2),
        },
        "lookback_5d_signaled": d2_lookback,
        "interpretation": (
            "强背离+持续流入: CMF连续5日>0 但价格不涨反跌, 典型压盘吸筹特征"
            if d2_strong and d2_lookback else
            "强背离: 资金持续流入但价格不涨反跌, 典型压盘吸筹特征"
            if d2_strong else
            "弱背离: 资金有流入迹象但价格反应迟钝, 继续观察"
            if d2_active else
            "无背离: 资金与价格方向一致"
        ),
    }
    scores["capital_price"] = d2_score
    lookback_signals["d2"] = d2_lookback

    # ── 背离③: 形态-认知背离 ──
    n_peaks = latest.get("n_peaks", 0)
    surface_divergent = n_peaks >= 3
    p1_trend_up = False

    if len(metrics_list) >= 3:
        p1_recent = [m["p1_pct"] for m in metrics_list[-3:]]
        p1_trend_up = p1_recent[-1] > p1_recent[0]

    p1_dom_pct = mp.get("p1_dominance", {}).get("latest_percentile", 50) or 50
    core_concentrating = p1_trend_up and p1_dom_pct > 60
    core_strong_conc   = p1_trend_up and p1_dom_pct > 75

    if len(metrics_list) >= 3:
        p1_price_recent = [m["p1"] for m in metrics_list[-3:]]
        p1_price_up = p1_price_recent[-1] > p1_price_recent[0]
    else:
        p1_price_up = False

    d3_active = surface_divergent and core_concentrating
    d3_strong = surface_divergent and core_strong_conc and p1_price_up

    n_factor   = min(n_peaks / 5, 1.0) if surface_divergent else 0
    core_factor = min(p1_dom_pct / 80, 1.0)
    d3_score = round(min(n_factor * core_factor * 100, 100), 0)

    # 5日回看: 形态是否早在5天前就已多峰
    if len(metrics_list) >= 6:
        early_peaks = [m.get("n_peaks", 0) for m in metrics_list[-6:-2]]
        d3_lookback = np.mean(early_peaks) >= 3
    else:
        d3_lookback = False

    signals["morphology_cognition_divergence"] = {
        "active": d3_active,
        "strong": d3_strong,
        "score": d3_score,
        "details": {
            "n_peaks": n_peaks,
            "surface_divergent": surface_divergent,
            "p1_pct_trend_up": p1_trend_up,
            "p1_price_trend_up": p1_price_up,
            "p1_dominance_percentile": p1_dom_pct,
        },
        "lookback_5d_signaled": d3_lookback,
        "interpretation": (
            "强背离+先兆: 筹码表面多峰发散且5天前已如此, 但P1暗中增强 → 主力持续在推升中收拢筹码"
            if d3_strong and d3_lookback else
            "强背离: 筹码表面多峰发散, 但P1暗中增强且成本上移 → 主力在推升中收拢筹码"
            if d3_strong else
            "弱背离: 分布看似发散, 但核心峰有集中迹象, 关注后续演化"
            if d3_active else
            "无背离: 形态与核心峰方向一致"
        ),
    }
    scores["morphology"] = d3_score
    lookback_signals["d3"] = d3_lookback

    # ── ★ 背离④: 时间-认知背离 (筹码领先价格) ──
    d4_active = False
    d4_strong = False
    d4_score = 0
    d4_details = {}

    if len(metrics_list) >= 6:
        # 回头看 t-5~t-3: 筹码是否已经高度集中
        early = metrics_list[-6:-2]
        mid_tpc_vals = [m.get("tpc", 0) for m in early]
        mid_ent_vals = [m.get("entropy", 9) for m in early]
        mid_w90_vals = [m.get("width_90", 100) for m in early]

        mid_tpc_avg = np.mean(mid_tpc_vals)
        mid_ent_avg = np.mean(mid_ent_vals)
        mid_w90_avg = np.mean(mid_w90_vals)

        # 全量历史的均值 (作为"正常水平")
        hist_tpc_mean = np.mean([m.get("tpc", 0) for m in metrics_list])
        hist_ent_mean = np.mean([m.get("entropy", 9) for m in metrics_list])
        hist_w90_mean = np.mean([m.get("width_90", 100) for m in metrics_list])

        # 条件: 5-3天前筹码已经显著集中 (TPC > 历史均值×1.3, entropy < 历史均值×0.7)
        chip_already_tight = (mid_tpc_avg > hist_tpc_mean * 1.3 and
                              mid_ent_avg < hist_ent_mean * 0.7 and
                              mid_w90_avg < hist_w90_mean * 0.6)

        # 价格在这3-5天里没有反应 (涨幅 < 弱阈值×3)
        recent_close = [m["close"] for m in metrics_list[-4:]]  # t-3 ~ t
        price_chg_since_tight = (recent_close[-1] - recent_close[0]) / abs(recent_close[0]) * 100
        price_not_responded = abs(price_chg_since_tight) < weak_threshold * 3

        if chip_already_tight and price_not_responded:
            d4_active = True
            d4_strong = (mid_tpc_avg > hist_tpc_mean * 1.5 and
                        abs(price_chg_since_tight) < weak_threshold * 1.5)

        # 评分: 筹码领先程度 × 价格迟钝程度
        lead_factor = min(mid_tpc_avg / max(hist_tpc_mean * 2, 5), 1.0)
        lag_factor  = max(0, (weak_threshold * 3 - abs(price_chg_since_tight)) / (weak_threshold * 3))
        d4_score = round(min(lead_factor * lag_factor * 100, 100), 0)

        d4_details = {
            "chip_tight_since_t_minus_5_to_3": chip_already_tight,
            "mid_tpc_avg": round(mid_tpc_avg, 2),
            "hist_tpc_mean": round(hist_tpc_mean, 2),
            "mid_entropy_avg": round(mid_ent_avg, 3),
            "hist_entropy_mean": round(hist_ent_mean, 3),
            "price_chg_since_tight_pct": round(price_chg_since_tight, 2),
            "price_not_responded": price_not_responded,
        }

    signals["time_cognition_divergence"] = {
        "active": d4_active,
        "strong": d4_strong,
        "score": d4_score,
        "details": d4_details,
        "interpretation": (
            "强信号: 筹码5天前已高度集中, 但价格至今未反应 → 主力布局完成, 只差催化 → 重点跟踪"
            if d4_strong else
            "弱信号: 筹码3-5天前有集中迹象, 价格滞后 → 关注是否即将突破"
            if d4_active else
            "无信号: 筹码与价格时间线一致"
        ),
    }
    scores["time_cognition"] = d4_score

    # ── 综合预期差强度 ──
    # 四类背离权重: 价格-筹码(35%) > 资金-价格(30%) > 形态(20%) > 时间(15%)
    total_score = round(scores.get("price_chip", 0) * 0.35 +
                        scores.get("capital_price", 0) * 0.30 +
                        scores.get("morphology", 0) * 0.20 +
                        scores.get("time_cognition", 0) * 0.15, 0)

    active_count = sum([d1_active, d2_active, d3_active, d4_active])
    strong_count = sum([d1_strong, d2_strong, d3_strong, d4_strong])
    lookback_count = sum(lookback_signals.values())

    if strong_count >= 3:
        verdict = "极强背离(≥3类强信号)"
    elif strong_count >= 2 or (strong_count >= 1 and lookback_count >= 2):
        verdict = "强背离(≥2类强 或 强+多类回看)"
    elif strong_count == 1 or active_count >= 3:
        verdict = "中等背离(1类强 或 ≥3类弱)"
    elif active_count >= 1:
        verdict = f"弱背离({active_count}类)"
    else:
        verdict = "无背离"

    return {
        "signals": signals,
        "scores": scores,
        "total_score": total_score,
        "active_count": active_count,
        "strong_count": strong_count,
        "lookback_count": lookback_count,
        "verdict": verdict,
        "note": (
            "背离检测用于辅助验证 Layer1 逻辑预期差是否正在被资金兑现。"
            "高分 = 价格/资金/筹码之间存在「该涨不涨」或「表面弱实则强」的特征, "
            "可能暗示主力暗中布局。但需结合 Layer1 基本面的硬逻辑综合判断。"
            "时间背离(④)抓到的是「筹码已先行、价格未反应」最具操作价值。"
        ),
    }


def _build_narrative(metrics_list: list, morphology_seq: list,
                     locking: dict, dispatch: dict, divergence: dict) -> dict:
    """
    基于形态序列 + 趋势数据构建故事链叙事。

    输出一段可读的筹码演化叙事, 包含:
      - 当前阶段 (建仓期/集中期/锁仓期/震仓期/推升期/派发期)
      - 关键拐点日期和距离现在天数
      - 核心变化 (集中在加速/维持/松动)
      - 背离信号摘要
    """
    n = len(metrics_list)
    if n < 3:
        return {"phase": "数据不足", "story": "交易日不足3日"}

    latest = metrics_list[-1]
    first  = metrics_list[0]

    # ── 阶段判定 ──
    dispatch_total = dispatch.get("total", 0)
    lock_score = locking.get("locked_score", "0/6")
    lock_passed = int(lock_score.split("/")[0]) if "/" in str(lock_score) else 0
    div_verdict = divergence.get("verdict", "无背离")

    # 宽度的变化
    width_start = first.get("width", 100)
    width_now   = latest.get("width", 100)
    width_delta = width_now - width_start

    # TPC 的变化
    tpc_start = first.get("tpc", 0)
    tpc_now   = latest.get("tpc", 0)
    tpc_delta = tpc_now - tpc_start

    # 形态趋势
    recent_morphs = [m["morphology"] for m in morphology_seq[-5:]]
    morph_counts = {}
    for m in recent_morphs:
        morph_counts[m] = morph_counts.get(m, 0) + 1
    dominant_morph = max(morph_counts, key=morph_counts.get)

    # P1 趋势
    p1_start = first.get("p1", 0)
    p1_now   = latest.get("p1", 0)
    p1_delta = p1_now - p1_start

    # 判定阶段
    if dispatch_total >= 4:
        phase = "派发期"
        phase_desc = "派发5维评分≥4，筹码出现系统性分散信号"
    elif dispatch_total == 3:
        phase = "警惕期"
        phase_desc = "派发评分3/5，部分维度出现松动，需减仓观察"
    elif lock_passed >= 5:
        phase = "强锁仓期"
        phase_desc = "6项锁仓条件通过≥5，筹码高度稳定"
    elif lock_passed >= 4:
        phase = "锁仓期"
        phase_desc = f"锁仓{lock_score}，筹码基本稳定"
    elif tpc_delta > 5 and width_delta < -0.3:
        phase = "集中加速期"
        phase_desc = f"三峰总集中度 {tpc_start:.1f}%→{tpc_now:.1f}%，宽度 {width_start:.1f}%→{width_now:.1f}%，筹码快速集中"
    elif tpc_delta > 2:
        phase = "温和集中期"
        phase_desc = f"三峰总集中度 {tpc_start:.1f}%→{tpc_now:.1f}%，筹码缓慢集中"
    elif abs(tpc_delta) < 2 and abs(p1_delta) < 0.5:
        phase = "横盘整理期"
        phase_desc = "P1和TPC均无明显变化，多空均衡"
    elif p1_delta > 2:
        phase = "推升期"
        phase_desc = f"P1 成本上移 {p1_delta:+.2f} 元，主力抬升成本区间"
    elif p1_delta < -1:
        phase = "回撤期"
        phase_desc = f"P1 成本下移 {p1_delta:+.2f} 元，主力主动打压或被动撤退"
    else:
        phase = "过渡期"
        phase_desc = "多项指标信号不一致，需进一步观察"

    # ── 关键拐点 ──
    inflection_points = []
    # 找 P1 占比最高点
    max_p1pct_idx = max(range(n), key=lambda i: metrics_list[i]["p1_pct"])
    inflection_points.append({
        "type": "P1占比峰值",
        "date": metrics_list[max_p1pct_idx]["date"],
        "days_ago": n - 1 - max_p1pct_idx,
        "value": f"{metrics_list[max_p1pct_idx]['p1_pct']}%"
    })
    # 找形态突变点
    for i in range(1, len(morphology_seq)):
        if morphology_seq[i]["morphology"] != morphology_seq[i-1]["morphology"]:
            inflection_points.append({
                "type": "形态突变",
                "date": morphology_seq[i]["date"],
                "days_ago": len(morphology_seq) - 1 - i,
                "from": morphology_seq[i-1]["morphology"],
                "to": morphology_seq[i]["morphology"],
            })
            break  # 只取最近一次

    # ── 构建故事 ──
    days_total = n
    story_parts = [
        f"近 {days_total} 日{phase}",
        phase_desc,
    ]

    if dominant_morph and dominant_morph != "?":
        story_parts.append(f"主导形态: {dominant_morph} (近5日中 {morph_counts[dominant_morph]}/5 日)")

    # 背离摘要
    if "强" in div_verdict or "中等" in div_verdict:
        div_active = [k for k, v in divergence.get("signals", {}).items() if v.get("active")]
        if div_active:
            story_parts.append(f"检测到背离: {', '.join(div_active)}")

    story = "。".join(story_parts) + "。"

    return {
        "phase": phase,
        "phase_description": phase_desc,
        "dominant_morphology": dominant_morph,
        "days_analyzed": n,
        "inflection_points": inflection_points,
        "story": story,
        "key_changes": {
            "p1": f"{p1_start:.2f}→{p1_now:.2f} (Δ{p1_delta:+.2f})",
            "tpc": f"{tpc_start:.1f}%→{tpc_now:.1f}% (Δ{tpc_delta:+.1f})",
            "width": f"{width_start:.1f}%→{width_now:.1f}% (Δ{width_delta:+.1f})",
            "winner": f"{first.get('winner',0):.0f}%→{latest.get('winner',0):.0f}%",
        }
    }


# ══════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════

def analyze(ts_code: str, days: int = 14, end_date: Optional[str] = None) -> dict:
    pro = get_tushare_pro()

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    # 范围：往前推 180 天（覆盖足够的交易日）
    start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=180)
    start_date = start_dt.strftime("%Y%m%d")

    print(f"[analyze] 拉取 {ts_code} 筹码+技术数据...", file=sys.stderr)

    # ── 1. cyq_chips (一次拉取全量历史) ──
    df_chips = pro.cyq_chips(ts_code=ts_code, fields='ts_code,trade_date,price,percent')
    all_chip_dates = sorted(df_chips['trade_date'].unique())
    print(f"[analyze] cyq_chips: {len(df_chips)}行, {len(all_chip_dates)}交易日 ({all_chip_dates[0]}~{all_chip_dates[-1]})", file=sys.stderr)

    # ── 2. stk_factor (K线+技术指标) ──
    df_factor = pro.stk_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
    df_factor = df_factor.sort_values('trade_date').reset_index(drop=True)
    print(f"[analyze] stk_factor: {len(df_factor)}行", file=sys.stderr)

    # ── 3. moneyflow ──
    try:
        df_mf = pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
        df_mf = df_mf.sort_values('trade_date').reset_index(drop=True)
        print(f"[analyze] moneyflow: {len(df_mf)}行", file=sys.stderr)
    except Exception:
        df_mf = pd.DataFrame()

    # ── 4. daily_basic ──
    try:
        df_basic = pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
        df_basic = df_basic.sort_values('trade_date').reset_index(drop=True)
    except Exception:
        df_basic = pd.DataFrame()

    # ── 5. 合并 ──
    df_merged = df_factor.copy()
    if not df_mf.empty:
        df_merged = df_merged.merge(
            df_mf[['ts_code', 'trade_date', 'net_mf_amount']],
            on=['ts_code', 'trade_date'], how='left', suffixes=('', '_mf')
        )
    if not df_basic.empty:
        df_merged = df_merged.merge(
            df_basic[['ts_code', 'trade_date', 'turnover_rate', 'volume_ratio', 'pe_ttm', 'pb']],
            on=['ts_code', 'trade_date'], how='left', suffixes=('', '_db')
        )

    for col in ['net_mf_amount', 'turnover_rate', 'volume_ratio']:
        if col in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(0)

    # ── 6. 确定分析窗口 ──
    chip_dates = [d for d in all_chip_dates if d in df_merged['trade_date'].values]
    recent_dates = chip_dates[-days:] if len(chip_dates) >= days else chip_dates
    recent_set = set(recent_dates)
    print(f"[analyze] 分析窗口: {len(recent_dates)}日 ({recent_dates[0]}~{recent_dates[-1]})", file=sys.stderr)

    # ── 7. 全量历史筹码指标计算 (作为分位数基线) ──
    all_metrics   = []   # 全量历史
    metrics_list  = []   # 仅分析窗口
    prev_metrics  = None

    for td in chip_dates:
        chip_today = df_chips[df_chips['trade_date'] == td]
        kline_row  = df_merged[df_merged['trade_date'] == td]
        if len(chip_today) < 3 or len(kline_row) == 0:
            continue

        close = float(kline_row.iloc[0]['close'])
        m = compute_chip_metrics(chip_today, close)
        if m is None:
            continue

        kr = kline_row.iloc[0]
        m['date']        = str(td)
        m['open']        = round(float(kr.get('open', 0)), 2)
        m['high']        = round(float(kr.get('high', 0)), 2)
        m['low']         = round(float(kr.get('low', 0)), 2)
        m['close']       = close
        m['pct_change']  = round(float(kr.get('pct_change', 0)), 2)
        m['volume']      = int(kr.get('vol', 0) or 0)
        m['amount']      = round(float(kr.get('amount', 0) or 0), 0)
        m['turnover_rate']  = round(float(kr.get('turnover_rate', 0) or 0), 2)
        m['volume_ratio']   = round(float(kr.get('volume_ratio', 1) or 1), 2)
        m['net_mf_amount']  = round(float(kr.get('net_mf_amount', 0) or 0), 0)
        m['pe_ttm'] = float(kr.get('pe_ttm', 0) or 0)
        m['pb']     = float(kr.get('pb', 0) or 0)

        all_metrics.append(m)

        # 仅在分析窗口内做 emoji 标注
        if td in recent_set:
            emoji, behavior, reason = judge_emoji(prev_metrics, m)
            m['emoji']    = emoji
            m['behavior'] = behavior
            m['reason']   = reason
            metrics_list.append(m)
            prev_metrics = m

    if len(metrics_list) < 3:
        return {"error": "有效筹码数据不足"}
    print(f"[analyze] 全量筹码历史: {len(all_metrics)}日 (用于分位数基线)", file=sys.stderr)

    # ── 8. 经典量化指标 (CMF/ADX/ATR) ──
    fct = df_factor
    arr_h, arr_l, arr_c, arr_v = fct['high'].values, fct['low'].values, fct['close'].values, fct['vol'].values
    cmf_vals  = compute_cmf(arr_h, arr_l, arr_c, arr_v, period=21)
    adx_info  = compute_adx(arr_h, arr_l, arr_c, period=14)
    atr_vals  = compute_atr(arr_h, arr_l, arr_c, period=14)

    # 取最新值
    latest_cmf = round(float(cmf_vals[-1]), 3) if not np.isnan(cmf_vals[-1]) else None
    latest_adx = round(float(adx_info["adx"][-1]), 2) if not np.isnan(adx_info["adx"][-1]) else None
    latest_pdi = round(float(adx_info["pdi"][-1]), 2) if not np.isnan(adx_info["pdi"][-1]) else None
    latest_mdi = round(float(adx_info["mdi"][-1]), 2) if not np.isnan(adx_info["mdi"][-1]) else None
    latest_atr = round(float(atr_vals[-1]), 2) if not np.isnan(atr_vals[-1]) else None
    atr_pct    = round(latest_atr / float(fct['close'].iloc[-1]) * 100, 2) if latest_atr else None

    # ATR 滚动分位
    atr_arr = atr_vals[~np.isnan(atr_vals)]
    if len(atr_arr) >= 20:
        atr_pctile = compute_rolling_percentile(atr_arr, window=min(60, len(atr_arr)))[-1]
    else:
        atr_pctile = 50.0

    # CMF 近5日正值占比
    cmf_recent5 = cmf_vals[-5:] if len(cmf_vals) >= 5 else cmf_vals
    cmf_pos_ratio = round(np.nansum(cmf_recent5 > 0) / max(np.sum(~np.isnan(cmf_recent5)), 1), 2)

    classic_indicators = {
        "cmf": {
            "latest": latest_cmf,
            "recent_5d_positive_ratio": cmf_pos_ratio,
            "signal": "资金流入(吸筹/推升)" if (latest_cmf and latest_cmf > 0.05) else
                      "资金流出(出货/打压)" if (latest_cmf and latest_cmf < -0.05) else "中性",
            "note": "蔡金资金流 - 结合价格位置+成交量"
        },
        "adx": {
            "latest_adx": latest_adx,
            "latest_pdi": latest_pdi,
            "latest_mdi": latest_mdi,
            "regime": "趋势市" if (latest_adx and latest_adx >= 25) else "震荡市",
            "direction": "多头主导" if (latest_pdi and latest_mdi and latest_pdi > latest_mdi) else "空头主导",
            "strength": f"ADX={latest_adx}, +DI={latest_pdi}, -DI={latest_mdi}"
        },
        "atr": {
            "latest": latest_atr,
            "atr_pct_of_price": atr_pct,
            "atr_percentile": atr_pctile,
            "volatility_regime": "高波动(>" + f"{atr_pctile:.0f}" + "%分位)" if atr_pctile >= 80 else
                                 "低波动" if atr_pctile <= 20 else "中等波动"
        }
    }

    # ── 9. 滚动分位数归一化 ──
    pct_context = build_chip_percentile_context(all_metrics, metrics_list)

    # ── 10. 锁仓判定 ──
    locking = assess_locking(metrics_list)

    # ── 11. 派发评分 ──
    dispatch = dispatch_score(metrics_list)

    # ── 12. 技术面打分 ──
    tech = score_tech(df_factor.tail(max(14, days)))

    # ── 13. 价格-筹码背离检测 (Layer2.5 验证层) ──
    divergence = detect_divergence(metrics_list, pct_context, classic_indicators)

    # ── 14. 构建输出 ──
    # 关键拐点
    idx_densest = max(range(len(metrics_list)), key=lambda i: metrics_list[i]['p1_pct'])
    idx_top5    = max(range(len(metrics_list)), key=lambda i: metrics_list[i]['top5'])
    idx_p1low   = min(range(len(metrics_list)), key=lambda i: metrics_list[i]['p1_pct'])
    idx_dist    = max(range(len(metrics_list)), key=lambda i: abs(metrics_list[i]['dist']))

    # 最近3日技术指标快照
    indicators_3d = []
    for i in range(max(0, len(df_factor) - 3), len(df_factor)):
        r = df_factor.iloc[i].to_dict()
        indicators_3d.append({
            "date": str(r.get("trade_date", "")),
            "close": round(float(r.get("close", 0)), 2),
            "pct_change": round(float(r.get("pct_change", 0)), 2),
            "rsi_6": round(float(r.get("rsi_6", 0) or 0), 1),
            "rsi_12": round(float(r.get("rsi_12", 0) or 0), 1),
            "rsi_24": round(float(r.get("rsi_24", 0) or 0), 1),
            "macd_dif": round(float(r.get("macd_dif", 0) or 0), 3),
            "macd_dea": round(float(r.get("macd_dea", 0) or 0), 3),
            "macd_bar": round(float(r.get("macd", 0) or 0), 3),
            "kdj_k": round(float(r.get("kdj_k", 0) or 0), 1),
            "kdj_d": round(float(r.get("kdj_d", 0) or 0), 1),
            "kdj_j": round(float(r.get("kdj_j", 0) or 0), 1),
            "boll_upper": round(float(r.get("boll_upper", 0) or 0), 2),
            "boll_mid": round(float(r.get("boll_mid", 0) or 0), 2),
            "boll_lower": round(float(r.get("boll_lower", 0) or 0), 2),
        })

    # ── 峰值演变 + 新增指标趋势 ──
    p1_trend    = [m['p1'] for m in metrics_list]
    top5_trend  = [m['top5'] for m in metrics_list]
    tpc_trend   = [m['tpc'] for m in metrics_list]
    skew_trend  = [m['skewness'] for m in metrics_list]
    kurt_trend  = [m['kurtosis'] for m in metrics_list]
    grad_trend  = [m['gradient'] for m in metrics_list]
    w90_trend   = [m['width_90'] for m in metrics_list]
    ent_trend   = [m['entropy'] for m in metrics_list]

    # ── 形态演变摘要 ──
    latest_metrics = metrics_list[-1]
    morphology_history = {}
    for m in metrics_list:
        morph = m.get('morphology', '未知')
        morphology_history[morph] = morphology_history.get(morph, 0) + 1
    # 最新日形态详情
    morphology_latest = {
        "type": latest_metrics.get("morphology", "未知"),
        "n_peaks": latest_metrics.get("n_peaks", 0),
        "peak_positions": latest_metrics.get("peak_positions", []),
        "peak_heights": latest_metrics.get("peak_heights", []),
        "p1_dominance": latest_metrics.get("p1_dominance", 0),
        "peak_entropy": latest_metrics.get("peak_entropy", 0),
    }

    # ── 阻力支撑信息 ──
    support_resistance = {
        "resistance": latest_metrics.get("resistance"),
        "support": latest_metrics.get("support"),
        "resistance_distance_pct": latest_metrics.get("resistance_distance_pct"),
        "support_distance_pct": latest_metrics.get("support_distance_pct"),
    }

    # ── 分布统计快照 ──
    distribution_stats = {
        "latest": {
            "skewness": latest_metrics["skewness"],
            "skew_hint": latest_metrics["skew_hint"],
            "kurtosis": latest_metrics["kurtosis"],
            "kurt_hint": latest_metrics["kurt_hint"],
            "gradient": latest_metrics["gradient"],
            "grad_hint": latest_metrics["grad_hint"],
            "entropy": latest_metrics["entropy"],
            "width_70": latest_metrics["width_70"],
            "width_90": latest_metrics["width_90"],
        },
        "period_stats": {
            "skewness_range": [round(min(skew_trend), 3), round(max(skew_trend), 3)],
            "kurtosis_range": [round(min(kurt_trend), 3), round(max(kurt_trend), 3)],
            "gradient_range": [round(min(grad_trend), 3), round(max(grad_trend), 3)],
            "entropy_range": [round(min(ent_trend), 3), round(max(ent_trend), 3)],
            "width_90_range": [round(min(w90_trend), 2), round(max(w90_trend), 2)],
        }
    }

    # ── 筹码峰形态序列 (逐日) ──
    morphology_sequence = [
        {"date": m["date"], "morphology": m.get("morphology", "?"),
         "n_peaks": m.get("n_peaks", 0),
         "p1_dominance": m.get("p1_dominance", 0),
         "entropy": m.get("entropy", 0)}
        for m in metrics_list
    ]

    result = {
        "meta": {
            "ts_code": ts_code,
            "trade_days": len(metrics_list),
            "total_chip_history_days": len(all_chip_dates),
            "date_range": f"{metrics_list[0]['date']} ~ {metrics_list[-1]['date']}",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "price_summary": {
            "latest_close": metrics_list[-1]['close'],
            "period_high": max(m['high'] for m in metrics_list),
            "period_low": min(m['low'] for m in metrics_list),
            "period_pct": round((metrics_list[-1]['close'] - metrics_list[0]['close']) / max(metrics_list[0]['close'], 0.01) * 100, 2),
        },
        "indicators_snapshot": indicators_3d,
        "chip_evolution": {
            "daily_records": metrics_list,
            "locking_assessment": locking,
            "dispatch_score": dispatch,
            "key_inflection_points": {
                "densest_day": metrics_list[idx_densest]['date'],
                "densest_p1_pct": metrics_list[idx_densest]['p1_pct'],
                "top5_peak_day": metrics_list[idx_top5]['date'],
                "top5_peak": metrics_list[idx_top5]['top5'],
                "p1_lowest_day": metrics_list[idx_p1low]['date'],
                "p1_lowest": metrics_list[idx_p1low]['p1_pct'],
                "dist_extreme_day": metrics_list[idx_dist]['date'],
                "dist_extreme": metrics_list[idx_dist]['dist'],
            },
            "trends": {
                "p1":      {"start": p1_trend[0],   "end": p1_trend[-1],   "delta": round(p1_trend[-1]-p1_trend[0], 2)},
                "top5":    {"start": top5_trend[0],  "end": top5_trend[-1],  "delta": round(top5_trend[-1]-top5_trend[0], 2)},
                "tpc":     {"start": tpc_trend[0],   "end": tpc_trend[-1],   "delta": round(tpc_trend[-1]-tpc_trend[0], 2)},
                "width":   {"start": metrics_list[0]['width'], "end": metrics_list[-1]['width'],
                            "delta": round(metrics_list[-1]['width']-metrics_list[0]['width'], 2)},
                "dist":    {"start": metrics_list[0]['dist'], "end": metrics_list[-1]['dist'],
                            "delta": round(metrics_list[-1]['dist']-metrics_list[0]['dist'], 2)},
                "winner":  {"start": metrics_list[0]['winner'], "end": metrics_list[-1]['winner'],
                            "delta": round(metrics_list[-1]['winner']-metrics_list[0]['winner'], 1)},
                "skewness":{"start": skew_trend[0],  "end": skew_trend[-1],  "delta": round(skew_trend[-1]-skew_trend[0], 3)},
                "kurtosis":{"start": kurt_trend[0],  "end": kurt_trend[-1],  "delta": round(kurt_trend[-1]-kurt_trend[0], 3)},
                "gradient":{"start": grad_trend[0],  "end": grad_trend[-1],  "delta": round(grad_trend[-1]-grad_trend[0], 3)},
                "entropy": {"start": ent_trend[0],   "end": ent_trend[-1],   "delta": round(ent_trend[-1]-ent_trend[0], 3)},
                "width_90":{"start": w90_trend[0],   "end": w90_trend[-1],   "delta": round(w90_trend[-1]-w90_trend[0], 2)},
            }
        },
        # ★ 筹码形态分析
        "chip_morphology": {
            "latest": morphology_latest,
            "history_summary": morphology_history,
            "sequence": morphology_sequence,
            "support_resistance": support_resistance,
        },
        # ★ 分布统计
        "distribution_statistics": distribution_stats,
        # ★ v2.2 新增: 经典量化辅助指标
        "classic_indicators": classic_indicators,
        # ★ v2.2 新增: 筹码因子滚动分位数归一化 (自适应阈值, 跨股票可比)
        "chip_factor_ranks": pct_context,
        # ★ v2.3 新增: 价格-筹码背离检测 (Layer2.5 — 验证逻辑预期差是否被资金兑现)
        "divergence_signals": divergence,
        # ★ v2.4 新增: 故事链叙事 (基于形态序列 + 趋势 + 拐点)
        "narrative": _build_narrative(metrics_list, morphology_sequence, locking, dispatch, divergence),
        "tech_analysis": tech,
    }

    return result


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="筹码峰 + 技术面统一分析脚本 v2.3 (背离检测版)",
        epilog="示例: python analyze.py 301428.SZ --days 14"
    )
    parser.add_argument("code", help="Tushare代码 (301428.SZ / 000001.SZ / 600519.SH)")
    parser.add_argument("--days", type=int, default=14, help="回溯交易日数 (默认14)")
    parser.add_argument("--output", "-o", help="输出JSON文件")
    parser.add_argument("--end-date", help="截止日期 YYYYMMDD")
    parser.add_argument("--pretty", action="store_true", help="美化输出")

    args = parser.parse_args()

    result = analyze(args.code, days=args.days, end_date=args.end_date)

    indent = 2 if args.pretty else None
    json_str = json.dumps(result, ensure_ascii=False, indent=indent, default=str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"[done] 已写入 {args.output} ({len(json_str)}字节)", file=sys.stderr)
    else:
        print(json_str)


if __name__ == "__main__":
    main()
