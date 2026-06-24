#!/usr/bin/env python3
"""
交易文件导入脚本 — Phase 1
解析 data/tradeHistroy.txt 和 data/tradeHistroy_fz.txt 为结构化数据

用法:
  python scripts/import_trades.py                    # 导入两个文件
  python scripts/import_trades.py --dry-run          # 只解析不入库
  python scripts/import_trades.py --file tradeHistroy.txt  # 指定单文件

输出:
  - trade_logs 表: 每笔交易明细
  - positions 表: 当前持仓 (按 FIFO 匹配后未平仓的部分)
"""
import argparse
import os
import sys
import re
from collections import defaultdict
from datetime import datetime

# 让脚本可独立运行
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from app import app, db
from database.models import TradeLog, Position


# ═══════════════════════════════════════════════════════
# 1. 文件解析
# ═══════════════════════════════════════════════════════

def read_file_smart(path: str) -> list[str]:
    """智能识别编码 (UTF-8 / GBK)"""
    for enc in ['utf-8', 'gbk', 'gb18030']:
        try:
            with open(path, encoding=enc) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法解码 {path}")


def parse_metadata(lines: list[str]) -> dict:
    """解析文件头: 营业部名称 / 期间 / 股东"""
    meta = {
        'broker': '',         # 营业部名称
        'period_start': '',   # YYYY-MM-DD
        'period_end': '',     # YYYY-MM-DD
        'account_holder': '', # 股东
    }
    for line in lines[:10]:
        line = line.strip()
        if '营业部名称' in line:
            meta['broker'] = line.split('：', 1)[-1].strip()
        elif '期间' in line:
            m = re.search(r'(\d{4})\s*-\s*(\d{2})\s*-\s*(\d{2})\s*至\s*(\d{4})\s*-\s*(\d{2})\s*-\s*(\d{2})', line)
            if m:
                y1, m1, d1, y2, m2, d2 = m.groups()
                meta['period_start'] = f"{y1}{m1}{d1}"
                meta['period_end']   = f"{y2}{m2}{d2}"
        elif '股东' in line:
            meta['account_holder'] = line.split('：', 1)[-1].strip()
    return meta


def parse_trades(lines: list[str]) -> list[dict]:
    """解析所有交易记录"""
    # 找到表头
    header_idx = None
    for i, line in enumerate(lines):
        if '\t' in line and '成交日期' in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    # 解析每行
    trades = []
    skipped = 0
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        cols = line.strip().split('\t')
        if len(cols) < 6:
            continue
        try:
            date = cols[0].strip()
            time = cols[1].strip() if len(cols) > 1 else ''
            code = cols[2].strip()
            name = cols[3].strip()
            op   = cols[4].strip()
            qty  = int(cols[5])
            if qty == 0:
                continue
            price = float(cols[6]) if cols[6] and cols[6] != '0.000' else 0.0
            amount = float(cols[7]) if len(cols) > 7 and cols[7] and cols[7] != '0.000' else 0.0

            # 手续费/印花税/其他费用 (位置在不同文件中不同)
            commission = 0.0
            stamp_tax  = 0.0
            other_fee  = 0.0
            # 文件1字段顺序: 手续费 印花税 其他杂费 发生金额 备注...
            # 文件2字段顺序: 印花税 其他杂费 发生金额 备注... (commission 在最后)
            # 通过尝试解析找到这些列
            for c in cols[8:14]:
                try:
                    val = float(c) if c and c != '0.000' else 0.0
                    if val > 0 and val < 1000:
                        if commission == 0:
                            commission = val
                        elif stamp_tax == 0:
                            stamp_tax = val
                        else:
                            other_fee += val
                except (ValueError, IndexError):
                    pass

            # ★ 过滤无效交易: 配号、申购、指数代码等
            SKIP_KEYWORDS = ['申购配号', '认购', '配号', '失效', '撤销']
            SKIP_CODES_PREFIX = ['789', '799', '511', '519', '159']
            if any(kw in op for kw in SKIP_KEYWORDS):
                skipped += 1
                continue
            if any(code.startswith(p) for p in SKIP_CODES_PREFIX):
                skipped += 1
                continue
            if price <= 0:
                skipped += 1
                continue

            # 判断方向: 数量为正 = 买入, 负 = 卖出
            direction = 'buy' if qty > 0 else 'sell'

            trades.append({
                'trade_date': date,
                'trade_time': time,
                'ts_code': code,
                'name': name,
                'direction': direction,
                'price': price,
                'qty': abs(qty),
                'amount': amount,
                'commission': commission,
                'stamp_tax': stamp_tax,
                'other_fee': other_fee,
            })
        except (ValueError, IndexError) as e:
            print(f"  [WARN] 跳过解析失败的行: {line.strip()[:80]}", file=sys.stderr)
            continue
    return trades, skipped


# ═══════════════════════════════════════════════════════
# 2. FIFO 推导 positions
# ═══════════════════════════════════════════════════════

def derive_positions(trades: list[dict], account: str) -> list[dict]:
    """
    按 FIFO 匹配每笔买入/卖出，推导出每个 (account, ts_code) 的持仓周期

    Returns:
        list of position dicts with status='active' or 'closed'
    """
    # 按 ts_code 分组
    by_code = defaultdict(list)
    for t in trades:
        by_code[t['ts_code']].append(t)

    positions = []
    for code, ts in by_code.items():
        # 按时间排序 (日期 + 时间)
        ts.sort(key=lambda t: (t['trade_date'], t['trade_time']))

        open_lots = []  # FIFO 队列: [{'trade': t, 'qty_remaining': int}]
        current_pos = None

        for trade in ts:
            if trade['direction'] == 'buy':
                # 加权平均成本
                if current_pos is None or current_pos['qty'] == 0:
                    # 新建 position
                    current_pos = {
                        'account': account,
                        'ts_code': code,
                        'name': trade['name'],
                        'entry_date': trade['trade_date'],
                        'entry_price': trade['price'],
                        'qty': trade['qty'],
                        'cost': trade['price'] * trade['qty'],
                        'realized_pnl': 0.0,
                        'trade_count': 1,
                        'buy_count': 1,
                        'sell_count': 0,
                        'first_buy': trade,
                    }
                else:
                    # 加权更新
                    new_qty = current_pos['qty'] + trade['qty']
                    new_cost = current_pos['cost'] + trade['price'] * trade['qty']
                    current_pos['entry_price'] = new_cost / new_qty
                    current_pos['qty'] = new_qty
                    current_pos['cost'] = new_cost
                    current_pos['trade_count'] += 1
                    current_pos['buy_count'] += 1
                open_lots.append({'trade': trade, 'qty_remaining': trade['qty']})

            elif trade['direction'] == 'sell':
                if current_pos is None or current_pos['qty'] == 0:
                    # 没有对应持仓, 跳过 (异常情况)
                    continue
                remaining_to_sell = trade['qty']
                sell_pnl = 0.0

                # FIFO 匹配 open_lots
                while remaining_to_sell > 0 and open_lots:
                    lot = open_lots[0]
                    matched = min(lot['qty_remaining'], remaining_to_sell)
                    pnl = (trade['price'] - lot['trade']['price']) * matched
                    sell_pnl += pnl
                    lot['qty_remaining'] -= matched
                    remaining_to_sell -= matched
                    if lot['qty_remaining'] == 0:
                        open_lots.pop(0)

                current_pos['qty'] -= trade['qty']
                current_pos['cost'] = current_pos['entry_price'] * current_pos['qty']
                current_pos['realized_pnl'] += sell_pnl
                current_pos['trade_count'] += 1
                current_pos['sell_count'] += 1
                current_pos['last_sell'] = trade

                if current_pos['qty'] == 0:
                    # Position 关闭
                    current_pos['status'] = 'closed'
                    current_pos['exit_date'] = trade['trade_date']
                    current_pos['exit_price'] = trade['price']
                    if current_pos['buy_count'] > 0:
                        current_pos['realized_pnl_pct'] = round(
                            current_pos['realized_pnl'] / (current_pos['entry_price'] * sum(
                                t['qty'] for t in ts if t['direction'] == 'buy' and t['trade_date'] <= trade['trade_date']
                            )) * 100, 2
                        )
                    else:
                        current_pos['realized_pnl_pct'] = 0
                    positions.append(current_pos)
                    current_pos = None

        # 剩余未平仓的 = 当前活跃持仓
        if current_pos and current_pos['qty'] > 0:
            current_pos['status'] = 'active'
            current_pos['exit_date'] = None
            current_pos['exit_price'] = None
            current_pos['realized_pnl_pct'] = 0  # 未实现
            positions.append(current_pos)

    return positions


# ═══════════════════════════════════════════════════════
# 3. 数据库导入
# ═══════════════════════════════════════════════════════

def import_file(file_path: str, account: str, dry_run: bool = False):
    """导入单个文件"""
    print(f"\n{'='*60}")
    print(f"  处理: {file_path}")
    print(f"  账户: {account}")
    print(f"{'='*60}")

    lines = read_file_smart(file_path)
    meta = parse_metadata(lines)
    print(f"  营业部: {meta['broker']}")
    print(f"  期间: {meta['period_start']} ~ {meta['period_end']}")

    trades, skipped = parse_trades(lines)
    print(f"  解析到 {len(trades)} 笔有效交易 (跳过 {skipped} 笔无效: 配号/申购/无效价格)")

    if not trades:
        return 0, 0

    buys = sum(1 for t in trades if t['direction'] == 'buy')
    sells = sum(1 for t in trades if t['direction'] == 'sell')
    print(f"  买/卖: {buys}/{sells}")
    print(f"  涉及股票: {len(set(t['ts_code'] for t in trades))} 只")

    positions = derive_positions(trades, account=account)
    active = [p for p in positions if p['status'] == 'active']
    closed = [p for p in positions if p['status'] == 'closed']
    print(f"  推导 positions: {len(positions)} 个 (活跃 {len(active)}, 已关闭 {len(closed)})")

    if closed:
        wins = [p for p in closed if p['realized_pnl'] > 0]
        losses = [p for p in closed if p['realized_pnl'] < 0]
        print(f"  胜率: {len(wins)}/{len(closed)} = {len(wins)/len(closed)*100:.1f}%")
        print(f"  累计盈亏: {sum(p['realized_pnl'] for p in closed):+,.0f} 元")

    if dry_run:
        print("\n  [DRY-RUN] 不写入数据库")
        print("\n  当前活跃持仓预览:")
        for p in active[:10]:
            print(f"    {p['ts_code']} {p['name']}: {p['qty']}股 @ {p['entry_price']:.2f} "
                  f"(入场 {p['entry_date']}, 累计买入 {p['buy_count']} 次)")
        return len(trades), len(positions)

    # 写入数据库
    with app.app_context():
        # 清空该账户的旧数据 (允许重新导入)
        deleted_trades = TradeLog.query.filter_by(account_holder=account).delete()
        deleted_positions = Position.query.filter_by(account=account).delete()
        db.session.commit()
        if deleted_trades or deleted_positions:
            print(f"  [清理] 删除旧数据: {deleted_trades} 笔交易, {deleted_positions} 个持仓")

        # 导入 trades
        for t in trades:
            db.session.add(TradeLog(
                ts_code=t['ts_code'],
                name=t['name'],
                trade_date=t['trade_date'],
                trade_time=t['trade_time'],
                direction=t['direction'],
                price=t['price'],
                qty=t['qty'],
                amount=t['amount'],
                commission=t['commission'],
                stamp_tax=t['stamp_tax'],
                other_fee=t['other_fee'],
                source='broker_import',
                broker=meta['broker'],
                account_holder=account,
            ))
        db.session.commit()
        print(f"  [OK] 导入 {len(trades)} 笔交易")

        # 导入 positions (按 entry_date 升序, 先建老仓后建新仓以保证关联)
        position_map = {}  # (account, ts_code) -> position.id
        for p in positions:
            pos = Position(
                account=p['account'],
                ts_code=p['ts_code'],
                name=p['name'],
                entry_date=p['entry_date'],
                entry_price=round(p['entry_price'], 3),
                qty=p['qty'],
                cost=round(p['cost'], 2),
                entry_reason=f"首次买入 {p['buy_count']} 次, 加权均价",
                status=p['status'],
                exit_date=p.get('exit_date'),
                exit_price=p.get('exit_price'),
                realized_pnl=round(p['realized_pnl'], 2) if p['status'] == 'closed' else 0,
                realized_pnl_pct=p.get('realized_pnl_pct', 0),
            )
            db.session.add(pos)
            db.session.flush()  # 获取 id
            position_map[(p['account'], p['ts_code'])] = pos.id

        db.session.commit()
        print(f"  [OK] 导入 {len(positions)} 个 positions")

        # 关联 trade_log.position_id (按时间顺序匹配)
        # 简化: 不做精细关联, 留给后续 UI 手动补全
        print(f"  [INFO] trade_log.position_id 关联待后续实现")

    return len(trades), len(positions)


def main():
    parser = argparse.ArgumentParser(description='导入券商交易文件到数据库')
    parser.add_argument('--dry-run', action='store_true', help='只解析不入库')
    parser.add_argument('--file', help='指定单个文件 (默认导入两个)')
    args = parser.parse_args()

    data_dir = os.path.join(_ROOT, 'data')

    if args.file:
        # 单文件模式: 账户名需要手动指定
        print("单文件模式: 请通过 --account 参数指定账户 (暂未实现)")
        return
    else:
        # 默认两个文件
        files = [
            (os.path.join(data_dir, 'tradeHistroy.txt'), '衡祥安'),
            (os.path.join(data_dir, 'tradeHistroy_fz.txt'), '邱磊'),
        ]
        total_trades, total_positions = 0, 0
        for fp, account in files:
            if os.path.exists(fp):
                t, p = import_file(fp, account, dry_run=args.dry_run)
                total_trades += t
                total_positions += p
            else:
                print(f"  [SKIP] 文件不存在: {fp}")

        print(f"\n{'='*60}")
        print(f"  汇总: {total_trades} 笔交易, {total_positions} 个 positions")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()