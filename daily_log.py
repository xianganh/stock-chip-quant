#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日分析日志系统:
  - 每天分析结果自动保存到 daily_log/YYYY-MM-DD.json
  - 提供查询历史、日间对比功能
"""
import os, sys, json, warnings
from datetime import datetime
from typing import Dict, List, Optional
warnings.filterwarnings('ignore')

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_log')
os.makedirs(LOG_DIR, exist_ok=True)

TODAY = datetime.now().strftime('%Y-%m-%d')
LOG_PATH = os.path.join(LOG_DIR, f'{TODAY}.json')


def load_today() -> dict:
    """加载今天的分析记录"""
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'date': TODAY, 'stocks': {}, 'summary': ''}


def save_today(data: dict):
    """保存今天的分析记录"""
    data['date'] = TODAY
    data['updated_at'] = datetime.now().isoformat()
    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f'已保存到 {LOG_PATH}')


def add_stock(sym: str, name: str, category: str, result: dict):
    """添加一只股票的分析结果"""
    data = load_today()
    key = f'{sym}|{name}'
    data['stocks'][key] = {
        'symbol': sym,
        'name': name,
        'category': category,  # 持仓/关注/临时
        'v1': result.get('v1', 0),
        'v2': result.get('v2', 0.0),
        'v2_grade': result.get('v2g', '—'),
        'v3': result.get('v3', 0.0),
        'v3_grade': result.get('v3g', '—'),
        'total': result.get('tot', 0.0),
        'close': result.get('close', 0.0),
        'tpc': result.get('tpc', 0),
        'winner': result.get('wnr', 0),
        'peaks_below': result.get('pb', 0),
        'resistance': result.get('rd'),
        'morphology': result.get('morph', '—'),
        'trend': result.get('trend', '—'),
        'l0': result.get('l0', 0.5),
        'decision': result.get('decision', ''),
        'peak_shift_14d': result.get('peak_shift_14d'),
        'peak_shift_streak': result.get('peak_shift_streak', 0),
        'tpc_streak': result.get('tpc_streak', 0),
        'conv_path_score': result.get('conv_path_score', 0.0),
        'dense_days': result.get('dense_days', 0),
        'res_melt_7d': result.get('res_melt_7d'),
        'evol_consistency': result.get('evol_consistency', 0),
    }
    save_today(data)
    return data


def add_batch(stocks_with_results: List[tuple]):
    """批量添加分析结果
    stocks_with_results: [(sym, name, category, result_dict), ...]
    """
    data = load_today()
    for sym, name, cat, r in stocks_with_results:
        key = f'{sym}|{name}'
        data['stocks'][key] = {
            'symbol': sym, 'name': name, 'category': cat,
            'v1': r.get('v1', 0), 'v2': r.get('v2', 0.0), 'v2_grade': r.get('v2g', '—'),
            'v3': r.get('v3', 0.0), 'v3_grade': r.get('v3g', '—'),
            'total': r.get('tot', 0.0), 'close': r.get('close', 0.0),
            'tpc': r.get('tpc', 0), 'winner': r.get('wnr', 0),
            'peaks_below': r.get('pb', 0), 'resistance': r.get('rd'),
            'morphology': r.get('morph', '—'), 'trend': r.get('trend', '—'),
            'l0': r.get('l0', 0.5), 'decision': r.get('decision', ''),
            'peak_shift_14d': r.get('peak_shift_14d'),
            'peak_shift_streak': r.get('peak_shift_streak', 0),
            'tpc_streak': r.get('tpc_streak', 0),
            'conv_path_score': r.get('conv_path_score', 0.0),
            'dense_days': r.get('dense_days', 0),
            'res_melt_7d': r.get('res_melt_7d'),
            'evol_consistency': r.get('evol_consistency', 0),
        }
    save_today(data)
    return data


def list_dates() -> List[str]:
    """列出所有有记录的日期"""
    dates = []
    for f in sorted(os.listdir(LOG_DIR)):
        if f.endswith('.json') and not f.startswith('_'):
            dates.append(f.replace('.json', ''))
    return dates


def load_date(date_str: str) -> Optional[dict]:
    """加载指定日期的记录"""
    path = os.path.join(LOG_DIR, f'{date_str}.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def diff_stock(sym: str, date1: str, date2: str) -> dict:
    """对比某股票在两个日期的变化"""
    d1 = load_date(date1)
    d2 = load_date(date2)
    if not d1 or not d2: return {}
    for key, val in d1.get('stocks', {}).items():
        if val.get('symbol') == sym:
            s1 = val; break
    else: s1 = None
    for key, val in d2.get('stocks', {}).items():
        if val.get('symbol') == sym:
            s2 = val; break
    else: s2 = None
    if not s1 or not s2: return {}
    return {
        'name': s1['name'],
        'date1': date1, 'date2': date2,
        'v1': f'{s1["v1"]} → {s2["v1"]}',
        'v2': f'{s1["v2"]:.1f} → {s2["v2"]:.1f}',
        'total': f'{s1["total"]:.1f} → {s2["total"]:.1f}',
        'winner': f'{s1["winner"]:.1%} → {s2["winner"]:.1%}',
        'trend': f'{s1["trend"]} → {s2["trend"]}',
        'close': f'{s1["close"]:.2f} → {s2["close"]:.2f}',
    }


def today_summary() -> dict:
    """今天的快速摘要"""
    data = load_today()
    stocks = list(data['stocks'].values())
    holdings = [s for s in stocks if s['category'] == '持仓']
    watchlist = [s for s in stocks if s['category'] == '关注']

    top = sorted(stocks, key=lambda x: x['total'], reverse=True)[:5]
    worst = sorted(stocks, key=lambda x: x['total'])[:3]
    strong = [s for s in stocks if s['v1'] >= 6]
    avoid = [s for s in stocks if s['v1'] <= -2]

    return {
        'date': TODAY,
        'total': len(stocks),
        'holdings': len(holdings), 'watchlist': len(watchlist),
        'avg_v1_holdings': sum(h['v1'] for h in holdings)/max(len(holdings),1),
        'top5': [(s['name'], s['v1'], s['total']) for s in top],
        'worst3': [(s['name'], s['v1'], s['total']) for s in worst],
        'strong_buy': [(s['name'], s['v1']) for s in strong],
        'avoid': [(s['name'], s['v1']) for s in avoid],
    }


if __name__ == '__main__':
    s = today_summary()
    print(f'📅 {s["date"]} 分析日志摘要')
    print(f'   总计: {s["total"]}只 (持仓{s["holdings"]} + 关注{s["watchlist"]})')
    print(f'   持仓平均v1: {s["avg_v1_holdings"]:.1f}')
    print(f'   Top5: {", ".join(f"{n}(v1={v},tot={t})" for n,v,t in s["top5"])}')
    print(f'   最差: {", ".join(f"{n}(v1={v})" for n,v in s["worst3"])}')
    print(f'   强买: {", ".join(f"{n}(v1={v})" for n,v in s["strong_buy"])}')
    print(f'   回避: {", ".join(f"{n}(v1={v})" for n,v in s["avoid"])}')
    print(f'\n   历史记录: {list_dates()}')
