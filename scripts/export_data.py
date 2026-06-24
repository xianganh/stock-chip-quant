#!/usr/bin/env python3
"""
数据导出脚本 — 把数据库导出为 JSON 方便跨电脑同步

用法:  python scripts/export_data.py [output_file.json]
默认输出: data_dump_<timestamp>.json
"""
import argparse
import json
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from app import app
from database.models import (
    Watchlist, AnalysisSnapshot, BacktestRun, BacktestTrade, EvolutionRun,
    Position, TradeLog,
)


def export_all(output_path: str):
    """导出所有表到 JSON"""
    with app.app_context():
        data = {
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "version": "1.0",
                "tables": [],
            },
            "tables": {}
        }

        # 1. watchlist
        watchlist = [w.to_dict() for w in Watchlist.query.order_by(Watchlist.ts_code).all()]
        data["tables"]["watchlist"] = watchlist
        data["metadata"]["tables"].append({"name": "watchlist", "count": len(watchlist)})

        # 2. positions
        positions = [p.to_dict() for p in Position.query.order_by(
            Position.account, Position.ts_code, Position.entry_date
        ).all()]
        data["tables"]["positions"] = positions
        data["metadata"]["tables"].append({"name": "positions", "count": len(positions)})

        # 3. trade_logs
        trade_logs = [t.to_dict() for t in TradeLog.query.order_by(
            TradeLog.account_holder, TradeLog.trade_date, TradeLog.trade_time
        ).all()]
        data["tables"]["trade_logs"] = trade_logs
        data["metadata"]["tables"].append({"name": "trade_logs", "count": len(trade_logs)})

        # 4. analysis_snapshots
        snapshots = [s.to_dict() for s in AnalysisSnapshot.query.order_by(
            AnalysisSnapshot.ts_code, AnalysisSnapshot.trade_date
        ).all()]
        data["tables"]["analysis_snapshots"] = snapshots
        data["metadata"]["tables"].append({"name": "analysis_snapshots", "count": len(snapshots)})

        # 5. backtest_runs + backtest_trades
        bt_runs = [r.to_dict() for r in BacktestRun.query.order_by(
            BacktestRun.created_at.desc()
        ).all()]
        data["tables"]["backtest_runs"] = bt_runs
        data["metadata"]["tables"].append({"name": "backtest_runs", "count": len(bt_runs)})

        # 6. evolution_runs
        evo_runs = [r.to_dict() for r in EvolutionRun.query.order_by(
            EvolutionRun.created_at.desc()
        ).all()]
        data["tables"]["evolution_runs"] = evo_runs
        data["metadata"]["tables"].append({"name": "evolution_runs", "count": len(evo_runs)})

        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        # 统计
        total = sum(t["count"] for t in data["metadata"]["tables"])
        print(f"\n=== 导出完成 ===")
        print(f"输出文件: {output_path}")
        print(f"文件大小: {os.path.getsize(output_path) / 1024:.1f} KB")
        print(f"总记录数: {total}")
        print(f"\n各表记录:")
        for t in data["metadata"]["tables"]:
            print(f"  {t['name']:25} {t['count']:>6} 条")
        print(f"\n可通过微信/邮件/git 同步此文件, 然后在另一台电脑运行:")
        print(f"  python scripts/import_data.py {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        help="输出文件路径 (默认: data_dump_<timestamp>.json)",
    )
    args = parser.parse_args()

    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data_dump_{timestamp}.json"

    export_all(output_path)