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
        # 默认参数 - v3.1 进化版（最终版：软门槛+递减减仓）
        self.params = params or {
            # ===== 建仓：双路径（左侧抄底+右侧突破），L1软门槛 =====
            'entry_score': 5,
            'entry_strict': False,
            'require_tpc_converge': False,  # 不强求，评分里已经加权
            'entry_width_max_q': 0.9,

            # 三级减仓（触发阈值）
            'warn_winner': 80,
            'warn_cost_dist': 10,
            'warn_min_ret': 10,

            'high_winner': 90,
            'high_cost_dist': 15,
            'high_min_ret': 20,

            'exit_winner': 95,
            'exit_cost_dist': 20,

            # ===== L2：预止盈（极高收益+高位滞涨才触发，防止卖飞主升浪） =====
            'enable_pre_take_profit': True,
            'pre_tp_winner': 92,       # W 更高才考虑
            'pre_tp_days': 3,          # 连续 3 天（要求更严）
            'pre_tp_stall_days': 2,    # 最近 2 天没创新高（确认滞涨）
            'pre_tp_pct': 0.5,
            'pre_tp_min_ret': 60,      # 至少赚 60% 才预止盈

            # ===== L3：递减减仓（替代硬限次，越涨越"舍不得卖"） =====
            # 预警每次比例：第1次30% → 20% → 10% → 5%，之后维持5%
            'warn_ratio_schedule': [0.30, 0.20, 0.10, 0.05],
            # 高度预警首次减仓比例（剩余部分按预警表继续递减）
            'high_first_ratio': 0.30,
            # 底仓保护：剩 <15% 就不再预警/高度减，留给清仓/预止盈
            'warn_min_keep': 0.15,

            # 硬止损
            'stop_loss': 0.92,
        }
        self._warn_count = 0
        self._high_count = 0
        self._pre_tp_done = False

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
        """入场信号评分 v3.1 进化版（纠正TPC方向 + 新增左侧抄底路径）

        关键修正(宏昌电子实证):
          TPC↑变大 = 筹码更集中(好事)。对应 winner=99.5% → TPC=21.3；winner=45% → TPC=15.8

        双路径打分：
          ① 左侧抄底(winner<25% 极端被套) + ② 右侧突破(筹码集中度持续提升)
        """
        s = 0

        # ============= 路径①：左侧抄底（3/20 那种极端坑，winner<25% + 超跌 + 趋势不崩） =============
        winner = row.get('winner', 50)
        cd = row.get('cost_dist_pct', 0)
        if winner < 25:
            # 极端恐慌盘：大部分人被套，反而是抄底黄金坑
            if cd < -7:
                s += 3.0  # 超跌7%以上给大分
            elif cd < -4:
                s += 2.0
            # 只要不创新低 + 站上MA20就加
            if row['close'] > row['ma20']:
                s += 1.5
            if row.get('skewness', 0) > 0.2:  # 右偏(峰在下方，获利盘在往上走)
                s += 0.5

        # ============= 路径②：右侧突破（筹码在收敛，获利盘在提升） =============
        # 获利盘上升趋势 (连续7天净流入，这是主力拉抬前提)
        if row['winner_chg_7d'] > row.get('winner_chg_7d_70', 0): s += 2

        # 支撑位 + 站上MA20（趋势确认）
        if row['support_distance_pct'] < 3 and row['close'] > row['ma20']: s += 2

        # v3.1 修正方向：TPC↑变大 = 更集中 → 加分；且TPC绝对水平高于中位数
        if row['tpc_chg_7d'] > 0 and row['tpc'] > row.get('tpc_50', 0): s += 1.5  # 原版是对的

        # width 收窄 + 绝对宽度不高 → 说明筹码在收敛
        if row['width_chg_7d'] < 0 and row['width'] < row.get('width_50', 999): s += 1

        # 熵下降（集中度提升）
        if row['entropy_chg_7d'] < 0 and row['entropy'] < row.get('entropy_50', 999): s += 1

        # 成本偏负（低于加权成本，安全边际）→ 只在右侧突破时也加一点
        if cd < -5 and winner >= 25:
            s += 1.0

        # 右偏 + 站上MA20，向上动力
        if row['skewness'] > 0.3 and row['close'] > row['ma20']: s += 1
        return s

    def backtest(self, df: pd.DataFrame, start_idx: int = 0,
                 initial_cash: float = 100000) -> Tuple[float, List]:
        """
        分级持仓回测 v3.1 进化版

        阶段:
          1. 建仓: score≥5 + (可选)近7天TPC收敛 + width分位过滤
          2. 持仓中:
            - 预警: W>80%+CD>10%+涨幅>10% → 减30% (最多2次)
            - 高度预警: W>90%+CD>15%+涨幅>20% → 减50% (最多1次)
            - 预止盈 v3.1新增: 连续2天 W>90% + 股价非5日新高 → 减50%
            - 出货: W>95%+CD>20%+破MA10 → 清仓
            - 硬止损: 亏8% → 清仓
        """
        p = self.params
        cash, position, shares, cost = initial_cash, 0, 0, 0
        log = []
        last_buy_date = None
        # v3.1：初始化减仓计数器（每次新建仓都会重置）
        self._warn_count = 0
        self._high_count = 0
        self._pre_tp_done = False

        df = df.iloc[start_idx:].reset_index(drop=True)

        # 计算分位数
        quantiles = {}
        quantiles['winner_chg_7d_70'] = df['winner_chg_7d'].quantile(0.7)
        quantiles['tpc_50'] = df['tpc'].quantile(0.5)
        quantiles['width_50'] = df['width'].quantile(0.5)
        quantiles['entropy_50'] = df['entropy'].quantile(0.5)
        # v3.1：建仓用的 width 最大分位（默认0.6 = 排除前40%最分散的日子）
        quantiles['width_entry_max'] = df['width'].quantile(p.get('entry_width_max_q', 0.6))

        # v3.1：近5日最高收盘价（用于判断"不创新高"）
        stall = p.get('pre_tp_stall_days', 1)
        df['high_roll'] = df['close'].rolling(2 + stall, min_periods=2).max()
        df['stalled'] = df['close'] < df['high_roll']  # 今天没创(2+stall)日新高
        # v3.1：连续N天W>阈值的计数器
        df['winner_above_tp'] = (df['winner'] > p.get('pre_tp_winner', 91)).astype(int)
        df['winner_streak'] = df['winner_above_tp'].rolling(
            p.get('pre_tp_days', 2), min_periods=p.get('pre_tp_days', 2)).sum()

        for i, row in df.iterrows():
            if pd.isna(row['close']): continue
            date = row['date'].date()
            price = row['close']

            # ============================================================
            # 阶段1: 建仓
            #   entry_strict=False (默认) → 软门槛：score≥5 就上，TPC/width 只是参考
            #   entry_strict=True        → 硬门槛：必须 TPC 收敛+width 不发散
            # ============================================================
            if position == 0 and row['score'] >= p['entry_score']:
                entry_ok = True
                strict = p.get('entry_strict', False)
                if strict:
                    # 严格模式：TPC 必须收敛+width必须分位内
                    if p.get('require_tpc_converge', False) and not (row.get('tpc_chg_7d', 0) < 0):
                        entry_ok = False
                    if row.get('width', 999) > quantiles['width_entry_max']:
                        entry_ok = False
                else:
                    # 软模式：只有在"极度发散（width > 0.95分位）"才拦截
                    if row.get('width', 999) > df['width'].quantile(0.95):
                        entry_ok = False

                if entry_ok:
                    shares = cash / price
                    cost = price
                    position = 1
                    cash = 0
                    last_buy_date = date
                    self._warn_count = 0
                    self._high_count = 0
                    self._pre_tp_done = False
                    log.append({
                        'date': date, 'action': '建仓', 'price': price,
                        'shares': 1.0, 'reason': f'信号触发 (score={row["score"]:.1f})'
                    })
                    continue

            if position == 0: continue

            # ============================================================
            # 阶段2: 持仓管理
            # ============================================================
            current_ret = (price / cost - 1) * 100
            cost_dist = row.get('cost_dist_pct', 0)
            winner = row.get('winner', 0)
            ma10 = row.get('ma10', price)

            warn = (winner > p['warn_winner'] and
                    cost_dist > p['warn_cost_dist'] and
                    current_ret > p['warn_min_ret'])
            high_warn = (winner > p['high_winner'] and
                         cost_dist > p['high_cost_dist'] and
                         current_ret > p['high_min_ret'])
            exit_signal = (winner > p['exit_winner'] and
                          cost_dist > p['exit_cost_dist'] and
                          price < ma10)

            # v3.1 L2 进化：预止盈
            pre_tp_signal = False
            if (p.get('enable_pre_take_profit', True)
                    and not self._pre_tp_done
                    and row.get('winner_streak', 0) >= p.get('pre_tp_days', 2)
                    and bool(row.get('stalled', False))
                    and current_ret > p.get('pre_tp_min_ret', 35)):
                pre_tp_signal = True

            # ============================================================
            # 操作执行（优先级：清仓 > 预止盈 > 高度预警 > 预警 > 止损）
            # ============================================================
            if exit_signal:
                cash += shares * price
                log.append({
                    'date': date, 'action': f'出货清仓({current_ret:+.1f}%)',
                    'price': price, 'shares': 0,
                    'reason': f'W>{p["exit_winner"]}%+CD>{p["exit_cost_dist"]}%+破MA10'
                })
                shares = 0
                position = 0

            elif pre_tp_signal:
                # v3.1 新增：预止盈50%
                sell_ratio = p.get('pre_tp_pct', 0.5)
                sell_n = shares * sell_ratio
                cash += sell_n * price
                shares = shares * (1 - sell_ratio)
                self._pre_tp_done = True
                log.append({
                    'date': date, 'action': f'预止盈{int(sell_ratio*100)}%({current_ret:+.1f}%)',
                    'price': price, 'shares': shares,
                    'reason': f'W>90%连续{p.get("pre_tp_days",2)}天+未创新高'
                })

            elif high_warn and shares > 0:
                # ===== L3 进化：高度预警不再一刀切减50%，首30%，然后走递减 =====
                base_shares = initial_cash / cost  # 初始建仓股数（用于计算剩余仓位比例）
                keep_ratio_now = shares / base_shares
                if keep_ratio_now >= p.get('warn_min_keep', 0.15):
                    schedule = p.get('warn_ratio_schedule', [0.30, 0.20, 0.10, 0.05])
                    if self._high_count == 0:
                        ratio = p.get('high_first_ratio', 0.30)
                    else:
                        idx = min(self._warn_count, len(schedule) - 1)
                        ratio = schedule[idx]
                    self._high_count += 1
                    self._warn_count += 1
                    sell_n = shares * ratio
                    cash += sell_n * price
                    shares = shares - sell_n
                    log.append({
                        'date': date, 'action': f'高度减{int(ratio*100)}%#{self._high_count}({current_ret:+.1f}%)',
                        'price': price, 'shares': shares,
                        'reason': f'W>{p["high_winner"]}%+CD>{p["high_cost_dist"]}% | 余{keep_ratio_now*100:.0f}%'
                    })

            elif warn and shares > 0:
                # ===== L3 进化：递减减仓 30%→20%→10%→5%，替代硬限次 =====
                base_shares = initial_cash / cost
                keep_ratio_now = shares / base_shares
                if keep_ratio_now >= p.get('warn_min_keep', 0.15):
                    schedule = p.get('warn_ratio_schedule', [0.30, 0.20, 0.10, 0.05])
                    idx = min(self._warn_count, len(schedule) - 1)
                    ratio = schedule[idx]
                    self._warn_count += 1
                    sell_n = shares * ratio
                    cash += sell_n * price
                    shares = shares - sell_n
                    log.append({
                        'date': date, 'action': f'预警减{int(ratio*100)}%#{self._warn_count}({current_ret:+.1f}%)',
                        'price': price, 'shares': shares,
                        'reason': f'W>{p["warn_winner"]}%+CD>{p["warn_cost_dist"]}% | 余{keep_ratio_now*100:.0f}%'
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
        if position == 1 and shares > 0:
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
