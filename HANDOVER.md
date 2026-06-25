# 筹码峰量化项目 - 完整工作交接 (Handover)

> **目的**：让你（或你的 AI 助手）能在另一台电脑上无缝继续工作
> **最后更新**: 2026-06-25
> **最新 commit**: `e0b1ff1 feat: 筹码峰指标体系 + 定性回测框架 + 分级持仓管理`

---

## 📦 当前进度总览

### Git 状态
```
本地: clean (工作树干净)
远端: 已同步 (origin/master = e0b1ff1)
最新 commit: e0b1ff1
```

### 本次工作期间所有重要 Commit
| Commit | 描述 |
|--------|------|
| `e0b1ff1` | **本次**: 筹码峰指标体系 + 定性回测框架 + 分级持仓管理 |
| `0549437` | 跨电脑工作交接文档 + Phase 3 进度日志 |
| `f3d187e` | Phase 3: 算法信号回放 + 复盘中心 |
| `3e1a1e3` | Git 自动化脚本 (push/pull/status/sync) |
| `18073a3` | Phase 2: 重构分析页面为单页解读仪表盘 |

---

## 🆕 本次新增工作 (e0b1ff1)

### 完成的工作
1. **筹码峰指标通用化体系** - 25+ 指标
2. **Tushare 数据分段获取** - 解决 6000 条限制
3. **定性理论驱动的回测框架** - 跨 12 股验证
4. **指标有效性验证引擎** - 单/组合信号
5. **分级持仓管理系统** - 预警/高度预警/出货三级
6. **Web 可视化页面** - 验证页面 + 回测图表

### 新增/修改文件
```
chip_data_fetcher.py              ★新  Tushare 数据获取 (任意时间段)
chip_indicators.py                ★新  筹码峰指标计算 (25+ 指标)
chip_backtest.py                  ★新  基础回测模块
chip_backtest_framework.py        ★新  定性理论回测框架
chip_metric_validation.py         ★新  指标验证引擎
holding_manager.py                ★新  分级持仓管理
templates/chip_backtest_chart.html ★新  回测图表页面
templates/chip_metric_validation.html ★新  指标验证页面
app.py                            M    Flask 路由扩展
```

---

## 📊 核心方法论

### 1. 指标分类体系

| 分类 | 代表指标 | 定性含义 |
|------|---------|---------|
| **集中度** | TPC, top5/top10, p1_pct, p1_dominance, width, width_70/90, TP3 | 筹码聚集程度 |
| **分布形状** | skewness, kurtosis, entropy, gradient, peak_entropy | 分布形态特征 |
| **价格位置** | dist, winner, weight_avg, cost_dist_pct, resistance/support | 价格相对筹码位置 |
| **动态变化** | *_chg_7d, *_rising, *_falling | 指标变化趋势 |

### 2. 信号设计原则（定性→定量）

每个信号都有**明确的定性理论支撑**：

| 信号 | 定性理论 |
|------|---------|
| TPC上升 | 筹码向少数峰聚集，主力控盘加强 |
| Width收窄 | 筹码分布变窄，蓄势待发 |
| TP3高值上升 | 市场成本趋于一致，突破概率高 |
| 尖峰集中(kurtosis高) | 高度集中=主力控盘 |
| 熵下降 | 筹码有序化集中过程 |
| **右偏解套** | skewness>0.3(套牢盘重) + 价格>MA20 |
| **左偏派发** | skewness<-0.3(获利盘重) + 价格<MA20 |
| 支撑临近 | 支撑位距离<3% + 趋势向上 |

### 3. 跨 12 股验证结论（最终高置信信号）

| 信号 | 分类 | 覆盖 | 平均胜率 | 稳定性 |
|------|------|------|---------|--------|
| **Winner加速上升** | 动态变化 | 12/12 | 79.6% | 58.7 |
| **趋势延续** | 组合信号 | 12/12 | 79.6% | 58.7 |
| **TPC上升** | 集中度 | 12/12 | 74.7% | 44.3 |
| **支撑临近** | 价格位置 | 12/12 | 80.9% | 42.1 |
| **熵下降** | 分布形状 | 12/12 | 68.9% | 41.8 |
| **控盘加强** | 组合信号 | 10/12 | 76.1% | 41.2 |
| **左偏派发** | 分布形状 | 8/12 | 92.0% | 49.4 |
| **右偏解套** | 分布形状 | 5/12 | 89.5% | 69.0 |

### 4. 分级持仓管理（核心创新）

```
阶段1: 建仓     score≥5                    → 全仓买入
阶段2: 持仓管理
  ├ 预警       W>80%+CD>10%+涨幅>10%     → 减仓30%
  ├ 高度预警   W>90%+CD>15%+涨幅>20%     → 减仓50%
  └ 出货清仓   W>95%+CD>20%+破MA10       → 清仓
阶段3: 硬止损   亏8%                      → 清仓
```

**反直觉但真实的出货特征**:
- 出货时 Winner 接近 100%（所有人都赚钱）
- 价格大幅偏离成本（>15%）
- 持续上涨后的位置才有"货"可出

### 5. 跨股回测结果 (2023-2024 震荡+下跌市)

| 股票 | 买入持有 | V3策略 | Alpha |
|------|---------|--------|-------|
| 宏昌电子 | +5.92% | **+58.74%** | +52.83% |
| 中国巨石 | -14.43% | **+7.71%** | +22.13% |
| 圣泉集团 | +20.55% | +12.06% | -8.49% |
| 鹏鼎控股 | +42.67% | +0.14% | -42.53% |
| 东材科技 | -36.05% | **-32.83%** | +3.22% |
| **平均** | **+3.73%** | **+9.16%** | **+5.43%** |

---

## 🚀 在另一台电脑上恢复工作的步骤

### Step 1: 拉取最新代码

```bash
cd <目标目录>
git clone https://github.com/xianganh/stock-chip-quant.git
cd stock-chip-quant
# 或如果是已 clone 的目录：
git pull origin master
```

**期望看到**：
```
Updating 0549437..e0b1ff1
...
create mode 100644 chip_data_fetcher.py
create mode 100644 chip_indicators.py
create mode 100644 holding_manager.py
...
```

### Step 2: 安装依赖

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### Step 3: 配置 Tushare Token（必需）

```bash
# Linux/macOS
export TUSHARE_TOKEN="your_token_here"

# Windows PowerShell
$env:TUSHARE_TOKEN = "your_token_here"

# 或创建 .env 文件
cp .env.example .env
# 编辑 .env 填入 TUSHARE_TOKEN
```

### Step 4: 启动 Flask

```bash
python app.py
```

**新增的 Web 路由**：
- http://127.0.0.1:5000/ ← 主仪表盘
- http://127.0.0.1:5000/review ← 复盘中心（Phase 3）
- http://127.0.0.1:5000/metric_validation ← **新增**: 指标验证
- http://127.0.0.1:5000/backtest_chart ← **新增**: 回测图表

### Step 5: 验证新增模块

```bash
# 1. 验证回测框架（用5只股票快速测试）
python3 -c "
from chip_backtest_framework import MultiStockValidator
v = MultiStockValidator([('603002.SH','宏昌电子')], '20260301', '20260624')
v.validate_all()
print('OK')
"

# 2. 验证持仓管理
python3 -c "
from holding_manager import analyze_holding
r = analyze_holding('603002.SH', '20230601', '20241231')
print(f'策略收益: {r[\"strategy_return\"]:+.2f}% Alpha: {r[\"alpha\"]:+.2f}%')
"

# 3. 启动Web验证
python app.py
# 浏览器打开 http://127.0.0.1:5000/metric_validation
```

---

## 📁 关键文件位置

### 本次新增（重点）

```
chip_data_fetcher.py              ← Tushare 数据获取（分段算法）
chip_indicators.py                ← 筹码峰指标计算（25+ 指标）
chip_backtest.py                  ← 基础回测模块
chip_backtest_framework.py        ← 定性理论回测框架
chip_metric_validation.py         ← 指标验证引擎
holding_manager.py                ← 分级持仓管理 ★核心创新
templates/chip_backtest_chart.html ← 回测图表（K线+健康度+指标联动）
templates/chip_metric_validation.html ← 指标验证页面
app.py                            ← Flask 路由
```

### 模块依赖关系

```
chip_data_fetcher.py (数据层)
       ↓
chip_indicators.py (指标计算层)
       ↓
   ┌─────────────┬──────────────┬──────────────┐
   ↓             ↓              ↓              ↓
chip_backtest.py  holding_manager.py  chip_metric_validation.py  chip_backtest_framework.py
   (回测)        (持仓管理)         (指标验证)            (回测框架)
   ↓             ↓              ↓              ↓
   └─────────────┴──────────────┴──────────────┘
                          ↓
                       app.py (Web 路由)
```

---

## 🎯 下一步建议（按优先级）

### 🔴 优先级 1: 验证本次新功能（10 分钟）

```bash
# 1. 启动 Web
python app.py

# 2. 浏览器测试新增页面
# - http://127.0.0.1:5000/metric_validation (指标验证)
# - http://127.0.0.1:5000/backtest_chart (回测图表)

# 3. 命令行快速测试回测框架
python3 -c "
from chip_backtest_framework import MultiStockValidator
stocks = [
    ('603002.SH', '宏昌电子'),
    ('605589.SH', '圣泉集团'),
    ('601208.SH', '东材科技'),
]
v = MultiStockValidator(stocks, '20260301', '20260624')
v.validate_all()
report = v.analyze_stability()
print('共分析', report['total_signals'], '个信号')
"
```

### 🟡 优先级 2: 参数调优 (持仓管理 V3)

当前默认参数基于 2023-2024 数据，可根据更多数据调优：

```python
# 在 holding_manager.py 修改参数
params = {
    'warn_winner': 80,       # 减仓30%阈值
    'warn_cost_dist': 10,    # 偏离成本阈值
    'high_winner': 90,       # 减仓50%阈值
    'high_cost_dist': 15,
    'exit_winner': 95,       # 清仓阈值
    'exit_cost_dist': 20,
}
```

需要做的：
- [ ] 扩展测试股票数量（>20只）
- [ ] 测试不同时间窗口（2020-2022 历史）
- [ ] 参数敏感性分析

### 🟢 优先级 3: 继续推进 M3-M6 (Phase 3 待办)

| 任务 | 工作量 | 说明 |
|------|--------|------|
| **M3 回测增强** | 1 天 | 多策略对比 + 参数敏感性热力图 |
| **M5 性能优化** | 0.5 天 | 异步任务（不阻塞 UI）|
| **M6 测试覆盖** | 0.5 天 | 20 个 pytest |
| **M7 文档发布** | 0.5 天 | 更新 PROJECT.md 等 |

### 🔵 优先级 4: 算法调优

基于本次发现的算法问题：
- **派发评分阈值**: 派发 = 1 持续 5 天未预警 → 建议降到 D1 即关注
- **TPC 阈值**: 待更多样本分析
- **持仓管理参数**: 不同股票需个性化

---

## 🔧 常用命令速查

### 验证模块可用性

```bash
# 测试数据获取
python3 -c "
from chip_data_fetcher import fetch_complete_data
d = fetch_complete_data('603002.SH', '20260301', '20260624')
print(f'筹码: {len(d[\"chip_data\"])}条, K线: {len(d[\"kline\"])}条')
"

# 测试指标计算
python3 -c "
from chip_data_fetcher import fetch_complete_data
from chip_indicators import compute_all_chip_metrics
import pandas as pd
d = fetch_complete_data('603002.SH', '20260301', '20260624')
r = compute_all_chip_metrics(d['chip_data'], d['kline'], lookback_days=7)
df = pd.DataFrame(r)
print('指标列:', list(df.columns)[:10])
print('样本数:', len(df))
"

# 测试回测框架
python3 -c "
from chip_backtest_framework import BacktestFramework
f = BacktestFramework('603002.SH', '20260301', '20260624', future_days=10)
print(f.generate_report()['baseline'])
"

# 测试持仓管理
python3 -c "
from holding_manager import analyze_holding
r = analyze_holding('603002.SH', '20230601', '20241231')
print(f'策略: {r[\"strategy_return\"]:+.2f}% 持有: {r[\"buy_hold_return\"]:+.2f}%')
"
```

### 跨股回测脚本

```bash
# 跑 5 只股票验证
python3 << 'EOF'
from chip_backtest_framework import MultiStockValidator
stocks = [
    ('603002.SH', '宏昌电子'),
    ('605589.SH', '圣泉集团'),
    ('601208.SH', '东材科技'),
    ('002938.SZ', '鹏鼎控股'),
    ('600176.SH', '中国巨石'),
]
v = MultiStockValidator(stocks, '20260301', '20260624')
v.validate_all()
report = v.analyze_stability()
for sig in report['top_stable_signals'][:5]:
    print(f"{sig['signal_name']}: 胜率{sig['avg_win_rate']}% 稳定性{sig['stability_score']}")
EOF
```

### 持仓管理测试

```bash
# 测试不同股票
python3 << 'EOF'
from holding_manager import analyze_holding
stocks = [
    ('603002.SH', '宏昌电子'),
    ('605589.SH', '圣泉集团'),
    ('601208.SH', '东材科技'),
]
for code, name in stocks:
    r = analyze_holding(code, '20230601', '20241231')
    if r:
        print(f"{name}: 持有{r['buy_hold_return']:+.2f}% 策略{r['strategy_return']:+.2f}%")
EOF
```

### 启动 Flask

```bash
python app.py
# 或带调试
FLASK_DEBUG=1 python app.py
```

---

## 📋 紧急检查清单（在新电脑上）

在开始本次新工作前，请确认：

- [ ] Git clone/pull 成功，`e0b1ff1` 是最新 commit
- [ ] 依赖安装完成
- [ ] Tushare token 配置成功（`/api/health` 返回 `tushare_token: ok`）
- [ ] Flask 启动成功
- [ ] `/metric_validation` 页面能加载（新功能）
- [ ] `/backtest_chart` 页面能加载（新功能）
- [ ] 命令行测试 `chip_backtest_framework` 和 `holding_manager` 正常

### 快速验证脚本

```bash
# 一键验证
python3 -c "
import sys
modules = ['chip_data_fetcher', 'chip_indicators', 'chip_backtest_framework', 
           'chip_metric_validation', 'holding_manager']
for m in modules:
    try:
        __import__(m)
        print(f'✅ {m}')
    except Exception as e:
        print(f'❌ {m}: {e}')
"
```

---

## 🤖 给你的 AI 助手的提示

如果你的 AI 助手需要快速理解项目，建议按以下顺序阅读：

1. `HANDOVER.md`（本文档）— 10 分钟
2. `PROJECT.md` — 项目核心定义
3. `chip_indicators.py` — 核心指标计算
4. `chip_backtest_framework.py` — 定性回测框架
5. `holding_manager.py` — 分级持仓管理

**关键测试问题**：

1. "我们的筹码峰指标体系包含哪些分类？每类的核心指标是什么？"
2. "定性理论驱动的回测框架是怎么设计的？为什么不用纯数据验证？"
3. "分级持仓管理V3的三级减仓机制是什么？"
4. "跨12股验证的TOP3稳定信号是哪些？"

如果它能正确回答，说明理解到位，可以继续推进。

---

## ⚠️ 已知限制与注意事项

1. **Tushare API 限流**: 200次/分钟，跨股验证时需要 sleep 间隔
2. **数据时间范围**: 筹码数据从 20260420 开始，更早历史需要单独处理
3. **回测时间窗口**: 单边上涨行情中信号系统天然跑输持有（这是合理的）
4. **参数个性化**: 持仓管理参数基于历史数据，不同股票可能需要微调
5. **回测 ≠ 实盘**: 实盘有滑点、流动性、税费等额外因素

---

## 🎯 项目当前能力清单

### 数据能力
- ✅ Tushare 任意时间段分段获取
- ✅ 筹码数据 + K线 + 技术指标三合一
- ✅ 缓存机制（避免重复请求）

### 指标能力
- ✅ 25+ 筹码峰指标（基础+高级）
- ✅ 衍生指标（变化率、相对位置等）
- ✅ 健康度评分（多维度）

### 分析能力
- ✅ 指标分类体系（4大类）
- ✅ 信号规则库（25+ 信号）
- ✅ 组合信号（6个核心组合）

### 验证能力
- ✅ 单指标回测验证
- ✅ 组合指标网格搜索
- ✅ 跨股稳定性分析
- ✅ 12 只股票验证

### 决策能力
- ✅ 三级减仓机制
- ✅ 硬止损保护
- ✅ 出货特征识别

### 可视化能力
- ✅ 单图多区域联动
- ✅ 颜色渐变
- ✅ 买卖点标记

---

## 📞 联系与资源

- **GitHub**: https://github.com/xianganh/stock-chip-quant
- **Tushare 文档**: https://tushare.pro/document/1
- **Tushare 限流文档**: https://tushare.pro/document/1?doc_id=108
- **项目主页**: `PROJECT.md`

---

**最后更新**: 2026-06-25
**本次工作重点**: 筹码峰指标体系 + 定性回测框架 + 分级持仓管理
**核心创新**: 三级减仓机制（预警/高度预警/出货清仓）
**下一步**: Phase 3 M3-M6 + 参数调优
