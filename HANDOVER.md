# 工作交接说明 (Handover)

> **目的**：让你（或你的 AI 助手）能在另一台电脑上无缝继续 Phase 3 工作
> **最后更新**: 2026-06-24
> **最新 commit**: `f3d187e feat(phase3): 算法信号回放 + 复盘中心`

---

## 📦 当前进度一览

### Git 状态
```
本地: clean (工作树干净)
远端: 已同步 (origin/master = f3d187e)
最新 commit: f3d187e feat(phase3): 算法信号回放 + 复盘中心
```

### 已完成的工作（最近 4 个 commit）
| Commit | 描述 |
|--------|------|
| `f3d187e` | Phase 3 初始：算法回放引擎 + 复盘 UI |
| `3e1a1e3` | Git 自动化脚本 (push/pull/status/sync) |
| `18073a3` | Phase 2: 单页解读仪表盘重构 |
| ... | Phase 1 完成 |

### Phase 3 已完成
- ✅ M1 数据基础：`engine/replay_engine.py` + `scripts/batch_replay.py`
- ✅ M2 API 后端：`/api/review/*` 4 个端点
- ✅ M4 UI 可视化：`/review` 页面（Plotly 仪表板）
- ✅ Git 同步（推送 `f3d187e`）

### Phase 3 未完成（待继续）
- ⏳ M3 回测增强（多策略对比 + 参数敏感性）
- ⏳ M5 性能优化（异步任务 + 批量并发）
- ⏳ M6 测试覆盖（20 个 pytest）

---

## 🚀 在另一台电脑上恢复工作的步骤

### Step 1: 拉取最新代码（2 分钟）

```bash
cd <目标目录>
git clone https://github.com/xianganh/stock-chip-quant.git
cd stock-chip-quant
# 或如果是已 clone 的目录：
git pull origin master
```

**期望看到**：
```
Updating 3e1a1e3..f3d187e
...
create mode 100644 docs/CodeWiki/12_phase3_roadmap.md
create mode 100644 engine/replay_engine.py
...
```

### Step 2: 安装依赖（1-3 分钟）

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**注意**：如果之前有 venv，建议复用或重建。

### Step 3: 配置 Tushare Token（必需）

```bash
# Windows PowerShell
$env:TUSHARE_TOKEN = "your_token_here"

# 或创建文件 ~/.config/tushare/token
```

### Step 4: 启动 Flask（验证安装）

```bash
python app.py
```

浏览器打开：
- http://127.0.0.1:5000/review ← **复盘中心（Phase 3 新功能）**
- http://127.0.0.1:5000/ ← 仪表盘
- http://127.0.0.1:5000/api/health ← 健康检查

### Step 5: 数据库初始化

**重要**：SQLite 数据库 (`data/stock.db`) **不会** 通过 git 同步！

两种选择：

#### 选项 A: 用本地已有数据（推荐先尝试）

```bash
# 在另一台电脑上，如果有交易数据：
python scripts/import_trades.py --dry-run    # 预览
python scripts/import_trades.py             # 真实导入
```

#### 选项 B: 从本机导出 → 另一台导入

**本机执行**：
```bash
python scripts/export_data.py data_dump_20260624.json
```

**另一台接收文件后**：
```bash
python scripts/import_data.py data_dump_20260624.json --merge
```

---

## 📊 当前数据快照（2026-06-24）

### 已回放的 20 笔样本
- **总数**: 20 笔 closed position
- **累计盈亏**: -16.54%
- **算法误判**: 7 笔 (35%)
- **数据不足**: 13 笔 (65%)

### 重点发现

| 问题 | 数据 | 建议 |
|------|------|------|
| 快克智能 603203 | 算法持有 80% → 实际 -4.32% | 派发阈值可能太低 |
| 立昂微 605358 | 算法观望 → 实际 +7.78% | 数据边缘导致错失 |
| 65% data_insufficient | 持仓期太短或数据范围不足 | 需要更早 cyq_chips |

### 已写入数据库
- `Position.algorithm_signal` 字段：20 笔已填充 JSON

---

## 📁 关键文件位置

### Phase 3 新增文件
```
engine/replay_engine.py              ← 核心引擎 (~550 行)
scripts/batch_replay.py              ← 批量回放 CLI (~200 行)
templates/review.html                ← 复盘 UI (~400 行)
docs/CodeWiki/12_phase3_roadmap.md   ← 路线图
docs/run_poc_samples.py              ← POC 测试脚本
docs/replay_poc_v2_full.log           ← POC 完整日志
```

### Phase 3 修改文件
```
app.py                    +280 行 (4 个新 API + /review 路由)
templates/base.html       +1 行 (导航栏链接)
```

### 历史文件（参考）
```
docs/CodeWiki/01_overview.md            ← 项目概述
docs/CodeWiki/02_architecture.md        ← 整体架构
docs/CodeWiki/04_algorithms.md          ← 8 大算法引擎
docs/CodeWiki/05_data_model.md          ← 7 张表
docs/CodeWiki/06_api_reference.md       ← 22 个 API
docs/PROJECT.md                         ← 项目主文档
docs/PROJECT_STATUS.md                  ← 更新日志
docs/ROADMAP.md                         ← 阶段路线图
docs/RUNBOOK.md                         ← 运维手册
```

---

## 🎯 下一步建议（按优先级）

### 🔴 优先级 1：先验证 UI（5 分钟）
```
1. 启动 Flask: python app.py
2. 浏览器打开 http://127.0.0.1:5000/review
3. 点击 "▶ 触发回放" 按钮
4. 在输入框填 "603773.SH,603039.SH,002602.SZ" 测试指定股票
5. 查看每笔的 "展开" 详情
```

### 🟡 优先级 2：批量跑全部 2130 笔（约 36 分钟）
```bash
python scripts/batch_replay.py --limit 100  # 先跑 100 笔试试
python scripts/batch_replay.py --limit 2130 # 全量
```

或在 UI 上设置 limit = 500 触发。

### 🟢 优先级 3：继续推进 M3-M7

| 任务 | 工作量 | 说明 |
|------|--------|------|
| **M3 回测增强** | 1 天 | 多策略对比 + 参数敏感性热力图 |
| **M5 性能优化** | 0.5 天 | 异步任务（不阻塞 UI）|
| **M6 测试覆盖** | 0.5 天 | 20 个 pytest |
| **M7 文档发布** | 0.5 天 | 更新 PROJECT.md 等 |

### 🔵 优先级 4：算法调优

基于 20 笔样本发现的算法问题：
- **派发评分阈值**: 派发 = 1 持续 5 天未预警 → 建议降到 D1 即关注
- **锁仓评分**: 5/6 强信号对 6.02/20 样本（30%）误判 → 验证是否高
- **TPC 阈值**: 待更多样本分析

---

## 🔧 常用命令速查

### Git 自动化脚本（已推送到远端）

```bash
# 推送本地变更
push.bat "feat: xxx"
# 或 PowerShell
.\push.ps1 -Message "feat: xxx"

# 拉取远端更新
pull.bat
# 或
.\pull.ps1

# 跨电脑同步（先 pull 再 push）
sync.bat

# 查看状态
status.bat
```

### 数据库操作

```bash
# 导入券商交易文件
python scripts/import_trades.py --dry-run    # 预览
python scripts/import_trades.py             # 真实导入

# 导出/导入数据（跨电脑同步）
python scripts/export_data.py data_dump.json
python scripts/import_data.py data_dump.json --merge
```

### 批量回放

```bash
# 指定股票 + 数量
python scripts/batch_replay.py --ts-codes "603773.SH,603039.SH" --limit 10

# 指定账户
python scripts/batch_replay.py --account 衡祥安 --limit 50

# 仅预览（不入库）
python scripts/batch_replay.py --dry-run --limit 20
```

### 启动 Flask

```bash
# 标准启动
python app.py

# 指定端口
FLASK_PORT=8080 python app.py

# 开发模式（自动 reload）
FLASK_DEBUG=1 python app.py
```

### 测试

```bash
# 跑全部测试
python -m pytest tests/ -v

# 单个测试
python -m pytest tests/test_smoke.py -v

# 跑新增的复盘测试（如果已写）
python -m pytest tests/test_replay.py -v
```

---

## 📋 紧急检查清单（在新电脑上）

在开始 Phase 3 工作前，请确认：

- [ ] Git clone/pull 成功，`f3d187e` 是最新 commit
- [ ] 依赖安装完成（`pip install` 无报错）
- [ ] Tushare token 配置成功（`/api/health` 返回 `tushare_token: ok`）
- [ ] Flask 启动成功（http://127.0.0.1:5000 可访问）
- [ ] `/review` 页面能加载（应该看到 20 笔样本数据）
- [ ] `data/stock.db` 有数据（trade_logs ≈ 2130 笔）

---

## 🤖 给你的 AI 助手的提示

如果你的 AI 助手需要快速理解项目，建议按以下顺序阅读：

1. `HANDOVER.md`（本文档）— 5 分钟
2. `PROJECT.md` — 项目核心定义
3. `docs/CodeWiki/04_algorithms.md` — 8 大算法引擎
4. `docs/CodeWiki/12_phase3_roadmap.md` — Phase 3 详细路线图
5. `engine/replay_engine.py` — Phase 3 核心代码

测试问题：
> "我的项目是做什么的？Phase 3 的回放引擎工作原理是什么？"

如果它能正确回答，说明理解到位，可以继续推进。

---

## ⚠️ 已知限制

1. **数据时间范围**: Tushare cyq_chips 数据从 20260420 开始，2024-2025 历史交易大多因"数据不足"无法验证
2. **回放粒度**: 当前是逐日重算，未来如需更高精度可加逐笔
3. **API 限流**: Tushare 有调用频率限制，批量回放时可能触发限流（建议每次 ≤100 只股票）
4. **SQLite 性能**: 大批量回放写入可能慢，可后续迁移到 PostgreSQL

---

## 📞 联系方式

- GitHub: https://github.com/xianganh/stock-chip-quant
- Tushare 文档: https://tushare.pro/document/1
- 项目主页: `PROJECT.md`

---

**最后更新**: 2026-06-24 by AI Assistant
**目的**: 跨设备无缝衔接 Phase 3 工作