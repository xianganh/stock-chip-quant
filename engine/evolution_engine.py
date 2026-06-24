"""
进化引擎 — 参数网格搜索 + 最优参数发现
通过遍历参数组合，找到使回测表现最优的参数配置
"""
import json
import os
import sys
import itertools
import numpy as np
from datetime import datetime

# 确保项目根目录在 sys.path 中
_sys_path_fix = os.path.join(os.path.dirname(__file__), "..")
if _sys_path_fix not in sys.path:
    sys.path.insert(0, _sys_path_fix)

from .backtest_engine import BacktestEngine
from utils import get_tushare_pro
from config import EVOLUTION_DEFAULT_GRIDS


class EvolutionEngine:
    """
    参数进化引擎

    用法:
        evo = EvolutionEngine(ts_code="000066.SZ")
        best = evo.evolve(signal_type="locking", param_grid={
            "min_conditions": [4, 5, 6],
        }, metric="sharpe")
    """

    @staticmethod
    def default_grid(signal_type: str) -> dict:
        """获取默认参数网格 (来自 config.py)"""
        return EVOLUTION_DEFAULT_GRIDS.get(signal_type, {})

    def __init__(self, ts_code: str, start_date: str = None, end_date: str = None):
        self.ts_code = ts_code
        self.start_date = start_date or "20200101"
        self.end_date = end_date or datetime.now().strftime("%Y%m%d")

    def evolve(self, signal_type: str = "locking",
               param_grid: dict = None,
               metric: str = "sharpe",
               holding_params: dict = None) -> dict:
        """
        遍历参数网格，回测每种组合，找到最优参数

        Args:
            signal_type: 信号类型
            param_grid: 参数网格，为 None 时使用默认网格
            metric: 优化目标 — "sharpe" | "win_rate" | "total_return"
            holding_params: 持仓参数 {"max_holding_days": 20, "stop_loss_pct": -8, "take_profit_pct": 20}

        Returns:
            dict with best_params, best_metric_value, results, total_tested
        """
        if param_grid is None:
            param_grid = self.default_grid(signal_type)

        if not param_grid:
            return {"error": "无参数网格可搜索"}

        # 生成所有参数组合
        keys   = list(param_grid.keys())
        values = [param_grid[k] for k in keys]
        combinations = list(itertools.product(*values))

        hp = holding_params or {}
        max_holding  = hp.get("max_holding_days", 20)
        stop_loss    = hp.get("stop_loss_pct", -8)
        take_profit  = hp.get("take_profit_pct", 20)

        results = []
        best_metric_val = -float("inf") if metric != "max_drawdown" else float("inf")
        best_params = None
        best_trades = []

        engine = BacktestEngine(self.ts_code, self.start_date, self.end_date)
        engine.load_price_data()

        # ★ 大盘基线只算一次: 直接用已加载的 price_data, 避免重复 Tushare 调用
        df = engine.price_data
        if df is not None and len(df) >= 2:
            first_close = float(df.iloc[0]["close"])
            last_close  = float(df.iloc[-1]["close"])
            buy_hold_ret = round((last_close - first_close) / first_close * 100, 2)
        else:
            buy_hold_ret = 0

        for combo in combinations:
            params = dict(zip(keys, combo))

            bt_result = engine.run(
                signal_type=signal_type,
                params=params,
                max_holding_days=max_holding,
                stop_loss_pct=stop_loss,
                take_profit_pct=take_profit,
            )

            if bt_result.get("total_trades", 0) == 0:
                metric_val = -float("inf")
            else:
                metric_val = bt_result.get(metric, 0)

            # 大盘基线：策略必须跑赢 buy & hold
            excess = (
                bt_result.get("total_return", 0) - buy_hold_ret
                if bt_result.get("total_trades", 0) > 0
                else -float("inf")
            )

            results.append({
                "params": params,
                "metric_value": metric_val,
                "total_trades": bt_result.get("total_trades", 0),
                "win_rate": bt_result.get("win_rate", 0),
                "total_return": bt_result.get("total_return", 0),
                "sharpe": bt_result.get("sharpe", 0),
                "excess_return": round(excess, 2),
            })

            # 更新最优
            is_better = (metric_val > best_metric_val) if metric != "max_drawdown" else (metric_val < best_metric_val)
            if is_better and bt_result.get("total_trades", 0) >= 3:
                best_metric_val = metric_val
                best_params = params
                best_trades = bt_result.get("trades", [])

        # 排序
        reverse = metric != "max_drawdown"
        results.sort(key=lambda x: x["metric_value"], reverse=reverse)

        return {
            "signal_type": signal_type,
            "metric": metric,
            "best_params": best_params,
            "best_metric_value": round(best_metric_val, 4),
            "best_trades": best_trades[:10],                    # 最优参数的前10笔交易
            "total_tested": len(combinations),
            "top_results": results[:10],                        # 前10名
        }

    def _compute_buy_hold_return(self) -> float:
        """计算买入持有策略的收益 (回测期内)"""
        try:
            pro = get_tushare_pro()
            df = pro.daily(ts_code=self.ts_code, start_date=self.start_date,
                           end_date=self.end_date, fields="close")
            if df is None or len(df) < 2:
                return 0
            # Tushare 返回的 df 按 trade_date 倒序：iloc[-1] 是最早日期, iloc[0] 是最晚
            start_price = float(df.iloc[-1]["close"])
            end_price   = float(df.iloc[0]["close"])
            return round((end_price - start_price) / start_price * 100, 2)
        except Exception:
            return 0
