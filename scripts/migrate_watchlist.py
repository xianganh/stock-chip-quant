#!/usr/bin/env python3
"""
Watchlist 数据迁移脚本
- 统一旧数据格式 (无后缀 → 带后缀)
- 合并重复记录 (同一股票 603773 + 603773.SH)

用法:  python scripts/migrate_watchlist.py [--dry-run]
"""
import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from app import app, db
from database.models import Watchlist
from app import normalize_ts_code  # 复用 normalize_ts_code


def migrate(dry_run=False):
    with app.app_context():
        print('=== 当前 watchlist 状态 ===')
        all_records = Watchlist.query.order_by(Watchlist.ts_code).all()
        for w in all_records:
            print(f'  {w.ts_code:15} active={w.active} name={w.name}')

        # 找出所有需要迁移的 (无后缀)
        to_migrate = []
        for w in all_records:
            if '.' not in w.ts_code and w.ts_code.isdigit() and len(w.ts_code) == 6:
                new_code = normalize_ts_code(w.ts_code)
                to_migrate.append((w, new_code))

        print(f'\n=== 待迁移 (无后缀 → 带后缀): {len(to_migrate)} 条 ===')
        for w, new_code in to_migrate:
            print(f'  {w.ts_code:15} → {new_code:15} name={w.name}')

        # 找重复: 同一股票的两条记录
        print(f'\n=== 检查重复记录 ===')
        by_code6 = {}
        for w in all_records:
            code6 = w.ts_code.split('.')[0]
            by_code6.setdefault(code6, []).append(w)

        duplicates = []
        for code6, records in by_code6.items():
            if len(records) > 1:
                duplicates.append((code6, records))
                print(f'  [DUP] {code6} 有 {len(records)} 条记录:')
                for r in records:
                    print(f'     {r.ts_code:15} active={r.active} name={r.name}')

        if dry_run:
            print('\n[DRY-RUN] 不写入数据库')
            return

        # 执行迁移
        print(f'\n=== 开始迁移 ===')

        # 1. 先处理重复: 保留带后缀的, 把无后缀的合并过去
        for code6, records in duplicates:
            # 优先保留带后缀的 (sorted_with_suffix first)
            with_suffix = [r for r in records if '.' in r.ts_code]
            without_suffix = [r for r in records if '.' not in r.ts_code]

            if with_suffix:
                # 有带后缀的: 合并无后缀的字段过来, 然后删除无后缀的
                primary = with_suffix[0]
                for r in without_suffix:
                    # 字段合并: name/notes/category 取非空值
                    if r.name and not primary.name: primary.name = r.name
                    if r.notes and not primary.notes: primary.notes = r.notes
                    if r.category and not primary.category: primary.category = r.category
                    if r.active: primary.active = True
                    print(f'  合并 {r.ts_code} → {primary.ts_code}, 删除 {r.ts_code}')
                    db.session.delete(r)
                # 如果还有多个带后缀的, 保留第一个, 删除其余
                for extra in with_suffix[1:]:
                    print(f'  删除重复 {extra.ts_code}')
                    db.session.delete(extra)
            else:
                # 都没有后缀: 保留 active=True 的
                active_recs = [r for r in records if r.active]
                if active_recs:
                    primary = active_recs[0]
                    for r in records:
                        if r.id != primary.id:
                            print(f'  删除重复 {r.ts_code} (保留 {primary.ts_code})')
                            db.session.delete(r)

        db.session.commit()

        # 2. 处理无后缀的: 改 ts_code
        print(f'\n=== 迁移无后缀记录 ===')
        for w, new_code in to_migrate:
            # 检查是否已经有带后缀的同股票记录
            existing = Watchlist.query.filter_by(ts_code=new_code).first()
            if existing:
                # 有重复: 合并字段到带后缀记录
                if w.name and not existing.name: existing.name = w.name
                if w.notes and not existing.notes: existing.notes = w.notes
                if w.category and not existing.category: existing.category = w.category
                if w.active: existing.active = True
                print(f'  {w.ts_code} 已存在 {new_code}, 合并字段并删除 {w.ts_code}')
                db.session.delete(w)
            else:
                # 没重复: 直接更新 ts_code
                print(f'  {w.ts_code} → {new_code}')
                w.ts_code = new_code

        db.session.commit()

        print(f'\n=== 迁移后状态 ===')
        for w in Watchlist.query.order_by(Watchlist.ts_code).all():
            print(f'  {w.ts_code:15} active={w.active} name={w.name}')

        print(f'\n[OK] 迁移完成')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)