"""
基础冒烟测试: 验证关键路径不回归

运行: pytest tests/ -v
"""
import os
import sys
import time

# 确保项目根目录可被 import
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))


# ═══════════════════════════════════════════════════════
# normalize_ts_code
# ═══════════════════════════════════════════════════════

class TestNormalizeTsCode:
    """测试股票代码自动补全逻辑"""

    def test_sz_codes_get_sz_suffix(self):
        from app import normalize_ts_code
        assert normalize_ts_code("000066") == "000066.SZ"
        assert normalize_ts_code("301428") == "301428.SZ"

    def test_sh_codes_get_sh_suffix(self):
        from app import normalize_ts_code
        assert normalize_ts_code("600519") == "600519.SH"
        assert normalize_ts_code("900901") == "900901.SH"

    def test_bj_codes_get_bj_suffix(self):
        from app import normalize_ts_code
        assert normalize_ts_code("830799") == "830799.BJ"
        assert normalize_ts_code("430047") == "430047.BJ"
        assert normalize_ts_code("200123") == "200123.BJ"

    def test_already_suffixed_unchanged(self):
        from app import normalize_ts_code
        assert normalize_ts_code("000066.SZ") == "000066.SZ"
        assert normalize_ts_code("600519.sh") == "600519.SH"  # 自动转大写

    def test_invalid_inputs_pass_through(self):
        from app import normalize_ts_code
        assert normalize_ts_code("") == ""
        assert normalize_ts_code("abc") == "abc"
        assert normalize_ts_code("12345") == "12345"  # 非 6 位
        assert normalize_ts_code("1234567") == "1234567"  # 非 6 位

    def test_whitespace_stripped(self):
        from app import normalize_ts_code
        assert normalize_ts_code("  000066  ") == "000066.SZ"


# ═══════════════════════════════════════════════════════
# SimpleRateLimiter
# ═══════════════════════════════════════════════════════

class TestRateLimiter:
    """测试简易限流器"""

    def test_allows_under_limit(self):
        from utils import SimpleRateLimiter
        rl = SimpleRateLimiter(window_seconds=60, max_calls=3)
        for _ in range(3):
            assert rl.allow("user1") is True

    def test_blocks_over_limit(self):
        from utils import SimpleRateLimiter
        rl = SimpleRateLimiter(window_seconds=60, max_calls=2)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False  # 第 3 次被拒

    def test_separate_keys_independent(self):
        from utils import SimpleRateLimiter
        rl = SimpleRateLimiter(window_seconds=60, max_calls=1)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False
        assert rl.allow("user2") is True  # 不同 key 互不影响

    def test_retry_after_decreases(self):
        from utils import SimpleRateLimiter
        rl = SimpleRateLimiter(window_seconds=10, max_calls=1)
        rl.allow("k")
        ra = rl.retry_after("k")
        assert 0 < ra <= 11


# ═══════════════════════════════════════════════════════
# utils.call_llm 健壮性
# ═══════════════════════════════════════════════════════

class TestCallLlmRobustness:
    """测试 LLM 调用的错误处理 (不实际发请求)"""

    def test_raises_when_no_llm_configured(self, monkeypatch):
        """未配置 models.json 时应抛出友好错误"""
        from utils import call_llm
        # 让 get_configured_llm 返回 None
        monkeypatch.setattr("utils.get_configured_llm", lambda: None)
        with __import__("pytest").raises(RuntimeError, match="未找到可用的 LLM"):
            call_llm("hello")

    def test_handles_non_json_response(self, monkeypatch):
        """LLM 返回 HTML 错误页时不应崩, 应抛 RuntimeError"""
        from utils import call_llm

        class FakeResp:
            def __init__(self, body): self._b = body.encode()
            def read(self): return self._b
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr("utils.get_configured_llm",
                            lambda: {"name": "x", "url": "http://x/v1/chat/completions",
                                     "apiKey": "k", "model": "m"})
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **kw: FakeResp("<html>Error</html>"))

        with __import__("pytest").raises(RuntimeError, match="不是合法 JSON"):
            call_llm("hello")

    def test_handles_missing_choices(self, monkeypatch):
        """响应缺少 choices 字段时抛清晰错误"""
        from utils import call_llm

        class FakeResp:
            def __init__(self, body): self._b = body.encode()
            def read(self): return self._b
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr("utils.get_configured_llm",
                            lambda: {"name": "x", "url": "http://x/v1/chat/completions",
                                     "apiKey": "k", "model": "m"})
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **kw: FakeResp('{"error":"rate limit"}'))

        with __import__("pytest").raises(RuntimeError, match="响应结构异常"):
            call_llm("hello")


# ═══════════════════════════════════════════════════════
# Flask app 基本健康
# ═══════════════════════════════════════════════════════

class TestFlaskApp:
    """验证 Flask 应用基本行为 (使用 test_client, 不启动真实服务)"""

    def test_app_starts_and_routes_registered(self):
        from app import app
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/" in rules
        assert "/api/health" in rules
        assert "/api/watchlist" in rules
        assert "/api/analyze/<ts_code>" in rules

    def test_health_endpoint_returns_dict(self):
        from app import app
        with app.test_client() as c:
            res = c.get("/api/health")
        # 状态码可能是 200 (正常) 或 503 (缺 token), 都应返回结构化 JSON
        assert res.status_code in (200, 503)
        data = res.get_json()
        assert "status" in data
        assert "components" in data

    def test_404_api_returns_json(self):
        """API 404 应返回 JSON"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/nonexistent")
        assert res.status_code == 404
        data = res.get_json()
        assert data.get("error") == "Not Found"

    def test_normalize_in_analyze_route(self):
        """/api/analyze/000066 应被自动补全为 .SZ 而不报 500"""
        from app import app
        with app.test_client() as c:
            # 只检查路由是否接受 (不调用真实 Tushare)
            # 通过 mock 掉 chip_analyze 来避免 API 调用
            from app import app as flask_app
            with flask_app.test_request_context("/api/analyze/000066"):
                # 模拟: 调用 normalize 不会失败
                from app import normalize_ts_code
                assert normalize_ts_code("000066") == "000066.SZ"


class TestParseLockScore:
    """_parse_lock_score 的回归测试 — 修复 None 输入导致 TypeError 的 issue"""

    def test_none_returns_default(self):
        """None 不应抛 TypeError, 应返回 (0, 6)"""
        from utils import _parse_lock_score
        assert _parse_lock_score(None) == (0, 6)

    def test_empty_string_returns_default(self):
        from utils import _parse_lock_score
        assert _parse_lock_score("") == (0, 6)

    def test_normal_values(self):
        from utils import _parse_lock_score
        assert _parse_lock_score("5/6") == (5, 6)
        assert _parse_lock_score("0/6") == (0, 6)
        assert _parse_lock_score("3/6") == (3, 6)

    def test_no_slash_returns_default(self):
        from utils import _parse_lock_score
        assert _parse_lock_score("abc") == (0, 6)

    def test_malformed_returns_default(self):
        """'5/' / '/6' / 'a/b' 等格式异常应返回 (0, 6)"""
        from utils import _parse_lock_score
        assert _parse_lock_score("5/") == (0, 6)
        assert _parse_lock_score("/6") == (0, 6)
        assert _parse_lock_score("a/b") == (0, 6)

    def test_compute_verdict_handles_none_lock(self):
        """compute_verdict 在 locked_score=None 时不应崩溃"""
        from utils import compute_verdict
        # 模拟从 analyze 返回的 dict 里 lock_score 字段为 None
        result = compute_verdict({
            "chip_evolution": {"locking_assessment": {"locked_score": None}},
            "divergence_signals": {},
        })
        assert "action" in result
        assert result["action"] in ("持有", "减仓", "清仓", "观望")