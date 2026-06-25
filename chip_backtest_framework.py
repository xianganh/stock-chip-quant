#!/usr/bin/env python3
"""
定性理论驱动的筹码峰指标回测框架 (v2.0)
============================================

核心设计理念:
  1. 定性优先: 每一个信号都基于经典量化理论或筹码分布原理
  2. 分类体系: 指标按"集中度""分布形状""价格位置""动态变化"四大类组织
  3. 信号规则: 从定性理论推导出精确的量化条件
  4. 多维验证: 胜率、收益、稳定性、跨股一致性多维度评估
  5. 组合筛选: 基于定性逻辑的组合，而非暴力搜索

架构:
  MetricCategory (指标分类) → SignalRule (信号规则) → SignalEngine (信号生成) 
  → ValidationEngine (验证引擎) → Portfolio (组合筛选) → Report (报告)
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum

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


# ═══════════════════════════════════════════════════════
# 1. 指标分类体系 (定性驱动)
# ═══════════════════════════════════════════════════════

class MetricCategory(Enum):
    """指标分类：基于定性属性"""
    CONCENTRATION = "集中度"       # 筹码聚集程度
    DISTRIBUTION = "分布形状"      # 分布形态特征
    PRICE_POSITION = "价格位置"    # 价格相对筹码的位置
    DYNAMIC_CHANGE = "动态变化"    # 指标变化趋势


@dataclass
class MetricDefinition:
    """指标定义：定性描述 + 定量计算"""
    name: str                    # 指标名称 (列名)
    category: MetricCategory     # 所属分类
    description: str             # 定性含义
    unit: str = "%"              # 单位
    is_positive: bool = True     # 越高越好?
    is_dynamic: bool = False     # 是否需要看变化率?


# 核心指标定义库 (定性理论驱动)
METRIC_LIBRARY = [
    # ── 集中度类 ──
    MetricDefinition("tpc", MetricCategory.CONCENTRATION,
                     "三峰集中度: 前3峰筹码占比之和", "%", True),
    MetricDefinition("top5", MetricCategory.CONCENTRATION,
                     "前5价位集中度", "%", True),
    MetricDefinition("top10", MetricCategory.CONCENTRATION,
                     "前10价位集中度", "%", True),
    MetricDefinition("p1_pct", MetricCategory.CONCENTRATION,
                     "主峰占比", "%", True),
    MetricDefinition("p1_dominance", MetricCategory.CONCENTRATION,
                     "主峰支配度: P1占三峰的比例", "", True),
    MetricDefinition("width", MetricCategory.CONCENTRATION,
                     "三峰宽度", "%", False),
    MetricDefinition("width_70", MetricCategory.CONCENTRATION,
                     "70%筹码集中宽度", "%", False),
    MetricDefinition("width_90", MetricCategory.CONCENTRATION,
                     "90%筹码集中宽度", "%", False),
    MetricDefinition("tp3", MetricCategory.CONCENTRATION,
                     "±3%成本集中度", "%", True),

    # ── 分布形状类 ──
    MetricDefinition("skewness", MetricCategory.DISTRIBUTION,
                     "偏度: >0右偏(套牢盘重), <0左偏(获利盘重)", "", False),
    MetricDefinition("kurtosis", MetricCategory.DISTRIBUTION,
                     "峰度: >2尖峰(集中), <0扁平(分散)", "", True),
    MetricDefinition("entropy", MetricCategory.DISTRIBUTION,
                     "熵: 越小越有序集中", "", False),
    MetricDefinition("gradient", MetricCategory.DISTRIBUTION,
                     "梯度: >0.5有断层", "", False),
    MetricDefinition("peak_entropy", MetricCategory.DISTRIBUTION,
                     "峰熵: 三峰均匀程度", "", False),

    # ── 价格位置类 ──
    MetricDefinition("dist", MetricCategory.PRICE_POSITION,
                     "价格偏离P1", "%", False),
    MetricDefinition("winner", MetricCategory.PRICE_POSITION,
                     "获利盘比例", "%", False),
    MetricDefinition("weight_avg", MetricCategory.PRICE_POSITION,
                     "加权平均成本", "元", False),
    MetricDefinition("cost_dist_pct", MetricCategory.PRICE_POSITION,
                     "价格偏离加权成本", "%", False),
    MetricDefinition("resistance_distance_pct", MetricCategory.PRICE_POSITION,
                     "阻力位距离", "%", False),
    MetricDefinition("support_distance_pct", MetricCategory.PRICE_POSITION,
                     "支撑位距离", "%", False),

    # ── 动态变化类 (衍生指标) ──
    MetricDefinition("tpc_chg_7d", MetricCategory.DYNAMIC_CHANGE,
                     "TPC7日变化率", "%", True),
    MetricDefinition("width_chg_7d", MetricCategory.DYNAMIC_CHANGE,
                     "Width7日变化率", "%", False),
    MetricDefinition("tp3_chg_7d", MetricCategory.DYNAMIC_CHANGE,
                     "TP37日变化率", "%", True),
    MetricDefinition("winner_chg_7d", MetricCategory.DYNAMIC_CHANGE,
                     "获利盘7日变化率", "%", False),
    MetricDefinition("entropy_chg_7d", MetricCategory.DYNAMIC_CHANGE,
                     "熵7日变化率", "%", False),
]


# ═══════════════════════════════════════════════════════
# 2. 信号规则定义 (定性→定量)
# ═══════════════════════════════════════════════════════

class SignalDirection(Enum):
    BULLISH = "看涨"
    BEARISH = "看跌"
    NEUTRAL = "中性"


@dataclass
class SignalRule:
    """
    信号规则：从定性理论推导出的精确量化条件

    核心设计:
      - theory: 定性理论支撑
      - condition_func: 定量条件 (返回布尔Series)
      - trend_filter: 是否需要趋势过滤
      - min_signals: 最小信号次数阈值
    """
    id: str
    name: str
    theory: str                    # 定性理论描述
    category: MetricCategory       # 主要关联分类
    direction: SignalDirection     # 信号方向
    condition_func: Callable       # 定量条件函数
    trend_filter: Optional[str] = None  # "up"/"down"/None
    min_signals: int = 5           # 最小有效信号次数


@dataclass
class SignalResult:
    """信号验证结果"""
    signal_id: str
    signal_name: str
    theory: str
    direction: str
    category: str
    signal_count: int
    win_rate: float
    avg_return: float
    profit_loss_ratio: float
    sharpe_like: float
    max_drawdown: float
    avg_hold_days: float = 0.0


# ═══════════════════════════════════════════════════════
# 3. 信号规则库 (定性理论 → 定量条件)
# ═══════════════════════════════════════════════════════

def create_signal_rules(df: pd.DataFrame) -> List[SignalRule]:
    """
    基于定性理论创建信号规则库。

    定性理论体系:
    1. 集中度理论: 筹码越集中，控盘越强，上涨概率越高
    2. 分布形状理论: 
       - 尖峰(kurtosis高): 高度集中 → 看涨
       - 右偏(skewness>0): 套牢盘重 → 需趋势配合
       - 左偏(skewness<0): 获利盘重 → 需趋势配合
       - 低熵(entropy低): 有序集中 → 看涨
    3. 价格位置理论:
       - 价格低于P1/成本价: 超跌 → 可能反弹
       - 价格高于阻力位: 突破 → 看涨
    4. 动态变化理论:
       - 集中度上升: 正在集中 → 看涨
       - 宽度收窄: 正在集中 → 看涨
       - 熵下降: 有序化过程 → 看涨
    """
    rules = []

    # ── 集中度类信号 ──
    rules.extend([
        SignalRule(
            id="tpc_rising",
            name="TPC上升",
            theory="TPC上升意味着筹码向少数峰聚集，主力控盘加强",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['tpc_rising'] & (df['tpc'] > df['tpc'].quantile(0.5)),
        ),
        SignalRule(
            id="width_falling",
            name="Width收窄",
            theory="Width收窄意味着筹码分布变窄，蓄势待发",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['width_falling'] & (df['width'] < df['width'].quantile(0.5)),
        ),
        SignalRule(
            id="tp3_high_rising",
            name="TP3高值上升",
            theory="TP3高值且上升意味着市场成本趋于一致，突破概率高",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['tp3_rising'] & (df['tp3'] > df['tp3'].quantile(0.6)),
        ),
        SignalRule(
            id="top5_rising",
            name="Top5上升",
            theory="Top5上升意味着前5价位集中度提升，控盘加强",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['top5_rising'] & (df['top5'] > df['top5'].quantile(0.5)),
        ),
        SignalRule(
            id="p1_dominant",
            name="主峰突出",
            theory="P1支配度>0.6且P1占比>12%，主峰明显突出，控盘有力",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: (df['p1_dominance'] > 0.6) & (df['p1_pct'] > 12),
        ),
        SignalRule(
            id="width70_falling",
            name="Width70收窄",
            theory="Width70收窄意味着70%核心筹码快速集中",
            category=MetricCategory.CONCENTRATION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['width_70_falling'] & (df['width_70'] < df['width_70'].quantile(0.4)),
        ),
    ])

    # ── 分布形状类信号 ──
    rules.extend([
        SignalRule(
            id="kurtosis_high",
            name="尖峰集中",
            theory="kurtosis>70%分位，筹码分布呈尖峰态，高度集中",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['kurtosis'] > df['kurtosis'].quantile(0.7),
        ),
        SignalRule(
            id="entropy_low",
            name="低熵集中",
            theory="entropy<30%分位，筹码分布有序集中",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['entropy'] < df['entropy'].quantile(0.3),
        ),
        SignalRule(
            id="entropy_falling",
            name="熵下降",
            theory="entropy下降，筹码正在向有序化集中演化",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['entropy_falling'] & (df['entropy'] < df['entropy'].quantile(0.5)),
        ),
        SignalRule(
            id="skew_right_bull",
            name="右偏解套",
            theory="skewness>0.3(套牢盘重) + 价格>MA20 → 套牢盘解套，看涨",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: (df['skewness'] > 0.3) & (df['close'] > df['ma20']),
        ),
        SignalRule(
            id="skew_left_bear",
            name="左偏派发",
            theory="skewness<-0.3(获利盘重) + 价格<MA20 → 获利盘出逃，看跌",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BEARISH,
            condition_func=lambda df: (df['skewness'] < -0.3) & (df['close'] < df['ma20']),
        ),
        SignalRule(
            id="gradient_high",
            name="筹码断层",
            theory="gradient>0.5，筹码分布有明显断层(真空区)，价格可能快速穿越",
            category=MetricCategory.DISTRIBUTION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['gradient'] > 0.5,
        ),
    ])

    # ── 价格位置类信号 ──
    rules.extend([
        SignalRule(
            id="dist_overbought",
            name="超跌反弹",
            theory="DIST<10%分位，价格大幅低于P1(主力成本)，超跌状态",
            category=MetricCategory.PRICE_POSITION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['dist'] < df['dist'].quantile(0.1),
        ),
        SignalRule(
            id="cost_dist_oversold",
            name="加权成本超跌",
            theory="价格低于加权成本5%以上，超跌状态",
            category=MetricCategory.PRICE_POSITION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['cost_dist_pct'] < -5,
        ),
        SignalRule(
            id="support_near_bull",
            name="支撑临近",
            theory="支撑位距离<3%且趋势向上，强支撑附近",
            category=MetricCategory.PRICE_POSITION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: (df['support_distance_pct'] < 3) & (df['close'] > df['ma20']),
        ),
        SignalRule(
            id="winner_trend_up",
            name="Winner高值(上涨趋势)",
            theory="上涨趋势中Winner高值，获利盘继续推升，趋势延续",
            category=MetricCategory.PRICE_POSITION,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['trend_up'] & (df['winner'] > df['winner'].quantile(0.7)),
        ),
        SignalRule(
            id="winner_trend_down",
            name="Winner高值(下跌趋势)",
            theory="下跌趋势中Winner高值，高位获利盘仍在，下跌可能继续",
            category=MetricCategory.PRICE_POSITION,
            direction=SignalDirection.BEARISH,
            condition_func=lambda df: df['trend_down'] & (df['winner'] > df['winner'].quantile(0.7)),
        ),
    ])

    # ── 动态变化类信号 ──
    rules.extend([
        SignalRule(
            id="tpc_accelerate",
            name="TPC加速上升",
            theory="TPC变化率>70%分位，筹码集中速度加快",
            category=MetricCategory.DYNAMIC_CHANGE,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['tpc_chg_7d'] > df['tpc_chg_7d'].quantile(0.7),
        ),
        SignalRule(
            id="width_accelerate",
            name="Width加速收窄",
            theory="Width负变化率<30%分位，筹码集中速度加快",
            category=MetricCategory.DYNAMIC_CHANGE,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['width_chg_7d'] < df['width_chg_7d'].quantile(0.3),
        ),
        SignalRule(
            id="tp3_accelerate",
            name="TP3加速上升",
            theory="TP3变化率>70%分位，±3%成本集中度快速提升",
            category=MetricCategory.DYNAMIC_CHANGE,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['tp3_chg_7d'] > df['tp3_chg_7d'].quantile(0.7),
        ),
        SignalRule(
            id="winner_accelerate_up",
            name="Winner加速上升",
            theory="获利盘快速增加，趋势确认或加速",
            category=MetricCategory.DYNAMIC_CHANGE,
            direction=SignalDirection.BULLISH,
            condition_func=lambda df: df['winner_chg_7d'] > df['winner_chg_7d'].quantile(0.7),
        ),
        SignalRule(
            id="winner_accelerate_down",
            name="Winner加速下降",
            theory="获利盘快速减少，派发或恐慌出逃",
            category=MetricCategory.DYNAMIC_CHANGE,
            direction=SignalDirection.BEARISH,
            condition_func=lambda df: df['winner_chg_7d'] < df['winner_chg_7d'].quantile(0.3),
        ),
    ])

    return rules


# ═══════════════════════════════════════════════════════
# 4. 信号组合规则 (定性逻辑驱动)
# ═══════════════════════════════════════════════════════

@dataclass
class CombinationRule:
    """组合信号规则：基于定性逻辑的多指标组合"""
    id: str
    name: str
    theory: str
    component_signals: List[str]   # 组件信号ID列表
    logic: str = "AND"             # AND/OR
    min_signals: int = 5


COMBINATION_RULES = [
    CombinationRule(
        id="con_control",
        name="控盘加强",
        theory="TPC上升(筹码集中) + Width收窄(分布变窄) → 主力控盘加强",
        component_signals=["tpc_rising", "width_falling"],
        logic="AND",
    ),
    CombinationRule(
        id="breakout_confirm",
        name="突破确认",
        theory="TP3高值上升(成本一致) + 价格>MA20(趋势向上) → 突破概率高",
        component_signals=["tp3_high_rising"],
        logic="AND",
    ),
    CombinationRule(
        id="oversold_bounce",
        name="超跌反弹",
        theory="DIST负偏离(超跌) + Width收窄(筹码集中) → 可能反弹",
        component_signals=["dist_overbought", "width_falling"],
        logic="AND",
    ),
    CombinationRule(
        id="strong_control",
        name="强势控盘",
        theory="TPC上升 + TP3上升 + Width收窄 → 多维度确认主力控盘",
        component_signals=["tpc_rising", "tp3_high_rising", "width_falling"],
        logic="AND",
    ),
    CombinationRule(
        id="trend_continue",
        name="趋势延续",
        theory="Winner高值上升(获利盘增加) + 价格>MA20(趋势向上)",
        component_signals=["winner_accelerate_up"],
        logic="AND",
    ),
    CombinationRule(
        id="distribution_warning",
        name="派发预警",
        theory="Winner骤降(获利盘出逃) + 价格<MA20(趋势向下)",
        component_signals=["winner_accelerate_down"],
        logic="AND",
    ),
]


# ═══════════════════════════════════════════════════════
# 5. 验证引擎核心
# ═══════════════════════════════════════════════════════

class BacktestFramework:
    """定性理论驱动的回测验证框架"""

    def __init__(self, ts_code: str, start_date: str, end_date: str,
                 future_days: int = 10, min_signals: int = 5):
        self.ts_code = ts_code
        self.start_date = start_date
        self.end_date = end_date
        self.future_days = future_days
        self.min_signals = min_signals
        self.df = None
        self.signal_rules = []
        self.signal_results = {}

    def prepare_data(self):
        """获取数据并计算所有指标"""
        print(f"[BacktestFramework] 📊 获取 {self.ts_code} 数据...")
        data = fetch_complete_data(self.ts_code, self.start_date, self.end_date)
        results = compute_all_chip_metrics(data['chip_data'], data['kline'], lookback_days=7)
        self.df = pd.DataFrame(results)
        self.df = self.df[self.df['future_return'].notna()]
        self._compute_trend_and_derived()
        print(f"[BacktestFramework] ✅ 数据准备完成: {len(self.df)}个有效样本")
        return self

    def _compute_trend_and_derived(self):
        """计算趋势指标和衍生指标"""
        # MA
        for period in [5, 20, 60]:
            self.df[f'ma{period}'] = self.df['close'].rolling(period).mean()

        # 趋势方向
        self.df['trend_up'] = (self.df['ma5'] > self.df['ma20']) & (self.df['ma20'] > self.df['ma60'])
        self.df['trend_down'] = (self.df['ma5'] < self.df['ma20']) & (self.df['ma20'] < self.df['ma60'])
        self.df['trend_side'] = ~self.df['trend_up'] & ~self.df['trend_down']

        # 所有指标的7日变化率和方向
        all_metrics = [m.name for m in METRIC_LIBRARY if m.name in self.df.columns]
        for metric in all_metrics:
            self.df[f'{metric}_chg_7d'] = self.df[metric].diff(7)
            self.df[f'{metric}_rising'] = self.df[f'{metric}_chg_7d'] > 0
            self.df[f'{metric}_falling'] = self.df[f'{metric}_chg_7d'] < 0

        # 加权成本偏离
        if 'weight_avg' in self.df.columns:
            self.df['cost_dist_pct'] = (self.df['close'] - self.df['weight_avg']) / self.df['weight_avg'] * 100

    def _calc_stats(self, returns: pd.Series) -> Dict:
        """计算统计指标"""
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

    def validate_single_signals(self):
        """验证单指标信号"""
        print(f"[BacktestFramework] 🔍 验证单指标信号...")
        self.signal_rules = create_signal_rules(self.df)
        for rule in self.signal_rules:
            try:
                mask = rule.condition_func(self.df)
                if mask.sum() >= rule.min_signals:
                    stats = self._calc_stats(self.df[mask]['future_return'])
                    self.signal_results[rule.id] = SignalResult(
                        signal_id=rule.id,
                        signal_name=rule.name,
                        theory=rule.theory,
                        direction=rule.direction.value,
                        category=rule.category.value,
                        **stats
                    )
            except Exception as e:
                print(f"  [WARN] 信号 {rule.id} 验证失败: {e}")
        print(f"  ✅ 有效信号: {len(self.signal_results)}/{len(self.signal_rules)}")

    def validate_combinations(self):
        """验证组合信号"""
        print(f"[BacktestFramework] 🔍 验证组合信号...")
        for comb in COMBINATION_RULES:
            # 构建组合条件
            masks = []
            for sig_id in comb.component_signals:
                if sig_id in self.signal_results:
                    rule = next((r for r in self.signal_rules if r.id == sig_id), None)
                    if rule:
                        masks.append(rule.condition_func(self.df))
            if not masks:
                continue

            if comb.logic == "AND":
                mask = masks[0]
                for m in masks[1:]:
                    mask = mask & m
            else:
                mask = masks[0]
                for m in masks[1:]:
                    mask = mask | m

            if mask.sum() >= comb.min_signals:
                stats = self._calc_stats(self.df[mask]['future_return'])
                self.signal_results[comb.id] = SignalResult(
                    signal_id=comb.id,
                    signal_name=comb.name,
                    theory=comb.theory,
                    direction=SignalDirection.BULLISH.value,
                    category="组合信号",
                    **stats
                )
        print(f"  ✅ 有效组合信号: {sum(1 for s in self.signal_results.values() if s.category == '组合信号')}")

    def generate_report(self) -> Dict:
        """生成完整报告"""
        if self.df is None:
            self.prepare_data()
        self.validate_single_signals()
        self.validate_combinations()

        # 基准统计
        all_returns = self.df['future_return']
        baseline = self._calc_stats(all_returns)

        # 趋势分布
        trend_stats = {
            'up_days': int(self.df['trend_up'].sum()),
            'down_days': int(self.df['trend_down'].sum()),
            'side_days': int(self.df['trend_side'].sum()),
        }

        # 按分类组织信号
        signals_by_category = {}
        for sig in self.signal_results.values():
            signals_by_category.setdefault(sig.category, []).append(asdict(sig))

        # 排序所有信号
        all_signals = sorted(self.signal_results.values(),
                           key=lambda x: (x.win_rate * 0.5 + x.avg_return * 0.5),
                           reverse=True)

        return {
            'ts_code': self.ts_code,
            'period': f"{self.start_date}~{self.end_date}",
            'total_samples': len(self.df),
            'future_days': self.future_days,
            'baseline': baseline,
            'trend_distribution': trend_stats,
            'signals_by_category': signals_by_category,
            'all_signals_ranked': [asdict(s) for s in all_signals],
        }


# ═══════════════════════════════════════════════════════
# 6. 跨股验证与信号稳定性分析
# ═══════════════════════════════════════════════════════

class MultiStockValidator:
    """多股票验证器：评估信号跨股稳定性"""

    def __init__(self, stocks: List[Tuple[str, str]], start_date: str, end_date: str):
        self.stocks = stocks
        self.start_date = start_date
        self.end_date = end_date
        self.reports = {}

    def validate_all(self):
        """验证所有股票"""
        for code, name in self.stocks:
            print(f"\n{'='*70}")
            print(f"验证 {name} ({code})")
            print('='*70)
            framework = BacktestFramework(code, self.start_date, self.end_date, future_days=10)
            report = framework.generate_report()
            self.reports[code] = {
                'name': name,
                'report': report,
            }

    def analyze_stability(self) -> Dict:
        """分析信号跨股稳定性"""
        signal_stats = {}

        # 收集所有信号的表现
        for code, data in self.reports.items():
            for signal in data['report']['all_signals_ranked']:
                sig_id = signal['signal_id']
                if sig_id not in signal_stats:
                    signal_stats[sig_id] = {
                        'name': signal['signal_name'],
                        'theory': signal['theory'],
                        'category': signal['category'],
                        'direction': signal['direction'],
                        'stock_results': [],
                    }
                signal_stats[sig_id]['stock_results'].append({
                    'stock': data['name'],
                    'win_rate': signal['win_rate'],
                    'avg_return': signal['avg_return'],
                    'signal_count': signal['signal_count'],
                })

        # 计算稳定性指标
        stable_signals = []
        for sig_id, stats in signal_stats.items():
            results = stats['stock_results']
            if len(results) < 2:
                continue

            win_rates = [r['win_rate'] for r in results if r['win_rate'] > 0]
            returns = [r['avg_return'] for r in results if r['signal_count'] >= 5]

            if len(win_rates) < 2 or len(returns) < 2:
                continue

            avg_win_rate = np.mean(win_rates)
            std_win_rate = np.std(win_rates)
            avg_return = np.mean(returns)
            std_return = np.std(returns)

            # 稳定性评分: 胜率高且标准差小
            stability_score = avg_win_rate - std_win_rate * 2
            consistency_score = 1 - (std_return / (abs(avg_return) + 0.1))

            stable_signals.append({
                'signal_id': sig_id,
                'signal_name': stats['name'],
                'theory': stats['theory'],
                'category': stats['category'],
                'direction': stats['direction'],
                'coverage': len(results),
                'avg_win_rate': round(avg_win_rate, 1),
                'std_win_rate': round(std_win_rate, 1),
                'avg_return': round(avg_return, 2),
                'std_return': round(std_return, 2),
                'stability_score': round(stability_score, 1),
                'consistency_score': round(consistency_score, 2),
                'stock_results': results,
            })

        # 排序
        stable_signals.sort(key=lambda x: x['stability_score'], reverse=True)

        return {
            'total_signals': len(stable_signals),
            'top_stable_signals': stable_signals[:15],
            'all_signals': stable_signals,
        }


# ═══════════════════════════════════════════════════════
# 7. 主函数
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("定性理论驱动的筹码峰指标回测框架 (v2.0)")
    print("=" * 70)

    # 待验证股票
    stocks = [
        ('603002.SH', '宏昌电子'),
        ('605589.SH', '圣泉集团'),
        ('000066.SZ', '中国长城'),
        ('600176.SH', '中国巨石'),
        ('601208.SH', '东材科技'),
    ]

    # 多股票验证
    validator = MultiStockValidator(stocks, '20260301', '20260624')
    validator.validate_all()

    # 稳定性分析
    stability_report = validator.analyze_stability()

    # 输出稳定性报告
    print(f"\n{'='*70}")
    print("跨股稳定性分析报告")
    print("="*70)
    print(f"\n共分析 {stability_report['total_signals']} 个信号")
    print(f"\n{'排名':<3} {'信号':<18} {'分类':<8} {'方向':<4} {'覆盖':<4} {'平均胜率':<8} {'稳定性':<6}")
    print("-"*70)
    for i, sig in enumerate(stability_report['top_stable_signals'][:15], 1):
        print(f"{i:<3} {sig['signal_name']:<18} {sig['category']:<8} {sig['direction']:<4} "
              f"{sig['coverage']:<4} {sig['avg_win_rate']:<8} {sig['stability_score']:<6}")

    # 输出详细报告
    print(f"\n{'='*70}")
    print("详细信号表现")
    print("="*70)
    for sig in stability_report['top_stable_signals'][:10]:
        print(f"\n📌 {sig['signal_name']} ({sig['category']})")
        print(f"   理论: {sig['theory']}")
        print(f"   方向: {sig['direction']}")
        print(f"   平均胜率: {sig['avg_win_rate']}% (标准差: {sig['std_win_rate']}%)")
        print(f"   平均收益: {sig['avg_return']}% (标准差: {sig['std_return']}%)")
        print(f"   覆盖股票: {sig['coverage']}只")
        print(f"   各股表现:")
        for r in sig['stock_results']:
            print(f"     • {r['stock']}: 胜率{r['win_rate']}% 收益{r['avg_return']}% 次数{r['signal_count']}")

    # 保存报告
    output = {
        'validator_reports': validator.reports,
        'stability_analysis': stability_report,
    }
    with open('/home/xiangan/Documents/trae_projects/backtest_framework_report.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已导出")


if __name__ == '__main__':
    main()