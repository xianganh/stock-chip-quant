"""
Kronos 轻量级集成适配器 — 无需完整 clone 仓库
直接从 HuggingFace 加载预训练权重，与筹码峰演化分析深度结合

安装方式（最小依赖，无需 git clone Kronos）:
    pip install torch transformers pandas numpy --break-system-packages

注：PyPI 上的 kronos-pipeliner 是另一个基因分析项目，不要装那个！
"""
import os
import sys
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple

_sys_path_fix = os.path.join(os.path.dirname(__file__), "..")
if _sys_path_fix not in sys.path:
    sys.path.insert(0, _sys_path_fix)


class KronosChipFuser:
    """
    Kronos AI 预测 + 筹码峰演化分析 三层融合器

    三层架构:
    ┌─────────────────────────────────────────────┐
    │  L1 输入层：K线 + 筹码指标 联合编码          │
    │    (OHLCV → Kronos tokenizer)                │
    │    + (23项筹码指标 → 扩展embedding通道)      │
    └──────────────────┬──────────────────────────┘
                       ▼
    ┌─────────────────────────────────────────────┐
    │  L2 信号层：双信号贝叶斯融合                 │
    │    Kronos 概率预测 P(涨)    ~65% 基准       │
    │    筹码健康度评分 Score     ~77.8% 实测     │
    │    → 融合置信度 FusedScore  目标≥85%        │
    └──────────────────┬──────────────────────────┘
                       ▼
    ┌─────────────────────────────────────────────┐
    │  L3 决策层：演化引擎 + 不确定性过滤          │
    │    EvolutionEngine 搜索最优参数网格          │
    │    Kronos 5路径采样 → 分歧过滤（路径差>阈值则放弃）│
    └─────────────────────────────────────────────┘
    """

    def __init__(self, model_name: str = "NeoQuasar/Kronos-small",
                 device: str = "cpu",
                 chip_weight: float = 0.70,
                 kronos_weight: float = 0.30):
        """
        初始化融合器

        Args:
            model_name: HuggingFace 上的 Kronos 模型名
                        - "NeoQuasar/Kronos-mini"   4.1M 参数，CPU也快
                        - "NeoQuasar/Kronos-small" 24.7M 参数，平衡版（推荐）
                        - "NeoQuasar/Kronos-base"  102.3M 参数，精度更高
            device: "cpu" | "cuda:0"
            chip_weight: 筹码健康度在融合中的权重（默认70%，你的核心能力）
            kronos_weight: Kronos AI 预测在融合中的权重（默认30%，辅助增强）
        """
        self.model_name = model_name
        self.device = device
        self.chip_weight = chip_weight
        self.kronos_weight = kronos_weight

        # 延迟加载：第一次真正用的时候才加载模型，避免启动慢
        self._tokenizer = None
        self._model = None
        self._predictor = None
        self._loaded = False

    # ------------------------------------------------------------------
    # 懒加载模型（避免 import 时就占内存）
    # ------------------------------------------------------------------
    def _ensure_loaded(self):
        if self._loaded:
            return
        # 已经尝试过加载且失败了 → 静默降级，不再重复打印
        if hasattr(self, '_attempted_load') and self._attempted_load:
            return
        self._attempted_load = True
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError:
            print(f"[KronosFuser] 警告：未安装 transformers 库")
            print("[KronosFuser] 将降级为仅使用筹码健康度模式（降级模式）")
            self._loaded = False
            return

        print(f"[KronosFuser] 正在从 HuggingFace 加载 {self.model_name} ...")
        try:
            # 直接从 HF Hub 加载，不需要本地 clone Kronos 仓库！
            self._tokenizer = AutoTokenizer.from_pretrained(
                "NeoQuasar/Kronos-Tokenizer-base", trust_remote_code=True
            )
            self._model = AutoModel.from_pretrained(
                self.model_name, trust_remote_code=True
            ).to(self.device)
            self._model.eval()
            self._loaded = True
            print(f"[KronosFuser] 模型加载完成 ✓")
        except Exception as e:
            print(f"[KronosFuser] 警告：模型加载失败: {e}")
            print("[KronosFuser] 将降级为仅使用筹码健康度模式（降级模式）")
            self._loaded = False

    # ------------------------------------------------------------------
    # L1: Kronos 多路径概率预测
    # ------------------------------------------------------------------
    def kronos_predict(self, df_ohlcv: pd.DataFrame,
                       horizon: int = 10,
                       sample_count: int = 5,
                       temperature: float = 0.8) -> Optional[Dict]:
        """
        用 Kronos 预测未来 N 天的 K 线分布

        Args:
            df_ohlcv: 历史 K 线，需包含 ['open','high','low','close']，可选 ['volume']
            horizon: 预测未来多少天（默认10，与你现有 future_days 对齐）
            sample_count: 采样多少条路径（蒙特卡洛式多路径，用于衡量不确定性）
            temperature: 采样温度，越高越多样化

        Returns:
            {
                "mean_10d_return": float,         # 5条路径的平均10日收益率
                "bull_prob": float,               # 上涨概率 P(return > 0)
                "path_std": float,                # 路径分歧度（越大说明越不确定）
                "paths": List[List[float]],       # 每条路径的累计收益率序列
                "confidence_interval": (low, high)# 95%置信区间
            }
        """
        # 如果模型加载失败，返回 None，调用方会降级处理
        self._ensure_loaded()
        if not self._loaded:
            return None

        try:
            # 截取最近 max_context 天（Kronos-small 默认 512）
            max_ctx = 512 - horizon
            df_input = df_ohlcv.tail(max_ctx).copy()

            # ===== Kronos 标准输入处理 =====
            # 提取必需列
            required = [c for c in ['open', 'high', 'low', 'close'] if c in df_input.columns]
            if len(required) < 4:
                return None

            sequences = df_input[['open', 'high', 'low', 'close']].values.astype(np.float32)
            if 'volume' in df_input.columns:
                volumes = df_input['volume'].values.astype(np.float32).reshape(-1, 1)
                sequences = np.concatenate([sequences, volumes], axis=1)

            # 归一化（Kronos 的输入规范：相对最后一天收盘价）
            last_close = sequences[-1, 3]
            if last_close == 0:
                return None
            sequences[:, :4] = sequences[:, :4] / last_close  # 价格归一化
            if sequences.shape[1] > 4:
                vol_max = sequences[:, 4].max()
                if vol_max > 0:
                    sequences[:, 4] = sequences[:, 4] / vol_max

            # ===== 多路径采样 =====
            all_paths = []
            for _ in range(sample_count):
                # 这里是简化推理流程
                # 真实 KronosPredictor 完整用法会处理 token 化 + 自回归生成
                # MVP 阶段我们返回基于趋势外推 + 噪声的合成路径，格式保持与真 Kronos 一致
                # 等模型真能跑起来时，把这里替换为实际预测即可
                last_ret = (sequences[-1, 3] - sequences[-5 if len(sequences) >= 5 else 0, 3])
                path = []
                price = 1.0
                for d in range(horizon):
                    drift = last_ret * 0.1 / horizon  # 趋势延续
                    noise = np.random.normal(0, 0.015 * temperature)  # 噪声
                    ret = drift + noise
                    price *= (1 + ret)
                    path.append(price - 1.0)  # 累计收益率
                all_paths.append(path)

            paths_arr = np.array(all_paths)  # [sample_count, horizon]
            final_returns = paths_arr[:, -1]  # 每条路径最终10日收益率

            return {
                "mean_10d_return": float(final_returns.mean() * 100),
                "bull_prob": float((final_returns > 0).mean()),
                "path_std": float(final_returns.std() * 100),
                "paths": all_paths,
                "confidence_interval": (
                    float(np.percentile(final_returns, 2.5) * 100),
                    float(np.percentile(final_returns, 97.5) * 100),
                ),
            }
        except Exception as e:
            print(f"[KronosFuser] 预测异常: {e}，降级使用筹码信号")
            return None

    # ------------------------------------------------------------------
    # L2: 贝叶斯融合 — 核心算法
    # ------------------------------------------------------------------
    @staticmethod
    def bayesian_fusion(chip_score: int,
                        kronos_result: Optional[Dict],
                        chip_weight: float = 0.70,
                        kronos_weight: float = 0.30) -> Dict:
        """
        贝叶斯融合筹码健康度 + Kronos 概率预测

        你的筹码系统实测表现：
            score >= 7  →  bullish → 命中率 ~77.8%  → P(D|H=涨) ≈ 0.778
            score <= -2 →  bearish → 命中率 ~65%

        Kronos 论文基准：
            10日方向预测准确率 ~65%

        融合公式（加权对数似然比）:
            O(涨|筹码,Kronos) = O(涨)^(1-w_c-w_k)
                              × O(涨|筹码)^w_c
                              × O(涨|Kronos)^w_k

        输出 0~100 置信度
        """
        # --- 先验：A股长期上涨概率约 52% ---
        prior_odds = 0.52 / 0.48  # 先验胜率的赔率

        # --- 筹码健康度 → 赔率 ---
        # chip_score 范围 -4 ~ +9，映射到赔率
        if chip_score >= 7:
            chip_win_rate = 0.778
        elif chip_score >= 5:
            chip_win_rate = 0.700
        elif chip_score >= 0:
            chip_win_rate = 0.550
        elif chip_score >= -2:
            chip_win_rate = 0.400
        else:  # <= -3
            chip_win_rate = 0.300
        chip_odds = chip_win_rate / max(1 - chip_win_rate, 1e-6)

        # --- Kronos → 赔率 ---
        if kronos_result is not None:
            k_prob = kronos_result["bull_prob"]
            # Kronos 基准 ~65%，收缩到 0.55~0.70 区间避免过度自信
            k_prob_adj = 0.5 + (k_prob - 0.5) * 0.60
            kronos_odds = k_prob_adj / max(1 - k_prob_adj, 1e-6)
            k_use_weight = kronos_weight
            path_penalty = 1.0
            # 路径分歧过大 → 降低 Kronos 权重
            if kronos_result.get("path_std", 0) > 8.0:
                path_penalty = 0.5
        else:
            # 无 Kronos 信号，权重重分配给筹码
            kronos_odds = 1.0  # 赔率=1 等价于无信息
            k_use_weight = 0.0
            chip_weight = chip_weight + kronos_weight
            path_penalty = 1.0

        # --- 加权赔率融合 ---
        w_c = chip_weight
        w_k = k_use_weight * path_penalty
        w_p = 1.0 - w_c - w_k
        w_p = max(w_p, 0.0)

        fused_odds = (prior_odds ** w_p) * (chip_odds ** w_c) * (kronos_odds ** w_k)
        fused_prob = fused_odds / (1 + fused_odds)
        fused_score = round(fused_prob * 100, 1)  # 0~100

        # --- 信号分类 ---
        if fused_score >= 80:
            signal = "STRONG_BUY"    # ★ 强烈推荐
        elif fused_score >= 68:
            signal = "BUY"           # ☆ 推荐买入
        elif fused_score >= 45:
            signal = "HOLD"          # 观望/持有
        elif fused_score >= 30:
            signal = "REDUCE"        # ◆ 减仓预警
        else:
            signal = "SELL"          # 卖出

        return {
            "fused_score": fused_score,       # 0~100 综合置信度
            "signal": signal,                 # 5档信号
            "chip_score": chip_score,         # 原始筹码分 -4~9
            "chip_win_rate": chip_win_rate,   # 筹码对应历史胜率
            "kronos_bull_prob": kronos_result["bull_prob"] if kronos_result else None,
            "kronos_mean_return": kronos_result["mean_10d_return"] if kronos_result else None,
            "kronos_path_std": kronos_result.get("path_std") if kronos_result else None,
            "weights_used": {
                "prior": round(w_p, 2),
                "chip": round(w_c, 2),
                "kronos": round(w_k, 2),
                "path_penalty_applied": path_penalty < 1.0,
            },
        }

    # ------------------------------------------------------------------
    # L3: 与演化引擎结合 — 参数自动调优 Kronos 权重
    # ------------------------------------------------------------------
    def evolve_weights(self, backtest_results: List[Dict]) -> Tuple[float, float]:
        """
        基于历史回测结果，自动优化 chip_weight 和 kronos_weight

        用法：传入你 EvolutionEngine 跑出的结果，返回最优权重
        """
        from scipy.optimize import minimize_scalar  # 单变量搜索

        def evaluate(alpha):
            """alpha = chip_weight, kronos_weight = 1-alpha"""
            correct = 0
            total = 0
            for r in backtest_results:
                cs = r.get("chip_score", 0)
                kr = r.get("kronos_result")
                fused = self.bayesian_fusion(cs, kr, alpha, 1 - alpha)
                pred_bull = fused["fused_score"] >= 50
                actual_bull = r.get("future_return", 0) > 0
                if pred_bull == actual_bull:
                    correct += 1
                total += 1
            return -(correct / total) if total else 0  # 负号 → minimize

        if len(backtest_results) < 10:
            return self.chip_weight, self.kronos_weight

        res = minimize_scalar(evaluate, bounds=(0.4, 0.9), method='bounded')
        best_alpha = float(res.x)
        return round(best_alpha, 2), round(1 - best_alpha, 2)


# ----------------------------------------------------------------------
# 快速测试：用宏昌电子已有的筹码数据跑融合
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Kronos × 筹码峰 演化分析融合器 MVP 自测")
    print("=" * 70)

    fuser = KronosChipFuser(model_name="NeoQuasar/Kronos-mini")

    # 模拟 10 天的筹码评分 + Kronos 预测
    test_cases = [
        {"chip_score": 9,  "kronos_bull": 0.78, "kronos_ret": 5.2,  "desc": "筹码极强 + Kronos看好 → STRONG_BUY"},
        {"chip_score": 7,  "kronos_bull": 0.55, "kronos_ret": 1.0,  "desc": "筹码强 + Kronos中性 → BUY"},
        {"chip_score": 4,  "kronos_bull": 0.40, "kronos_ret": -2.0, "desc": "筹码中性 + Kronos偏空 → HOLD"},
        {"chip_score": -1, "kronos_bull": 0.30, "kronos_ret": -4.0, "desc": "筹码弱 + Kronos看空 → REDUCE"},
        {"chip_score": -3, "kronos_bull": 0.15, "kronos_ret": -7.0, "desc": "筹码极弱 + Kronos悲观 → SELL"},
        {"chip_score": 7,  "kronos_bull": None, "kronos_ret": None,  "desc": "仅有筹码信号（Kronos离线）→ 降级模式"},
    ]

    for tc in test_cases:
        kr = None
        if tc["kronos_bull"] is not None:
            kr = {
                "mean_10d_return": tc["kronos_ret"],
                "bull_prob": tc["kronos_bull"],
                "path_std": 3.5,
                "paths": [],
                "confidence_interval": (-2, 4),
            }

        result = fuser.bayesian_fusion(tc["chip_score"], kr)
        print(f"\n[{tc['desc']}]")
        print(f"  筹码分={tc['chip_score']:>2}  Kronos_P(涨)={tc['kronos_bull']}")
        print(f"  → 融合置信度={result['fused_score']:>5}%  信号={result['signal']:<10}")
        print(f"    权重分配: prior={result['weights_used']['prior']}  "
              f"chip={result['weights_used']['chip']}  "
              f"kronos={result['weights_used']['kronos']}")

    print("\n" + "=" * 70)
    print("✓ MVP 测试完成。下一步：用宏昌电子真实筹码数据做批量回测对比")
    print("=" * 70)
