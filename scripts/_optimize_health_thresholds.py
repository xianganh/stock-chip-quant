#!/usr/bin/env python3
"""
classify_health 阈值进化优化器 v2
====================================

策略: 用底层指标构造 health 分类 (绕过 action/lock_passed)
评估: 用真实 future_return 验证命中率

数据: data/backtest_12stocks_raw.json
- 869 个 (日期, 指标) 样本
- 每条记录含: tpc, p1_pct, winner, peaks_below_close, p1_dominance, gap_pct 等
- 还有 future_return 字段 (T+某个窗口的实际涨跌)

参数空间 (健康度判断条件):
  accumulate: tpc>=X AND p1_pct>=Y AND (winner<=Z OR peaks_below>=W)
  dispatch:   winner>=A AND tpc>=B (顶部信号)
  shaking:    其他

目标: 最大化 accumulate 的 future_returns 命中率
"""
import sys, os, json, time, itertools, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

from collections import Counter

# ---------- 数据加载 ----------
with open('data/backtest_12stocks_raw.json', 'r', encoding='utf-8') as f:
    stocks_data = json.load(f)

# 合并所有天的数据, 保留 (ts_code, date, ...) 上下文
all_samples = []
for s in stocks_data:
    for m in s['metrics']:
        all_samples.append({
            'ts_code': s['ts_code'],
            'date':    m.get('date', ''),
            'close':   m.get('close', 0),
            'future_return': m.get('future_return', None),
            'tpc':     m.get('tpc', 0),
            'p1_pct':  m.get('p1_pct', 0),
            'p1':      m.get('p1', 0),
            'winner':  m.get('winner', 0),
            'width_70': m.get('width_70', 0),
            'p1_dominance': m.get('p1_dominance', 0),
            'gap_pct': m.get('gap_pct', 0),
            'peaks_below_close': m.get('peaks_below_close', 0),
            'peak_entropy': m.get('peak_entropy', 0),
        })

# 过滤: 必须有 future_return 且 close > 0
all_samples = [s for s in all_samples if s['future_return'] is not None and s['close'] > 0]
print(f'样本数 (有 future_return): {len(all_samples)} / {len(all_samples)}')

# 检查 future_return 的分布
fr_dist = Counter(round(s['future_return'], 0) for s in all_samples)
print(f'future_return 分布 (top 5): {dict(fr_dist.most_common(5))}')

# 看 T+某窗口的涨跌幅阈值
RISE_THRESHOLD = 5.0   # future_return >= 5% → "rise"
FALL_THRESHOLD = -5.0
print(f'约定: future_return >= {RISE_THRESHOLD} → rise (验证 accumulate)')
print(f'约定: future_return <= {FALL_THRESHOLD} → fall (验证 dispatch)')

# ---------- 规则引擎 (参数化) ----------
# 输入: m (metrics dict), params (dict)
# 输出: health in {'accumulate', 'dispatch', 'shaking', 'unclear'}
def classify_rule(m, params):
    """参数化的健康度分类, 基于底层指标"""
    tpc = m.get('tpc', 0)
    p1_pct = m.get('p1_pct', 0)
    winner = m.get('winner', 0)
    peaks_below = m.get('peaks_below_close', 0)
    p1_dom = m.get('p1_dominance', 0)
    width_70 = m.get('width_70', 0)
    peak_entropy = m.get('peak_entropy', 0)

    # dispatch 优先 (顶部信号)
    if (winner >= params['dispatch_winner']) and (tpc >= params['dispatch_tpc']):
        return 'dispatch'
    # accumulate 信号 (多种成立条件之一)
    is_acc = False
    if tpc >= params['acc_tpc'] and p1_pct >= params['acc_p1_pct']:
        is_acc = True
    if peaks_below >= params['acc_peaks_below']:
        is_acc = True
    if p1_dom >= params['acc_p1_dominance']:
        is_acc = True
    if is_acc:
        return 'accumulate'
    # 弱信号 - 震荡
    if tpc >= params['shaking_tpc'] or p1_pct >= params['shaking_p1_pct']:
        return 'shaking'
    # 其余不明朗
    return 'unclear'


# ---------- 评估函数 ----------
def evaluate_one(health_label, future_return):
    """用 future_return 评估 health 判定是否正确"""
    # accumulate → 预测上涨, 验证:
    #   rise >= 5%: agree (确认拉升)
    #   fall <= -5%: disagree (判定吸筹但没涨)
    # dispatch   → 预测下跌, 验证:
    #   fall <= -5%: agree (确认出货)
    #   rise >= 5%: disagree
    if health_label == 'accumulate':
        if future_return >= RISE_THRESHOLD: return 'agree'
        if future_return <= FALL_THRESHOLD: return 'disagree'
        return 'neutral'
    if health_label == 'dispatch':
        if future_return <= FALL_THRESHOLD: return 'agree'
        if future_return >= RISE_THRESHOLD: return 'disagree'
        return 'neutral'
    return None  # shaking/unclear 不评估


def evaluate_params(params):
    """评估一组参数: 总命中率 + 各健康度独立命中率"""
    health_count = Counter()
    valid_count = Counter()  # accumulate / dispatch
    agree_count = Counter()
    disagree_count = Counter()

    for s in all_samples:
        health = classify_rule(s, params)
        health_count[health] += 1
        if health in ('accumulate', 'dispatch'):
            result = evaluate_one(health, s['future_return'])
            if result == 'agree':
                agree_count[health] += 1
            elif result == 'disagree':
                disagree_count[health] += 1

    total_agree = sum(agree_count.values())
    total_dis = sum(disagree_count.values())
    total_valid = total_agree + total_dis

    specific = {}
    for h in ('accumulate', 'dispatch'):
        a = agree_count[h]; d = disagree_count[h]
        n = a + d
        specific[h] = {
            'hit_rate': a/n if n else 0,
            'samples': n,
            'agree': a, 'disagree': d,
        }

    return {
        'overall_hit_rate': total_agree / total_valid if total_valid else 0,
        'total_valid': total_valid,
        'agree': total_agree, 'disagree': total_dis,
        'health_dist': dict(health_count),
        'specific': specific,
    }


# ---------- 网格搜索 ----------
PARAM_GRID = {
    'dispatch_winner':    [80, 85, 90, 95],          # 高位信号阈值
    'dispatch_tpc':       [15, 20, 25, 30],          # 派发需要的最低集中度
    'acc_tpc':            [15, 20, 25, 30],          # 吸筹需要的最低集中度
    'acc_p1_pct':         [5, 8, 10, 12, 15],        # 主峰占比阈值
    'acc_peaks_below':    [1, 2, 3],                # 成本下方峰数阈值
    'acc_p1_dominance':   [40, 50, 60],             # 主峰主导度阈值
    'shaking_tpc':        [10, 12, 15],             # 弱集中度阈值
    'shaking_p1_pct':     [3, 5, 7],                # 弱主峰阈值
}

keys = list(PARAM_GRID.keys())
values_list = [PARAM_GRID[k] for k in keys]
all_combos = list(itertools.product(*values_list))
n_combos = len(all_combos)
print(f'\n参数空间: {[(k,len(v)) for k,v in PARAM_GRID.items()]}')
print(f'组合数: {n_combos}')

t0 = time.time()
results = []
for i, combo in enumerate(all_combos):
    p = dict(zip(keys, combo))
    res = evaluate_params(p)
    # 综合评分: 全局命中率 + 各健康度都有样本时的奖励
    score = res['overall_hit_rate']
    if res['total_valid'] >= 100:
        results.append({'params': p, **res, 'score': score})
    if (i+1) % 500 == 0:
        elapsed = time.time() - t0
        print(f'  [{i+1}/{n_combos}]  {elapsed:.1f}s')

print(f'\n网格搜索完成, 总耗时 {time.time()-t0:.1f}s, 有效组合 {len(results)}')

# ---------- TOP 15 ----------
results.sort(key=lambda r: (r['overall_hit_rate'], r['total_valid']), reverse=True)

print('\n=== TOP 15 参数组合 (按 overall_hit_rate 排序) ===')
print(f"{'rank':4s} {'派发w':5s} {'派发T':5s} {'吸T':4s} {'吸P':4s} {'吸pb':5s} {'吸Dom':5s} {'振T':4s} {'振P':4s} {'命中率':>8s} {'样本':>5s} {'accumulate':>11s} {'dispatch':>10s}")
for i, r in enumerate(results[:15]):
    pp = r['params']
    sp = r['specific']
    acc_str = f"{sp['accumulate']['agree']}/{sp['accumulate']['samples']}={sp['accumulate']['hit_rate']*100:.0f}%" if sp['accumulate']['samples'] else "0"
    dis_str = f"{sp['dispatch']['agree']}/{sp['dispatch']['samples']}={sp['dispatch']['hit_rate']*100:.0f}%" if sp['dispatch']['samples'] else "0"
    print(f"#{i+1:3d} {pp['dispatch_winner']:5d} {pp['dispatch_tpc']:5d} {pp['acc_tpc']:4d} "
          f"{pp['acc_p1_pct']:4d} {pp['acc_peaks_below']:5d} {pp['acc_p1_dominance']:5d} "
          f"{pp['shaking_tpc']:4d} {pp['shaking_p1_pct']:4d} "
          f"{r['overall_hit_rate']*100:7.1f}% {r['total_valid']:5d} acc={acc_str:>11s} dis={dis_str:>10s}")

# ---------- 保存结果 ----------
top = results[:15] if results else None
output = {
    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'data/backtest_12stocks_raw.json (869 future_return 样本)',
    'eval_window': f'future_return ±{RISE_THRESHOLD}% (rise/fall/neutral)',
    'best_params': top[0]['params'] if top else None,
    'best_hit_rate': top[0]['overall_hit_rate'] if top else None,
    'best_samples': top[0]['total_valid'] if top else None,
    'top15': [{
        'rank': i+1,
        'params': r['params'],
        'overall_hit_rate': r['overall_hit_rate'],
        'total_valid': r['total_valid'],
        'health_dist': r['health_dist'],
        'specific': r['specific'],
    } for i, r in enumerate(top)] if top else [],
}

result_path = 'data/health_threshold_evolution_v2.json'
with open(result_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f'\n结果: {result_path}')
print('建议: 选取 top15 之一, 用其参数构造 classify_health_params 函数')
