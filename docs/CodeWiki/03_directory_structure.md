# 03. 目录结构

```
Analysis/                                 ← 项目根目录
├── 📄 README.md                          ← 原始简介（外层）
├── 📄 PROJECT.md                         ← 主文档（agent context）
├── 📄 PROJECT_STATUS.md                  ← 更新日志
│
├── 🐍 入口文件
│   ├── app.py                            ← Flask Web 应用 + API 路由
│   ├── config.py                         ← 全局配置
│   ├── utils.py                          ← 共享工具（token/限流/LLM/KG）
│   └── analyze.py                        ← 独立可运行副本（与 scripts/ 同步）
│
├── 🚀 启动/部署
│   ├── start.bat                         ← Windows 一键启动
│   ├── pull.bat                          ← Windows git pull
│   ├── pull.ps1                          ← PowerShell 版本
│   ├── demo_commit.bat                   ← 演示提交
│   ├── .env.example                      ← 环境变量模板
│   ├── .gitignore                        ← Git 忽略规则
│   ├── _check.py                         ← 自检脚本
│   ├── pytest.ini                        ← pytest 配置
│   ├── requirements.txt                  ← 运行时依赖
│   └── requirements-dev.txt              ← 开发依赖（pytest）
│
├── 📦 database/                          ← 数据层（SQLAlchemy + CRUD）
│   ├── __init__.py                       ← 模块导出
│   ├── models.py                         ← 6 张业务表的 ORM 模型
│   └── db_manager.py                     ← 统一 CRUD 封装（DBManager 类）
│
├── ⚙️ engine/                            ← 策略引擎
│   ├── __init__.py                       ← 导出 BacktestEngine + EvolutionEngine
│   ├── backtest_engine.py                ← 时序事件驱动回测
│   └── evolution_engine.py               ← 参数网格搜索进化
│
├── 🧮 scripts/                           ← 业务脚本 + 核心算法
│   ├── analyze.py                        ← ⭐ 筹码峰分析 8 大引擎（v2.5）
│   ├── import_trades.py                  ← 导入券商交易文件（FIFO 推导持仓）
│   ├── migrate_watchlist.py              ← watchlist 数据迁移（合并重复 + 补后缀）
│   ├── export_data.py                    ← 数据库导出 JSON（跨电脑同步）
│   ├── import_data.py                    ← JSON 导入数据库
│   └── setup_knowledge_graph.py          ← 复制外部 KG 到项目内
│
├── 🌐 templates/                         ← Jinja2 模板
│   ├── base.html                         ← 基础布局（导航 + 通用样式）
│   ├── index.html                        ← 仪表盘主页
│   ├── watchlist.html                    ← 选股池管理
│   ├── analysis.html                     ← 单只股票分析（Plotly 图表）
│   └── backtest.html                     ← 回测参数配置 + 结果展示
│
├── 🧪 tests/                             ← pytest 测试（38 个）
│   ├── test_smoke.py                     ← 17 个基础冒烟测试
│   ├── test_analyze_fixes.py             ← 11 个算法回归测试（8 个 review bug）
│   ├── test_positions.py                 ← 10 个 Position/TradeLog CRUD 测试
│   ├── test_knowledge_graph.py           ← 知识图谱集成测试
│   └── test_kg_ui.py                     ← KG UI 交互测试
│
├── 📚 docs/                              ← 详细文档
│   ├── README.md                         ← 原始 docs README
│   ├── DATA_MODEL.md                     ← 数据模型详细
│   ├── ROADMAP.md                        ← 阶段路线图
│   ├── RUNBOOK.md                        ← 运维手册
│   └── CodeWiki/                         ← ⭐ 本文档（Code Wiki）
│       ├── README.md                     ← Wiki 入口
│       ├── 01_overview.md
│       ├── 02_architecture.md
│       ├── 03_directory_structure.md     ← 本文件
│       └── ...
│
├── 💾 data/                              ← 本地数据（不入库）
│   ├── stock.db                          ← SQLite 数据库
│   ├── .secret_key                       ← Flask SECRET_KEY（自动生成）
│   ├── tradeHistroy.txt                  ← 衡祥安账户交易记录（参考）
│   └── tradeHistroy_fz.txt               ← 邱磊账户交易记录（参考）
│
└── 🕸️ knowledgeGraph/                    ← 知识图谱（随 git 同步）
    ├── README.md                         ← 编辑指南
    ├── ontology.md                       ← 本体规范
    ├── NAMING_CONVENTION.md              ← 命名约定
    ├── node_index.md                     ← 节点索引
    ├── company/                          ← 50 家公司档案
    ├── concept/                          ← 37 个概念
    ├── technology/                       ← 18 个技术
    ├── sector/                           ← 13 个板块
    ├── component/                        ← 15 个部件
    ├── event/                            ← 事件
    ├── supply_chain/                     ← 供应链
    ├── _workspace/                       ← 草稿/证据池
    └── (其他主题文件)                     ← AI算力.md / 玻璃基板.md ...
```

## 📊 各目录职责

### 根目录
- **入口文件**: app.py（Flask）、config.py（配置）、utils.py（工具）
- **入口分析**: analyze.py 是 scripts/analyze.py 的副本，保持同步（避免 import 路径问题）

### database/
- **职责**: SQLite 数据持久化层
- **核心类**:
  - `db` (SQLAlchemy 实例)
  - `DBManager` (静态方法封装 CRUD)
- **6 张表**: watchlist / analysis_snapshots / backtest_runs / backtest_trades / evolution_runs / positions / trade_logs

### engine/
- **职责**: 量化回测与参数优化
- **核心类**:
  - `BacktestEngine` — 时序事件驱动回测
  - `EvolutionEngine` — 参数网格搜索进化

### scripts/
- **职责**: 命令行工具 + 业务核心算法
- **核心脚本**:
  - `analyze.py` — 8 大引擎的入口（1873 行）
  - `import_trades.py` — 券商文件导入
  - `export_data.py` / `import_data.py` — 跨电脑同步
  - `migrate_watchlist.py` — 数据迁移
  - `setup_knowledge_graph.py` — 复制外部 KG

### templates/
- **职责**: Flask Jinja2 模板
- **技术**: Bootstrap 5.3 + Bootstrap Icons + Plotly.js 2.32
- **样式**: 暗色主题（slate palette）

### tests/
- **职责**: pytest 自动化测试
- **统计**: 38 个测试，覆盖核心算法、CRUD、KG 集成

### docs/
- **职责**: 项目文档
- **结构**:
  - `CodeWiki/` — 本文档（Code Wiki）
  - `DATA_MODEL.md` — 数据模型详细
  - `ROADMAP.md` — 阶段路线图
  - `RUNBOOK.md` — 运维手册

### data/
- **职责**: 本地数据存储（不入 git）
- **关键文件**:
  - `stock.db` — SQLite 数据库
  - `.secret_key` — Flask SECRET_KEY（自动生成）

### knowledgeGraph/
- **职责**: 股票研究笔记（Obsidian 风格）
- **格式**: YAML frontmatter + Markdown
- **同步**: 随 git 同步，跨电脑自动可用
- **统计**: 约 168 个 .md 文件

## 📋 文件大小量级（估算）

| 类别 | 行数 | 占比 |
|------|------|------|
| scripts/analyze.py | ~1873 | 60% |
| app.py | ~789 | 25% |
| engine/* | ~430 | 14% |
| database/* | ~520 | 17% |
| utils.py | ~605 | 19% |
| tests/* | ~1500 | 48% |
| knowledgeGraph/*.md | ~5000+ | — |

## 🔄 关键文件依赖关系

```
app.py
  ├── analyze.py (scripts/ 和 root 副本同步)
  ├── utils.py
  ├── config.py
  ├── database/
  │   ├── models.py
  │   └── db_manager.py
  └── engine/
      ├── backtest_engine.py → analyze.py + utils.py
      └── evolution_engine.py → backtest_engine.py + utils.py + config.py

scripts/analyze.py
  └── utils.py (get_tushare_pro)
```