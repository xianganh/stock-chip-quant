# PROJECT STATUS (更新日志)

> 简短的工作记录. 详细见 [PROJECT.md](PROJECT.md)
> 每次重大变更后追加一条

---

## 2026-06-24 (late session) — Phase 3 启动 + 复盘中心 MVP

### 完成
- ✅ 算法信号回放引擎: `engine/replay_engine.py` (v2 性能优化版)
  - 每只股票只拉一次 Tushare 数据 (~0.5s/股)
  - 内存切片 + 离线计算 (~0.2s/日)
  - 性能: 1.02s/position, 2130 笔预计 36 分钟
- ✅ 批量回放 CLI: `scripts/batch_replay.py`
  - 支持 `--ts-codes / --account / --limit / --dry-run`
  - 写入 `Position.algorithm_signal` (JSON)
  - 汇总报告 + 逐条详情
- ✅ 4 个 REST API:
  - `GET  /api/review/stats` - 偏差分析统计
  - `GET  /api/review/list` - 回放列表
  - `GET  /api/review/detail/<id>` - 详情
  - `POST /api/replay/run` - 触发回放
- ✅ 复盘 UI: `templates/review.html`
  - 5 个统计卡片 + 3 个图表 + 3 个有效性表格
  - 触发回放按钮 + 筛选 (股票代码/账户/数量)
  - 自动 30s 刷新
- ✅ 交接文档: `HANDOVER.md` (跨电脑工作)
- ✅ Git 推送: commit `f3d187e`

### POC 验证 (20 样本)
- 总数: 20 笔
- 累计盈亏: **-16.54%**
- 算法误判: 7 (35.0%)
- 数据不足: 13 (65.0%)

### 关键发现
- 🔴 快克智能 603203: 算法持有 80% → 实际 -4.32% (误判)
- 🟡 立昂微 605358: 算法观望 → 实际 +7.78% (错失)
- ⚠️ 65% data_insufficient: 持仓期短 / 数据边缘

### 测试
- POC 验证通过
- 38 个 pytest 仍全部通过 (未新增)
- 17 → 21 个 API 端点 (+4)

### 下一步: M3-M7
- M3 回测增强 (多策略对比 + 参数敏感性)
- M5 性能优化 (异步任务)
- M6 测试覆盖 (新增 20 个 pytest)
- 调优算法阈值 (基于偏差统计)

详细路线图见 [docs/CodeWiki/12_phase3_roadmap.md](docs/CodeWiki/12_phase3_roadmap.md)
跨电脑工作流见 [HANDOVER.md](HANDOVER.md)

---

## 2026-06-24 — Phase 1 完成 + 文档化

### 完成
- ✅ 数据模型: `position` + `trade_log` 表
- ✅ 导入脚本: `scripts/import_trades.py` (FIFO)
- ✅ Watchlist 修复: 双向反查 + 一键硬删除
- ✅ 算法修复: 8 个 bug (median_price / peak_triplets / 命名 / 对称性等)
- ✅ 项目文档化: `PROJECT.md` + `docs/` 子目录
- ✅ 数据同步脚本: `export_data.py` + `import_data.py`

### 数据统计
- trade_logs: **2130 笔** (衡祥安 641 + 邱磊 1489)
- positions: **752 个** (5 活跃 + 747 已关闭)
- 历史胜率: **41.8%**
- 累计盈亏: **+560,950 元**

### 测试
- 38 个 pytest 全部通过
- 13 个 API 端点
- 6 张业务表

### 下一步: Phase 2 (决策仪表盘)
1. 综合判定卡片
2. 三维评分卡
3. 持仓评估模式
4. 算法信号回放
5. 调整 vs 反转识别

详细任务见 [docs/ROADMAP.md](docs/ROADMAP.md)

---

## 2026-06-24 (early session) — 重构 + 算法优化

- utils.py 抽取: token 加载, LLM 调用, 限流器
- analyze.py v2.5: 4 类背离 (新增时间-认知背离)
- AI 解读功能 (LLM 自动生成解读)
- 11 个回归测试覆盖 8 个 review bug 修复
- XSS / 限流 / 堆栈泄露安全补丁

---

## 2026-06-24 (更早) — Phase 1 启动

- 添加 2 个数据表: position, trade_log
- 导入 2130 笔历史交易
- 推导 752 个持仓 (含 FIFO)
- 修复 7 个 review 发现的算法 bug
- 同步 analyze.py root + scripts 两版本