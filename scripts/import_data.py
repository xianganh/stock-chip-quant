#!/usr/bin/env python3
"""
数据导入脚本 — 从 JSON 恢复数据库

用法:  python scripts/import_data.py <data_dump.json> [--merge|--replace]

模式:
  --merge   (默认) 增量导入, 不删除已有记录 (ts_code+date 唯一)
  --replace         清空所有表后导入 (慎用!)

注意:
  - 不导入 schema, 依赖目标机器上已有 app.py 可正常运行
  - 第一次导入前需要确保数据库已创建 (启动 app 一次即可)
"""
import argparse
import json
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from app import app, db
from database.models import (
    Watchlist, AnalysisSnapshot, BacktestRun, BacktestTrade, EvolutionRun,
    Position, TradeLog,
)


# 字段映射: 哪些字段从 to_dict() 取出后可直接设到 model
DIRECT_FIELDS = {
    "Watchlist": ["ts_code", "name", "added_date", "notes", "category", "active"],
    "Position": [
        "ts_code", "name", "account", "entry_date", "entry_price", "qty", "cost",
        "entry_reason", "expected_holding_days", "target_price", "stop_loss",
        "algorithm_signal", "algorithm_verdict",
        "status", "exit_date", "exit_price", "exit_reason",
        "realized_pnl", "realized_pnl_pct", "notes",
    ],
    "TradeLog": [
        "ts_code", "name", "trade_date", "trade_time", "direction",
        "price", "qty", "amount",
        "commission", "stamp_tax", "other_fee",
        "source", "broker", "account_holder",
        "reason", "emotion",
        "algorithm_signal", "algorithm_verdict", "notes",
    ],
    "AnalysisSnapshot": [
        "ts_code", "trade_date",
        "p1", "p1_pct", "tpc", "top5", "width_90", "winner", "dist",
        "skewness", "kurtosis", "entropy", "morphology", "n_peaks",
        "cmf", "adx", "atr_pct",
        "momentum_score", "trend_score", "reversal_score", "weighted_score",
        "divergence_score", "divergence_verdict",
        "interpretation", "interpretation_at", "full_data",
    ],
    "BacktestRun": [
        "ts_code", "name", "start_date", "end_date", "parameters",
        "total_trades", "win_rate", "avg_return", "max_return", "min_return",
        "sharpe", "max_drawdown", "total_return", "signal_type",
    ],
    "EvolutionRun": [
        "ts_code", "signal_type", "param_grid", "best_params",
        "best_sharpe", "best_win_rate", "total_tested", "results_json",
    ],
}


MODEL_MAP = {
    "watchlist": Watchlist,
    "positions": Position,
    "trade_logs": TradeLog,
    "analysis_snapshots": AnalysisSnapshot,
    "backtest_runs": BacktestRun,
    "evolution_runs": EvolutionRun,
}


def import_table(table_name: str, records: list, mode: str, stats: dict):
    """导入单个表"""
    model = MODEL_MAP.get(table_name)
    if not model:
        print(f"  [SKIP] 未知表 {table_name}")
        return

    fields = DIRECT_FIELDS.get(model.__name__, [])
    inserted, updated, skipped = 0, 0, 0

    for record in records:
        try:
            # 只取直接映射字段
            data = {k: v for k, v in record.items() if k in fields and k != 'id'}

            # 处理时间字段 (可能为字符串)
            for time_field in ('added_date', 'interpretation_at'):
                if time_field in data and isinstance(data[time_field], str):
                    try:
                        from datetime import datetime
                        data[time_field] = datetime.fromisoformat(data[time_field])
                    except Exception:
                        data[time_field] = None

            if mode == "replace":
                # 直接插入 (允许重复, 用 id=None)
                obj = model(**data)
                db.session.add(obj)
                inserted += 1
            else:  # merge 模式
                # 查找主键 (不同表主键不同)
                pk_field = None
                pk_value = None
                if table_name == "watchlist":
                    existing = model.query.filter_by(ts_code=data.get("ts_code")).first()
                    if existing:
                        for k, v in data.items():
                            setattr(existing, k, v)
                        updated += 1
                        continue
                    else:
                        obj = model(**data)
                        db.session.add(obj)
                        inserted += 1
                        continue
                elif table_name == "positions":
                    # positions 没有简单主键, 用 (account, ts_code, status) 组合
                    pk_filter = {
                        "account": data.get("account"),
                        "ts_code": data.get("ts_code"),
                        "status": data.get("status", "active"),
                    }
                    existing = model.query.filter_by(**pk_filter).first()
                    if existing:
                        for k, v in data.items():
                            setattr(existing, k, v)
                        updated += 1
                        continue
                    else:
                        obj = model(**data)
                        db.session.add(obj)
                        inserted += 1
                        continue
                elif table_name == "trade_logs":
                    # trade_logs 主键用 (ts_code, trade_date, trade_time, direction)
                    existing = model.query.filter_by(
                        ts_code=data.get("ts_code"),
                        trade_date=data.get("trade_date"),
                        trade_time=data.get("trade_time"),
                        direction=data.get("direction"),
                        account_holder=data.get("account_holder"),
                    ).first()
                    if existing:
                        # 更新少量字段 (避免覆盖本地新增的 reason/emotion)
                        for k in ("price", "qty", "amount", "commission"):
                            if k in data:
                                setattr(existing, k, data[k])
                        updated += 1
                        continue
                    else:
                        obj = model(**data)
                        db.session.add(obj)
                        inserted += 1
                        continue
                elif table_name == "analysis_snapshots":
                    existing = model.query.filter_by(
                        ts_code=data.get("ts_code"),
                        trade_date=data.get("trade_date"),
                    ).first()
                    if existing:
                        for k, v in data.items():
                            setattr(existing, k, v)
                        updated += 1
                        continue
                    else:
                        obj = model(**data)
                        db.session.add(obj)
                        inserted += 1
                        continue
                elif table_name in ("backtest_runs", "evolution_runs"):
                    # 简单追加 (这些是一次性记录, 不去重)
                    obj = model(**data)
                    db.session.add(obj)
                    inserted += 1
                    continue
                else:
                    obj = model(**data)
                    db.session.add(obj)
                    inserted += 1
                    continue
        except Exception as e:
            skipped += 1
            print(f"    [WARN] 跳过一条记录 ({table_name}): {e}")

    stats[table_name] = {"inserted": inserted, "updated": updated, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="输入 JSON 文件")
    parser.add_argument("--merge", action="store_true", default=True, help="(默认) 增量合并")
    parser.add_argument("--replace", action="store_true", help="清空所有表后导入")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] 文件不存在: {args.input}")
        sys.exit(1)

    mode = "replace" if args.replace else "merge"

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    if mode == "replace":
        print(f"\n[WARN] --replace 模式将清空所有表, 确认要继续吗? (输入 yes 继续)")
        confirm = input("确认 (yes/no): ")
        if confirm != "yes":
            print("已取消")
            return

    with app.app_context():
        if mode == "replace":
            print("\n清空所有表...")
            for model in [BacktestTrade, BacktestRun, EvolutionRun, TradeLog,
                          AnalysisSnapshot, Position, Watchlist]:
                model.query.delete()
            db.session.commit()

        stats = {}
        print(f"\n=== 开始导入 (mode={mode}) ===")
        for table_name, records in data.get("tables", {}).items():
            print(f"\n[{table_name}] {len(records)} 条记录")
            import_table(table_name, records, mode, stats)

        db.session.commit()

        # 统计
        total_inserted = sum(s.get("inserted", 0) for s in stats.values())
        total_updated = sum(s.get("updated", 0) for s in stats.values())
        total_skipped = sum(s.get("skipped", 0) for s in stats.values())

        print(f"\n=== 导入完成 ===")
        print(f"新增: {total_inserted}, 更新: {total_updated}, 跳过: {total_skipped}")
        for table_name, s in stats.items():
            print(f"  {table_name:25} 新增 {s.get('inserted', 0):>4}  更新 {s.get('updated', 0):>4}  跳过 {s.get('skipped', 0):>4}")


if __name__ == "__main__":
    main()