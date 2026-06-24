# 筹码峰量化投研平台

> **最后更新**: 2026-06-24
> **当前状态**: Phase 1 完成 (数据基础)
> **下一步**: Phase 2 决策仪表盘

---

# 🤖 AGENT CONTEXT (新智能体必读)

> 如果你是新加入这个项目的 AI 智能体, **按以下顺序阅读**:

```
1. 本文档 (PROJECT.md)                           ← 你正在读
2. docs/DATA_MODEL.md                            ← 理解表结构
3. docs/ROADMAP.md                              ← 了解阶段任务
4. docs/RUNBOOK.md                              ← 知道怎么跑
5. PROJECT_STATUS.md (下方)                     ← 最近的工作记录
```

## 项目一句话定义

**短线投资者的持仓决策辅助工具** — 分析筹码峰 + 技术面, 回答"该不该买/该不该卖"。

## 用户画像 (核心, 不要忘)

- **短线为主, 持仓 1 周以内** (大牛股除外)
- **算法对所有股票统一适用**, 不按"涨价/卡脖子"等类型分类
- **14 日分析窗口** 用于验证涨停后行情, **不代表持仓期**
- **Layer 0 选股在外部做** (本项目只看已经感兴趣的股票)
- **三大痛点**: 买点不好回调拿不住 / 短期调整卖飞 / 不会高抛低吸

## 立即能跑起来

```bash
cd <项目根目录>
python app.py                              # 启动 Flask
python -m pytest tests/ -v                # 跑测试
python scripts/import_trades.py           # 导入交易历史
```

## 立刻能继续 Phase 2

`docs/ROADMAP.md` 里 Phase 2 的 5 个子任务, 每个都标了预计工作量。

---

# 📋 PROJECT STATUS (最近更新)

## ✅ Phase 1 已完成 (2026-06-24)

### 数据基础
- `position` 表 (24 字段) — 持仓 + 决策依据 + 算法快照
- `trade_log` 表 (23 字段) — 历史交易明细
- `scripts/import_trades.py` — 解析券商导出 (FIFO 推导持仓)
- `scripts/migrate_watchlist.py` — watchlist 数据格式迁移

### Watchlist 修复
- 双向反查: 输入代码自动填名称, 输入名称自动填代码
- 一键硬删除 (替代之前的"移除 → 永久删除"两步流程)
- 数据格式统一: 自动 normalize 加 `.SZ`/`.SH` 后缀

### API 端点
13 个新增端点, 详见 `docs/DATA_MODEL.md`。

### 测试
38 个 pytest 全部通过:
- 17 个 smoke 测试 (基础)
- 11 个 analyze 修复回归
- 10 个 Position/TradeLog CRUD

## 🚧 Phase 2 待办 (决策仪表盘, 解决三大痛点)

完整任务清单见 `docs/ROADMAP.md` Phase 2 章节。

优先级最高的前 3 个:
1. **综合判定卡片** — 顶部显示"该买/持/卖"+ 信心度
2. **持仓评估模式** — 当前持仓股显示"该不该卖"
3. **算法信号回放** — 在每笔 trade_log 入场日跑 analyze, 存 `algorithm_signal` 快照

---

# 🎯 项目定位 (详细)

**这不是一个通用选股工具, 而是持仓决策辅助系统。**

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0: 选股 (用户的职责, 项目外)                          │
│   从 5000 只股票中找到「有预期差」的票                       │
│   触发方式: 涨停/产业链/信息挖掘/...                         │
└─────────────────────────────────────────────────────────────┘
                            ↓ 选股清单
┌─────────────────────────────────────────────────────────────┐
│ Layer 2.5: 本项目职责                                       │
│   给定一只股票, 回答 6 个问题:                                │
│   1. 结构是否健康?                                           │
│   2. 主力是否还在? (吸筹/洗盘/派发?)                         │
│   3. 有没有出货嫌疑?                                         │
│   4. 买卖点建议?                                             │
│   5. 关键支撑阻力位?                                         │
│   6. 该继续持有还是该卖?                                     │
└─────────────────────────────────────────────────────────────┘
```

---

# 📂 项目结构

```
Analysis/
├── PROJECT.md              ← 你正在读 (主文档)
├── PROJECT_STATUS.md       ← 最近更新日志 (轻量)
├── app.py                  # Flask 应用 + API 路由
├── config.py               # 全局配置
├── utils.py                # 共享工具 (token/LLM/限流)
├── analyze.py              # 独立可运行副本 (与 scripts/ 同步)
├── requirements.txt
├── requirements-dev.txt    # 测试依赖
├── start.bat
├── pytest.ini
│
├── scripts/
│   ├── analyze.py          # 核心算法 (v2.5, 4 类背离 + 14 日筹码)
│   ├── import_trades.py    # 导入券商交易文件
│   ├── migrate_watchlist.py # watchlist 数据迁移
│   ├── export_data.py      # 数据导出 JSON
│   └── import_data.py      # 数据导入 JSON
│
├── database/
│   ├── models.py           # SQLAlchemy 模型
│   └── db_manager.py        # CRUD 封装
│
├── engine/
│   ├── backtest_engine.py
│   └── evolution_engine.py
│
├── templates/              # Jinja2 模板
├── tests/                  # pytest 测试
│
├── docs/                   # 详细文档
│   ├── DATA_MODEL.md       # 数据模型详细
│   ├── ROADMAP.md          # 阶段路线图
│   └── RUNBOOK.md          # 运维手册
│
└── data/
    ├── stock.db            # SQLite (本地, 不入库)
    ├── tradeHistroy.txt    # 衡祥安账户 (参考)
    └── tradeHistroy_fz.txt # 邱磊账户 (参考)
└── knowledgeGraph/      # 知识图谱 (随 git 同步, 168 .md 文件)
    ├── README.md           # 编辑指南
    ├── company/            # 50 家公司档案
    ├── concept/            # 37 个概念
    ├── technology/         # 18 个技术
    ├── sector/             # 13 个板块
    └── (其他主题目录)
```

---

# 🚀 快速开始

### 安装
```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### 启动
```bash
python app.py
# 访问 http://127.0.0.1:5000
```

### 测试
```bash
python -m pytest tests/ -v
```

### 数据导入
```bash
python scripts/import_trades.py           # 真实导入
python scripts/import_trades.py --dry-run  # 预览
```

### 数据迁移
```bash
python scripts/migrate_watchlist.py
```

### 跨电脑同步数据
```bash
# 在源电脑
python scripts/export_data.py data_dump.json

# 同步 JSON (git/邮件/微信)

# 在目标电脑
python scripts/import_data.py data_dump.json --merge
```

---

# 💾 跨电脑同步方案

### 代码 (自动同步)
通过 git:
```bash
git pull
git add -A && git commit -m "..."
git push
```

### 数据 (三种方案)

| 方案 | 适用场景 | 操作 |
|------|---------|------|
| **云盘同步 data/** | 简单, 经常切换 | 将 data/ 放 OneDrive/iCloud/Dropbox |
| **export/import JSON** | 偶尔切换, 数据完整性 | 见上方 "跨电脑同步数据" |
| **Git LFS** | 数据库 < 1GB | `git lfs track "data/*.db"` |

---

# 📚 详细文档

| 文档 | 内容 | 何时读 |
|------|------|--------|
| `docs/DATA_MODEL.md` | 6 张表的字段、索引、关系 | 改 schema 前 |
| `docs/ROADMAP.md` | Phase 1-5 详细任务清单 | 决定做什么时 |
| `docs/RUNBOOK.md` | 启动/测试/故障排查 | 操作时 |
| `PROJECT_STATUS.md` | 最近的工作更新 | 快速了解进度 |
| `README.md` | 原始简介 | 了解项目背景 |

---

# 📝 关键设计决策 (不要违背)

1. **不按"预期差类型"分类算法** — 用户明确说分类不准确, 反而误导
2. **14 日分析窗口 ≠ 持仓期** — 前者用于验证, 后者是用户实际交易周期
3. **数据格式统一 `.SZ`/`.SH` 后缀** — 自动 normalize, 不接受 6 位数字裸码
4. **删除是硬删除** — 不再有"移除 → 恢复"软删除, trade_logs 保留
5. **Layer 0 选股在外部** — 本项目只看已经感兴趣的股票
6. **算法信号存在 trade_log.algorithm_signal** — 每笔交易关联当时的算法判断 (Phase 2 实现)

---

# 🐛 已知问题

| 问题 | 状态 | 备注 |
|------|------|------|
| `trade_log.position_id` 关联未实现 | Phase 2 处理 | 当前 trade → position 关联靠 ts_code+date 推断 |
| analyze.py root vs scripts 双副本 | 用测试覆盖防发散 | 修改时两个都要改 |
| 删除重复记录 | 已迁移修复 | 见 `scripts/migrate_watchlist.py` |

---

# 🔧 常见任务速查

| 任务 | 命令 |
|------|------|
| 看当前 watchlist | `sqlite3 data/stock.db "SELECT * FROM watchlist"` |
| 重置数据库 | `rm data/stock.db && python app.py` (自动重建) |
| 单独跑 analyze | `cd scripts && python analyze.py 000066.SZ --days 14` |
| 单独跑导入预览 | `python scripts/import_trades.py --dry-run` |
| 启动后台服务 | `nohup python app.py > /tmp/flask.log 2>&1 &` |

---

# 🤝 协作约定 (Convention)

1. **测试先于实现**: 新功能先写 pytest, 再写实现
2. **小步快跑**: 每个修复都要在测试通过后 commit
3. **不要破坏 watchlist.active 字段**: 即使不再使用, 保留字段避免 schema 迁移
4. **root analyze.py 与 scripts/analyze.py**: 保持同步, 任何修改两处都要改
5. **中文优先**: UI/日志/prompt 用中文, 代码注释用中文
6. **API 错误**: 返回 JSON `{error: "..."}`, 状态码用 HTTP 标准 (400/404/429/500)

---

# 📞 紧急联系方式

- Tushare: https://tushare.pro/document/1
- Plotly: https://plotly.com/python/
- CodeBuddy: https://www.codebuddy.ai/docs

---

# 🔖 项目元数据

- **创建时间**: 2025
- **当前版本**: v2.5 (筹码算法) + Phase 1 (数据基础)
- **代码行数**: ~3000 行 (不含测试和文档)
- **测试覆盖**: 38 个测试, 涵盖核心模块