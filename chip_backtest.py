#!/usr/bin/env python3
"""
筹码峰回测验证模块 (通用化)
============================
对任意股票进行筹码峰健康度回测，验证指标有效性。

使用示例:
    from chip_backtest import ChipBacktest

    # 创建回测实例
    bt = ChipBacktest('603002.SH', start_date='20260301', end_date='20260624')

    # 加载交易记录（可选）
    bt.load_trades()

    # 运行回测
    bt.run()

    # 获取结果
    report = bt.generate_report()
    bt.export_json('result.json')

    # 或一键完成
    bt = ChipBacktest('603002.SH', '20260301', '20260624').run()
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
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

from chip_data_fetcher import fetch_complete_data, load_trade_records, get_trades_for_stock
from chip_indicators import compute_all_chip_metrics, get_score_label


class ChipBacktest:
    """
    筹码峰回测引擎。

    Attributes:
        ts_code: 股票代码
        start_date: 回测起始日期
        end_date: 回测结束日期
        results: 回测结果列表
        trades: 用户交易记录
    """

    def __init__(self, ts_code: str, start_date: str, end_date: str,
                 lookback_days: int = 7, future_days: int = 10):
        """
        初始化回测引擎。

        Args:
            ts_code: 股票代码，如 '603002.SH'
            start_date: 起始日期，格式 'YYYYMMDD'
            end_date: 结束日期，格式 'YYYYMMDD'
            lookback_days: 健康度对比的回看天数，默认7天
            future_days: 未来收益验证天数，默认10天
        """
        self.ts_code = ts_code
        self.start_date = start_date
        self.end_date = end_date
        self.lookback_days = lookback_days
        self.future_days = future_days

        self.data = None
        self.results = []
        self.trades = pd.DataFrame()

    def fetch_data(self) -> 'ChipBacktest':
        """获取筹码+K线数据。"""
        print(f"\n[ChipBacktest] 📊 获取 {self.ts_code} 数据...")
        self.data = fetch_complete_data(self.ts_code, self.start_date, self.end_date)
        return self

    def load_trades(self, trades_df: Optional[pd.DataFrame] = None) -> 'ChipBacktest':
        """
        加载交易记录。

        Args:
            trades_df: 交易记录DataFrame，如果为None则从默认文件读取
        """
        if trades_df is None:
            trades_df = load_trade_records()

        self.trades = get_trades_for_stock(trades_df, self.ts_code)
        print(f"[ChipBacktest] 📝 加载交易记录: {len(self.trades)}条")
        return self

    def run(self) -> 'ChipBacktest':
        """运行回测。"""
        if self.data is None:
            self.fetch_data()

        print(f"[ChipBacktest] 🔍 计算指标与健康度...")
        self.results = compute_all_chip_metrics(
            self.data['chip_data'],
            self.data['kline'],
            lookback_days=self.lookback_days
        )

        # 匹配交易记录
        if not self.trades.empty:
            self._match_trades()

        print(f"[ChipBacktest] ✅ 回测完成: {len(self.results)}个交易日")
        return self

    def _match_trades(self):
        """将交易记录匹配到回测结果中。"""
        trade_map = {}
        for _, trade in self.trades.iterrows():
            date_str = trade['date'].strftime('%Y-%m-%d')
            if date_str not in trade_map:
                trade_map[date_str] = []
            trade_map[date_str].append({
                'action': trade['action'],
                'price': trade['price'],
                'note': trade['note'],
            })

        for result in self.results:
            date = result['date']
            if date in trade_map:
                result['trades'] = trade_map[date]
            else:
                result['trades'] = []

    # ═══════════════════════════════════════════════════════
    # 报告生成
    # ═══════════════════════════════════════════════════════

    def generate_report(self) -> Dict:
        """
        生成回测报告。

        Returns:
            Dict: 包含统计信息和详细数据的报告
        """
        if not self.results:
            return {'error': '请先运行回测'}

        scores = [r['score'] for r in self.results if r['score'] is not None]
        future_returns = [r['future_return'] for r in self.results
                          if r['future_return'] is not None]

        # 向好信号统计 (score >= 7)
        good_signals = [r for r in self.results
                        if r['score'] is not None and r['score'] >= 7]
        good_accuracy = 0
        good_avg_return = 0
        if good_signals:
            good_returns = [r['future_return'] for r in good_signals
                            if r['future_return'] is not None]
            if good_returns:
                good_accuracy = len([r for r in good_returns if r > 0]) / len(good_returns) * 100
                good_avg_return = sum(good_returns) / len(good_returns)

        # 最佳买入点 (score >= 10)
        best_buys = [r for r in self.results
                     if r['score'] is not None and r['score'] >= 10]

        # 交易点评分析
        trade_analysis = []
        if not self.trades.empty:
            for _, trade in self.trades.iterrows():
                date_str = trade['date'].strftime('%Y-%m-%d')
                record = next((r for r in self.results if r['date'] == date_str), None)

                analysis = {
                    'date': date_str,
                    'action': trade['action'],
                    'price': trade['price'],
                    'note': trade['note'],
                }

                if record and record['score'] is not None:
                    analysis['score'] = record['score']
                    analysis['status'] = record['status']
                    analysis['future_return'] = record['future_return']
                    analysis['reasons'] = record['reasons']

                    if trade['action'] == 'buy':
                        if record['score'] >= 10:
                            analysis['evaluation'] = '⭐优秀'
                        elif record['score'] >= 7:
                            analysis['evaluation'] = '✅良好'
                        elif record['score'] >= 4:
                            analysis['evaluation'] = '⚠️一般'
                        else:
                            analysis['evaluation'] = '❌较差'
                    else:  # sell
                        if record['score'] <= 0:
                            analysis['evaluation'] = '✅合理'
                        elif record['score'] <= 4:
                            analysis['evaluation'] = '⚠️谨慎'
                        else:
                            analysis['evaluation'] = '❌过早'
                else:
                    analysis['evaluation'] = '⚠️数据不足'

                trade_analysis.append(analysis)

        return {
            'ts_code': self.ts_code,
            'period': f"{self.start_date}~{self.end_date}",
            'total_days': len(self.results),
            'statistics': {
                'score_range': {'min': min(scores), 'max': max(scores)},
                'avg_score': round(sum(scores) / len(scores), 1),
                'negative_count': len([s for s in scores if s < 0]),
                'good_signals': {
                    'count': len(good_signals),
                    'accuracy': round(good_accuracy, 1),
                    'avg_return': round(good_avg_return, 2),
                },
                'best_buy_points': len(best_buys),
                'avg_future_return': round(sum(future_returns) / len(future_returns), 2) if future_returns else 0,
            },
            'trade_analysis': trade_analysis,
            'best_buy_points': [
                {
                    'date': r['date'],
                    'score': r['score'],
                    'close': r['close'],
                    'future_return': r['future_return'],
                    'reasons': r['reasons'],
                }
                for r in best_buys
            ],
            'daily_results': self.results,
        }

    def export_json(self, filepath: str):
        """导出回测结果为JSON文件。"""
        report = self.generate_report()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[ChipBacktest] 💾 报告已导出: {filepath}")

    def print_summary(self):
        """打印回测摘要。"""
        report = self.generate_report()

        print("\n" + "=" * 60)
        print(f"📊 {self.ts_code} 筹码峰回测报告")
        print("=" * 60)
        print(f"回测区间: {report['period']}")
        print(f"总交易日: {report['total_days']}")

        stats = report['statistics']
        print(f"\n💪 健康度统计:")
        print(f"   得分范围: {stats['score_range']['min']} ~ {stats['score_range']['max']}")
        print(f"   平均分: {stats['avg_score']}")
        print(f"   负分次数: {stats['negative_count']}")

        print(f"\n📈 信号统计:")
        print(f"   向好信号(≥7分): {stats['good_signals']['count']}次")
        print(f"   准确率: {stats['good_signals']['accuracy']}%")
        print(f"   平均未来收益: {stats['good_signals']['avg_return']:+.2f}%")
        print(f"   最佳买入点(≥10分): {stats['best_buy_points']}次")

        if report['trade_analysis']:
            print(f"\n🎯 交易点评:")
            for t in report['trade_analysis']:
                print(f"   {t['date']} {t['action']} {t['price']}元 - {t['evaluation']}")
                if 'score' in t:
                    print(f"      健康度: {t['score']}分 ({t['status']}) 未来10日: {t['future_return']:+.2f}%")

        print("=" * 60)


# ═══════════════════════════════════════════════════════
# 一键回测函数
# ═══════════════════════════════════════════════════════

def quick_backtest(ts_code: str, start_date: str, end_date: str,
                   with_trades: bool = True) -> ChipBacktest:
    """
    一键回测函数。

    Args:
        ts_code: 股票代码
        start_date: 起始日期
        end_date: 结束日期
        with_trades: 是否加载交易记录

    Returns:
        ChipBacktest: 回测实例
    """
    bt = ChipBacktest(ts_code, start_date, end_date)
    if with_trades:
        bt.load_trades()
    bt.run()
    bt.print_summary()
    return bt


# ═══════════════════════════════════════════════════════
# 主函数（测试用）
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("测试筹码峰回测模块")
    print("=" * 60)

    # 宏昌电子回测
    bt = quick_backtest('603002.SH', '20260301', '20260624')

    # 导出结果
    bt.export_json('/home/xiangan/Documents/trae_projects/hongchang_backtest_result.json')

    # 尝试另一只股票
    print("\n" + "=" * 60)
    print("测试泛微网络")
    print("=" * 60)
    bt2 = quick_backtest('603039.SH', '20260401', '20260624')