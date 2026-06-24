# 02. 整体架构

## 🏛️ 分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                       表现层 (Presentation)                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │  Flask Templates │  │  REST API        │  │  CLI Scripts │ │
│  │  (Jinja2 +       │  │  (JSON)          │  │  (argparse)  │ │
│  │   Bootstrap)     │  │                  │  │              │ │
│  └──────────────────┘  └──────────────────┘  └──────────────┘ │
└────────────────────────────────────────────────────────────────┘
                            ↓ ↑ HTTP/JSON
┌────────────────────────────────────────────────────────────────┐
│                       业务层 (Business Logic)                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  app.py (Flask Application)             │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐           │  │
│  │  │  Page      │ │  API       │ │  Error     │           │  │
│  │  │  Routes    │ │  Routes    │ │  Handlers  │           │  │
│  │  └────────────┘ └────────────┘ └────────────┘           │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              algorithms (业务核心)                        │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │  │
│  │  │ scripts/     │ │ engine/      │ │ utils.py         │  │  │
│  │  │ analyze.py   │ │ backtest_    │ │ compute_verdict  │  │  │
│  │  │ (8 大引擎)   │ │ engine.py    │ │ normalize_ts_    │  │  │
│  │  │              │ │ evolution_   │ │ code             │  │  │
│  │  │              │ │ engine.py    │ │ knowledge_graph  │  │  │
│  │  │              │ │              │ │ llm_call         │  │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                            ↓ ↑
┌────────────────────────────────────────────────────────────────┐
│                       数据层 (Data Layer)                        │
│  ┌──────────────────────────┐  ┌──────────────────────────┐    │
│  │  database/               │  │  External APIs           │    │
│  │  models.py (SQLAlchemy)  │  │  - Tushare Pro           │    │
│  │  db_manager.py (CRUD)    │  │  - CodeBuddy LLM         │    │
│  │  ── 6 tables ──          │  │                          │    │
│  │  watchlist               │  └──────────────────────────┘    │
│  │  analysis_snapshots      │                                  │
│  │  backtest_runs           │  ┌──────────────────────────┐    │
│  │  backtest_trades         │  │  Knowledge Graph         │    │
│  │  evolution_runs          │  │  (Markdown files)        │    │
│  │  positions               │  │  knowledgeGraph/         │    │
│  │  trade_logs              │  │                          │    │
│  └──────────────────────────┘  └──────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
                            ↓ ↑
┌────────────────────────────────────────────────────────────────┐
│                       基础设施层 (Infrastructure)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  SQLite      │  │  filesystem  │  │  .env + secret_key   │  │
│  │  data/stock.db│  │  data/ +    │  │                      │  │
│  │              │  │  logs/      │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## 🔄 数据流

### 数据流 1: 用户访问分析页面

```
用户浏览器
  ↓ GET /analysis/000066.SZ
app.py: analysis_page()
  ↓ chip_analyze(ts_code, days=14)
scripts/analyze.py: analyze()
  ↓ get_tushare_pro()
Tushare API (cyq_chips + stk_factor + moneyflow + daily_basic)
  ↓ 4 类数据
scripts/analyze.py: 8 大引擎并行计算
  ↓ dict 结果
app.py: 嵌入 HTML 渲染
  ↓ HTML
用户浏览器 (Plotly 渲染图表)
  ↓ 用户点击「保存快照」
DBManager.save_snapshot() → SQLite
```

### 数据流 2: 回测执行

```
用户浏览器
  ↓ POST /api/backtest/000066.SZ
app.py: api_run_backtest()
  ↓ BacktestEngine(ts_code, start_date, end_date)
engine/backtest_engine.py: BacktestEngine.__init__()
  ↓ engine.load_price_data()
Tushare API (pro.daily)
  ↓ price_data (DataFrame)
engine.run(signal_type, params, ...)
  ↓ 逐日时序回测
  ↓ 调用 chip_analyze() 获取每日信号
scripts/analyze.py: analyze() (多次)
  ↓ trades 列表
DBManager.save_backtest_run() → SQLite
  ↓ JSON 结果
用户浏览器
```

### 数据流 3: AI 解读

```
用户浏览器
  ↓ GET /api/interpret/000066.SZ?force=1
app.py: api_interpret()
  ↓ _force_limiter.allow(ts_code)  # 60s 限流
SimpleRateLimiter (utils.py)
  ↓ DBManager.get_latest_snapshot_meta()
SQLite (analysis_snapshots)
  ↓ 若缓存命中 → 返回缓存
  ↓ 若缓存未命中 → 加载 full_data
DBManager.get_snapshot_full_data()
  ↓ 构建精简 prompt
utils.call_llm(prompt, system)
  ↓ HTTP POST
CodeBuddy LLM API (OpenAI 兼容)
  ↓ markdown 文本
DBManager.save_interpretation() → SQLite
  ↓ JSON
用户浏览器
```

## 🧩 模块依赖图

```
                    ┌────────────────┐
                    │    app.py      │
                    │ (Flask entry)  │
                    └───────┬────────┘
                            │
        ┌───────────────────┼─────────────────────┐
        │                   │                     │
        ▼                   ▼                     ▼
  ┌──────────┐      ┌──────────────┐     ┌────────────┐
  │ database │      │   engine/    │     │   utils    │
  │          │      │              │     │            │
  └────┬─────┘      └──────┬───────┘     └─────┬──────┘
       │                   │                   │
       │                   │                   │
       └─────────┬─────────┴─────────┬─────────┘
                 │                   │
                 ▼                   ▼
          ┌─────────────┐    ┌──────────────────┐
          │ scripts/    │    │ config.py        │
          │ analyze.py  │    │ (global config)  │
          └──────┬──────┘    └──────────────────┘
                 │
                 ▼
          ┌─────────────┐
          │ Tushare API │
          └─────────────┘
```

## 🔐 安全架构

| 层级 | 措施 |
|------|------|
| 配置 | `.env` 文件 + `.secret_key` 文件（持久化跨重启）|
| 限流 | `SimpleRateLimiter`（模块级单例，避免并发竞态）|
| XSS | Jinja2 自动转义 + 手写限流防爆破 |
| 错误 | API 返回 JSON `{error: "..."}`，状态码用 HTTP 标准 |
| 堆栈泄露 | debug 模式附带堆栈，生产仅暴露类型+消息 |
| 输入校验 | `normalize_ts_code` 统一股票代码格式 |

## 🚦 启动流程

```
1. python app.py
   ↓
2. .env 加载 (环境变量)
   ↓
3. Flask app 初始化
   ├─ SQLAlchemy 绑定 SQLite (data/stock.db)
   ├─ SECRET_KEY 三级降级 (env → file → urandom)
   └─ 初始化 force 限流器
   ↓
4. db.create_all() + _migrate_schema()
   ├─ 创建不存在的表
   └─ 补齐缺失列 (interpretation, interpretation_at)
   ↓
5. 注册路由 (page + API + error handler)
   ↓
6. app.run(host, port, debug)
   ↓
7. 浏览器访问 http://127.0.0.1:5000
```

## 🔁 关闭流程

- **正常关闭**: Ctrl+C → Flask shutdown handler
- **强制关闭**: kill PID
- **数据一致性**: SQLite 单文件，无连接池，无需特殊处理
- **缓存清理**: 模块级单例随进程结束而释放

## 🌐 多进程/多线程

- **WSGI**: 默认 Flask 开发服务器单进程单线程
- **生产部署**: 需使用 gunicorn / uwsgi + nginx（未在项目中实现）
- **线程安全**: `SimpleRateLimiter` 内部使用 `threading.Lock`
- **Tushare 实例**: `lru_cache` 单例缓存，避免重复 token 设置

## 📦 部署模式

| 模式 | 用途 | 配置 |
|------|------|------|
| 开发模式 | 本地开发，自动 reload | `FLASK_DEBUG=1 python app.py` |
| 生产模式 | 单机部署 | `FLASK_DEBUG=0 python app.py` |
| 远程访问 | 允许外部 IP 访问 | `FLASK_HOST=0.0.0.0` ⚠️ 仅开发环境 |
| 自定义端口 | 端口冲突时 | `FLASK_PORT=8080` |
| 跨电脑同步 | 数据导出/导入 | `scripts/export_data.py` + `scripts/import_data.py` |