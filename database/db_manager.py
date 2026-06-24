"""数据库操作封装"""
from datetime import datetime
import json
import sys
import os
# 让 db_manager 可独立 import utils (避免依赖 app.py 的循环引用)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from utils import normalize_ts_code

from .models import (
    db, Watchlist, AnalysisSnapshot, BacktestRun, BacktestTrade, EvolutionRun,
    Position, TradeLog,
)


class DBManager:
    """统一数据管理层"""

    # ── 选股池 ──
    @staticmethod
    def add_stock(ts_code, name="", notes="", category=""):
        existing = Watchlist.query.filter_by(ts_code=ts_code).first()
        if existing:
            existing.active = True
            if name: existing.name = name
            if notes: existing.notes = notes
            if category: existing.category = category
        else:
            w = Watchlist(ts_code=ts_code, name=name, notes=notes, category=category)
            db.session.add(w)
        db.session.commit()

    @staticmethod
    def _resolve_stock(ts_code):
        """按代码查找 watchlist (兼容带/不带后缀, 支持 .SZ/.SH/.BJ)"""
        candidates = {ts_code, normalize_ts_code(ts_code)}
        for code in candidates:
            target = Watchlist.query.filter_by(ts_code=code).first()
            if target:
                return target
        return None

    @staticmethod
    def remove_stock(ts_code):
        """
        真删除选股记录 (硬删除, 不可恢复)
        会清理关联 Position.watchlist_id, 但保留 trade_logs 历史
        """
        target = DBManager._resolve_stock(ts_code)
        if not target:
            return 0  # 没找到
        # 清除 FK 引用
        Position.query.filter_by(watchlist_id=target.id).update(
            {Position.watchlist_id: None}, synchronize_session=False
        )
        deleted_code = target.ts_code
        db.session.delete(target)
        db.session.commit()
        return deleted_code

    @staticmethod
    def update_stock(ts_code, name=None, notes=None, category=None):
        """
        更新已有自选股的备注/分类/名称（不会改动 ts_code）
        None 字段不会被覆盖
        """
        target = DBManager._resolve_stock(ts_code)
        if not target:
            return False
        if name is not None:
            target.name = name
        if notes is not None:
            target.notes = notes
        if category is not None:
            target.category = category
        db.session.commit()
        return True

    @staticmethod
    def get_watchlist():
        """获取选股池 (硬删除后不存在软删除状态, 直接返回所有记录)"""
        return [w.to_dict() for w in Watchlist.query.order_by(
            Watchlist.added_date.desc()
        ).all()]

    # ── 分析快照 ──
    @staticmethod
    def save_snapshot(ts_code, trade_date, metrics: dict, raw_json: dict = None):
        existing = AnalysisSnapshot.query.filter_by(ts_code=ts_code, trade_date=trade_date).first()
        if existing:
            for k, v in metrics.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            if raw_json:
                existing.full_data = json.dumps(raw_json, ensure_ascii=False, default=str)
        else:
            snap = AnalysisSnapshot(ts_code=ts_code, trade_date=trade_date, full_data=json.dumps(raw_json, ensure_ascii=False, default=str) if raw_json else None, **metrics)
            db.session.add(snap)
        db.session.commit()

    @staticmethod
    def get_snapshots(ts_code, limit=60):
        snaps = AnalysisSnapshot.query.filter_by(ts_code=ts_code)\
                   .order_by(AnalysisSnapshot.trade_date.desc()).limit(limit).all()
        return [s.to_dict() for s in snaps]

    @staticmethod
    def get_snapshot_dates(ts_code):
        """获取某股票所有已有快照的日期"""
        snaps = AnalysisSnapshot.query.filter_by(ts_code=ts_code)\
                   .with_entities(AnalysisSnapshot.trade_date).all()
        return {s[0] for s in snaps}

    @staticmethod
    def get_latest_snapshot_meta(ts_code):
        """
        仅获取最近快照的元数据列 (不含 full_data 大字段)
        用于缓存命中检查等轻量场景
        """
        from sqlalchemy.orm import defer
        return AnalysisSnapshot.query.options(
            defer(AnalysisSnapshot.full_data)
        ).filter_by(ts_code=ts_code)\
         .order_by(AnalysisSnapshot.trade_date.desc()).first()

    @staticmethod
    def get_positions(account=None, status=None):
        """获取持仓列表"""
        q = Position.query
        if account:
            q = q.filter_by(account=account)
        if status:
            q = q.filter_by(status=status)
        return [p.to_dict() for p in q.order_by(Position.entry_date.desc()).all()]

    @staticmethod
    def get_position(id):
        """按 ID 获取单个持仓"""
        p = Position.query.get(id)
        return p.to_dict() if p else None

    @staticmethod
    def get_position_by_code(ts_code, account=None, status='active'):
        """按股票代码获取持仓"""
        q = Position.query.filter_by(ts_code=ts_code)
        if account:
            q = q.filter_by(account=account)
        if status:
            q = q.filter_by(status=status)
        return q.first()

    @staticmethod
    def upsert_position(data: dict):
        """创建或更新持仓"""
        existing = Position.query.filter_by(
            account=data['account'],
            ts_code=data['ts_code'],
            status=data.get('status', 'active')
        ).first()
        if existing:
            for k, v in data.items():
                if hasattr(existing, k) and k != 'id':
                    setattr(existing, k, v)
            db.session.commit()
            return existing
        else:
            pos = Position(**data)
            db.session.add(pos)
            db.session.commit()
            return pos

    @staticmethod
    def get_trade_logs(ts_code=None, account=None, limit=50):
        """获取交易日志"""
        q = TradeLog.query
        if ts_code:
            q = q.filter_by(ts_code=ts_code)
        if account:
            q = q.filter_by(account_holder=account)
        return [t.to_dict() for t in q.order_by(
            TradeLog.trade_date.desc(), TradeLog.trade_time.desc()
        ).limit(limit).all()]

    @staticmethod
    def get_snapshot_full_data(ts_code, trade_date):
        """按 ts_code+trade_date 精确取 full_data 字段"""
        snap = AnalysisSnapshot.query.filter_by(
            ts_code=ts_code, trade_date=trade_date
        ).first()
        return snap.full_data if snap else None

    @staticmethod
    def save_interpretation(ts_code, trade_date, interpretation: str):
        """保存 LLM 生成的解读"""
        snap = AnalysisSnapshot.query.filter_by(
            ts_code=ts_code, trade_date=trade_date
        ).first()
        if snap:
            snap.interpretation = interpretation
            snap.interpretation_at = datetime.now()
            db.session.commit()
            return True
        return False

    # ── 回测 ──
    @staticmethod
    def save_backtest_run(run_data: dict, trades: list) -> int:
        run = BacktestRun(**run_data)
        db.session.add(run)
        db.session.flush()  # 获取 run.id
        for t in trades:
            db.session.add(BacktestTrade(run_id=run.id, **t))
        db.session.commit()
        return run.id

    @staticmethod
    def get_backtest_runs(ts_code=None, limit=20):
        q = BacktestRun.query
        if ts_code:
            q = q.filter_by(ts_code=ts_code)
        runs = q.order_by(BacktestRun.created_at.desc()).limit(limit).all()
        return [r.to_dict() for r in runs]

    @staticmethod
    def get_backtest_trades(run_id):
        trades = BacktestTrade.query.filter_by(run_id=run_id)\
                    .order_by(BacktestTrade.entry_date).all()
        return [t.to_dict() for t in trades]

    # ── 进化 ──
    @staticmethod
    def save_evolution_run(data: dict):
        run = EvolutionRun(**data)
        db.session.add(run)
        db.session.commit()
        return run.id

    @staticmethod
    def get_evolution_runs(ts_code=None, limit=10):
        q = EvolutionRun.query
        if ts_code:
            q = q.filter_by(ts_code=ts_code)
        return [r.to_dict() for r in q.order_by(EvolutionRun.created_at.desc()).limit(limit).all()]

    @staticmethod
    def get_best_params(ts_code, signal_type):
        """获取某股票某信号类型历史上的最优参数"""
        run = EvolutionRun.query.filter_by(ts_code=ts_code, signal_type=signal_type)\
                  .order_by(EvolutionRun.best_sharpe.desc()).first()
        if run:
            return json.loads(run.best_params) if run.best_params else None
        return None
