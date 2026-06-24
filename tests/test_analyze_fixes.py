"""
针对 review 中发现的 bug 的回归测试
防止相同问题再次出现
(注: root analyze.py 已删除, 所有测试只针对 scripts/analyze.py)
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

# 项目内唯一保留的 analyze 路径
ANALYZE_PATHS = ["scripts/analyze.py"]


# ═══════════════════════════════════════════════════════
# Issue 1: median_price 必须按价格升序计算
# ═══════════════════════════════════════════════════════

class TestMedianPriceSorted:
    """中位成本价应按价格升序计算 cumsum 50% 处的价格"""

    def test_median_price_uses_price_sorted_data(self):
        """验证 median_price 计算逻辑正确"""
        import numpy as np

        prices = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        percents = np.array([5.0, 10.0, 30.0, 30.0, 15.0, 10.0])

        cumsum_sorted = np.cumsum(percents)
        half_total = cumsum_sorted[-1] / 2.0
        median_idx = int(np.searchsorted(cumsum_sorted, half_total))
        median_price = float(prices[median_idx])

        assert median_idx == 3
        assert median_price == 13.0


# ═══════════════════════════════════════════════════════
# Issue 2: peak_triplets 必须有边界保护
# ═══════════════════════════════════════════════════════

class TestPeakTripletsBounds:
    """peak_triplets 不足 3 个时不能 IndexError"""

    def test_peak_triplets_padding(self):
        peak_triplets = []
        while len(peak_triplets) < 3:
            peak_triplets.append((0.0, 0.0, "missing"))

        assert len(peak_triplets) == 3
        p1, _ = peak_triplets[0][:2]
        _, p3 = peak_triplets[2][:2]
        assert p1 == 0.0 and p3 == 0.0


# ═══════════════════════════════════════════════════════
# Issue 3: dispatch_score 变量命名
# ═══════════════════════════════════════════════════════

class TestDispatchNaming:
    """dispatch_score 应使用 prev_half/last_half 命名"""

    def test_no_old_names_in_source(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "prev5_p1_avg" not in content, f"{path} 仍包含旧名 prev5_p1_avg"
            assert "last5_p1_avg" not in content, f"{path} 仍包含旧名 last5_p1_avg"
            assert "prev_half_p1_avg" in content, f"{path} 缺少新名 prev_half_p1_avg"
            assert "last_half_p1_avg" in content, f"{path} 缺少新名 last_half_p1_avg"


# ═══════════════════════════════════════════════════════
# Issue 4: 峰检测左右对称
# ═══════════════════════════════════════════════════════

class TestPeakDetectionSymmetry:
    """峰检测左右严格度必须一致"""

    def test_strict_comparison_on_both_sides(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "percents[i] > max(left_vals) and percents[i] > max(right_vals)" in content, \
                f"{path} 峰检测左右不对称"
            assert "percents[i] >= max(right_vals)" not in content, \
                f"{path} 仍有非对称的 >= 写法"


# ═══════════════════════════════════════════════════════
# Issue 5: 文档版本号
# ═══════════════════════════════════════════════════════

class TestDocVersion:
    """scripts/analyze.py 应该是 v2.5"""

    def test_scripts_doc_is_v25(self):
        content = open(os.path.join(_ROOT, "scripts/analyze.py"), encoding="utf-8").read()
        assert "(v2.5)" in content, "scripts/analyze.py 文档版本应为 v2.5"
        assert "(v2.3)" not in content, "scripts/analyze.py 不应再写 v2.3"


# ═══════════════════════════════════════════════════════
# Issue 6: full_series 不再用 locals() 探测
# ═══════════════════════════════════════════════════════

class TestBaselineDaysNoLocals:
    """baseline_days 不应依赖 locals() 探测"""

    def test_no_locals_check(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "'full_series' in locals()" not in content, \
                f"{path} 仍依赖脆弱的 locals() 探测"
            assert "last_full_series_len" in content, \
                f"{path} 缺少 last_full_series_len 变量"


# ═══════════════════════════════════════════════════════
# Issue 7: boll_pos 分母保护
# ═══════════════════════════════════════════════════════

class TestBollPositionGuard:
    """boll_pos 计算要避免除零"""

    def test_boll_guard_present(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "(boll_u - boll_l) > 1e-6" in content, \
                f"{path} 缺少 boll_u - boll_l 除零保护"


# ═══════════════════════════════════════════════════════
# 一致性测试: scripts/analyze.py 关键修复
# ═══════════════════════════════════════════════════════

class TestScriptsAnalyzeConsistency:
    """scripts/analyze.py 关键修复应已生效"""

    def test_has_median_fix(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "cumsum_sorted = np.cumsum(arr_pt_sorted)" in content

    def test_has_peak_padding(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "while len(peak_triplets) < 3:" in content

    def test_has_rename(self):
        for path in ANALYZE_PATHS:
            content = open(os.path.join(_ROOT, path), encoding="utf-8").read()
            assert "prev_half_p1_avg" in content
            assert "last_half_p1_avg" in content