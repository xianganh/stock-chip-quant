# 04. 核心算法

> 文件位置: [scripts/analyze.py](../../scripts/analyze.py)（同步副本: [analyze.py](../../analyze.py)）
> 当前版本: **v2.5**（含时间-认知背离 v2.3）

## 🎯 设计目标

**给定一只股票和截止日期，回答 6 个问题：**

1. **结构是否健康？** → 锁仓评估 / 派发评分
2. **主力是否还在？** → emoji 行为标注（建仓/锁仓/震仓/推升/派发）
3. **有没有出货嫌疑？** → 5 维派发评分
4. **买卖点建议？** → 综合判定卡片（持有/减仓/清仓/观望）
5. **关键支撑阻力位？** → 形态分类 + 阻力支撑识别
6. **该继续持有还是该卖？** → 综合判定（utils.compute_verdict）

## 🏭 8 大引擎

```
analyze.py (v2.5)
├── 引擎①: compute_chip_metrics()         ← 筹码峰单日指标 (v2.1)
├── 引擎②: judge_emoji()                   ← 行为 emoji 标注 (v5.6.6)
├── 引擎③: assess_locking()                ← 6 条件锁仓判定 (v5.6.6)
├── 引擎④: dispatch_score()                ← 5 维派发评分 (v5.6.6)
├── 引擎⑤: score_tech()                    ← 技术面 3 策略打分
├── 引擎⑥: compute_cmf/adx/atr()           ← 经典量化辅助指标 (v2.2)
├── 引擎⑦: build_chip_percentile_context()← 滚动分位数归一化 (v2.2)
└── 引擎⑧: detect_divergence()             ← 4 类背离检测 (v2.3)
```

---

## 引擎①: 筹码峰单日指标 `compute_chip_metrics()`

**位置**: [analyze.py:259-452](../../scripts/analyze.py#L259-L452)

**输入**: `df_cyq` (单日 cyq_chips 数据), `close` (收盘价)

**输出**: 包含 40+ 字段的 dict

### 核心指标

| 指标 | 计算公式 | 含义 |
|------|---------|------|
| **p1, p1_pct** | 局部极大值最高峰 | 主峰位 + 占比 |
| **p2, p2_pct** | 局部极大值第 2 高峰 | 次峰位 + 占比 |
| **p3, p3_pct** | 局部极大值第 3 高峰 | 三峰位 + 占比 |
| **tpc** | p1_pct + p2_pct + p3_pct | 三峰总集中度 |
| **top5 / top10** | 按 percent 排序前 5/10 求和 | 5/10 档集中度 |
| **width** | (max(P1,P2,P3) - min) / min × 100 | 三峰价格宽度 |
| **dist** | (close - P1) / P1 × 100 | 价格相对 P1 的偏离 |
| **tp3** | close ±3% 区间筹码占比 | 当前价附近密集度 |
| **winner** | close 以下所有筹码之和 | 获利盘比例 |
| **median_price** | cumsum 50% 处价格 | 中位成本价 |
| **skewness** | 加权偏度（Fisher-Pearson） | 分布对称性 |
| **kurtosis** | 加权超额峰度 | 分布尖锐度 |
| **gradient** | 相邻筹码占比平均变化率 | 筹码断层程度 |
| **entropy** | 信息熵 (bits) | 分布分散程度 |
| **width_70/90** | 包含 70%/90% 筹码的最窄宽度 | 集中宽度 |
| **p1_dominance** | p1_pct / tpc | P1 支配度 |
| **peak_entropy** | 三峰信息熵 | 三峰均匀度 |

### 关键子函数

#### `_detect_local_peaks(prices, percents, min_height=0.5, min_distance=0.02)`

局部极大值峰值检测（不依赖 scipy）：
1. **找原始峰**: 每个点的左右 2 邻居都严格小于该点
2. **合并过近峰**: 相对距离 < 2% 时保留更高的

#### `_classify_morphology(peak_info, tpc, width)`

形态分类（基于峰数量 + TPC + 宽度）：

| 峰数 | 条件 | 形态 |
|------|------|------|
| 0 | — | 无峰(极度分散) |
| 1 | TPC > 15 | 单峰密集 |
| 1 | TPC ≤ 15 | 单峰(弱) |
| 2 | gap < 5% | 双峰密集(窄) |
| 2 | gap < 15% | 双峰对峙 |
| 2 | gap ≥ 15% | 双峰发散(宽) |
| 3 | 高度均匀 | 三峰均衡 |
| 3 | 主峰突出 | 三峰(主峰突出) |
| 3 | 其他 | 三峰分布 |
| ≥4 | — | 多峰发散 |

#### `_compute_weighted_skewness` / `_compute_weighted_kurtosis`

加权偏度/峰度（Fisher-Pearson 标准化矩系数）：
```python
mu = np.average(prices, weights=percents)
sigma = sqrt(np.average((prices - mu)**2, weights=percents))
skewness = np.average((prices - mu)**3, weights=percents) / sigma**3
```

---

## 引擎②: 行为 Emoji 标注 `judge_emoji()`

**位置**: [analyze.py:459-505](../../scripts/analyze.py#L459-L505)

**逻辑**: 基于 ΔP1 + ΔTop5 + ΔWinner 等指标的双向判定

| Emoji | 行为 | 触发条件 |
|-------|------|---------|
| 🔴 | 派发 | ΔP1 < -2 且 ΔTop5 < -3 |
| ⚠️ | 预警 | ΔTop5 < -10 |
| 🏗️ | 建仓 | ΔP1 > 2 且 ΔTop5 > 3 |
| 🔒 | 锁仓 | \|ΔP1\| < 0.5 且 ΔTop5 > 1 |
| 🌊 | 震仓 | \|ΔP1\| < 0.5 且 ΔTop5 < -1 |
| 📈 | 推升 | ΔP1 > 1 且 \|ΔTop5\| < 2 |
| 📈 | 推升(弱) | ΔP1 > 0.5 |
| 🌊 | 震仓(弱) | ΔP1 < -0.5 |
| 🔒 | 锁仓(弱) | 无明显行为 |

---

## 引擎③: 6 条件锁仓判定 `assess_locking()`

**位置**: [analyze.py:512-627](../../scripts/analyze.py#L512-L627)

**6 项条件**（每项评估为 True/False）：

| # | 条件 | 阈值 | 含义 |
|---|------|------|------|
| ① | P1 稳定性 | 最近 5 日 P1 range/avg < 1% | 峰位不动 |
| ② | tp3 提升 | 最新 tp3 > 5 日前 | 当前价附近密集 |
| ③ | dist 转正 | 最新 dist > 0 | 主力浮盈 |
| ④ | Top5 趋势 | Top5 delta > 0 | 集中度抬升 |
| ⑤ | Winner 趋势 | 近 5 日均值 > 前 5 日 | 获利盘增加 |
| ⑥ | TPC 趋势 | TPC delta > 0 | 三峰总占比抬升 |

**综合判定**：
- ≥ 5/6 条件 → 强锁仓
- ≥ 4/6 → 中等锁仓
- ≥ 3/6 → 弱锁仓
- < 3/6 → 未锁仓

**输出**:
```python
{
    "p1": {"status": "✅/❌", "stab_pct": ..., "verdict": "..."},
    "tp3": {"status": "✅/❌", "current": ..., "delta": ..., "verdict": "..."},
    ...
    "overall": "强锁仓 (5/6)",
    "locked_score": "5/6"
}
```

---

## 引擎④: 5 维派发评分 `dispatch_score()`

**位置**: [analyze.py:634-698](../../scripts/analyze.py#L634-L698)

**5 项检查**（每项 0 或 1 分）：

| # | 检查 | 阈值 | 含义 |
|---|------|------|------|
| D1 | P1 占比与价格反向 | 5日跌幅 < -7% 且后半段 P1 占比比前半段高 30% | 价格跌但筹码集中 |
| D2 | 加权成本与价格反向 | 价格上涨 ≥ 5% 但成本涨 < 2% | 拉升但成本未动 |
| D3 | Top5 两阶段对比 | 前半段 ≥ 35% 且后半段 ≤ 前半段 × 0.7 | 集中度从高到低 |
| D4 | 连续 3 日 close < 加权成本 | ≥ 3/3 日 | 价格跌破成本 |
| D5 | 内部人动作 | 暂未量化 | 预留 |

**综合判定**：
- ≥ 4/5 → 派发（清仓）
- = 3/5 → 警惕（减仓 1/3）
- ≤ 2/5 → 健康（按计划持有/建仓）

---

## 引擎⑤: 技术面 3 策略打分 `score_tech()`

**位置**: [analyze.py:705-813](../../scripts/analyze.py#L705-L813)

### 动量策略（权重 0.35）
基于 RSI_6 + KDJ_J：
| RSI_6 区间 | 评分 | 标签 |
|-----------|------|------|
| 40-60 | 4 | RSI 中性偏强 |
| 60-75 | 5 | RSI 偏强 |
| ≥ 75 | 2 | RSI 超买→扣分 |
| < 40 | 2 | RSI 偏弱 |

KDJ_J > 100 或 < 0 时再扣 1 分（最低 1）。

### 趋势策略（权重 0.40）
基于 MACD + BOLL：
| MACD 状态 | 评分 | 标签 |
|----------|------|------|
| DIF > DEA 且 MACD > 0 | 5 | MACD 多头 |
| DIF > DEA 但 MACD < 0 | 4 | MACD 金叉待放 |
| 其他 | 2 | MACD 空头 |

BOLL 位置 > 90% 或 < 15% 时扣 1 分。

### 反转策略（权重 0.25）
触发条件（任一满足）：
- 价格顶背离（价峰不在同一根 K 线）
- KDJ_J > 90
- RSI_6 > 70
- CCI > 200

### 加权综合

```python
weighted = momentum_score * 0.35 + trend_score * 0.40 + reversal_score * 0.25
```

**反对票**（超买/超卖警告）：KDJ_J > 80、RSI_6 > 65、BOLL > 85%、MACD 空头、CCI > 150

---

## 引擎⑥: 经典量化指标

### CMF (蔡金资金流) `compute_cmf()`

```python
mfm = ((close - low) - (high - close)) / (high - low)  # Money Flow Multiplier
mfv = mfm * volume                                       # Money Flow Volume
cmf = sum(mfv[period]) / sum(volume[period])            # 21 日滚动
```

**取值范围**: [-1, +1]
- 正值 → 资金流入（吸筹/推升）
- 负值 → 资金流出（出货/打压）

### ADX (平均趋向指数) `compute_adx()`

**计算步骤**:
1. **True Range** = max(high-low, |high-prev_close|, |low-prev_close|)
2. **+DM** = max(high - prev_high, 0) 当 up_move > down_move
3. **-DM** = max(prev_low - low, 0) 当 down_move > up_move
4. **Wilder 平滑** (类似 EMA)
5. **+DI** = 100 × +DM_smoothed / TR_smoothed
6. **-DI** = 100 × -DM_smoothed / TR_smoothed
7. **DX** = 100 × |+DI - -DI| / (+DI + -DI)
8. **ADX** = Wilder 平滑 DX

**判读**:
- ADX > 25 → 趋势市
- ADX < 20 → 震荡市
- +DI > -DI → 多头主导，反之空头

### ATR (平均真实波幅) `compute_atr()`

```python
tr = max(high - low, |high - prev_close|, |low - prev_close|)
atr[period-1] = mean(tr[:period])
atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period  # Wilder 平滑
```

**atr_pct_of_price** = ATR / close × 100（用于自适应阈值）

---

## 引擎⑦: 滚动分位数归一化 `build_chip_percentile_context()`

**位置**: [analyze.py:949-1048](../../scripts/analyze.py#L949-L1048)

**目的**: 消除硬编码阈值，**跨股票可比**

**算法**:
```python
def compute_rolling_percentile(series, window=60, min_periods=20):
    ranks = []
    for i in range(len(series)):
        lookback = series[max(0, i - window + 1):i+1]
        ranks.append(searchsorted(sort(lookback), series[i]) / len(lookback) * 100)
    return ranks
```

**21 个指标** 全部计算滚动分位（最近 60 日）：
tpc, top3, top5, top10, p1_pct, p2_pct, p3_pct, width, width_70, width_90, dist, tp3, gap_pct, winner, weight_avg, skewness, kurtosis, gradient, entropy, p1_dominance, peak_entropy

**分位水平标签**:
- ≥ 85% → 极高
- 70-85% → 偏高
- 30-70% → 中等
- 15-30% → 偏低
- < 15% → 极低

**Z-score 标准化**（用于跨股票比较）:
```python
z = (latest - mean) / std
```

---

## 引擎⑧: 4 类背离检测 `detect_divergence()`

**位置**: [analyze.py:1055-1366](../../scripts/analyze.py#L1055-L1366)

**权重配置**:
- 价格-筹码背离: 35%
- 资金-价格背离: 30%
- 形态-认知背离: 20%
- 时间-认知背离: 15%

### 背离①: 价格-筹码背离（暗中建仓）
**条件**: 价格弱势 + 筹码暗中集中
- **价格弱**: |pct_change| < weak_threshold（ATR 自适应）
- **筹码紧**: TPC > 60分位 且 entropy < 50分位 且 width_90 < 50分位
- **强信号**: 价格跌 + TPC > 75分位 + entropy < 35分位 + width_90 < 35分位

**5 日回看**: T-5~T-3 时 P1 占比已显著增加 + entropy 显著降低

### 背离②: 资金-价格背离（压盘吸筹）
**条件**: CMF 持续流入 + 价格不涨
- **资金流入**: CMF > 0.05
- **价格横盘**: 5 日涨跌幅 < weak_threshold × 5
- **强信号**: CMF > 0.1 且价格下跌

**5 日回看**: 近 5 日 CMF > 0 占比 > 60%

### 背离③: 形态-认知背离（表散实聚）
**条件**: 表面多峰发散 + 实际 P1 暗中增强
- **表面发散**: n_peaks ≥ 3
- **核心集中**: P1 占比上升 + P1 支配度 > 60分位
- **强信号**: P1 支配度 > 75分位 + P1 价格上移

### 背离④: 时间-认知背离（筹码领先价格）⭐ 新增
**条件**: 5-3 天前筹码已高度集中 + 价格至今未反应
- **筹码已紧**: mid TPC > hist TPC × 1.3 且 mid entropy < hist entropy × 0.7
- **价格未反应**: 3-5 日涨幅 < weak_threshold × 3

**意义**: 主力布局已完成，只差催化 → 最有操作价值

### 综合判定

```python
total_score = d1 * 0.35 + d2 * 0.30 + d3 * 0.20 + d4 * 0.15

if strong_count >= 3: verdict = "极强背离"
elif strong_count >= 2: verdict = "强背离"
elif strong_count == 1 or active_count >= 3: verdict = "中等背离"
elif active_count >= 1: verdict = f"弱背离({active_count}类)"
else: verdict = "无背离"
```

---

## 主流程 `analyze()`

**位置**: [analyze.py:1507-1839](../../scripts/analyze.py#L1507-L1839)

### 数据采集（步骤 1-5）

```python
# 1. cyq_chips (全量历史)
df_chips = pro.cyq_chips(ts_code=ts_code, fields='ts_code,trade_date,price,percent')

# 2. stk_factor (K线+技术指标)
df_factor = pro.stk_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)

# 3. moneyflow
df_mf = pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)

# 4. daily_basic
df_basic = pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)

# 5. merge (按 ts_code + trade_date)
df_merged = df_factor.merge(df_mf).merge(df_basic)
```

### 指标计算（步骤 6-7）

```python
# 6. 确定分析窗口 (默认 14 日)
recent_dates = all_chip_dates[-days:]

# 7. 逐日计算筹码指标
for td in chip_dates:
    chip_today = df_chips[df_chips['trade_date'] == td]
    close = df_merged[td]['close']
    m = compute_chip_metrics(chip_today, close)
    # 只对窗口内做 emoji 标注
    if td in recent_set:
        emoji, behavior, reason = judge_emoji(prev_metrics, m)
        m['emoji'] = emoji
```

### 8 大引擎串联（步骤 8-13）

```python
# 8. 经典量化指标
classic_indicators = {cmf, adx, atr}

# 9. 滚动分位数归一化
pct_context = build_chip_percentile_context(all_metrics, metrics_list)

# 10. 锁仓判定
locking = assess_locking(metrics_list)

# 11. 派发评分
dispatch = dispatch_score(metrics_list)

# 12. 技术面打分
tech = score_tech(df_factor)

# 13. 4 类背离检测
divergence = detect_divergence(metrics_list, pct_context, classic_indicators)
```

### 结果组装（步骤 14）

最终输出包含以下 key：

| Key | 内容 |
|-----|------|
| `meta` | ts_code / trade_days / date_range / generated_at |
| `price_summary` | latest_close / period_high / period_low / period_pct |
| `indicators_snapshot` | 最近 3 日技术指标快照 |
| `chip_evolution` | daily_records / locking_assessment / dispatch_score / trends |
| `chip_morphology` | latest / history_summary / sequence / support_resistance |
| `distribution_statistics` | latest + period_stats |
| `classic_indicators` | CMF / ADX / ATR |
| `chip_factor_ranks` | 滚动分位数 + Z-score |
| `divergence_signals` | 4 类背离 + total_score |
| `narrative` | 故事链叙事（阶段 + 拐点 + 关键变化） |
| `tech_analysis` | momentum / trend / reversal / weighted |

---

## 🎯 综合判定 `utils.compute_verdict()`

**位置**: [utils.py:154-251](../../utils.py#L154-L251)

**输入**: `analyze()` 返回的完整 dict

**输出**:
```python
{
    "action": "持有" | "减仓" | "清仓" | "观望",
    "confidence": 0-100,
    "color": "green" | "yellow" | "red" | "gray",
    "reasons": [...],
    "scores": {
        "lock": (passed, total),
        "dispatch": int,
        "divergence_strong": int,
        "divergence_active": int,
        "tpc": float,
        "morphology": str,
    }
}
```

### 判定规则（按优先级）

| 优先级 | 条件 | 动作 | 信心度 |
|--------|------|------|--------|
| 1 | dispatch_total >= 4 | 清仓 | 85% |
| 2 | lock_passed >= 5 | 持有 | 80% |
| 3 | lock_passed >= 3 且 div_strong >= 1 | 持有 | 60% |
| 4 | lock_passed < 3 且 dispatch_total >= 2 | 减仓 | 65% |
| 5 | 其他 | 观望 | 50% |

---

## 🧬 算法演进历史

| 版本 | 特性 | 文件 |
|------|------|------|
| v1.0 | 基础 P1/P2/P3 + TPC | analyze.py |
| v2.0 | 局部极大值检测 + 形态分类 | analyze.py |
| v2.1 | 中位成本价 + 阻力支撑 | analyze.py |
| v2.2 | 经典量化指标 + 滚动分位数 | analyze.py |
| v2.3 | 3 类背离检测（价格/资金/形态） | analyze.py |
| v2.4 | 故事链叙事 | analyze.py |
| **v2.5** | **+ 时间-认知背离** | analyze.py |

---

## 🐛 已修复 Bug（v2.5 前）

来自 8 个 review bug 修复：

1. **median_price 计算错误**: 改用 cumsum 找 50% 处价格（按价格升序）
2. **peak_triplets 不对称**: 局部极大值左右邻居严格度统一（`>` vs `>=`）
3. **命名错误**: `prev_half_*` 实际是前后半窗口均值，不是 5 日
4. **信号缓存未清空**: Evolution 引擎多轮搜索时无限增长
5. **大盘基线重复**: 在 evo 循环内每次都重新计算
6. **快照元数据查询**: 用 defer 避免加载 full_data 大字段
7. **LLM 响应解析**: 增加非 JSON 响应处理
8. **API 错误堆栈泄露**: debug 模式才附带堆栈