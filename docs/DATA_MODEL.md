# 数据模型详解

> 最后更新: 2026-06-24
> 数据库: SQLite (`data/stock.db`)

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

## 📋 字段详细说明

### watchlist (选股池)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | 自增 |
| ts_code | VARCHAR(20) | ✓ | unique, 例: `000066.SZ` |
| name | VARCHAR(50) | | 股票名称 |
| added_date | DATETIME | | 加入时间 |
| notes | TEXT | | 备注 (逻辑预期差等) |
| category | VARCHAR(50) | | 分类 (涨价/订单/卡脖子等, 仅备注) |
| active | BOOLEAN | | 默认 True (历史遗留字段, 已统一使用) |

### positions (持仓)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | 自增 |
| ts_code | VARCHAR(20) | ✓ | 例: `603039` |
| name | VARCHAR(50) | | |
| account | VARCHAR(50) | | "衡祥安" / "邱磊" |
| entry_date | VARCHAR(8) | ✓ | YYYYMMDD |
| entry_price | FLOAT | ✓ | 加权平均成本 |
| qty | INTEGER | ✓ | 当前持仓数量 |
| cost | FLOAT | | 剩余成本 = entry_price × qty |
| entry_reason | TEXT | | 用户填的买入原因 |
| expected_holding_days | INTEGER | | |
| target_price | FLOAT | | |
| stop_loss | FLOAT | | |
| algorithm_signal | TEXT | | JSON: 买入时跑的完整分析 |
| algorithm_verdict | VARCHAR(50) | | 算法建议 |
| watchlist_id | INTEGER | FK | 关联 watchlist.id |
| status | VARCHAR(20) | | active / closed / stopped_out |
| exit_date | VARCHAR(8) | | |
| exit_price | FLOAT | | |
| exit_reason | TEXT | | |
| realized_pnl | FLOAT | | 已实现盈亏 |
| realized_pnl_pct | FLOAT | | 百分比 |
| notes | TEXT | | |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

**索引**: `ix_position_account_code (account, ts_code, status)`

### trade_logs (交易日志)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | 自增 |
| ts_code | VARCHAR(20) | ✓ | |
| name | VARCHAR(50) | | |
| trade_date | VARCHAR(8) | ✓ | YYYYMMDD |
| trade_time | VARCHAR(8) | | HH:MM:SS |
| direction | VARCHAR(10) | ✓ | buy / sell |
| price | FLOAT | ✓ | |
| qty | INTEGER | ✓ | |
| amount | FLOAT | | 成交金额 |
| commission | FLOAT | | 手续费 |
| stamp_tax | FLOAT | | 印花税 |
| other_fee | FLOAT | | |
| position_id | INTEGER | FK | 关联 positions.id (待实现) |
| snapshot_id | INTEGER | FK | 关联 analysis_snapshots.id |
| source | VARCHAR(20) | | broker_import / manual |
| broker | VARCHAR(50) | | xchxwtyh8 / 长沙-58 |
| account_holder | VARCHAR(50) | | 衡祥安 / 邱磊 |
| reason | TEXT | | 决策依据 |
| emotion | VARCHAR(20) | | 冷静 / 冲动 / FOMO / 恐慌 |
| algorithm_signal | TEXT | | JSON |
| algorithm_verdict | VARCHAR(50) | | |
| notes | TEXT | | |

**索引**: `ix_trade_account_date (account_holder, trade_date)`, `ix_trade_ts_date (ts_code, trade_date)`

### analysis_snapshots (分析快照)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| ts_code | VARCHAR(20) | ✓ | |
| trade_date | VARCHAR(8) | ✓ | |
| (核心指标) | | | |
| p1, p1_pct, tpc, top5, top10, winner | FLOAT | | |
| width_90, dist, skewness, kurtosis, entropy | FLOAT | | |
| morphology, n_peaks | VARCHAR/INT | | 形态分类 |
| (技术指标) | | | |
| cmf, adx, atr_pct | FLOAT | | |
| momentum_score, trend_score, reversal_score, weighted_score | INT/FLOAT | | |
| (背离信号) | | | |
| divergence_score, divergence_verdict | FLOAT/VARCHAR | | |
| (LLM 解读) | | | |
| interpretation | TEXT | | LLM 解读 |
| interpretation_at | DATETIME | | |
| full_data | TEXT | | 完整 JSON |

**索引**: `ix_ts_date (ts_code, trade_date) UNIQUE`

---

## 🔄 数据流

### Phase 1 现状

```
券商导出 tradeHistroy.txt
    ↓ [scripts/import_trades.py]
trade_logs (所有历史交易明细)
    ↓ [FIFO 算法在 import_trades.py 里]
positions (当前持仓 + 已关闭持仓)
    ↓ [用户手动]
watchlist (关注股票池)
```

### Phase 2 计划 (算法信号回放)

```
trade_logs.entry_date
    ↓ [运行 analyze.py]
analysis_snapshots (买入日的算法快照)
    ↓ [更新]
trade_logs.algorithm_signal
    ↓ [决策仪表盘]
"该买/该持/该卖" 建议
```

---

## 🧪 数据完整性约束

1. **FK 删除**: 删除 watchlist → 自动 SET NULL positions.watchlist_id
2. **硬删除 trade_logs/positions**: 不级联, 保留历史
3. **账户隔离**: 通过 `account_holder` 字段, 同一股票不同账户独立记录

---

## 📈 索引设计

| 表 | 索引 | 用途 |
|----|------|------|
| watchlist | ts_code UNIQUE | 主键查询 |
| positions | (account, ts_code, status) | 多账户组合查询 |
| trade_logs | (ts_code, trade_date) | 单股历史时间序列 |
| trade_logs | (account_holder, trade_date) | 单账户历史 |
| analysis_snapshots | (ts_code, trade_date) UNIQUE | 单股单日分析 |