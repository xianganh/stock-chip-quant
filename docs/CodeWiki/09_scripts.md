# 09. 脚本工具

> 目录: [scripts/](../../scripts/)
> 主要脚本: `analyze.py` (核心算法) / `import_trades.py` (数据导入) / `migrate_watchlist.py` (数据迁移) / `export_data.py` + `import_data.py` (跨电脑同步) / `setup_knowledge_graph.py` (KG 复制)

## 📋 脚本清单

| 脚本 | 用途 | 调用频率 |
|------|------|---------|
| [analyze.py](#analyzepy) | ⭐ 筹码峰分析 CLI | 经常 |
| [import_trades.py](#import_tradespy) | 导入券商交易文件 | 偶尔 |
| [migrate_watchlist.py](#migrate_watchlistpy) | watchlist 数据迁移 | 一次性 |
| [export_data.py](#export_datapy) | 导出数据库为 JSON | 跨电脑时 |
| [import_data.py](#import_datapy) | 从 JSON 导入数据库 | 跨电脑时 |
| [setup_knowledge_graph.py](#setup_knowledge_graphpy) | 复制外部 KG | 一次性 |

---

## analyze.py

**位置**: [scripts/analyze.py](../../scripts/analyze.py)（同步副本: [analyze.py](../../analyze.py)）
**行数**: 1873
**核心入口**: `analyze(ts_code, days=14, end_date=None)`

### 概述

v2.5 版本的筹码峰演化 + 技术面综合分析脚本。

**包含 8 大引擎**：
1. 筹码峰单日指标（compute_chip_metrics）
2. 行为 emoji 标注（judge_emoji）
3. 6 条件锁仓判定（assess_locking）
4. 5 维派发评分（dispatch_score）
5. 技术面 3 策略打分（score_tech）
6. 经典量化指标（CMF/ADX/ATR）
7. 滚动分位数归一化
8. 4 类背离检测

### CLI 用法

```bash
# 基础用法
python analyze.py 000066.SZ

# 指定分析窗口
python analyze.py 301428.SZ --days 14

# 指定截止日期
python analyze.py 000066.SZ --end-date 20260623

# 输出到文件
python analyze.py 000066.SZ -o result.json

# 美化输出
python analyze.py 000066.SZ --pretty

# 完整示例
python analyze.py 301428.SZ --days 14 --end-date 20260623 -o result.json --pretty
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `code` (位置参数) | 必填 | Tushare 股票代码 |
| `--days` | 14 | 回溯交易日数 |
| `--output` / `-o` | None | 输出 JSON 文件路径 |
| `--end-date` | 今天 | 截止日期 YYYYMMDD |
| `--pretty` | False | 美化输出（缩进） |

### 作为模块调用

```python
from analyze import analyze

result = analyze("000066.SZ", days=14)

# result 是 dict，包含:
# - meta: 元信息
# - price_summary: 价格汇总
# - chip_evolution: 筹码演化
# - chip_morphology: 筹码形态
# - distribution_statistics: 分布统计
# - classic_indicators: 经典量化指标
# - chip_factor_ranks: 滚动分位数
# - divergence_signals: 4 类背离
# - narrative: 故事链叙事
# - tech_analysis: 技术面分析
```

### 详细算法说明

详见 [04_algorithms.md](04_algorithms.md)

---

## import_trades.py

**位置**: [scripts/import_trades.py](../../scripts/import_trades.py)

### 概述

解析券商导出的交易文件（`data/tradeHistroy.txt` 和 `data/tradeHistroy_fz.txt`），入库到 `trade_logs` 和 `positions` 表。

**FIFO 推导持仓**：
1. 解析每笔交易（日期/代码/方向/价格/数量）
2. 按时间排序
3. 买入 → 开仓/加仓
4. 卖出 → 按 FIFO 匹配之前的买入，剩余部分形成新持仓
5. 计算加权平均成本

### 文件格式

支持 UTF-8 / GBK / GB18030 编码自动识别：

```
营业部名称：某某证券营业部
期间：2024-01-01 至 2026-06-24
股东：衡祥安
...

成交日期	成交时间	证券代码	证券名称	委托方向	成交数量	成交价格	成交金额
20240101	09:30:00	603039	泛微网络	买入	100	45.20	4520.00
20240201	14:00:00	603039	泛微网络	卖出	100	48.50	4850.00
...
```

### CLI 用法

```bash
# 预览（不入库）
python scripts/import_trades.py --dry-run

# 真实导入（导入两个文件）
python scripts/import_trades.py

# 指定单文件
python scripts/import_trades.py --file tradeHistroy.txt

# 指定账户
python scripts/import_trades.py --account 衡祥安
```

### 数据流

```
data/tradeHistroy.txt (衡祥安)
  ↓ read_file_smart() 自动识别编码
  ↓ parse_metadata() 解析头部
  ↓ parse_trades() 解析每行
  ↓ FIFO 推导
  ↓ DBManager.add_trade_log() / add_position()
SQLite (trade_logs + positions)
```

### 输出统计

```
=== 导入完成 ===
trade_logs: 641 笔 (衡祥安)
positions: 245 个 (active: 2, closed: 243)
realized_pnl: +234,567 元
```

---

## migrate_watchlist.py

**位置**: [scripts/migrate_watchlist.py](../../scripts/migrate_watchlist.py)

### 概述

Watchlist 数据迁移工具，统一旧数据格式：
- 无后缀 → 带后缀（如 `000066` → `000066.SZ`）
- 合并重复记录（如 `000066` + `000066.SZ` 合并为一条）

### CLI 用法

```bash
# 预览（不写入数据库）
python scripts/migrate_watchlist.py --dry-run

# 真实迁移
python scripts/migrate_watchlist.py
```

### 迁移流程

1. **扫描当前 watchlist**
2. **识别需要迁移的**：
   - 无后缀的 6 位数字代码
   - 同股票的两条记录
3. **合并策略**：
   - 有带后缀的：保留带后缀的，无后缀的字段合并过去
   - 多个带后缀的：保留第一个，其余删除
4. **字段合并规则**：
   - `name`: 取非空值
   - `notes`: 取非空值
   - `category`: 取非空值
   - `active`: 任一为 True 则为 True

### 输出示例

```
=== 待迁移 (无后缀 → 带后缀): 5 条 ===
  000066        → 000066.SZ      name=中国长城
  ...

=== 检查重复记录 ===
  [DUP] 603039 有 2 条记录:
     603039        active=True name=泛微网络
     603039.SH     active=False name=None

=== 开始迁移 ===
  合并 603039 → 603039.SH, 删除 603039
  ...
```

---

## export_data.py

**位置**: [scripts/export_data.py](../../scripts/export_data.py)

### 概述

把数据库导出为 JSON，用于跨电脑同步。

### CLI 用法

```bash
# 默认输出 data_dump_<timestamp>.json
python scripts/export_data.py

# 指定输出文件
python scripts/export_data.py my_dump.json
```

### 导出内容

```json
{
  "metadata": {
    "exported_at": "2026-06-24T15:30:00",
    "version": "1.0",
    "tables": [
      {"name": "watchlist", "count": 15},
      {"name": "positions", "count": 752},
      ...
    ]
  },
  "tables": {
    "watchlist": [...],
    "positions": [...],
    "trade_logs": [...],
    "analysis_snapshots": [...],
    "backtest_runs": [...],
    "evolution_runs": [...]
  }
}
```

**注意**: 不导出 `backtest_trades`（数据量大）

---

## import_data.py

**位置**: [scripts/import_data.py](../../scripts/import_data.py)

### 概述

从 JSON 文件导入数据库（与 `export_data.py` 配套）。

### CLI 用法

```bash
# 默认合并模式（推荐，保留现有数据）
python scripts/import_data.py data_dump.json --merge

# 覆盖模式（清空后再导入）
python scripts/import_data.py data_dump.json --overwrite
```

### 合并策略

- **--merge**: 仅插入新记录，保留现有数据（按主键去重）
- **--overwrite**: 清空所有表后再导入

---

## setup_knowledge_graph.py

**位置**: [scripts/setup_knowledge_graph.py](../../scripts/setup_knowledge_graph.py)

### 概述

将外部知识图谱目录复制到项目内（一次性操作）。

**源**: `D:\stock\knowledgeGraph`
**目标**: `<项目根>/knowledgeGraph/`

### CLI 用法

```bash
python scripts/setup_knowledge_graph.py
```

### 排除规则

**排除目录**: `_archive/`、`_meta/`、`index/`

**排除文件**: `node_index.md`、`ontology.md`

### 流程

1. 检查源目录是否存在
2. 检查目标目录是否存在（如存在则询问是否覆盖）
3. 遍历源目录，按规则排除
4. 复制文件到目标目录
5. 输出统计（文件数 + 总大小）

---

## 🛠️ 脚本开发约定

### 路径处理

```python
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
```

### 导入项目模块

```python
from app import app, db
from database.models import Watchlist, Position, TradeLog
from utils import normalize_ts_code
```

### CLI 参数

```python
import argparse

parser = argparse.ArgumentParser(description="...")
parser.add_argument("code", help="...")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--days", type=int, default=14)
args = parser.parse_args()
```

### 日志输出

```python
print(f"[INFO] xxx", file=sys.stderr)
print(f"[WARN] xxx", file=sys.stderr)
print(f"[ERROR] xxx", file=sys.stderr)
```

### 干运行模式

支持 `--dry-run` 参数的脚本：
- [import_trades.py](#import_tradespy)
- [migrate_watchlist.py](#migrate_watchlistpy)

只解析不入库，用于预览。

---

## 📊 脚本调用频率

| 频率 | 脚本 |
|------|------|
| 每次分析 | analyze.py（通常通过 API） |
| 每周一次 | import_trades.py（导入新交易） |
| 一次性 | migrate_watchlist.py、setup_knowledge_graph.py |
| 跨电脑时 | export_data.py、import_data.py |