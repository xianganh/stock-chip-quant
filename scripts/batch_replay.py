#!/usr/bin/env python3
"""
批量算法信号回放 - Phase 3

对数据库中的 position 逐日跑算法信号，存入 position.algorithm_signal (JSON)
支持：
- 自定义股票列表
- 自定义账户筛选
- 自定义时间窗口
- 进度显示

用法:
    python scripts/batch_replay.py                            # 所有 closed positions
    python scripts/batch_replay.py --ts-codes 603773.SH,603039.SH  # 指定股票
    python scripts/batch_replay.py --account 衡祥安          # 指定账户
    python scripts/batch_replay.py --limit 10               # 仅回放 10 个
    python scripts/batch_replay.py --dry-run                 # 预览不入库
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

# 让脚本可独立运行
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "engine"))

from app import app, db
from database.models import Position, TradeLog
from engine.replay_engine import ReplayEngine, ReplayResult


def list_positions(args):
    """根据参数筛选 positions"""
    with app.app_context():
        query = Position.query
        if args.account:
            query = query.filter_by(account=args.account)
        if args.ts_codes:
            codes = [c.strip() for c in args.ts_codes.split(",")]
            query = query.filter(Position.ts_code.in_(codes))
        if args.status:
            query = query.filter_by(status=args.status)
        query = query.order_by(Position.entry_date.desc())
        if args.limit:
            query = query.limit(args.limit)
        return query.all()


def replay_one_position(engine, pos, dry_run=False):
    """回放单个 position"""
    from utils import normalize_ts_code
    try:
        # 自动补全 ts_code 后缀
        ts_code = normalize_ts_code(pos.ts_code)
        result = engine.replay_position(
            ts_code=ts_code,
            entry_date=pos.entry_date,
            exit_date=pos.exit_date,
        )
        if pos.realized_pnl_pct is not None:
            result.set_actual_pnl(pos.realized_pnl_pct)
        result.name = pos.name or pos.ts_code
        result.account = pos.account or ""

        if not dry_run:
            with app.app_context():
                p = Position.query.get(pos.id)
                if p:
                    # 写库: 存完整信号序列 + 偏差分析
                    signal_payload = {
                        "version": "v1",
                        "replayed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "entry_signal": result.entry_signal,
                        "exit_signal": result.exit_signal,
                        "daily_signals": result.daily_signals,
                        "action_distribution": result.get_action_distribution(),
                        "deviation": result.compute_deviation(),
                        "holding_days": result.holding_days,
                        "preload_seconds": round(result.preload_seconds, 2),
                        "calc_seconds": round(result.calc_seconds, 2),
                    }
                    p.algorithm_signal = json.dumps(signal_payload, ensure_ascii=False, default=str)
                    if result.entry_signal:
                        p.algorithm_verdict = result.entry_signal.get("action", "")
                    db.session.commit()

        return result
    except Exception as e:
        print(f"  [ERROR] Position {pos.id} ({pos.ts_code}): {e}", file=sys.stderr)
        return None


def aggregate_stats(results):
    """聚合所有结果的统计"""
    stats = {
        "total": len(results),
        "algorithmic_agree": 0,
        "algorithmic_warn": 0,
        "algorithmic_disagree": 0,
        "data_insufficient": 0,
        "no_actual_data": 0,
        "by_action": {},
        "by_outcome": {},
        "total_pnl": 0,
    }
    for r in results:
        if not r:
            continue
        deviation = r.compute_deviation()
        verdict = deviation.get("verdict", "no_actual_data")
        if verdict in stats:
            stats[verdict] += 1
        # action 分布
        entry_action = r.entry_signal.get("action", "?") if r.entry_signal else "?"
        stats["by_action"][entry_action] = stats["by_action"].get(entry_action, 0) + 1
        # 实际盈亏
        if r.actual_pnl_pct is not None:
            stats["total_pnl"] += r.actual_pnl_pct
            outcome = deviation.get("actual_outcome", "?")
            stats["by_outcome"][outcome] = stats["by_outcome"].get(outcome, 0) + 1
    return stats


def print_report(results, stats, total_seconds):
    """打印汇总报告"""
    print()
    print("=" * 70)
    print("批量回放汇总报告")
    print("=" * 70)
    total = max(stats["total"], 1)  # 避免除零
    print(f"总样本数:    {stats['total']}")
    if stats["total"] > 0:
        print(f"算法判断准确: {stats['algorithmic_agree']} ({stats['algorithmic_agree']/total*100:.1f}%)")
        print(f"算法预警准确: {stats['algorithmic_warn']} ({stats['algorithmic_warn']/total*100:.1f}%)")
        print(f"算法判断错误: {stats['algorithmic_disagree']} ({stats['algorithmic_disagree']/total*100:.1f}%)")
        print(f"数据不足:    {stats['data_insufficient']} ({stats['data_insufficient']/total*100:.1f}%)")
    else:
        print("(无有效样本)")
    print()
    print(f"入场 Action 分布:")
    for action, count in sorted(stats["by_action"].items(), key=lambda x: -x[1]):
        print(f"  {action:<8} {count:>4} ({count/total*100:.1f}%)")
    print()
    print(f"实际结果分布:")
    for outcome, count in sorted(stats["by_outcome"].items(), key=lambda x: -x[1]):
        print(f"  {outcome:<8} {count:>4} ({count/total*100:.1f}%)")
    print()
    print(f"累计盈亏: {stats['total_pnl']:+.2f}%")
    if stats["total"] > 0:
        print(f"总耗时:   {total_seconds:.1f}s ({total_seconds/total:.2f}s/position)")


def main():
    parser = argparse.ArgumentParser(description="批量算法信号回放")
    parser.add_argument("--ts-codes", help="逗号分隔的股票代码列表")
    parser.add_argument("--account", help="账户筛选（衡祥安/邱磊）")
    parser.add_argument("--status", default="closed", help="持仓状态 (默认 closed)")
    parser.add_argument("--limit", type=int, default=20, help="最多回放 N 个 (默认 20)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入数据库")
    parser.add_argument("--days", type=int, default=14, help="分析窗口 (默认 14)")
    parser.add_argument("--report-only", action="store_true", help="只输出报告")
    args = parser.parse_args()

    positions = list_positions(args)
    if not positions:
        print("未找到符合条件的 position。")
        return

    print(f"找到 {len(positions)} 个 position 待回放:")
    for p in positions[:5]:
        pnl = p.realized_pnl_pct or 0
        marker = "WIN " if pnl > 0 else "LOSS"
        print(f"  [{marker}] {p.ts_code} | {p.name or '(no name)'} | {p.entry_date}~{p.exit_date or '(active)'} | pnl={pnl:+.2f}%")
    if len(positions) > 5:
        print(f"  ... and {len(positions) - 5} more")
    print()

    if args.dry_run:
        print("[DRY-RUN] 不会写入数据库")
        print()

    # 回放
    engine = ReplayEngine(verbose=False)
    results = []
    t_start = time.time()
    for i, pos in enumerate(positions, 1):
        print(f"[{i}/{len(positions)}] Replaying {pos.ts_code} ({pos.name or '?'}) "
              f"[{pos.entry_date} ~ {pos.exit_date or 'now'}]")
        result = replay_one_position(engine, pos, dry_run=args.dry_run)
        if result:
            results.append(result)
            dev = result.compute_deviation()
            entry_action = result.entry_signal.get("action", "?") if result.entry_signal else "?"
            actual_outcome = dev.get("actual_outcome", "?")
            print(f"  -> Entry: {entry_action} | Actual: {actual_outcome} | "
                  f"Verdict: {dev.get('verdict', '?')}")
        print()
    t_total = time.time() - t_start

    # 报告
    stats = aggregate_stats(results)
    print_report(results, stats, t_total)

    # 详细列表
    print()
    print("=" * 70)
    print("逐条详情")
    print("=" * 70)
    for r in results:
        if not r:
            continue
        dev = r.compute_deviation()
        entry_action = r.entry_signal.get("action", "?") if r.entry_signal else "?"
        pnl_str = f"{r.actual_pnl_pct:+.2f}%" if r.actual_pnl_pct is not None else "  N/A"
        print(f"  {r.ts_code:12} {r.name or '?':10} | entry: {entry_action:6} | "
              f"pnl: {pnl_str:>8} | "
              f"deviation: {dev.get('verdict', '?')}")


if __name__ == "__main__":
    main()