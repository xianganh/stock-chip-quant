#!/usr/bin/env python3
"""
筹码峰指标回测验证引擎 (带定性理论支撑)
============================================
在经典量化理论指导下，对各项筹码峰指标进行历史回测验证。

核心理论框架:
  1. 趋势方向优先: 指标必须结合趋势解读才有意义
  2. 变化趋势比绝对值重要: 指标上升/下降的动量更有预测价值
  3. 多空场景分离: 同一指标在不同趋势下可能有相反含义

验证维度:
  1. 趋势环境下的单指标验证: 分上涨/下跌趋势验证指标有效性
  2. 指标变化率验证: 验证指标变化速度与未来收益的相关性
  3. 理论驱动的信号组合: 基于量化理论构建信号组合进行验证
  4. 健康度评分修正: 根据回测结果修正评分体系

评估指标:
  - 胜率 (Win Rate): 信号出现后未来N日上涨的比例
  - 平均收益 (Avg Return): 信号出现后未来N日的平均收益率
  - 盈亏比 (Profit/Loss Ratio): 平均盈利 / 平均亏损
  - 夏普比率 (Sharpe-like): 平均收益 / 收益标准差
  - 信号次数 (Signal Count): 满足条件的交易日数量
  - 最大回撤 (Max Drawdown): 信号后最坏情况
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

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


@dataclass
class SignalResult:
    """单次信号验证结果"""
    signal_name: str          # 信号名称
    description: str          # 信号描述（定性理论）
    condition: str            # 触发条件
    signal_count: int         # 信号次数
    win_rate: float           # 胜率 (%)
    avg_return: float         # 平均未来收益 (%)
    profit_loss_ratio: float  # 盈亏比
    sharpe_like: float        # 夏普-like比率
    max_drawdown: float       # 最大回撤 (%)


class QualitativeValidator:
    """
    定性驱动的筹码峰指标验证器。

    核心理论:
      - TPC上升 = 筹码向少数峰聚集 = 主力控盘加强 → 看涨
      - Width收窄 = 筹码集中过程 = 蓄势待发 → 看涨
      - TP3>28%且上升 = 市场成本一致 = 突破概率高 → 看涨
      - Winner必须结合趋势: 趋势向上时Winner高是趋势延续，趋势向下时是派发风险
      - DIST负偏离过大 = 超跌 = 可能反弹 → 看涨

    用法:
        validator = QualitativeValidator('603002.SH', '20260301', '20260624')
        validator.fetch_and_compute()
        report = validator.generate_report()
    """

    def __init__(self, ts_code: str, start_date: str, end_date: str,
                 future_days: int = 10, min_signals: int = 5):
        self.ts_code = ts_code
        self.start_date = start_date
        self.end_date = end_date
        self.future_days = future_days
        self.min_signals = min_signals

        self.data = None
        self.results = []
        self.df = None

    def fetch_and_compute(self):
        """获取数据并计算所有指标（含趋势指标）。"""
        print(f"[QualitativeValidator] 📊 获取 {self.ts_code} 数据...")
        self.data = fetch_complete_data(self.ts_code, self.start_date, self.end_date)

        print(f"[QualitativeValidator] 🔍 计算指标...")
        self.results = compute_all_chip_metrics(
            self.data['chip_data'],
            self.data['kline'],
            lookback_days=7
        )

        self.df = pd.DataFrame(self.results)
        self.df = self.df[self.df['future_return'].notna()]

        # 计算趋势指标
        self._compute_trend_indicators()

        print(f"[QualitativeValidator] ✅ 数据准备完成: {len(self.df)}个有效样本")
        return self

    def _compute_trend_indicators(self):
        """计算趋势辅助指标 + 新指标变化率。"""
        # MA
        self.df['ma5'] = self.df['close'].rolling(5).mean()
        self.df['ma20'] = self.df['close'].rolling(20).mean()
        self.df['ma60'] = self.df['close'].rolling(60).mean()

        # 价格变化率
        self.df['price_chg_5d'] = self.df['close'].pct_change(5) * 100
        self.df['price_chg_20d'] = self.df['close'].pct_change(20) * 100

        # 趋势方向
        self.df['trend_up'] = (self.df['ma5'] > self.df['ma20']) & (self.df['ma20'] > self.df['ma60'])
        self.df['trend_down'] = (self.df['ma5'] < self.df['ma20']) & (self.df['ma20'] < self.df['ma60'])
        self.df['trend_side'] = ~self.df['trend_up'] & ~self.df['trend_down']

        # 基础指标变化率 (7日)
        for metric in ['tpc', 'width', 'tp3', 'winner', 'dist']:
            self.df[f'{metric}_chg_7d'] = self.df[metric].diff(7)
            self.df[f'{metric}_rising'] = self.df[f'{metric}_chg_7d'] > 0

        # ★ 新增: 高级指标变化率 (7日)
        advanced_metrics = ['top5', 'top10', 'skewness', 'kurtosis', 'gradient',
                           'entropy', 'width_70', 'width_90', 'p1_dominance',
                           'peak_entropy', 'p1_pct', 'gap_pct']
        for metric in advanced_metrics:
            if metric in self.df.columns:
                self.df[f'{metric}_chg_7d'] = self.df[metric].diff(7)
                self.df[f'{metric}_rising'] = self.df[f'{metric}_chg_7d'] > 0
                self.df[f'{metric}_falling'] = self.df[f'{metric}_chg_7d'] < 0

        # ★ 新增: 加权成本偏离
        if 'weight_avg' in self.df.columns:
            self.df['cost_dist_pct'] = (self.df['close'] - self.df['weight_avg']) / self.df['weight_avg'] * 100

        # ★ 新增: 阻力/支撑距离
        if 'resistance_distance_pct' in self.df.columns:
            self.df['has_resistance'] = self.df['resistance_distance_pct'].notna()
        if 'support_distance_pct' in self.df.columns:
            self.df['has_support'] = self.df['support_distance_pct'].notna()

    def _calc_stats(self, returns: pd.Series) -> Dict:
        """计算统计指标。"""
        if len(returns) == 0:
            return {
                'signal_count': 0, 'win_rate': 0, 'avg_return': 0,
                'profit_loss_ratio': 0, 'sharpe_like': 0, 'max_drawdown': 0,
            }

        wins = returns[returns > 0]
        losses = returns[returns < 0]

        win_rate = len(wins) / len(returns) * 100
        avg_return = returns.mean()
        avg_profit = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
        profit_loss_ratio = avg_profit / avg_loss if avg_loss != 0 else 0
        std = returns.std()
        sharpe_like = avg_return / std if std != 0 else 0
        max_drawdown = returns.min()

        return {
            'signal_count': len(returns),
            'win_rate': round(win_rate, 1),
            'avg_return': round(avg_return, 2),
            'profit_loss_ratio': round(profit_loss_ratio, 2),
            'sharpe_like': round(sharpe_like, 2),
            'max_drawdown': round(max_drawdown, 2),
        }

    def validate_single_metric_in_trend(self) -> List[SignalResult]:
        """
        在不同趋势环境下验证单指标。

        理论: 指标必须结合趋势解读才有意义。
              Winner在上涨趋势中高是好事，在下跌趋势中高是风险。
        """
        results = []
        df = self.df.dropna(subset=['trend_up', 'trend_down'])

        # 上涨趋势下的指标验证
        up_df = df[df['trend_up']]
        down_df = df[df['trend_down']]

        # TPC在上涨趋势中上升 → 主力控盘加强
        mask = up_df['tpc_rising'] & (up_df['tpc'] > up_df['tpc'].quantile(0.6))
        if len(up_df[mask]) >= self.min_signals:
            stats = self._calc_stats(up_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='TPC上升(上涨趋势)',
                description='上涨趋势中TPC持续上升，说明筹码向少数峰聚集，主力控盘加强',
                condition='trend_up & tpc_rising & tpc>60%分位',
                **stats
            ))

        # Width在上涨趋势中收窄 → 筹码集中
        mask = (~up_df['width_rising']) & (up_df['width'] < up_df['width'].quantile(0.4))
        if len(up_df[mask]) >= self.min_signals:
            stats = self._calc_stats(up_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Width收窄(上涨趋势)',
                description='上涨趋势中Width持续收窄，说明筹码集中过程加速，蓄势待发',
                condition='trend_up & width_falling & width<40%分位',
                **stats
            ))

        # TP3在上涨趋势中高值且上升 → 成本一致
        mask = up_df['tp3_rising'] & (up_df['tp3'] > up_df['tp3'].quantile(0.7))
        if len(up_df[mask]) >= self.min_signals:
            stats = self._calc_stats(up_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='TP3高值上升(上涨趋势)',
                description='上涨趋势中TP3高值且上升，说明市场成本趋于一致，突破概率高',
                condition='trend_up & tp3_rising & tp3>70%分位',
                **stats
            ))

        # Winner在上涨趋势中高值 → 趋势延续 (获利盘继续推升)
        mask = up_df['winner'] > up_df['winner'].quantile(0.7)
        if len(up_df[mask]) >= self.min_signals:
            stats = self._calc_stats(up_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Winner高值(上涨趋势)',
                description='上涨趋势中Winner高值，说明获利盘占比高，趋势有望延续',
                condition='trend_up & winner>70%分位',
                **stats
            ))

        # ============== 下跌趋势 ==============
        # TPC在下跌趋势中上升 → 可能在筑底 (筹码向新的峰聚集)
        mask = down_df['tpc_rising']
        if len(down_df[mask]) >= self.min_signals:
            stats = self._calc_stats(down_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='TPC上升(下跌趋势)',
                description='下跌趋势中TPC上升，可能是筹码在新价位重新聚集，筑底信号',
                condition='trend_down & tpc_rising',
                **stats
            ))

        # Width在下跌趋势中收窄 → 可能止跌 (筹码集中)
        mask = (~down_df['width_rising']) & (down_df['width'] < down_df['width'].quantile(0.4))
        if len(down_df[mask]) >= self.min_signals:
            stats = self._calc_stats(down_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Width收窄(下跌趋势)',
                description='下跌趋势中Width收窄，筹码开始集中，可能是止跌信号',
                condition='trend_down & width_falling & width<40%分位',
                **stats
            ))

        # Winner在下跌趋势中高值 → 派发风险 (高位获利盘出逃)
        mask = down_df['winner'] > down_df['winner'].quantile(0.7)
        if len(down_df[mask]) >= self.min_signals:
            stats = self._calc_stats(down_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Winner高值(下跌趋势)',
                description='下跌趋势中Winner高值，说明高位获利盘仍在，下跌可能继续',
                condition='trend_down & winner>70%分位',
                **stats
            ))

        # Winner在下跌趋势中骤降 → 恐慌盘出逃，可能反弹
        mask = down_df['winner_chg_7d'] < down_df['winner_chg_7d'].quantile(0.1)
        if len(down_df[mask]) >= self.min_signals:
            stats = self._calc_stats(down_df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Winner骤降(下跌趋势)',
                description='下跌趋势中Winner大幅下降，恐慌盘出逃，可能出现反弹',
                condition='trend_down & winner_chg_7d<10%分位',
                **stats
            ))

        # ============== 不分趋势 ==============
        # DIST负偏离过大 → 超跌反弹
        mask = df['dist'] < df['dist'].quantile(0.1)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='DIST负偏离(超跌)',
                description='价格大幅低于P1（主力成本），超跌状态，可能出现反弹',
                condition='dist<10%分位',
                **stats
            ))

        return results

    def validate_indicator_momentum(self) -> List[SignalResult]:
        """
        验证指标变化率（动量）与未来收益的相关性。

        理论: 指标变化趋势比绝对值更重要。
              TPC从20%上升到25%，比TPC稳定在30%更有意义。
        """
        results = []
        df = self.df.dropna(subset=['tpc_chg_7d', 'width_chg_7d', 'tp3_chg_7d', 'winner_chg_7d'])

        # TPC加速上升 (变化率大于中位数)
        mask = df['tpc_chg_7d'] > df['tpc_chg_7d'].quantile(0.7)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='TPC加速上升',
                description='TPC变化率处于高位，筹码集中速度加快，看涨信号',
                condition='tpc_chg_7d>70%分位',
                **stats
            ))

        # Width加速收窄 (负变化率绝对值大)
        mask = df['width_chg_7d'] < df['width_chg_7d'].quantile(0.3)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Width加速收窄',
                description='Width负变化率大，筹码集中速度加快，看涨信号',
                condition='width_chg_7d<30%分位',
                **stats
            ))

        # TP3加速上升
        mask = df['tp3_chg_7d'] > df['tp3_chg_7d'].quantile(0.7)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='TP3加速上升',
                description='TP3变化率处于高位，±3%成本集中度快速提升，看涨信号',
                condition='tp3_chg_7d>70%分位',
                **stats
            ))

        # Winner加速上升 (趋势确认)
        mask = df['winner_chg_7d'] > df['winner_chg_7d'].quantile(0.7)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Winner加速上升',
                description='获利盘快速增加，趋势确认或加速',
                condition='winner_chg_7d>70%分位',
                **stats
            ))

        # Winner加速下降 (派发确认)
        mask = df['winner_chg_7d'] < df['winner_chg_7d'].quantile(0.3)
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='Winner加速下降',
                description='获利盘快速减少，派发或恐慌出逃',
                condition='winner_chg_7d<30%分位',
                **stats
            ))

        return results

    def validate_theory_based_signals(self) -> List[SignalResult]:
        """
        验证基于经典量化理论构建的信号组合。

        理论组合:
          1. 控盘加强组合: TPC上升 + Width收窄 → 主力控盘加强
          2. 突破确认组合: TP3高值上升 + 价格>MA20 → 突破概率高
          3. 趋势延续组合: Winner高值上升 + 价格>MA20 → 趋势延续
          4. 超跌反弹组合: DIST负偏离 + Width收窄 → 超跌反弹
          5. 派发预警组合: Winner骤降 + 价格<MA20 → 派发确认
        """
        results = []
        df = self.df.dropna(subset=['ma20', 'tpc_rising', 'width_rising', 'tp3_rising', 'winner_rising'])

        # 组合1: 控盘加强 → TPC上升 + Width收窄
        mask = df['tpc_rising'] & (~df['width_rising'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='控盘加强组合',
                description='TPC上升(筹码集中) + Width收窄(分布变窄) → 主力控盘加强，看涨',
                condition='tpc_rising & width_falling',
                **stats
            ))

        # 组合2: 突破确认 → TP3高值上升 + 价格>MA20
        mask = (df['tp3_rising']) & (df['tp3'] > df['tp3'].quantile(0.6)) & (df['close'] > df['ma20'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='突破确认组合',
                description='TP3高值上升(成本一致) + 价格>MA20(趋势向上) → 突破概率高',
                condition='tp3_rising & tp3>60%分位 & close>ma20',
                **stats
            ))

        # 组合3: 趋势延续 → Winner高值上升 + 价格>MA20
        mask = (df['winner_rising']) & (df['winner'] > df['winner'].quantile(0.6)) & (df['close'] > df['ma20'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='趋势延续组合',
                description='Winner高值上升(获利盘增加) + 价格>MA20(趋势向上) → 趋势延续',
                condition='winner_rising & winner>60%分位 & close>ma20',
                **stats
            ))

        # 组合4: 超跌反弹 → DIST负偏离 + Width收窄
        mask = (df['dist'] < df['dist'].quantile(0.2)) & (~df['width_rising'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='超跌反弹组合',
                description='DIST负偏离(超跌) + Width收窄(筹码集中) → 可能出现反弹',
                condition='dist<20%分位 & width_falling',
                **stats
            ))

        # 组合5: 派发预警 → Winner骤降 + 价格<MA20
        mask = (df['winner_chg_7d'] < df['winner_chg_7d'].quantile(0.2)) & (df['close'] < df['ma20'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='派发预警组合',
                description='Winner骤降(获利盘出逃) + 价格<MA20(趋势向下) → 派发确认，看跌',
                condition='winner_chg_7d<20%分位 & close<ma20',
                **stats
            ))

        # 组合6: 强势控盘 → TPC上升 + TP3上升 + Width收窄
        mask = df['tpc_rising'] & df['tp3_rising'] & (~df['width_rising'])
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='强势控盘组合',
                description='TPC上升 + TP3上升 + Width收窄 → 多维度确认主力控盘，强烈看涨',
                condition='tpc_rising & tp3_rising & width_falling',
                **stats
            ))

        return results

    def validate_advanced_indicators(self) -> List[SignalResult]:
        """
        验证高级筹码分布指标的有效性。

        新指标定性理论:
          - skewness>0.3: 右偏，套牢盘重。若价格突破MA20，套牢盘解套→看涨
          - skewness<-0.3: 左偏，获利盘重。若价格跌破MA20，获利盘出逃→看跌
          - kurtosis>2: 尖峰，筹码高度集中→看涨
          - entropy低: 分布有序集中→看涨; entropy下降→集中过程
          - width_70/width_90收窄: 核心/整体筹码集中→看涨
          - p1_dominance>0.6: 主峰突出，控盘明显→看涨
          - top5>60%: 高度集中→看涨
          - cost_dist_pct<-5%: 价格低于加权成本，超跌→可能反弹
          - gradient>0.5: 断层明显，有筹码真空区→价格可能快速穿越
        """
        results = []
        df = self.df

        # 1. 偏度右偏 + 趋势向上 → 套牢盘解套
        if 'skewness' in df.columns:
            mask = (df['skewness'] > 0.3) & (df['close'] > df['ma20'])
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='右偏解套(趋势向上)',
                    description='skewness>0.3(套牢盘重) + 价格>MA20 → 套牢盘解套，看涨',
                    condition='skewness>0.3 & close>ma20',
                    **stats
                ))

            # 偏度左偏 + 趋势向下 → 获利盘出逃
            mask = (df['skewness'] < -0.3) & (df['close'] < df['ma20'])
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='左偏派发(趋势向下)',
                    description='skewness<-0.3(获利盘重) + 价格<MA20 → 获利盘出逃，看跌',
                    condition='skewness<-0.3 & close<ma20',
                    **stats
                ))

        # 2. 峰度高值 → 筹码高度集中
        if 'kurtosis' in df.columns:
            mask = df['kurtosis'] > df['kurtosis'].quantile(0.7)
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='尖峰集中(kurtosis高)',
                    description='kurtosis>70%分位，筹码分布呈尖峰态，高度集中→看涨',
                    condition='kurtosis>70%分位',
                    **stats
                ))

        # 3. 熵低值 → 分布有序集中
        if 'entropy' in df.columns:
            mask = df['entropy'] < df['entropy'].quantile(0.3)
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='低熵集中(entropy低)',
                    description='entropy<30%分位，筹码分布有序集中→看涨',
                    condition='entropy<30%分位',
                    **stats
                ))

            # 熵下降 → 集中过程
            mask = df['entropy_falling'] & (df['entropy'] < df['entropy'].quantile(0.5))
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='熵下降(集中过程)',
                    description='entropy下降且低于中位数，筹码正在向集中演化→看涨',
                    condition='entropy_falling & entropy<50%分位',
                    **stats
                ))

        # 4. width_70收窄 → 核心筹码集中
        if 'width_70' in df.columns:
            mask = df['width_70_falling'] & (df['width_70'] < df['width_70'].quantile(0.4))
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='Width70收窄(核心集中)',
                    description='width_70收窄且低于40%分位，70%核心筹码快速集中→看涨',
                    condition='width_70_falling & width_70<40%分位',
                    **stats
                ))

        # 5. P1支配度高 → 主峰突出
        if 'p1_dominance' in df.columns and 'p1_pct' in df.columns:
            mask = (df['p1_dominance'] > 0.6) & (df['p1_pct'] > 12)
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='主峰突出(P1支配)',
                    description='p1_dominance>0.6且p1_pct>12%，主峰明显突出，主力控盘→看涨',
                    condition='p1_dominance>0.6 & p1_pct>12%',
                    **stats
                ))

        # 6. top5高度集中
        if 'top5' in df.columns:
            mask = df['top5'] > 60
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='Top5高度集中',
                    description='top5>60%，前5价位筹码占比极高，极度集中→看涨',
                    condition='top5>60%',
                    **stats
                ))

            mask = df['top5_rising'] & (df['top5'] > df['top5'].quantile(0.6))
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='Top5上升(集中加速)',
                    description='top5上升且>60%分位，集中度加速提升→看涨',
                    condition='top5_rising & top5>60%分位',
                    **stats
                ))

        # 7. 加权成本偏离超跌
        if 'cost_dist_pct' in df.columns:
            mask = df['cost_dist_pct'] < -5
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='加权成本偏离(超跌)',
                    description='价格低于加权成本5%以上，超跌状态→可能反弹',
                    condition='cost_dist_pct<-5%',
                    **stats
                ))

        # 8. 梯度断层 → 有筹码真空区
        if 'gradient' in df.columns:
            mask = df['gradient'] > 0.5
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='筹码断层(gradient高)',
                    description='gradient>0.5，筹码分布有明显断层(真空区)，价格可能快速穿越',
                    condition='gradient>0.5',
                    **stats
                ))

        # 9. 支撑近 + 趋势向上 → 有支撑
        if 'support_distance_pct' in df.columns:
            mask = (df['support_distance_pct'] < 3) & (df['close'] > df['ma20'])
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                results.append(SignalResult(
                    signal_name='支撑临近(趋势向上)',
                    description='支撑位距离<3%且趋势向上，强支撑附近→看涨',
                    condition='support_distance_pct<3% & close>ma20',
                    **stats
                ))

        return results

    def validate_health_score(self) -> List[SignalResult]:
        """验证健康度评分体系的有效性。"""
        results = []
        df = self.df.dropna(subset=['score'])

        # 不同分数段的验证
        for threshold, label in [(0, '健康度≥0'), (4, '健康度≥4'), (7, '健康度≥7'), (10, '健康度≥10')]:
            mask = df['score'] >= threshold
            if len(df[mask]) >= self.min_signals:
                stats = self._calc_stats(df[mask]['future_return'])
                desc = {
                    0: '健康度≥0表示中性或向好',
                    4: '健康度≥4表示弱向好',
                    7: '健康度≥7表示中向好',
                    10: '健康度≥10表示强向好',
                }[threshold]
                results.append(SignalResult(
                    signal_name=label,
                    description=desc,
                    condition=f'score >= {threshold}',
                    **stats
                ))

        # 负分验证 (向坏)
        mask = df['score'] < 0
        if len(df[mask]) >= self.min_signals:
            stats = self._calc_stats(df[mask]['future_return'])
            results.append(SignalResult(
                signal_name='健康度<0(向坏)',
                description='健康度负分，表示筹码结构恶化，看跌',
                condition='score < 0',
                **stats
            ))

        return results

    def generate_report(self) -> Dict:
        """生成完整验证报告。"""
        if self.df is None:
            self.fetch_and_compute()

        print("[QualitativeValidator] 📊 生成完整报告...")

        # 基准统计
        all_returns = self.df['future_return']
        baseline = self._calc_stats(all_returns)

        # 趋势分布统计
        trend_stats = {
            'up_days': int(self.df['trend_up'].sum()),
            'down_days': int(self.df['trend_down'].sum()),
            'side_days': int(self.df['trend_side'].sum()),
        }

        # 各项验证
        trend_validation = self.validate_single_metric_in_trend()
        momentum_validation = self.validate_indicator_momentum()
        theory_signals = self.validate_theory_based_signals()
        advanced_validation = self.validate_advanced_indicators()
        health_validation = self.validate_health_score()

        # 汇总所有信号并排序
        all_signals = [*trend_validation, *momentum_validation, *theory_signals,
                       *advanced_validation, *health_validation]
        all_signals.sort(key=lambda x: (x.win_rate * 0.5 + x.avg_return * 0.5), reverse=True)

        return {
            'ts_code': self.ts_code,
            'period': f"{self.start_date}~{self.end_date}",
            'total_samples': len(self.df),
            'future_days': self.future_days,
            'baseline': baseline,
            'trend_distribution': trend_stats,
            'trend_validation': [asdict(s) for s in trend_validation],
            'momentum_validation': [asdict(s) for s in momentum_validation],
            'theory_based_signals': [asdict(s) for s in theory_signals],
            'advanced_indicators_validation': [asdict(s) for s in advanced_validation],
            'health_score_validation': [asdict(s) for s in health_validation],
            'all_signals_ranked': [asdict(s) for s in all_signals],
        }

    def export_report(self, filepath: str):
        """导出报告为JSON。"""
        report = self.generate_report()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[QualitativeValidator] 💾 报告已导出: {filepath}")


# ═══════════════════════════════════════════════════════
# 快捷函数
# ═══════════════════════════════════════════════════════

def validate_stock(ts_code: str, start_date: str, end_date: str,
                   future_days: int = 10) -> Dict:
    """一键验证。"""
    validator = QualitativeValidator(ts_code, start_date, end_date, future_days)
    validator.fetch_and_compute()
    return validator.generate_report()


# ═══════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 70)
    print("筹码峰指标回测验证 (定性理论驱动)")
    print("=" * 70)

    report = validate_stock('603002.SH', '20260301', '20260624', future_days=10)

    print(f"\n📊 样本数量: {report['total_samples']}")
    print(f"📈 基准胜率: {report['baseline']['win_rate']}%")
    print(f"📉 基准收益: {report['baseline']['avg_return']}%")
    print(f"\n📊 趋势分布: 上涨{report['trend_distribution']['up_days']}天 / "
          f"下跌{report['trend_distribution']['down_days']}天 / "
          f"震荡{report['trend_distribution']['side_days']}天")

    print("\n" + "=" * 70)
    print("按胜率+收益综合排序的信号 TOP10")
    print("=" * 70)
    for i, signal in enumerate(report['all_signals_ranked'][:10], 1):
        print(f"\n{i}. {signal['signal_name']}")
        print(f"   描述: {signal['description']}")
        print(f"   条件: {signal['condition']}")
        print(f"   信号次数: {signal['signal_count']}")
        print(f"   胜率: {signal['win_rate']}%")
        print(f"   平均收益: {signal['avg_return']}%")
        print(f"   盈亏比: {signal['profit_loss_ratio']}")

    export_path = '/home/xiangan/Documents/trae_projects/chip_metric_validation.json'
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已导出: {export_path}")
