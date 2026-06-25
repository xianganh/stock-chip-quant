#!/usr/bin/env python3
"""
筹码峰指标计算模块 (通用化)
===========================
封装所有筹码峰相关指标的计算逻辑。

使用示例:
    from chip_indicators import compute_chip_metrics, analyze_chip_health

    # 计算单日筹码指标
    day_chip = chip_data[chip_data['trade_date'] == '2026-04-08']
    metrics = compute_chip_metrics(day_chip, close_price=10.93)

    # 计算健康度评分
    score = analyze_chip_health(current_metrics, prev_7d_metrics)

核心指标:
  - TPC: 三峰集中度 (Top-3 Peak Concentration)
  - Width: 筹码宽度 (%)
  - DIST: 价格偏离P1 (%)
  - TP3: ±3%成本集中度 (%)
  - Winner: 获利盘比例 (approximated)
"""

import os
import sys
from typing import Dict, Optional, Tuple, List
import pandas as pd
import numpy as np

# 加载 .env 环境变量
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()


# ═══════════════════════════════════════════════════════
# 1. 高级指标计算辅助函数
# ═══════════════════════════════════════════════════════

def _detect_local_peaks(prices: np.ndarray, percents: np.ndarray,
                        min_height: float = 0.5, min_distance: float = 0.02) -> dict:
    """局部极大值峰值检测"""
    n = len(prices)
    if n < 3:
        return {"positions": [], "heights": [], "indices": []}
    raw_peaks = []
    for i in range(1, n - 1):
        left_vals  = percents[max(0, i-2):i]
        right_vals = percents[i+1:min(n, i+3)]
        if left_vals.size > 0 and right_vals.size > 0:
            if percents[i] > max(left_vals) and percents[i] > max(right_vals):
                if percents[i] >= min_height:
                    raw_peaks.append((i, float(prices[i]), float(percents[i])))
    if not raw_peaks:
        return {"positions": [], "heights": [], "indices": []}
    merged = [raw_peaks[0]]
    for idx, price, h in raw_peaks[1:]:
        last_idx, last_price, last_h = merged[-1]
        rel_dist = abs(price - last_price) / last_price if last_price > 0 else 1
        if rel_dist < min_distance:
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
    """加权偏度"""
    w = np.maximum(percents, 1e-9)
    mu = np.average(prices, weights=w)
    sigma = np.sqrt(np.average((prices - mu) ** 2, weights=w))
    if sigma < 1e-9:
        return 0.0
    skew = np.average((prices - mu) ** 3, weights=w) / (sigma ** 3)
    return round(float(skew), 3)


def _compute_weighted_kurtosis(prices: np.ndarray, percents: np.ndarray) -> float:
    """加权超额峰度"""
    w = np.maximum(percents, 1e-9)
    mu = np.average(prices, weights=w)
    sigma = np.sqrt(np.average((prices - mu) ** 2, weights=w))
    if sigma < 1e-9:
        return 0.0
    kurt = np.average((prices - mu) ** 4, weights=w) / (sigma ** 4) - 3.0
    return round(float(kurt), 3)


def _compute_gradient(prices: np.ndarray, percents: np.ndarray) -> float:
    """筹码密度梯度: 相邻价位筹码占比的平均变化率"""
    if len(percents) < 2:
        return 0.0
    diffs = np.abs(np.diff(percents))
    avg_diff = float(np.mean(diffs))
    avg_pct = float(np.mean(percents)) if np.mean(percents) > 0 else 1.0
    return round(avg_diff / avg_pct, 3)


def _compute_concentration_width(prices: np.ndarray, percents: np.ndarray, pct_level: float = 90) -> float:
    """计算包含 pct_level% 筹码的最窄价格宽度 (%)"""
    if len(prices) < 3:
        return 0.0
    sorted_idx = np.argsort(prices)
    sorted_prices = prices[sorted_idx]
    sorted_percents = percents[sorted_idx]
    total = float(sorted_percents.sum())
    if total < 1e-9:
        return 0.0
    target = total * pct_level / 100.0
    cum = 0.0
    best_width = float('inf')
    best_range = None
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
    mid_price = (best_range[0] + best_range[1]) / 2
    width_pct = round(best_width / mid_price * 100, 2) if mid_price > 0 else 0
    return max(0.01, width_pct) if best_width < 0.001 else width_pct


def _compute_chip_entropy(percents: np.ndarray) -> float:
    """筹码分布的信息熵 (bits)，值越大分布越分散"""
    p = np.maximum(percents, 1e-9)
    p = p / p.sum()
    entropy = -np.sum(p * np.log2(p))
    return round(float(entropy), 3)


# ═══════════════════════════════════════════════════════
# 2. 单日筹码峰指标计算 (完整版)
# ═══════════════════════════════════════════════════════

def compute_chip_metrics(day_chip: pd.DataFrame, close: float) -> Optional[Dict]:
    """
    计算单日的完整筹码峰指标集 (v2.1 增强版)。

    返回指标包括:
      基础: p1/p2/p3, tpc, width, dist, tp3, winner
      高级: top5/top10, weight_avg, median_price, gap_pct, gap_12, gap_23
      分布统计: skewness, kurtosis, gradient, entropy
      集中宽度: width_70, width_90
      形态: morphology, n_peaks, peak_positions, peak_heights
      结构: p1_dominance, peak_entropy, peaks_below_close
      阻力支撑: resistance, support, resistance_distance_pct, support_distance_pct
    """
    if len(day_chip) < 3:
        return None

    # 基础数据
    df = day_chip.sort_values('percent', ascending=False).copy()
    arr_price = df['price'].values.astype(float)
    arr_percent = df['percent'].values.astype(float)

    df_sorted = day_chip.sort_values('price').copy()
    arr_p_sorted = df_sorted['price'].values.astype(float)
    arr_pt_sorted = df_sorted['percent'].values.astype(float)

    # 局部极大值峰值检测
    peak_info = _detect_local_peaks(arr_p_sorted, arr_pt_sorted, min_height=0.5, min_distance=0.02)

    # 三峰: 优先用局部极大值，不足3个则从df.head()补
    peak_triplets = []
    for i in range(len(peak_info["positions"])):
        peak_triplets.append((peak_info["positions"][i], peak_info["heights"][i], "peak"))
    if len(peak_triplets) < 3:
        exclude_mask = np.zeros(len(df), dtype=bool)
        for dp in peak_info["positions"]:
            exclude_mask |= ((df['price'] >= dp * 0.95) & (df['price'] <= dp * 1.05))
        supplement = df[~exclude_mask].head(3 - len(peak_triplets))
        for _, row in supplement.iterrows():
            peak_triplets.append((float(row['price']), float(row['percent']), "supplement"))
    while len(peak_triplets) < 3:
        peak_triplets.append((0.0, 0.0, "missing"))
    peak_triplets.sort(key=lambda x: x[1], reverse=True)
    peak_triplets = peak_triplets[:3]

    p1, p1_pct = peak_triplets[0][0], peak_triplets[0][1]
    p2, p2_pct = peak_triplets[1][0], peak_triplets[1][1]
    p3, p3_pct = peak_triplets[2][0], peak_triplets[2][1]

    # 集中度
    tpc = round(p1_pct + p2_pct + p3_pct, 2)
    top5 = round(float(df.head(5)['percent'].sum()), 2)
    top10 = round(float(df.head(10)['percent'].sum()), 2)

    # 宽度: 三峰价格极差 / 最低峰价 × 100
    mn_peak, mx_peak = min(p1, p2, p3), max(p1, p2, p3)
    width = round((mx_peak - mn_peak) / mn_peak * 100, 2) if mn_peak > 0 else 0

    # dist / tp3 / gap / winner / weight_avg / median_price
    dist = round((close - p1) / p1 * 100, 2) if p1 > 0 else 0
    lo, hi = close * 0.97, close * 1.03
    tp3 = round(float(df[(df['price'] >= lo) & (df['price'] <= hi)]['percent'].sum()), 2)
    gap_pct = round(abs(p1 - p2) / p1 * 100, 2) if p1 > 0 else 0
    winner = round(float(df[df['price'] <= close]['percent'].sum()), 2)
    total_pct = float(df['percent'].sum())
    weight_avg = round(float((df['price'] * df['percent']).sum() / total_pct), 2) if total_pct > 0 else 0
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

    # 形态分类
    morphology = _classify_morphology(peak_info, tpc, width)
    n_peaks = len(peak_info["positions"])

    # 阻力位/支撑位
    rs = _find_resistance_support(peak_info, close)

    # 分布统计
    skewness = _compute_weighted_skewness(arr_price, arr_percent)
    kurtosis = _compute_weighted_kurtosis(arr_price, arr_percent)
    gradient = _compute_gradient(arr_p_sorted, arr_pt_sorted)
    entropy = _compute_chip_entropy(arr_percent)

    # 集中宽度
    width_70 = _compute_concentration_width(arr_p_sorted, arr_pt_sorted, 70)
    width_90 = _compute_concentration_width(arr_p_sorted, arr_pt_sorted, 90)

    # 三峰结构
    p1_dominance = round(p1_pct / tpc, 3) if tpc > 0 else 0
    peak_weights = np.array([p1_pct, p2_pct, p3_pct])
    peak_weights = np.maximum(peak_weights, 1e-9)
    peak_weights = peak_weights / peak_weights.sum()
    peak_entropy = round(float(-np.sum(peak_weights * np.log2(peak_weights))), 3)

    return {
        # 基础指标
        "p1": p1, "p1_pct": p1_pct,
        "p2": p2, "p2_pct": p2_pct,
        "p3": p3, "p3_pct": p3_pct,
        "tpc": tpc, "top5": top5, "top10": top10,
        "width": width,
        "dist": dist,
        "tp3": tp3,
        "gap_pct": gap_pct,
        "gap_12": gap_12, "gap_23": gap_23,
        "winner": winner,
        "weight_avg": weight_avg,
        "median_price": median_price,
        "peaks_below_close": peaks_below,

        # 形态识别
        "morphology": morphology,
        "n_peaks": n_peaks,
        "peak_positions": [round(p, 2) for p in peak_info["positions"]],
        "peak_heights": [round(h, 2) for h in peak_info["heights"]],

        # 阻力支撑
        "resistance": rs["resistance"],
        "support": rs["support"],
        "resistance_distance_pct": rs["resistance_distance_pct"],
        "support_distance_pct": rs["support_distance_pct"],

        # 分布统计
        "skewness": skewness,
        "kurtosis": kurtosis,
        "gradient": gradient,
        "entropy": entropy,

        # 集中宽度
        "width_70": width_70,
        "width_90": width_90,

        # 三峰结构
        "p1_dominance": p1_dominance,
        "peak_entropy": peak_entropy,
    }


# ═══════════════════════════════════════════════════════
# 2. 健康度评分体系
# ═══════════════════════════════════════════════════════

def analyze_chip_health(current: Dict, prev_7d: Dict) -> Dict:
    """
    分析筹码健康度变化，计算得分。

    评分规则:
      +2: TPC上升
      +2: 宽度收窄 (筹码集中)
      +2: 获利盘增加
      +2: TP3>28% 且上升
      +1: 价格>P1
      -1: TPC下降超过1%
      -1: 宽度扩大超过1%
      -1: 获利盘减少超过1%
      -1: 价格<P1

    Args:
        current: 当前日期的指标字典 (compute_chip_metrics返回)
        prev_7d: 7日前的指标字典

    Returns:
        Dict: {
            'score': int,           # 总分
            'status': str,          # 健康度状态
            'reasons': List[str],   # 评分理由
        }
    """
    score = 0
    reasons = []

    # TPC变化
    tpc_chg = current['tpc'] - prev_7d['tpc']
    if tpc_chg > 0:
        score += 2
        reasons.append(f"TPC↑{tpc_chg:+.1f}%")
    elif tpc_chg < -1:
        score -= 1
        reasons.append(f"TPC↓{abs(tpc_chg):.1f}%")

    # Width变化 (收窄=筹码集中=好)
    width_chg = current['width'] - prev_7d['width']
    if width_chg < 0:
        score += 2
        reasons.append(f"宽度↓{width_chg:.1f}%")
    elif width_chg > 1:
        score -= 1
        reasons.append(f"宽度↑{width_chg:.1f}%")

    # 获利盘变化
    winner_chg = current['winner'] - prev_7d['winner']
    if winner_chg > 0:
        score += 2
        reasons.append(f"获利↑{winner_chg:+.1f}%")
    elif winner_chg < -1:
        score -= 1
        reasons.append(f"获利↓{abs(winner_chg):.1f}%")

    # TP3变化
    tp3_chg = current['tp3'] - prev_7d['tp3']
    if current['tp3'] > 28 and tp3_chg > 0:
        score += 2
        reasons.append(f"TP3↑{tp3_chg:+.1f}%>28%")
    elif current['tp3'] > 28:
        score += 1
        reasons.append(f"TP3>{current['tp3']:.1f}%")

    # 价格位置
    if current['dist'] > 0:
        score += 1
        reasons.append("价格>P1")
    else:
        score -= 1
        reasons.append("价格<P1")

    # 状态判定
    if score >= 10:
        status = '向好（强）'
    elif score >= 7:
        status = '向好（中）'
    elif score >= 4:
        status = '向好（弱）'
    elif score >= 0:
        status = '中性'
    else:
        status = '向坏'

    return {
        'score': score,
        'status': status,
        'reasons': reasons,
    }


def get_score_color(score: int) -> str:
    """
    根据健康度得分返回对应的颜色。

    Returns:
        str: 颜色代码
    """
    if score >= 10:
        return '#52c41a'      # 绿色 - 强向好
    elif score >= 7:
        return '#8dd87d'      # 浅绿 - 中向好
    elif score >= 4:
        return '#faad14'      # 黄色 - 弱向好
    elif score >= 0:
        return '#d9d9d9'      # 灰色 - 中性
    else:
        return '#ff4d4f'      # 红色 - 向坏


def get_score_label(score: int) -> str:
    """
    根据健康度得分返回对应的状态标签。

    Returns:
        str: 状态标签
    """
    if score >= 10:
        return '向好(强)'
    elif score >= 7:
        return '向好(中)'
    elif score >= 4:
        return '向好(弱)'
    elif score >= 0:
        return '中性'
    else:
        return '向坏'


# ═══════════════════════════════════════════════════════
# 3. 批量计算
# ═══════════════════════════════════════════════════════

def compute_all_chip_metrics(chip_data: pd.DataFrame, kline_data: pd.DataFrame,
                              lookback_days: int = 7) -> List[Dict]:
    """
    批量计算所有交易日的筹码指标和健康度。

    Args:
        chip_data: fetch_cyq_chips返回的筹码数据
        kline_data: fetch_kline_data返回的K线数据
        lookback_days: 健康度对比的回看天数，默认7天

    Returns:
        List[Dict]: 每日指标和健康度数据
    """
    results = []
    all_dates = sorted(chip_data['trade_date'].unique())

    # 预计算每日指标
    daily_metrics = {}
    for date in all_dates:
        day_chip = chip_data[chip_data['trade_date'] == date]
        kline_row = kline_data[kline_data['trade_date'] == date]

        if len(day_chip) < 3 or len(kline_row) == 0:
            continue

        close = float(kline_row.iloc[0]['close'])
        metrics = compute_chip_metrics(day_chip, close)
        if metrics:
            metrics['date'] = date.strftime('%Y-%m-%d')
            metrics['close'] = close
            metrics['open'] = float(kline_row.iloc[0]['open'])
            metrics['high'] = float(kline_row.iloc[0]['high'])
            metrics['low'] = float(kline_row.iloc[0]['low'])
            metrics['vol'] = float(kline_row.iloc[0]['vol'])
            daily_metrics[date] = metrics

    # 计算健康度 (sorted_dates 为升序：从早到晚)
    sorted_dates = sorted(daily_metrics.keys())
    for i, date in enumerate(sorted_dates):
        current = daily_metrics[date]

        # 计算未来N日收益 (i + 10 为10天后的日期)
        future_return = None
        if i + 10 < len(sorted_dates):
            future_date = sorted_dates[i + 10]
            if future_date in daily_metrics:
                future_price = daily_metrics[future_date]['close']
                current_price = current['close']
                future_return = round((future_price - current_price) / current_price * 100, 2)

        # 健康度评分 (与 lookback_days 天前的数据对比)
        health = None
        if i - lookback_days >= 0:
            prev_date = sorted_dates[i - lookback_days]
            prev_metrics = daily_metrics[prev_date]
            health = analyze_chip_health(current, prev_metrics)

        result = current.copy()
        result['future_return'] = future_return
        if health:
            result['score'] = health['score']
            result['status'] = health['status']
            result['reasons'] = health['reasons']
        else:
            result['score'] = None
            result['status'] = '未知'
            result['reasons'] = []

        results.append(result)

    return results


# ═══════════════════════════════════════════════════════
# 4. 主函数（测试用）
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    from chip_data_fetcher import fetch_complete_data

    print("=" * 60)
    print("测试筹码峰指标计算模块")
    print("=" * 60)

    try:
        data = fetch_complete_data('603002.SH', '20260301', '20260624')
        results = compute_all_chip_metrics(data['chip_data'], data['kline'])

        print(f"\n✅ 计算完成: {len(results)}个交易日")

        if results:
            scores = [r['score'] for r in results if r['score'] is not None]
            print(f"   健康度范围: {min(scores)}~{max(scores)}分")
            print(f"   平均分: {sum(scores)/len(scores):.1f}分")
            print(f"   负分次数: {len([s for s in scores if s < 0])}")

            # 打印最佳买入点
            best_buys = [r for r in results if r['score'] and r['score'] >= 10]
            print(f"\n   最佳买入点(≥10分): {len(best_buys)}次")
            for r in best_buys[:3]:
                print(f"   {r['date']} 得分:{r['score']} 未来10日:{r['future_return']:+.2f}%")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")