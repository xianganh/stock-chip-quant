# 05. 数据库模型

> 数据库: SQLite (`data/stock.db`)
> ORM: Flask-SQLAlchemy 3.1
> 详细文档: [DATA_MODEL.md](../DATA_MODEL.md)

## 📊 表关系概览

```
┌──────────────────────────────────────────────────────────┐
│  watchlist (选股池)                                       │
│  - 关注的股票, 不一定持仓                                 │
│  - 与持仓通过 ts_code 关联 (软链接)                        │
└──────────────────────────────────────────────────────────┘
            │ (ts_code)
            ↓
┌──────────────────────────────────────────────────────────┐
│  positions (持仓)                                         │
│  - 当前/历史持仓 (FIFO 匹配后)                            │
│  - entry_date / entry_price (加权平均成本)                 │
│  - exit_date / exit_price / realized_pnl (已关闭)          │
│  - watchlist_id (FK, 删除 watchlist 时清空)                │
└──────────────────────────────────────────────────────────┘
            │ (position_id)
            ↓
┌──────────────────────────────────────────────────────────┐
│  trade_logs (交易日志)                                     │
│  - 每笔买入/卖出 (含手续费等)                              │
│  - source: broker_import / manual                          │
│  - algorithm_signal: 买入时的算法信号快照                  │
└──────────────────────────────────────────────────────────┘

(独立)
┌──────────────────────────────────────────────────────────┐
│  analysis_snapshots (分析快照)                             │
│  - 每天/每次跑分析的完整结果                              │
│  - full_data: JSON                                        │
│  - interpretation: LLM 解读                                │
└──────────────────────────────────────────────────────────┘

(独立)
┌──────────────────────────────────────────────────────────┐
│  backtest_runs + backtest_trades (回测)                     │
│  - 每次回测结果                                            │
└──────────────────────────────────────────────────────────┘

(独立)
┌──────────────────────────────────────────────────────────┐
│  evolution_runs (进化)                                     │
│  - 每次参数进化结果                                        │
└──────────────────────────────────────────────────────────┘
```

## 📋 表详细说明

### 1. `watchlist` (选股池)

**位置**: [models.py:8-21](../../database/models.py#L8-L21)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | unique, 例: `000066.SZ` |
| `name` | VARCHAR(50) | | 股票名称 |
| `added_date` | DATETIME | | 加入时间 |
| `notes` | TEXT | | 备注 (逻辑预期差等) |
| `category` | VARCHAR(50) | | 分类 (涨价/订单/卡脖子等, 仅备注) |
| `active` | BOOLEAN | | 默认 True (历史遗留字段, 已统一使用) |

**索引**: `ts_code` (unique)

---

### 2. `analysis_snapshots` (分析快照)

**位置**: [models.py:24-66](../../database/models.py#L24-L66)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | 例: `000066.SZ` |
| `trade_date` | VARCHAR(8) | ✓ | YYYYMMDD |
| **核心筹码指标** ||||
| `p1` | FLOAT | | 主峰位 |
| `p1_pct` | FLOAT | | 主峰占比 |
| `tpc` | FLOAT | | 三峰集中度 |
| `top5` | FLOAT | | Top5 集中度 |
| `width_90` | FLOAT | | 90% 集中宽度 |
| `winner` | FLOAT | | 获利盘比例 |
| `dist` | FLOAT | | 价格对 P1 偏离 |
| `skewness` | FLOAT | | 偏度 |
| `kurtosis` | FLOAT | | 峰度 |
| `entropy` | FLOAT | | 分布熵 |
| `morphology` | VARCHAR(30) | | 形态分类 |
| `n_peaks` | INTEGER | | 峰数量 |
| **经典量化** ||||
| `cmf` | FLOAT | | 蔡金资金流 |
| `adx` | FLOAT | | 平均趋向指数 |
| `atr_pct` | FLOAT | | ATR/价格 % |
| **技术面评分** ||||
| `momentum_score` | INTEGER | | 动量评分 |
| `trend_score` | INTEGER | | 趋势评分 |
| `reversal_score` | INTEGER | | 反转评分 |
| `weighted_score` | FLOAT | | 加权综合 |
| **背离信号** ||||
| `divergence_score` | FLOAT | | 背离总分 |
| `divergence_verdict` | VARCHAR(30) | | 背离判定 |
| **AI 解读** ||||
| `interpretation` | TEXT | | LLM 生成的 markdown |
| `interpretation_at` | DATETIME | | 解读生成时间 |
| **完整数据** ||||
| `full_data` | TEXT | | JSON string（完整 analyze 输出）|
| `created_at` | DATETIME | | 创建时间 |

**索引**: `ix_ts_date (ts_code, trade_date, unique=True)`

**说明**: 这是项目核心表，每次运行 `chip_analyze()` 都会写一条。

---

### 3. `backtest_runs` (回测运行记录)

**位置**: [models.py:69-97](../../database/models.py#L69-L97)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | 例: `000066.SZ` |
| `name` | VARCHAR(100) | | 回测名称 (例: `locking_0624_1530`) |
| `start_date` | VARCHAR(8) | | YYYYMMDD |
| `end_date` | VARCHAR(8) | | YYYYMMDD |
| `parameters` | TEXT | | JSON: 策略参数 |
| `total_trades` | INTEGER | | 总交易笔数 |
| `win_rate` | FLOAT | | 胜率 % |
| `avg_return` | FLOAT | | 平均每笔收益 % |
| `max_return` | FLOAT | | 最大收益 % |
| `min_return` | FLOAT | | 最小收益 % |
| `sharpe` | FLOAT | | 夏普比率 |
| `max_drawdown` | FLOAT | | 最大回撤 % |
| `total_return` | FLOAT | | 累计收益 % |
| `signal_type` | VARCHAR(50) | | lock / diverge / build_diverge / dispatch |
| `created_at` | DATETIME | | 创建时间 |

**关联**: `trades = relationship("BacktestTrade", backref="run", cascade="all, delete-orphan")`

---

### 4. `backtest_trades` (单笔交易记录)

**位置**: [models.py:100-116](../../database/models.py#L100-L116)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `run_id` | INTEGER | FK | → `backtest_runs.id` |
| `entry_date` | VARCHAR(8) | | 入场日期 |
| `exit_date` | VARCHAR(8) | | 出场日期 |
| `entry_price` | FLOAT | | 入场价 |
| `exit_price` | FLOAT | | 出场价 |
| `return_pct` | FLOAT | | 收益率 % |
| `holding_days` | INTEGER | | 持仓天数 |
| `signal_type` | VARCHAR(50) | | 信号类型 |
| `exit_reason` | VARCHAR(50) | | stop_loss / take_profit / time_exit / force_close |

**关联**: 通过 `run_id` 反向关联到 `BacktestRun`

---

### 5. `evolution_runs` (进化引擎运行记录)

**位置**: [models.py:119-139](../../database/models.py#L119-L139)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | 例: `000066.SZ` |
| `signal_type` | VARCHAR(50) | | 信号类型 |
| `param_grid` | TEXT | | JSON: 参数网格 |
| `best_params` | TEXT | | JSON: 最优参数 |
| `best_sharpe` | FLOAT | | 最优夏普 |
| `best_win_rate` | FLOAT | | 最优胜率 |
| `total_tested` | INTEGER | | 测试组合数 |
| `results_json` | TEXT | | 完整结果 JSON |
| `created_at` | DATETIME | | 创建时间 |

---

### 6. `positions` (当前/历史持仓)

**位置**: [models.py:146-196](../../database/models.py#L146-L196)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | 例: `603039` |
| `name` | VARCHAR(50) | | |
| `account` | VARCHAR(50) | | 账户标识 (衡祥安/邱磊) |
| **入场信息** ||||
| `entry_date` | VARCHAR(8) | ✓ | YYYYMMDD |
| `entry_price` | FLOAT | ✓ | 加权平均成本 |
| `qty` | INTEGER | ✓ | 当前持仓数量 |
| `cost` | FLOAT | | 剩余成本 = entry_price × qty |
| **决策依据（用户填）** ||||
| `entry_reason` | TEXT | | 用户填的买入原因 |
| `expected_holding_days` | INTEGER | | |
| `target_price` | FLOAT | | |
| `stop_loss` | FLOAT | | |
| **算法信号快照（买入时自动跑一次）** ||||
| `algorithm_signal` | TEXT | | JSON: 完整 analyze 结果 |
| `algorithm_verdict` | VARCHAR(50) | | 算法建议 (买入/持有/卖出风险) |
| **状态** ||||
| `status` | VARCHAR(20) | | active / closed / stopped_out |
| `exit_date` | VARCHAR(8) | | |
| `exit_price` | FLOAT | | |
| `exit_reason` | TEXT | | |
| `realized_pnl` | FLOAT | | 已实现盈亏 |
| `realized_pnl_pct` | FLOAT | | 百分比 |
| **关联** ||||
| `watchlist_id` | INTEGER | FK | → `watchlist.id` |
| `notes` | TEXT | | |
| `created_at` | DATETIME | | |
| `updated_at` | DATETIME | | 自动 onupdate |

**索引**: `ix_position_account_code (account, ts_code, status)`

---

### 7. `trade_logs` (完整交易日志)

**位置**: [models.py:199-253](../../database/models.py#L199-L253)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 自增 |
| `ts_code` | VARCHAR(20) | ✓ | |
| `name` | VARCHAR(50) | | |
| **交易基本信息** ||||
| `trade_date` | VARCHAR(8) | ✓ | YYYYMMDD |
| `trade_time` | VARCHAR(8) | | HH:MM:SS |
| `direction` | VARCHAR(10) | ✓ | buy / sell |
| `price` | FLOAT | ✓ | 成交价 |
| `qty` | INTEGER | ✓ | 成交数量 |
| `amount` | FLOAT | | 成交金额 |
| **手续费等** ||||
| `commission` | FLOAT | | 佣金 |
| `stamp_tax` | FLOAT | | 印花税 |
| `other_fee` | FLOAT | | 其他费用 |
| **关联** ||||
| `position_id` | INTEGER | FK | → `positions.id` |
| `snapshot_id` | INTEGER | FK | → `analysis_snapshots.id` |
| **来源** ||||
| `source` | VARCHAR(20) | | broker_import / manual |
| `broker` | VARCHAR(50) | | xchxwtyh8 / 长沙-58 |
| `account_holder` | VARCHAR(50) | | 衡祥安 / 邱磊 |
| **决策与情绪** ||||
| `reason` | TEXT | | 这笔交易的决策依据 |
| `emotion` | VARCHAR(20) | | 冷静 / 冲动 / FOMO / 恐慌 |
| **算法信号快照** ||||
| `algorithm_signal` | TEXT | | JSON |
| `algorithm_verdict` | VARCHAR(50) | | |
| `notes` | TEXT | | |
| `created_at` | DATETIME | | |

**索引**:
- `ix_trade_account_date (account_holder, trade_date)`
- `ix_trade_ts_date (ts_code, trade_date)`

---

## 🛠️ DBManager 类

**位置**: [db_manager.py](../../database/db_manager.py)

**职责**: 统一数据管理层（静态方法封装 CRUD）

### 方法分组

#### 选股池 (`Watchlist`)

| 方法 | 说明 |
|------|------|
| `add_stock(ts_code, name, notes, category)` | 添加/更新（若存在则更新 active=True）|
| `remove_stock(ts_code)` | 硬删除（清理 FK 引用但保留 trade_logs）|
| `update_stock(ts_code, name, notes, category)` | 更新字段（None 不覆盖）|
| `get_watchlist()` | 获取所有（按 added_date 倒序）|
| `_resolve_stock(ts_code)` | 内部：兼容带/不带后缀查找 |

#### 分析快照 (`AnalysisSnapshot`)

| 方法 | 说明 |
|------|------|
| `save_snapshot(ts_code, trade_date, metrics, raw_json)` | 保存/更新快照 |
| `get_snapshots(ts_code, limit=60)` | 获取历史快照（按 trade_date 倒序）|
| `get_snapshot_dates(ts_code)` | 获取所有已有快照的日期集合 |
| `get_latest_snapshot_meta(ts_code)` | 仅获取元数据（用 defer 跳过 full_data）|
| `get_snapshot_full_data(ts_code, trade_date)` | 精确取 full_data |
| `save_interpretation(ts_code, trade_date, text)` | 保存 LLM 解读 |

#### 持仓 (`Position`)

| 方法 | 说明 |
|------|------|
| `get_positions(account=None, status=None)` | 获取持仓列表 |
| `get_position(id)` | 按 ID 获取 |
| `get_position_by_code(ts_code, account, status='active')` | 按代码获取活跃持仓 |
| `upsert_position(data)` | 创建或更新 |

#### 交易日志 (`TradeLog`)

| 方法 | 说明 |
|------|------|
| `get_trade_logs(ts_code=None, account=None, limit=50)` | 获取交易日志 |

#### 回测 (`BacktestRun` / `BacktestTrade`)

| 方法 | 说明 |
|------|------|
| `save_backtest_run(run_data, trades)` | 保存回测（含 trades 列表）|
| `get_backtest_runs(ts_code=None, limit=20)` | 获取回测运行列表 |
| `get_backtest_trades(run_id)` | 获取单次回测的所有交易 |

#### 进化 (`EvolutionRun`)

| 方法 | 说明 |
|------|------|
| `save_evolution_run(data)` | 保存进化结果 |
| `get_evolution_runs(ts_code=None, limit=10)` | 获取进化运行列表 |
| `get_best_params(ts_code, signal_type)` | 获取历史上最优参数 |

---

## 🔄 关键业务流程

### 流程 1: 添加选股 → 自动 normalize

```python
@app.route("/api/watchlist", methods=["POST"])
def api_add_stock():
    data = request.json
    ts_code = data.get("ts_code", "").strip()
    ts_code = normalize_ts_code(ts_code)  # 000066 → 000066.SZ
    DBManager.add_stock(ts_code=ts_code, ...)
```

### 流程 2: 分析股票 → 写快照

```python
@app.route("/api/analyze/<ts_code>", methods=["GET"])
def api_analyze(ts_code):
    result = chip_analyze(ts_code, days=14)
    metrics = {p1, tpc, cmf, ...}  # 提取关键指标
    DBManager.save_snapshot(ts_code, trade_date, metrics, result)
    return json_response(result)
```

### 流程 3: 删除选股 → 级联清理

```python
@app.route("/api/watchlist/<ts_code>", methods=["DELETE"])
def api_remove_stock(ts_code):
    target = Watchlist.query.filter_by(ts_code=ts_code).first()
    # 清 FK 引用（保留历史交易）
    Position.query.filter_by(watchlist_id=target.id).update(
        {Position.watchlist_id: None}, synchronize_session=False
    )
    db.session.delete(target)
```

---

## 🔧 Schema 迁移

**位置**: [app.py:84-106](../../app.py#L84-L106)

### 自动迁移函数 `_migrate_schema()`

启动时执行，补齐 model 中已声明但 DB 中不存在的列：

```python
def _migrate_schema():
    insp = inspect(db.engine)
    if insp.has_table("analysis_snapshots"):
        existing_cols = {c["name"] for c in insp.get_columns("analysis_snapshots")}
        new_cols = {
            "interpretation":    "TEXT",
            "interpretation_at": "DATETIME",
        }
        for col, col_type in new_cols.items():
            if col not in existing_cols:
                db.session.execute(text(f"ALTER TABLE analysis_snapshots ADD COLUMN {col} {col_type}"))
                db.session.commit()
```

**触发时机**:
- Flask 应用启动时（`with app.app_context(): _migrate_schema()`）
- 仅在列缺失时执行（幂等）

**当前迁移项**: `interpretation` + `interpretation_at`（v2.4 LLM 解读引入）

---

## 📊 数据统计（截至 2026-06-24）

| 表 | 记录数 | 备注 |
|----|-------|------|
| `trade_logs` | 2,130 | 衡祥安 641 + 邱磊 1,489 |
| `positions` | 752 | 5 活跃 + 747 已关闭 |
| `watchlist` | — | 取决于用户维护 |
| `analysis_snapshots` | — | 每次跑分析 +1 |
| `backtest_runs` | — | 每次跑回测 +1 |
| `backtest_trades` | — | 每次回测 N 笔 |
| `evolution_runs` | — | 每次跑进化 +1 |

**历史胜率**: 41.8%
**累计盈亏**: +560,950 元