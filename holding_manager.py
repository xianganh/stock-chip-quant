#!/usr/bin/env python3
"""
分级持仓管理系统 (Holding Manager v3.0)
==========================================

核心目标:
  1. 判断出货: 通过 Winner + 成本偏离 识别主力出货
  2. 减仓分级: 预警30% → 高度预警50% → 出货清仓
  3. 避免卖飞: 在持续上涨中保留大部分仓位
  4. 控制回撤: 下跌时及时减仓保护利润

设计原则:
  - 真实出货特征驱动 (基于2023-2024年真实出货点)
  - 三级减仓机制 (从轻到重)
  - 配合硬止损 (极端情况)
"""

import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

from chip_data_fetcher import fetch_complete_data
from chip_indicators import compute_all_chip_metrics


class HoldingManager:
    """分级持仓管理器"""

    def __init__(self, params: Dict = None):
        # 默认参数 - 基于真实出货特征
        self.params = params or {
            # 建仓信号
            'entry_score': 5,        # 评分≥5建仓

            # 三级减仓
            'warn_winner': 80,       # 预警: 获利盘>80%
            'warn_cost_dist': 10,    # 预警: 偏离成本>10%
            'warn_min_ret': 10,      # 预警: 涨幅>10%

            'high_winner': 90,       # 高度预警: 获利盘>90%
            'high_cost_dist': 15,    # 高度预警: 偏离成本>15%
            'high_min_ret': 20,      # 高度预警: 涨幅>20%

            'exit_winner': 95,       # 出货: 获利盘>95%
            'exit_cost_dist': 20,    # 出货: 偏离成本>20%

            # 硬止损
            'stop_loss': 0.92,       # 亏8%止损
        }

    def prepare_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取并计算数据"""
        data = fetch_complete_data(ts_code, start_date, end_date)
        df = pd.DataFrame(compute_all_chip_metrics(data['chip_data'], data['kline'], lookback_days=7))
        df = df.reset_index(drop=False)
        date_col = [c for c in df.columns if 'date' in c.lower()][0]
        df['date'] = pd.to_datetime(df[date_col].astype(str))

        # 均线
        for period in [5, 10, 20, 60]:
            df[f'ma{period}'] = df['close'].rolling(period).mean()

        # 变化率
        for metric in ['tpc', 'width', 'tp3', 'winner', 'entropy', 'skewness', 'kurtosis', 'p1_dominance']:
            df[f'{metric}_chg_7d'] = df[metric].diff(7)

        # 价格偏离加权成本
        df['cost_dist_pct'] = (df['close'] - df['weight_avg']) / df['weight_avg'] * 100

        # 入场信号评分
        df['score'] = df.apply(self._score_entry, axis=1)
        return df

    def _score_entry(self, row):
        """入场信号评分 (基于跨12股稳定性>40的信号)"""
        s = 0
        if row['winner_chg_7d'] > row.get('winner_chg_7d_70', 0): s += 2
        if row['support_distance_pct'] < 3 and row['close'] > row['ma20']: s += 2
        if row['tpc_chg_7d'] > 0 and row['tpc'] > row.get('tpc_50', 0): s += 1.5
        if row['width_chg_7d'] < 0 and row['width'] < row.get('width_50', 0): s += 1
        if row['entropy_chg_7d'] < 0 and row['entropy'] < row.get('entropy_50', 0): s += 1
        if row['cost_dist_pct'] < -5: s += 1.5
        if row['skewness'] > 0.3 and row['close'] > row['ma20']: s += 1
        return s

    def backtest(self, df: pd.DataFrame, start_idx: int = 0,
                 initial_cash: float = 100000) -> Tuple[float, List]:
        """
        分级持仓回测

        阶段:
          1. 建仓: score≥5
          2. 持仓中:
            - 预警: W>80%+CD>10%+涨幅>10% → 减30%
            - 高度预警: W>90%+CD>15%+涨幅>20% → 减50%
            - 出货: W>95%+CD>20%+破MA10 → 清仓
            - 硬止损: 亏8% → 清仓
        """
        p = self.params
        cash, position, shares, cost = initial_cash, 0, 0, 0
        log = []
        last_buy_date = None

        df = df.iloc[start_idx:].reset_index(drop=True)

        # 计算分位数
        quantiles = {}
        for m in ['winner_chg_7d', 'tpc', 'width', 'entropy']:
            quantiles[f'{m}_70'] = df[m].quantile(0.7) if 'winner_chg_7d' in m else 0
            quantiles[f'{m}_50'] = df[m].quantile(0.5)
        quantiles['winner_chg_7d_70'] = df['winner_chg_7d'].quantile(0.7)
        quantiles['tpc_50'] = df['tpc'].quantile(0.5)
        quantiles['width_50'] = df['width'].quantile(0.5)
        quantiles['entropy_50'] = df['entropy'].quantile(0.5)

        for i, row in df.iterrows():
            if pd.isna(row['close']): continue
            date = row['date'].date()
            price = row['close']

            # === 阶段1: 建仓 ===
            if position == 0 and row['score'] >= p['entry_score']:
                shares = cash / price
                cost = price
                position = 1
                cash = 0
                last_buy_date = date
                log.append({
                    'date': date, 'action': '建仓', 'price': price,
                    'shares': 1.0, 'reason': f'信号触发 (score={row["score"]:.1f})'
                })
                continue

            if position == 0: continue

            # === 阶段2: 持仓管理 ===
            current_ret = (price / cost - 1) * 100
            cost_dist = row.get('cost_dist_pct', 0)
            winner = row.get('winner', 0)
            ma10 = row.get('ma10', price)

            # 出货信号检测
            warn = (winner > p['warn_winner'] and
                    cost_dist > p['warn_cost_dist'] and
                    current_ret > p['warn_min_ret'])

            high_warn = (winner > p['high_winner'] and
                         cost_dist > p['high_cost_dist'] and
                         current_ret > p['high_min_ret'])

            exit_signal = (winner > p['exit_winner'] and
                          cost_dist > p['exit_cost_dist'] and
                          price < ma10)

            # === 操作执行 ===
            if exit_signal:
                # 出货清仓
                cash += shares * price
                log.append({
                    'date': date, 'action': f'出货清仓({current_ret:+.1f}%)',
                    'price': price, 'shares': 0,
                    'reason': f'W>{p["exit_winner"]}%+CD>{p["exit_cost_dist"]}%+破MA10'
                })
                shares = 0
                position = 0

            elif high_warn and shares > 0:
                # 高度预警: 减50%
                sell_n = shares * 0.5
                cash += sell_n * price
                shares = shares * 0.5
                log.append({
                    'date': date, 'action': f'高度减50%({current_ret:+.1f}%)',
                    'price': price, 'shares': shares,
                    'reason': f'W>{p["high_winner"]}%+CD>{p["high_cost_dist"]}%'
                })

            elif warn and shares > 0:
                # 预警: 减30%
                sell_n = shares * 0.3
                cash += sell_n * price
                shares = shares * 0.7
                log.append({
                    'date': date, 'action': f'预警减30%({current_ret:+.1f}%)',
                    'price': price, 'shares': shares,
                    'reason': f'W>{p["warn_winner"]}%+CD>{p["warn_cost_dist"]}%'
                })

            elif price < cost * p['stop_loss']:
                # 硬止损
                cash += shares * price
                log.append({
                    'date': date, 'action': f'硬止损({current_ret:+.1f}%)',
                    'price': price, 'shares': 0, 'reason': f'亏{(1-p["stop_loss"])*100:.0f}%'
                })
                shares = 0
                position = 0

        # 期末平仓
        if position == 1:
            final_price = df.iloc[-1]['close']
            final_ret = (final_price / cost - 1) * 100
            cash += shares * final_price
            log.append({
                'date': df.iloc[-1]['date'].date(),
                'action': f'期末({final_ret:+.1f}%)',
                'price': final_price, 'shares': 0, 'reason': '期末'
            })

        return cash, log


# ═══════════════════════════════════════════════════════
#  实战接口
# ═══════════════════════════════════════════════════════

def analyze_holding(ts_code: str, start_date: str, end_date: str,
                    start_idx: int = 0) -> Dict:
    """
    持仓管理实战分析

    Args:
        ts_code: 股票代码
        start_date: 起始日期
        end_date: 结束日期
        start_idx: 开始回测的行索引 (默认0)

    Returns:
        {final_cash, log, buy_hold_return, strategy_return, alpha}
    """
    mgr = HoldingManager()
    df = mgr.prepare_data(ts_code, start_date, end_date)

    if start_idx > 0:
        df = df.iloc[start_idx:].reset_index(drop=True)

    final_cash, log = mgr.backtest(df, start_idx=0)
    buy_hold = (df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100
    strategy = (final_cash / 100000 - 1) * 100

    return {
        'ts_code': ts_code,
        'period': f"{df.iloc[0]['date'].date()} ~ {df.iloc[-1]['date'].date()}",
        'final_cash': final_cash,
        'buy_hold_return': buy_hold,
        'strategy_return': strategy,
        'alpha': strategy - buy_hold,
        'trades': log,
    }


if __name__ == '__main__':
    # 宏昌电子 2023-2024 测试
    result = analyze_holding('603002.SH', '20230601', '20241231')

    print('='*70)
    print(f"宏昌电子 持仓管理 V3 (2023-06-01 ~ 2024-12-31)")
    print('='*70)
    print(f"区间: {result['period']}")
    print(f"买入持有: {result['buy_hold_return']:+.2f}%")
    print(f"策略收益: {result['strategy_return']:+.2f}%")
    print(f"超额 alpha: {result['alpha']:+.2f}%")
    print(f"操作次数: {len(result['trades'])}")
    print()
    print('操作明细:')
    for t in result['trades']:
        print(f"  {t['date']} {t['action']} 价格{t['price']:.2f} 原因:{t['reason']}")
