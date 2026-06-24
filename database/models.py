"""SQLAlchemy 数据模型"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Watchlist(db.Model):
    """选股池"""
    __tablename__ = "watchlist"
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code    = db.Column(db.String(20), unique=True, nullable=False, index=True)  # 如 000066.SZ
    name       = db.Column(db.String(50))                                           # 如 中国长城
    added_date = db.Column(db.DateTime, default=datetime.now)
    notes      = db.Column(db.Text)                                                 # 逻辑预期差备注
    category   = db.Column(db.String(50))                                           # 涨价/订单/卡脖子/周期反转/估值调整
    active     = db.Column(db.Boolean, default=True)                                # 是否仍在池中

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns
                if c.name != "id"}


class AnalysisSnapshot(db.Model):
    """每日分析快照 (筹码+技术指标)"""
    __tablename__ = "analysis_snapshots"
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code     = db.Column(db.String(20), nullable=False, index=True)
    trade_date  = db.Column(db.String(8), nullable=False)
    # 核心筹码指标
    p1          = db.Column(db.Float)
    p1_pct      = db.Column(db.Float)
    tpc         = db.Column(db.Float)
    top5        = db.Column(db.Float)
    width_90    = db.Column(db.Float)
    winner      = db.Column(db.Float)
    dist        = db.Column(db.Float)
    skewness    = db.Column(db.Float)
    kurtosis    = db.Column(db.Float)
    entropy     = db.Column(db.Float)
    morphology  = db.Column(db.String(30))
    n_peaks     = db.Column(db.Integer)
    # 经典量化指标
    cmf         = db.Column(db.Float)
    adx         = db.Column(db.Float)
    atr_pct     = db.Column(db.Float)
    # 技术面评分
    momentum_score   = db.Column(db.Integer)
    trend_score      = db.Column(db.Integer)
    reversal_score   = db.Column(db.Integer)
    weighted_score   = db.Column(db.Float)
    # 背离信号
    divergence_score = db.Column(db.Float)
    divergence_verdict = db.Column(db.String(30))
    # AI 解读 (LLM 生成的 markdown 文本,缓存避免重复调用)
    interpretation     = db.Column(db.Text)
    interpretation_at  = db.Column(db.DateTime)
    # 完整JSON (原始数据)
    full_data    = db.Column(db.Text)   # JSON string
    created_at   = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (db.Index("ix_ts_date", "ts_code", "trade_date", unique=True),)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns
                if c.name not in ("id", "full_data", "created_at", "interpretation", "interpretation_at")}


class BacktestRun(db.Model):
    """回测运行记录"""
    __tablename__ = "backtest_runs"
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code      = db.Column(db.String(20), nullable=False)
    name         = db.Column(db.String(100))                 # 回测名称
    start_date   = db.Column(db.String(8))
    end_date     = db.Column(db.String(8))
    parameters   = db.Column(db.Text)                        # JSON: 策略参数
    total_trades = db.Column(db.Integer)
    win_rate     = db.Column(db.Float)
    avg_return   = db.Column(db.Float)                       # 平均每笔收益 %
    max_return   = db.Column(db.Float)
    min_return   = db.Column(db.Float)
    sharpe       = db.Column(db.Float)
    max_drawdown = db.Column(db.Float)
    total_return = db.Column(db.Float)                       # 累计收益 %
    signal_type  = db.Column(db.String(50))                  # lock/diverge/build_diverge
    created_at   = db.Column(db.DateTime, default=datetime.now)

    trades = db.relationship("BacktestTrade", backref="run", lazy="dynamic",
                              cascade="all, delete-orphan")

    def to_dict(self):
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns
             if c.name not in ("id", "parameters")}
        import json
        d["parameters"] = json.loads(self.parameters) if self.parameters else {}
        return d


class BacktestTrade(db.Model):
    """单笔交易记录"""
    __tablename__ = "backtest_trades"
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id       = db.Column(db.Integer, db.ForeignKey("backtest_runs.id"), nullable=False)
    entry_date   = db.Column(db.String(8))
    exit_date    = db.Column(db.String(8))
    entry_price  = db.Column(db.Float)
    exit_price   = db.Column(db.Float)
    return_pct   = db.Column(db.Float)
    holding_days = db.Column(db.Integer)
    signal_type  = db.Column(db.String(50))
    exit_reason  = db.Column(db.String(50))                  # stop_loss / take_profit / time_exit

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns
                if c.name != "id"}


class EvolutionRun(db.Model):
    """进化引擎运行记录"""
    __tablename__ = "evolution_runs"
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code       = db.Column(db.String(20), nullable=False)
    signal_type   = db.Column(db.String(50))
    param_grid    = db.Column(db.Text)                        # JSON: 参数网格
    best_params   = db.Column(db.Text)                        # JSON: 最优参数
    best_sharpe   = db.Column(db.Float)
    best_win_rate = db.Column(db.Float)
    total_tested  = db.Column(db.Integer)                     # 测试组合数
    results_json  = db.Column(db.Text)                        # 完整结果
    created_at    = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns
             if c.name not in ("id", "param_grid", "best_params", "results_json")}
        import json
        d["param_grid"]   = json.loads(self.param_grid) if self.param_grid else {}
        d["best_params"]  = json.loads(self.best_params) if self.best_params else {}
        return d


# ═══════════════════════════════════════════════════════
# 持仓 + 交易日志 (Phase 1)
# ═══════════════════════════════════════════════════════

class Position(db.Model):
    """当前/历史持仓"""
    __tablename__ = "positions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(50))
    account = db.Column(db.String(50), index=True)            # 账户标识 (衡祥安/邱磊)

    # 入场信息
    entry_date = db.Column(db.String(8), nullable=False)       # YYYYMMDD
    entry_price = db.Column(db.Float, nullable=False)          # 加权平均成本
    qty = db.Column(db.Integer, nullable=False, default=0)      # 当前持仓
    cost = db.Column(db.Float)                                  # 当前剩余成本 = entry_price * qty

    # 决策依据 (用户填写)
    entry_reason = db.Column(db.Text)
    expected_holding_days = db.Column(db.Integer)
    target_price = db.Column(db.Float)
    stop_loss = db.Column(db.Float)

    # 算法信号快照 (买入时自动跑一次)
    algorithm_signal = db.Column(db.Text)                       # JSON: 完整 analyze 结果
    algorithm_verdict = db.Column(db.String(50))               # 算法建议 (买入/持有/卖出风险)

    # 状态
    status = db.Column(db.String(20), default='active')         # active / closed / stopped_out
    exit_date = db.Column(db.String(8))
    exit_price = db.Column(db.Float)
    exit_reason = db.Column(db.Text)
    realized_pnl = db.Column(db.Float, default=0)                # 已实现盈亏
    realized_pnl_pct = db.Column(db.Float)                      # 百分比

    # 关联
    watchlist_id = db.Column(db.Integer, db.ForeignKey('watchlist.id'))

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (db.Index("ix_position_account_code", "account", "ts_code", "status"),)

    def to_dict(self):
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns
             if c.name not in ("algorithm_signal",)}
        if self.algorithm_signal:
            try:
                d["algorithm_signal"] = json.loads(self.algorithm_signal)
            except (json.JSONDecodeError, TypeError):
                pass
        return d


class TradeLog(db.Model):
    """完整交易日志 (从券商导入 + 手动补充)"""
    __tablename__ = "trade_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ts_code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(50))

    # 交易基本信息
    trade_date = db.Column(db.String(8), nullable=False, index=True)   # YYYYMMDD
    trade_time = db.Column(db.String(8))                              # HH:MM:SS
    direction = db.Column(db.String(10), nullable=False)              # buy / sell

    price = db.Column(db.Float, nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float)                                      # 成交金额

    # 手续费等 (从券商导出)
    commission = db.Column(db.Float)
    stamp_tax = db.Column(db.Float)
    other_fee = db.Column(db.Float)

    # 关联
    position_id = db.Column(db.Integer, db.ForeignKey('positions.id'))
    snapshot_id = db.Column(db.Integer, db.ForeignKey('analysis_snapshots.id'))

    # 来源
    source = db.Column(db.String(20))                                 # broker_import / manual
    broker = db.Column(db.String(50))                                 # xchxwtyh8 / 长沙-58
    account_holder = db.Column(db.String(50), index=True)             # 衡祥安 / 邱磊

    # 决策与情绪
    reason = db.Column(db.Text)                                       # 这笔交易的决策依据
    emotion = db.Column(db.String(20))                               # 冷静 / 冲动 / FOMO / 恐慌

    # 算法信号快照
    algorithm_signal = db.Column(db.Text)                            # JSON
    algorithm_verdict = db.Column(db.String(50))

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.Index("ix_trade_account_date", "account_holder", "trade_date"),
        db.Index("ix_trade_ts_date", "ts_code", "trade_date"),
    )

    def to_dict(self):
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        if self.algorithm_signal:
            try:
                d["algorithm_signal"] = json.loads(self.algorithm_signal)
            except (json.JSONDecodeError, TypeError):
                pass
        return d
