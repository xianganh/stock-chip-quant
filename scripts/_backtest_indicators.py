#!/usr/bin/env python3
"""
组件 A/B 验证框架: 单指标回测有效性
============================================

设计:
  - 对每个候选指标做 "带 vs 不带" 对比
  - 用 12 股本位数据, 对 768 个有 future_return 样本做评估
  - 衡量: 命中率 / 样本数 / 跨股稳定性 / 边际贡献

回测目的:
  1. 调整阈值 (找出最优参数)
  2. 发现不适用的指标 (drop 掉)
  3. 保留适用的指标或组合

候选指标 (基础集):
  - tpc, p1_pct, winner (必选, baseline)
  - p1_dominance     (主峰 vs 其他)
  - peaks_below_close (低位吸纳)
  - gap_pct          (双峰间距)
  - width_70         (70% 集中宽度)
  - peak_entropy     (峰位熵)
"""
import sys, os, json, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ---------- 数据准备 ----------
print('='*70)
print('加载 12 股回测数据...')
print('='*70)
with open('data/backtest_12stocks_raw.json', 'r', encoding='utf-8') as f:
    stocks_data = json.load(f)

all_samples = []
for s in stocks_data:
    for m in s['metrics']:
        all_samples.append({
            'ts_code': s['ts_code'],
            'date': m.get('date', ''),
            'future_return': m.get('future_return'),
            'tpc': m.get('tpc', 0),
            'p1_pct': m.get('p1_pct', 0),
            'p1': m.get('p1', 0),
            'winner': m.get('winner', 0),
            'peaks_below_close': m.get('peaks_below_close', 0),
            'p1_dominance': m.get('p1_dominance', 0),
            'gap_pct': m.get('gap_pct', 0),
            'width_70': m.get('width_70', 0),
            'peak_entropy': m.get('peak_entropy', 0),
        })
all_samples = [s for s in all_samples if s['future_return'] is not None]
print(f'有效样本数: {len(all_samples)}')

# ---------- 评估常数 ----------
RISE = 5.0   # future_return >= 5% → rise
FALL = -5.0  # future_return <= -5% → fall
FALL_PCT = 0  # future_return <= X → fall 评估

def evaluate_health(health, future_return):
    """评价 health 判定 vs 实际 future_return"""
    if health == 'accumulate':
        if future_return >= RISE: return 'agree'
        if future_return <= FALL: return 'disagree'
        return 'neutral'
    if health == 'dispatch':
        if future_return <= FALL: return 'agree'
        if future_return >= RISE: return 'disagree'
        return 'neutral'
    return None

# ---------- 1. 灵活规则 (支持组件启用/禁用) ----------
def classify_with_components(m, enabled_features):
    """
    分类逻辑: 通过启用/禁用各组件构建 A/B 实验
    enabled_features: dict of {feature_name: bool}

    核心规则: 满足任一 enabled 的 accumulate 条件 -> accumulate
              满足 enabled 的 dispatch 条件 -> dispatch
              满足 enabled 的 shaking 条件 -> shaking
              其他 -> unclear
    """
    # 1) Dispatch (顶部信号) 条件
    if enabled_features.get('dispatch_winner', False):
        if m['winner'] >= 90 and m['tpc'] >= 25:
            return 'dispatch'
    if enabled_features.get('dispatch_p1_drop', False):
        if m['p1_pct'] < 5 and m['tpc'] >= 20:  # 主峰消失 + 中度集中
            return 'dispatch'

    # 2) Accumulate 条件
    is_acc = False
    # 基础 (tpc + p1_pct)
    if enabled_features.get('base', True):
        if m['tpc'] >= 25 and m['p1_pct'] >= 12:
            is_acc = True
    # 低位吸纳
    if enabled_features.get('peaks_below', False):
        if m['peaks_below_close'] >= 2:
            is_acc = True
    # 主峰主导度高
    if enabled_features.get('p1_dominance', False):
        if m['p1_dominance'] >= 0.5:
            is_acc = True
    # 70% 集中宽度窄
    if enabled_features.get('width_70_tight', False):
        if m['width_70'] > 0 and m['width_70'] <= m['p1'] * 0.2:  # 宽度 < 20% P1
            is_acc = True
    # 峰位熵低 (尖锐主峰)
    if enabled_features.get('peak_entropy_low', False):
        if m['peak_entropy'] > 0 and m['peak_entropy'] <= 1.5:
            is_acc = True
    # 双峰间距合理 (中继形态)
    if enabled_features.get('gap_pct_mid', False):
        if m['gap_pct'] >= 3 and m['gap_pct'] <= 8:
            is_acc = True
    if is_acc:
        return 'accumulate'

    # 3) Shaking (震荡)
    if enabled_features.get('shaking_tpc', False):
        if m['tpc'] >= 15:
            return 'shaking'

    return 'unclear'


def evaluate_config(enabled_features, fallback_window=('rise', 'fall')):
    """评估一个 components 配置 — 返回详细指标"""
    from collections import Counter
    health_count = Counter()
    agree, disagree = Counter(), Counter()
    per_stock = {}

    for s in all_samples:
        h = classify_with_components(s, enabled_features)
        health_count[h] += 1
        ev = evaluate_health(h, s['future_return'])
        if ev in ('agree', 'disagree'):
            agree[h] += ev == 'agree'
            disagree[h] += ev == 'disagree'
            per_stock.setdefault(s['ts_code'], []).append((h, ev))

    total_agree = sum(agree.values())
    total_dis = sum(disagree.values())
    total_valid = total_agree + total_dis

    per_class = {}
    for cls in ('accumulate', 'dispatch'):
        a, d = agree[cls], disagree[cls]
        n = a + d
        per_class[cls] = {
            'samples': n,
            'hit_rate': a / n if n else 0,
            'agree': a, 'disagree': d,
        }

    # 跨股稳定性: 每个健康度命中率在股票间的标准差
    import statistics
    stock_hr_by_class = {c: [] for c in ('accumulate', 'dispatch')}
    for ts_code, results in per_stock.items():
        class_results = {'accumulate': [ev == 'agree' for h, ev in results if h == 'accumulate'],
                          'dispatch':  [ev == 'agree' for h, ev in results if h == 'dispatch']}
        for c in ('accumulate', 'dispatch'):
            lst = class_results[c]
            if len(lst) >= 3:  # 至少3个样本才计算 std
                stock_hr_by_class[c].append(sum(lst) / len(lst))

    stock_std = {}
    for c in ('accumulate', 'dispatch'):
        lst = stock_hr_by_class[c]
        if len(lst) >= 2:
            stock_std[c] = statistics.stdev(lst) if len(lst) > 1 else 0
        else:
            stock_std[c] = None

    return {
        'config': dict(enabled_features),
        'total_agree': total_agree,
        'total_disagree': total_dis,
        'total_valid': total_valid,
        'overall_hit_rate': total_agree / total_valid if total_valid else 0,
        'per_class': per_class,
        'health_dist': dict(health_count),
        'cross_stock_std': stock_std,  # 越小越好 (稳定)
    }


# ---------- 2. 实验矩阵 ----------
print('\n' + '='*70)
print('实验矩阵: A/B 验证')
print('='*70)

components = [
    'dispatch_winner', 'dispatch_p1_drop',
    'peaks_below', 'p1_dominance', 'width_70_tight',
    'peak_entropy_low', 'gap_pct_mid', 'shaking_tpc',
]

# 实验: baseline vs 加入每个组件
baseline_config = {'base': True}
baseline_result = evaluate_config(baseline_config)
print(f"\nBaseline (只有 base): hit={baseline_result['overall_hit_rate']*100:.1f}%, "
      f"acc={baseline_result['per_class']['accumulate']['agree']}/{baseline_result['per_class']['accumulate']['samples']} "
      f"dis={baseline_result['per_class']['dispatch']['agree']}/{baseline_result['per_class']['dispatch']['samples']}")

print('\n=== 单组件增量贡献 (逐步加入) ===')
print(f"{'组件':20s} {'整体命中率':>10s} {'accumulate':>20s} {'dispatch':>14s} {'跨股std':>10s} {'决策':>8s}")
print('-'*90)

results_table = [('Baseline', baseline_result)]
running_config = dict(baseline_config)

for comp in components:
    # 加入该组件
    running_config[comp] = True
    result = evaluate_config(running_config)
    results_table.append((comp, result))

    # 增量贡献 (与前一步对比)
    prev = results_table[-2][1]
    delta_total_hit = (result['overall_hit_rate'] - prev['overall_hit_rate']) * 100

    base = baseline_result
    delta_to_baseline_total = (result['overall_hit_rate'] - baseline_result['overall_hit_rate']) * 100
    delta_to_baseline_acc = result['per_class']['accumulate']['hit_rate'] - baseline_result['per_class']['accumulate']['hit_rate']
    delta_to_baseline_acc_pct = (result['per_class']['accumulate']['hit_rate'] - baseline_result['per_class']['accumulate']['hit_rate']) * 100

    # 决策: 加入此组件是否值得
    if delta_total_hit > 5:
        decision = 'KEEP'
    elif delta_total_hit >= 0:
        decision = '观察'
    else:
        decision = 'DROP'

    print(f"{comp:20s} {result['overall_hit_rate']*100:>9.1f}%({'+' if delta_to_baseline_total >= 0 else ''}{delta_to_baseline_total:.1f}%) "
          f"acc={result['per_class']['accumulate']['agree']}/{result['per_class']['accumulate']['samples']}({delta_to_baseline_acc_pct:+.1f}%) "
          f"dis={result['per_class']['dispatch']['agree']}/{result['per_class']['dispatch']['samples']} "
          f"acc_std={result['cross_stock_std']['accumulate'] if result['cross_stock_std']['accumulate'] else 'NA':>8} "
          f"{decision:>8s}")

# ---------- 3. 推荐配置 (top 5) ----------
print('\n' + '='*70)
print('推荐配置 (按整体命中率排序, 含跨股稳定性)')
print('='*70)

# 测试所有非空子集 (2^8 = 256, 不多)
from itertools import combinations as cmb
all_subsets = []
for r in range(0, len(components)+1):
    for subset in cmb(components, r):
        cfg = {'base': True}
        for c in subset: cfg[c] = True
        all_subsets.append((subset, cfg))

print(f'测试 {len(all_subsets)} 种组件组合...')
t0 = time.time()
all_results = []
for subset, cfg in all_subsets:
    r = evaluate_config(cfg)
    score = r['overall_hit_rate']
    # 加权: 整体命中率 + 跨股稳定性奖励
    if r['cross_stock_std']['accumulate'] is not None:
        stability_bonus = max(0, 0.05 - r['cross_stock_std']['accumulate']) * 0.5
        score += stability_bonus
    r['subset'] = list(subset)
    r['score'] = score
    all_results.append(r)
print(f'完成 (耗时 {time.time()-t0:.1f}s)')

all_results.sort(key=lambda r: (r['score'], r['total_valid']), reverse=True)

# 选出 TOP 5 但要求总样本 ≥ 30 (避免小样本)
top = [r for r in all_results if r['total_valid'] >= 30][:5]
print(f'\n=== TOP 5 配置 (要求总样本 ≥ 30) ===\n')
for i, r in enumerate(top):
    cls = r['per_class']
    print(f"#{i+1}  组件={r['subset'] or '仅 base'}")
    print(f"     整体命中率: {r['overall_hit_rate']*100:.1f}% ({r['total_agree']}/{r['total_valid']})")
    print(f"     accumulate: {cls['accumulate']['agree']}/{cls['accumulate']['samples']} = {cls['accumulate']['hit_rate']*100:.1f}%")
    print(f"     dispatch:   {cls['dispatch']['agree']}/{cls['dispatch']['samples']} = {cls['dispatch']['hit_rate']*100:.1f}%")
    if r['cross_stock_std']['accumulate'] is not None:
        print(f"     accumulate 跨股 std: {r['cross_stock_std']['accumulate']:.3f}")
    print()

# ---------- 4. 单指标 drop-test ----------
print('\n' + '='*70)
print('单指标 DROP 测试 (从最优配置移除每个组件, 看是否变差)')
print('='*70)
best = top[0]
best_config = {'base': True}
for c in best['subset']: best_config[c] = True
best_hit = best['overall_hit_rate']
print(f'最优基线: hit={best_hit*100:.1f}%  启用: {best["subset"]}')
print()
print(f"{'移除组件':25s} {'新命中率':>10s} {'Δ':>10s} {'决策':>10s}")
for comp in best['subset']:
    test_cfg = dict(best_config)
    del test_cfg[comp]
    r = evaluate_config(test_cfg)
    delta = (r['overall_hit_rate'] - best_hit) * 100
    if delta >= 0:
        decision = '可去'
    elif delta >= -3:
        decision = '建议去'
    else:
        decision = '保留'
    print(f"  no_{comp:18s} {r['overall_hit_rate']*100:>9.1f}% {delta:>+10.1f}% {decision:>10s}")

# ---------- 保存结果 ----------
output = {
    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': f'data/backtest_12stocks_raw.json ({len(all_samples)} samples)',
    'eval_window': f'future_return ±{RISE}%',
    'baseline': {k: v for k, v in baseline_result.items() if k in ('overall_hit_rate', 'per_class', 'health_dist')},
    'incremental': [{'config': [{'add': c} for c in (subset or [])],
                     'hit_rate': r['overall_hit_rate'],
                     'per_class': r['per_class']}
                    for subset, r in results_table],
    'top5_configurations': [{
        'subset': r['subset'],
        'overall_hit_rate': r['overall_hit_rate'],
        'accumulate_hit_rate': r['per_class']['accumulate']['hit_rate'],
        'dispatch_hit_rate': r['per_class']['dispatch']['hit_rate'],
        'samples': r['total_valid'],
        'cross_stock_std': r['cross_stock_std'],
    } for r in top],
}

result_path = 'data/indicator_ab_validation.json'
with open(result_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f'\n结果: {result_path}')
