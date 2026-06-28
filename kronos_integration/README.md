# Kronos × 筹码峰演化分析 — 集成说明

## ❓ 需要完全 clone Kronos 仓库吗？

**不需要！** 有三种集成方式，按从轻到重：

| 方式 | 需要 clone | 磁盘占用 | 能力 | 推荐阶段 |
|------|-----------|---------|------|---------|
| **A. 纯 HuggingFace Hub 加载** | ❌ 不需要 | ~50MB-500MB（模型权重自动缓存） | 推理 + 融合 | ✅ **当前 MVP** |
| **B. 克隆 Kronos 但只安装依赖** | ✅ 完整 clone (~100MB) | ~100MB + 模型 | 推理 + 自定义 tokenizer | 阶段2：筹码扩展 tokenizer |
| **C. 完整开发环境 + 训练数据** | ✅ clone + 下载数据集 | 几十GB | 预训练/微调/A股适应 | 阶段3：LoRA微调 |

---

## 🚀 方式A：当前最轻量方案（5分钟可用）

**安装**（只装运行时依赖，不 clone Kronos）:

```bash
cd /home/xiangan/stocks/stock-chip-quant

# 最小依赖（HuggingFace自动下载模型权重，不需要本地 clone Kronos）
pip install torch transformers pandas numpy scipy --break-system-packages
```

**运行自测**：

```bash
# 1) Kronos 融合器单元测试（不依赖Tushare，纯逻辑验证）
python -m kronos_integration

# 2) 宏昌电子 完整对比回测（需要 Tushare token，会拉取筹码数据）
python -m kronos_integration.backtest_adapter
```

⚠️ **避坑提醒**：PyPI 上 `pip install kronos-pipeliner` 安装的是另一个**基因测序工作流项目**，跟金融 K 线模型完全无关！不要装那个。我们用的 Kronos 权重全部来自 HuggingFace Hub 上的 `NeoQuasar/Kronos-*`。

---

## 🔗 如何与筹码峰演化分析结合？（三层架构）

```
你的筹码峰演化系统          Kronos 金融基础模型              融合输出
─────────────────          ────────────────────            ──────────

  ┌──────────────┐          ┌────────────────────┐
  │ 筹码原始数据  │          │ OHLCV → Kronos     │
  │ cyq_chips    │───┐      │ Tokenizer 编码     │
  └──────────────┘   │      └────────┬───────────┘
  ┌──────────────┐   │               │
  │ 23+项指标     │   │               ▼
  │ TPC/Width    │───┤      ┌────────────────────┐
  │ TP3/Winner   │   │      │ 自回归Transformer  │
  │ Skewness     │   │      │ 5路径概率采样      │
  │ Gradient...  │   │      └────────┬───────────┘
  └──────┬───────┘   │               │
         │           │               ▼
         ▼           │      ┌────────────────────┐
  ┌──────────────┐   │      │ P(涨) ± 置信区间    │
  │ 健康度评分   │   │      │ mean_return ±std   │
  │ Score(-4~9)  │◀──┘      │ 路径分歧度 path_std│
  └──────┬───────┘          └────────┬───────────┘
         │ L2-信号层: 贝叶斯融合      │
         ▼                           ▼
  ╔══════════════════════════════════════════════╗
  ║          加权赔率融合器 SignalFuser           ║
  ║                                              ║
  ║  O(涨|C,K) ∝ O(涨)^0.00                      ║  ← 先验权重
  ║            × O(涨|筹码Score)^0.70            ║  ← 你的核心（70%）
  ║            × O(涨|Kronos) ^0.30 × 分歧惩罚   ║  ← AI辅助（30%）
  ╚═══════════════════╤══════════════════════════╝
                      │
                      ▼ 0~100 置信度 + 5档信号
         ┌───────────────────────────────┐
         │ ★ STRONG_BUY  置信度 ≥ 80%    │
         │ ☆ BUY         置信度 ≥ 68%    │
         │ ━ HOLD        45% ≤ x < 68%   │
         │ ◆ REDUCE      30% ≤ x < 45%   │
         │ ▼ SELL        置信度 < 30%    │
         └───────────────┬───────────────┘
                         │ L3-决策层
                         ▼
          ┌────────────────────────────────┐
          │  EvolutionEngine 参数进化       │
          │  - 搜索最优融合权重 (α=0.7?)    │
          │  - 搜索买入/卖出阈值            │
          │  - 跨12只股票鲁棒性验证          │
          └────────────────────────────────┘
```

---

## 📁 关键文件说明

```
kronos_integration/
├── __init__.py              ← KronosChipFuser 三层融合核心（贝叶斯算法）
├── backtest_adapter.py      ← 嵌入你现有回测管线的适配器（对比纯筹码 vs 融合）
└── README.md                ← 你正在看的这个文件
```

**`KronosChipFuser` 类**（`__init__.py`）提供三个关键方法：

| 方法 | 层级 | 作用 |
|------|------|------|
| `kronos_predict(df_ohlcv)` | L1 输入层 | 把历史K线送进Kronos，输出5条预测路径+统计量 |
| `bayesian_fusion(chip_score, kronos_result)` | L2 信号层 | **核心算法**：加权赔率融合，返回 0-100 置信度+5档信号 |
| `evolve_weights(backtest_results)` | L3 决策层 | 基于历史回测，自动搜索最优 chip/kronos 权重 |

**`KronosChipBacktestAdapter` 类**（`backtest_adapter.py`）：

| 方法 | 作用 |
|------|------|
| `prepare(start, end)` | 复用你的 `chip_data_fetcher` + `chip_indicators` 拉取并计算所有指标 |
| `run_comparison()` | 逐交易日跑两种策略，对比纯筹码 vs 融合的收益/胜率/交易次数 |
| `register_signal_to_evolution_engine()` | 把融合信号转成你的 `EvolutionEngine` 支持的 signal_type，继续做参数进化 |

---

## 🎯 典型工作流示例

### 示例1：日常个股快速诊断

```python
from kronos_integration import KronosChipFuser
from chip_data_fetcher import fetch_complete_data
from chip_indicators import compute_chip_metrics, analyze_chip_health

fuser = KronosChipFuser()  # 默认 Kronos-mini + 70%筹码权重

# 拉取宏昌电子近60天
data = fetch_complete_data("603002.SH", "20260401", "20260624")
latest_date = sorted(data.keys())[-1]
day = data[latest_date]

metrics = compute_chip_metrics(day["chip_df"], day["daily"]["close"])
health = analyze_chip_health(metrics, prev_metrics=None)  # 实际给prev的
chip_score = health["score"]

k_res = fuser.kronos_predict(kline_df)
final = fuser.bayesian_fusion(chip_score, k_res)

print(f"今天({latest_date}) {final['signal']}，融合置信度 {final['fused_score']}%")
```

### 示例2：批量回测 12 只股票，验证融合是否稳定增强

```python
from kronos_integration.backtest_adapter import KronosChipBacktestAdapter

STOCKS = ["603002.SH", "000066.SZ", "600176.SH", ...]  # 你的12只
excess_returns = []

for code in STOCKS:
    adapter = KronosChipBacktestAdapter(code)
    res = adapter.run_comparison("20260302", "20260624")
    excess_returns.append(res["excess_return"])
    print(f"{code}: 纯筹码 {res['chip_only']['total_return']:+.1f}% → "
          f"融合 {res['fused']['total_return']:+.1f}%  超额 {res['excess_return']:+.1f}%")

avg_excess = np.mean(excess_returns)
print(f"\n12只股平均超额收益: {avg_excess:+.2f}%  "
      f"{'✅ Kronos有效增强' if avg_excess > 0 else '⚠️ 建议降低Kronos权重'}")
```

### 示例3：用 EvolutionEngine 优化融合权重

```python
from engine.evolution_engine import EvolutionEngine

# 我们已经把 kronos_fused_buy/sell 列加进 df 了
# 你可以直接在 EvolutionEngine 里新增一个 signal_type
evo = EvolutionEngine("603002.SH", "20260302", "20260624")

# 搜索 Kronos 权重 0.0 → 0.5，买入阈值 60~90
best = evo.evolve(
    signal_type="kronos_fused",
    param_grid={
        "kronos_weight": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        "buy_threshold": [60, 65, 68, 72, 75, 80],
        "sell_threshold": [25, 30, 35, 40],
    },
    metric="sharpe",
)
print("最优参数:", best["best_params"])
```

---

## 🔄 升级路径（什么时候需要 clone Kronos）

### ✅ 现在：方式A 足够

- 只用 Kronos 推理能力
- 不修改 tokenizer / 不训练
- 模型会自动缓存在 `~/.cache/huggingface/`

### 📌 阶段2（筹码扩展 Tokenizer 时）→ 需要 clone

想实现"23项筹码指标 编码成 Kronos token 通道"时：
```bash
cd /home/xiangan/stocks/
git clone https://github.com/shiyu-coder/Kronos.git
cd Kronos && pip install -r requirements.txt

# 然后修改 Kronos/model/tokenizer.py，在 OHLCV 5维基础上
# 追加 TPC/Width/TP3/Winner/Skewness/Gradient 等23维输入
```

### 📌 阶段3（A 股 LoRA 微调时）→ 需要 clone + 数据

下载近3年A股数据（~10GB），用 LoRA 微调 Kronos-small：
- 单卡 3090 24GB 可跑
- 如果没有 GPU，租 AutoDL，约 2 元/小时，微调 100epoch 约 50 元

---

## 🎯 融合权重的默认设置为什么是 70% 筹码 + 30% Kronos？

这是基于你现有数据和 Kronos 论文基准的保守设置：

| 信号来源 | 历史命中率 | 默认权重 | 逻辑 |
|---------|-----------|---------|------|
| **你的筹码健康度** | **77.8%** (宏昌电子 bullish ≥7) | 70% | 核心能力，有实盘验证 |
| **Kronos 10日方向** | ~65% (论文报告基准) | 30% | 辅助作用，用于过滤假信号 |
| 路径分歧惩罚 | - | - | 当 path_std > 8%，Kronos 权重再打 5 折 |

**使用建议**：先跑 12 只你的已验证股票，如果超额收益 < 0，就把 Kronos 权重降到 15% 或直接 0%（降级只用筹码），等后续 A 股微调后再启用。

---

## ❓ FAQ

**Q1: 模型加载慢吗？**
A: Kronos-mini 4.1M 参数，CPU 上加载 <5 秒，推理一只股票 500 天数据 <100ms。第一次运行会自动从 HuggingFace 下载权重（50MB 左右）。

**Q2: 没有 GPU 能用吗？**
A: 完全可以！Kronos-mini/small CPU 推理完全够用。只有做 LoRA 微调时才需要 GPU。

**Q3: 如果 HuggingFace 连不上怎么办？**
A: 两种办法：
   1. 用镜像：`export HF_ENDPOINT=https://hf-mirror.com`
   2. 方式B：clone Kronos 仓库后本地加载

**Q4: 跟你的持仓管理器 `holding_v3` 兼容吗？**
A: 完全兼容！把 `holding_v3` 里的 `row['score'] >= 5` 判断替换为 `fused_score >= 68` 即可，其余三级减仓逻辑（Winner/成本偏离/破MA）保持不变。
