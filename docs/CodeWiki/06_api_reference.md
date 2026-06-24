# 06. API 接口

> 基础 URL: `http://127.0.0.1:5000`
> 所有 API 返回 JSON
> 错误格式: `{"error": "..."}` + HTTP 标准状态码

## 📋 接口总览

| 方法 | 路径 | 功能 | 鉴权 |
|------|------|------|------|
| **页面** | | | |
| GET | `/` | 仪表盘主页 | 无 |
| GET | `/watchlist` | 选股池管理 | 无 |
| GET | `/analysis/<ts_code>` | 单只股票分析 | 无 |
| GET | `/backtest` | 回测页面 | 无 |
| **选股池** | | | |
| GET | `/api/watchlist` | 获取选股池 | 无 |
| POST | `/api/watchlist` | 添加/更新 | 无 |
| PUT | `/api/watchlist/<ts_code>` | 更新备注/分类 | 无 |
| DELETE | `/api/watchlist/<ts_code>` | 硬删除 | 无 |
| **分析** | | | |
| GET | `/api/analyze/<ts_code>` | 运行筹码峰分析 | 无 |
| GET | `/api/analyze/<ts_code>/verdict` | 综合判定 | 无 |
| GET | `/api/snapshots/<ts_code>` | 获取历史快照 | 无 |
| **AI 解读** | | | |
| GET | `/api/interpret/<ts_code>` | LLM 解读（带缓存） | 无 |
| **回测** | | | |
| POST | `/api/backtest/<ts_code>` | 运行回测 | 无 |
| GET | `/api/backtest/runs` | 获取回测列表 | 无 |
| GET | `/api/backtest/trades/<run_id>` | 获取回测交易 | 无 |
| **进化** | | | |
| POST | `/api/evolve/<ts_code>` | 运行参数进化 | 无 |
| GET | `/api/evolve/runs` | 获取进化列表 | 无 |
| **持仓/交易** | | | |
| GET | `/api/positions` | 持仓列表 | 无 |
| GET | `/api/positions/<id>` | 单个持仓 | 无 |
| GET | `/api/positions/by_code/<ts_code>` | 按代码查活跃持仓 | 无 |
| GET | `/api/trade_logs` | 交易日志 | 无 |
| **知识图谱** | | | |
| GET | `/api/stock_lookup` | 股票代码/名称反查 | 无 |
| GET | `/api/knowledge_graph/<ts_code>` | 按代码查 KG | 无 |
| GET | `/api/knowledge_graph/<ts_code>/related` | 按 tag 找关联 | 无 |
| GET | `/api/knowledge_graph/stats` | KG 统计 | 无 |
| **系统** | | | |
| GET | `/api/health` | 健康检查 | 无 |

---

## 📄 页面路由

### `GET /`
仪表盘主页
- **渲染**: [templates/index.html](../../templates/index.html)
- **数据**: `watchlist` (所有选股)

### `GET /watchlist`
选股池管理
- **渲染**: [templates/watchlist.html](../../templates/watchlist.html)

### `GET /analysis/<ts_code>`
单只股票分析
- **渲染**: [templates/analysis.html](../../templates/analysis.html)
- **服务端预渲染**: 直接调用 `chip_analyze()` 嵌入 HTML（避免前端 fetch 阻塞）
- **路径参数**: `ts_code` — 自动 normalize（000066 或 000066.SZ 都可）

### `GET /backtest`
回测页面
- **渲染**: [templates/backtest.html](../../templates/backtest.html)

---

## ⭐ 选股池 API

### `GET /api/watchlist`

获取所有选股（按 `added_date` 倒序）

**响应**:
```json
[
  {
    "ts_code": "000066.SZ",
    "name": "中国长城",
    "added_date": "2026-06-24T15:30:00",
    "notes": "...",
    "category": "涨价"
  }
]
```

### `POST /api/watchlist`

添加或更新选股

**请求体**:
```json
{
  "ts_code": "000066",          // 自动 normalize → 000066.SZ
  "name": "中国长城",
  "notes": "...",
  "category": "涨价"
}
```

**响应**:
```json
{ "ok": true, "ts_code": "000066.SZ" }
```

**错误**: `400 {"error": "请输入股票代码"}`

### `PUT /api/watchlist/<ts_code>`

更新备注/分类/名称（不修改 ts_code）

**请求体**:
```json
{ "name": "...", "notes": "...", "category": "..." }
```

### `DELETE /api/watchlist/<ts_code>`

一键硬删除

**响应**:
```json
{
  "ok": true,
  "deleted": "000066.SZ",
  "positions_unlinked": 2,    // 关联持仓被清 FK 引用数
  "trade_logs_kept": 15       // 保留的历史交易记录
}
```

**错误**: `404 {"error": "未找到该股票"}`

**注意**: 历史 `trade_logs` 保留（不级联删除）

---

## 🔬 分析 API

### `GET /api/analyze/<ts_code>`

运行筹码峰分析（**核心 API**）

**Query 参数**:
- `days` (int, 默认 14) — 分析窗口

**响应**: 完整 analyze 输出（详见 [04_algorithms.md](04_algorithms.md)）

```json
{
  "meta": { "ts_code": "...", "date_range": "...", "trade_days": 14 },
  "price_summary": { "latest_close": ..., "period_pct": ... },
  "chip_evolution": {
    "daily_records": [...],
    "locking_assessment": { "locked_score": "5/6", "overall": "强锁仓" },
    "dispatch_score": { "total": 2, "verdict": "健康" },
    "trends": { "p1": {...}, "tpc": {...} }
  },
  "chip_morphology": { "latest": {...}, "support_resistance": {...} },
  "distribution_statistics": {...},
  "classic_indicators": { "cmf": {...}, "adx": {...}, "atr": {...} },
  "chip_factor_ranks": { "metrics_percentiles": {...}, "latest_z_scores": {...} },
  "divergence_signals": {
    "signals": { "price_chip_divergence": {...}, "time_cognition_divergence": {...} },
    "total_score": 65,
    "verdict": "中等背离",
    "active_count": 2, "strong_count": 1
  },
  "narrative": { "phase": "...", "story": "..." },
  "tech_analysis": { "momentum": {...}, "trend": {...}, "reversal": {...}, "weighted": 4.2 }
}
```

**副作用**: 每次调用都会写一条 `analysis_snapshots` 记录

**错误**:
- `400 {"error": "..."}` — 分析失败（如股票代码无效）
- `500 {"error": "...", "traceback": [...]}` — 异常（仅 debug 模式附带堆栈）

### `GET /api/analyze/<ts_code>/verdict`

**综合判定**（Phase 2 决策仪表盘核心）

**Query 参数**:
- `days` (int, 默认 14)

**响应**:
```json
{
  "ts_code": "000066.SZ",
  "trade_date": "2026-06-23 ~ 2026-06-24",
  "action": "持有",                // 持有/减仓/清仓/观望
  "confidence": 80,                // 0-100
  "color": "green",                // green/yellow/red/gray
  "reasons": [
    "锁仓评分 5/6 条件满足, 主力稳定锁仓中",
    "P1 主峰占比 12.5%, 筹码集中度健康"
  ],
  "scores": {
    "lock": [5, 6],
    "dispatch": 1,
    "divergence_strong": 0,
    "divergence_active": 1,
    "tpc": 32.5,
    "morphology": "单峰密集"
  }
}
```

### `GET /api/snapshots/<ts_code>`

获取历史快照

**Query 参数**:
- `limit` (int, 默认 60)

**响应**:
```json
[
  { "ts_code": "...", "trade_date": "20260623", "p1": 12.5, "tpc": 32.5, ... },
  ...
]
```

---

## 🤖 AI 解读 API

### `GET /api/interpret/<ts_code>`

使用 LLM 生成中文解读（**带缓存 + 限流**）

**Query 参数**:
- `force=1` — 强制重新生成（忽略缓存，60 秒内同一股票仅允许 1 次）

**响应**:
```json
{
  "interpretation": "## 核心结论\n...\n## 筹码面解读\n...",
  "cached": true,
  "trade_date": "20260623",
  "generated_at": "2026-06-24 15:30:00"
}
```

**错误**:
- `404 {"error": "请先运行分析，再生成解读"}` — 没有快照
- `400 {"error": "快照缺少完整数据，请重新分析"}` — full_data 为空
- `429 {"error": "请求过于频繁, 请 60 秒后重试", "retry_after": 60}` — 限流
- `500 {"error": "LLM 调用失败: ..."}` — LLM 调用失败

**限流**: `SimpleRateLimiter(window_seconds=60, max_calls=1)`（模块级单例）

**Prompt 结构**（4 部分）:
1. 核心结论 (1-2 句话直接给方向判断)
2. 筹码面解读（基于 P1/TPC/形态/峰度等）
3. 技术面 + 资金面（基于 MACD/CMF/ADX/背离）
4. 操作建议（持有/观望/减仓，给出关键观察价位）

---

## 🔄 回测 API

### `POST /api/backtest/<ts_code>`

运行回测

**请求体**:
```json
{
  "signal_type": "locking",          // locking / divergence / dispatch / build_divergence
  "params": {
    "min_conditions": 5,             // signal 特定参数
    "divergence_threshold": 40,
    "min_dispatch_score": 3
  },
  "max_holding_days": 20,
  "stop_loss_pct": -8,
  "take_profit_pct": 20,
  "start_date": "20240101",
  "end_date": "20260624"
}
```

**响应**:
```json
{
  "total_trades": 15,
  "win_rate": 60.0,
  "avg_return": 3.2,
  "max_return": 18.5,
  "min_return": -7.8,
  "sharpe": 1.45,
  "max_drawdown": 12.3,
  "total_return": 48.0,
  "trades": [
    {
      "entry_date": "20240115",
      "exit_date": "20240205",
      "entry_price": 12.5,
      "exit_price": 14.8,
      "return_pct": 18.4,
      "holding_days": 15,
      "signal_type": "locking",
      "exit_reason": "take_profit"
    }
  ],
  "run_id": 42
}
```

### `GET /api/backtest/runs`

获取回测列表

**Query 参数**:
- `ts_code` (可选)
- `limit` (int, 默认 20)

### `GET /api/backtest/trades/<run_id>`

获取某次回测的所有交易

---

## 🧬 进化 API

### `POST /api/evolve/<ts_code>`

运行参数进化（网格搜索）

**请求体**:
```json
{
  "signal_type": "locking",
  "param_grid": {                  // 可选，不传用默认
    "min_conditions": [4, 5, 6]
  },
  "metric": "sharpe",              // sharpe / win_rate / total_return / max_drawdown
  "holding_params": {
    "max_holding_days": 20,
    "stop_loss_pct": -8,
    "take_profit_pct": 20
  },
  "start_date": "20240101",
  "end_date": "20260624"
}
```

**响应**:
```json
{
  "signal_type": "locking",
  "metric": "sharpe",
  "best_params": { "min_conditions": 5 },
  "best_metric_value": 1.85,
  "best_trades": [...],
  "total_tested": 3,
  "top_results": [
    { "params": {...}, "metric_value": 1.85, "sharpe": 1.85, "total_trades": 15, "win_rate": 60.0, "excess_return": 25.3 },
    ...
  ],
  "run_id": 7
}
```

**基线**: 同时计算 buy & hold 收益，要求策略必须跑赢大盘

### `GET /api/evolve/runs`

获取进化运行列表

---

## 💼 持仓 + 交易日志 API

### `GET /api/positions`

获取持仓列表

**Query 参数**:
- `account` (可选) — 衡祥安 / 邱磊
- `status` (可选) — active / closed / stopped_out

**响应**:
```json
[
  {
    "id": 123,
    "ts_code": "603039.SH",
    "name": "泛微网络",
    "account": "衡祥安",
    "entry_date": "20260401",
    "entry_price": 45.2,
    "qty": 100,
    "cost": 4520.0,
    "status": "active",
    "algorithm_verdict": "持有",
    ...
  }
]
```

### `GET /api/positions/<id>`

获取单个持仓详情

### `GET /api/positions/by_code/<ts_code>`

按股票代码查找活跃持仓（同时尝试带/不带后缀）

### `GET /api/trade_logs`

获取交易日志

**Query 参数**:
- `ts_code` (可选) — 自动 normalize
- `account` (可选)
- `limit` (int, 默认 50)

---

## 🕸️ 知识图谱 API

### `GET /api/stock_lookup`

股票代码/名称反查（支持双向查找）

**Query 参数**:
- `q` (str) — 查询字符串（代码或名称）
- `mode` (str) — `code` / `name` / `auto` (默认)
- `limit` (int, 默认 15)

**响应**:
```json
[
  { "ts_code": "000066.SZ", "name": "中国长城", "industry": "计算机", "area": "深圳", "market": "主板" },
  ...
]
```

### `GET /api/knowledge_graph/<ts_code>`

按股票代码获取知识图谱节点

**响应**:
```json
{
  "found": true,
  "code": "300174",
  "name": "元力股份",
  "tags": ["公司节点", "基础化工", "活性炭", "超级电容炭"],
  "type": "company",
  "summary": "福建元力活性炭股份有限公司...",
  "file": "company/元力股份_300174.md"
}
```

**错误**: `404 {"found": false, "ts_code": "..."}`

### `GET /api/knowledge_graph/<ts_code>/related`

按 tag 找关联公司

**响应**:
```json
{
  "tags": ["活性炭", "超级电容炭"],
  "related": {
    "活性炭": [
      { "code": "300174", "name": "元力股份", "tags": [...] }
    ]
  }
}
```

### `GET /api/knowledge_graph/stats`

知识图谱统计

**响应**:
```json
{
  "loaded": true,
  "companies": 50,
  "tags": 187
}
```

---

## 🏥 系统 API

### `GET /api/health`

健康检查

**响应**:
```json
{
  "status": "ok",
  "timestamp": "2026-06-24 15:30:00",
  "components": {
    "database": {
      "status": "ok",
      "watchlist_active": 15,
      "snapshots": 120,
      "backtest_runs": 8
    },
    "tushare_token": { "status": "ok" }
  }
}
```

**状态码**:
- `200` — 所有组件正常
- `503` — 有组件异常

---

## 🚨 错误处理

### 全局错误处理器

```python
@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not Found", "path": request.path}), 404
    return HTML 404 page

@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500
    return HTML 500 page
```

### 错误格式约定

| 类型 | 状态码 | 响应 |
|------|--------|------|
| 业务错误 | 400 | `{"error": "..."}` |
| 找不到 | 404 | `{"error": "Not Found", ...}` |
| 限流 | 429 | `{"error": "...", "retry_after": 60}` + `Retry-After` header |
| 服务异常 | 500 | `{"error": "Internal Server Error"}` |
| 分析失败 | 400 | `{"error": "..."}` |
| 服务降级 | 503 | `{"status": "degraded", "components": {...}}` |

---

## 🔐 安全特性

| 风险 | 措施 |
|------|------|
| 暴力破解 | `SimpleRateLimiter`（interpret API 60s/次）|
| 堆栈泄露 | 仅 debug 模式附带 `traceback` 字段 |
| XSS | Jinja2 自动转义 |
| CSRF | 未实现（单机使用，不需要）|
| 认证 | 未实现（局域网内使用）|
| SECRET_KEY | 三级降级（env → file → urandom）|

---

## 📊 统计（截至 2026-06-24）

- **页面路由**: 4 个
- **API 端点**: 22 个
- **错误处理器**: 2 个（404 / 500）
- **限流点**: 1 个（AI 解读 force）|