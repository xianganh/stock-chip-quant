# 10. 测试体系

> 目录: [tests/](../../tests/)
> 框架: pytest
> 测试数: **38 个** 全部通过
> 配置: [pytest.ini](../../pytest.ini)

## 📋 测试统计

| 文件 | 测试数 | 覆盖范围 |
|------|-------|---------|
| [test_smoke.py](#test_smokepy) | 17 | 基础冒烟测试 |
| [test_analyze_fixes.py](#test_analyze_fixespy) | 11 | 算法回归（8 个 review bug） |
| [test_positions.py](#test_positionspy) | 10 | Position/TradeLog CRUD |
| [test_knowledge_graph.py](#test_knowledge_graphpy) | — | 知识图谱集成 |
| [test_kg_ui.py](#test_kg_uipy) | — | KG UI 交互 |

**总计**: 38 个测试

## 🚀 运行测试

### 全部测试

```bash
python -m pytest tests/ -v
```

### 单个文件

```bash
python -m pytest tests/test_smoke.py -v
```

### 失败时详细输出

```bash
python -m pytest tests/ -v --tb=long
```

### 覆盖率（需 pytest-cov）

```bash
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=html
# 查看 htmlcov/index.html
```

### 性能分析

```bash
pip install pytest-profiling
python -m pytest tests/ --profile
```

---

## test_smoke.py

**位置**: [tests/test_smoke.py](../../tests/test_smoke.py)
**测试数**: 17

### `TestNormalizeTsCode` - 股票代码自动补全 (6)

```python
def test_sz_codes_get_sz_suffix():
    assert normalize_ts_code("000066") == "000066.SZ"
    assert normalize_ts_code("301428") == "301428.SZ"

def test_sh_codes_get_sh_suffix():
    assert normalize_ts_code("600519") == "600519.SH"
    assert normalize_ts_code("900901") == "900901.SH"

def test_bj_codes_get_bj_suffix():
    assert normalize_ts_code("830799") == "830799.BJ"
    assert normalize_ts_code("430047") == "430047.BJ"
    assert normalize_ts_code("200123") == "200123.BJ"

def test_already_suffixed_unchanged():
    assert normalize_ts_code("000066.SZ") == "000066.SZ"
    assert normalize_ts_code("600519.sh") == "600519.SH"  # 自动转大写

def test_invalid_inputs_pass_through():
    assert normalize_ts_code("") == ""
    assert normalize_ts_code("abc") == "abc"
    assert normalize_ts_code("12345") == "12345"  # 非 6 位
    assert normalize_ts_code("1234567") == "1234567"  # 非 6 位

def test_whitespace_stripped():
    assert normalize_ts_code("  000066  ") == "000066.SZ"
```

### `TestRateLimiter` - 简易限流器 (4)

```python
def test_allows_under_limit():
    rl = SimpleRateLimiter(window_seconds=60, max_calls=3)
    for _ in range(3):
        assert rl.allow("user1") is True

def test_blocks_over_limit():
    rl = SimpleRateLimiter(window_seconds=60, max_calls=2)
    assert rl.allow("user1") is True
    assert rl.allow("user1") is True
    assert rl.allow("user1") is False  # 第 3 次被拒

def test_separate_keys_independent():
    rl = SimpleRateLimiter(window_seconds=60, max_calls=1)
    assert rl.allow("user1") is True
    assert rl.allow("user1") is False
    assert rl.allow("user2") is True  # 不同 key 独立
```

### 其他（7）

- Flask 应用启动
- 数据库连接
- 配置加载
- SECERT_KEY 持久化
- 数据库 schema 创建
- Health endpoint
- API 错误处理

---

## test_analyze_fixes.py

**位置**: [tests/test_analyze_fixes.py](../../tests/test_analyze_fixes.py)
**测试数**: 11
**目的**: 防止 8 个 review bug 回归

### 覆盖的 Bug

| # | Bug | 测试方法 |
|---|-----|---------|
| 1 | `median_price` 计算错误（用降序排列找 50%） | `test_median_price_uses_sorted_cumsum` |
| 2 | 局部极大值左右邻居严格度不对称（`>` vs `>=`） | `test_local_peaks_strict_both_sides` |
| 3 | 命名错误（`prev_half_*` 实际不是 5 日） | `test_dispatch_naming_clarity` |
| 4 | 信号缓存未清空（Evolution 多轮时增长） | `test_signal_cache_cleared_between_runs` |
| 5 | 大盘基线重复计算（evo 循环内每次调用） | `test_buy_hold_baseline_computed_once` |
| 6 | 快照元数据查询未 defer full_data | `test_snapshot_meta_defers_full_data` |
| 7 | LLM 响应解析不健壮（非 JSON 响应崩溃） | `test_llm_non_json_response_handled` |
| 8 | API 错误堆栈泄露（生产也带堆栈） | `test_api_500_no_traceback_in_prod` |

### 示例

```python
def test_median_price_uses_sorted_cumsum():
    """median_price 必须按价格升序找 cumsum 50% 处"""
    # 构造测试数据
    df = pd.DataFrame({
        "price": [10, 20, 30, 40, 50],
        "percent": [10, 20, 30, 20, 10]
    })
    metrics = compute_chip_metrics(df, close=30)
    # 中位价应该是 30（cumsum 到 50 的位置）
    assert metrics["median_price"] == 30
```

---

## test_positions.py

**位置**: [tests/test_positions.py](../../tests/test_positions.py)
**测试数**: 10
**覆盖**: Phase 1 持仓 + 交易日志功能

### `TestPositions` - Position CRUD (4)

```python
def test_get_positions_all():
    """获取所有持仓 (不限账户)"""
    with app.app_context():
        count = Position.query.count()
        assert count > 0, "应该有持仓数据 (Phase 1 已导入)"

def test_get_positions_by_account():
    """按账户分开查询"""
    res1 = c.get("/api/positions?account=衡祥安")
    res2 = c.get("/api/positions?account=邱磊")
    # 验证两个账户确实分开
    for p in res1: assert p["account"] == "衡祥安"
    for p in res2: assert p["account"] == "邱磊"

def test_get_positions_active_only():
    """只看活跃持仓"""
    res = c.get("/api/positions?status=active")
    for p in res: assert p["status"] == "active"

def test_get_position_by_code():
    """按股票代码查找活跃持仓"""
    res = c.get("/api/positions/by_code/603039")
    assert res["ts_code"] in ("603039", "603039.SH")
    assert res["status"] == "active"
```

### `TestTradeLogs` - TradeLog CRUD (3)

```python
def test_get_trade_logs():
    """获取所有交易日志"""
    
def test_get_trade_logs_by_ts_code():
    """按股票代码过滤"""
    
def test_get_trade_logs_by_account():
    """按账户过滤"""
```

### API 端点 (3)

```python
def test_positions_api_endpoints():
    """/api/positions 系列端点"""

def test_trade_logs_api_endpoints():
    """/api/trade_logs 系列端点"""

def test_positions_by_code_normalize():
    """带/不带后缀都应能查到"""
```

---

## test_knowledge_graph.py

**位置**: [tests/test_knowledge_graph.py](../../tests/test_knowledge_graph.py)

### `TestKnowledgeGraph` (7+)

```python
def test_kg_directory_exists():
    """知识图谱目录存在"""
    from config import KNOWLEDGE_GRAPH_DIR
    assert os.path.isdir(KNOWLEDGE_GRAPH_DIR)

def test_load_kg_returns_stats():
    """load_knowledge_graph 返回统计"""
    result = load_knowledge_graph()
    assert result["stats"]["available"] is True
    assert result["stats"]["companies"] > 0

def test_get_kg_by_code():
    """按代码查询返回节点"""
    node = get_kg_by_code("300174")
    assert node["name"] == "元力股份"
    assert "活性炭" in node["tags"]

def test_get_kg_by_code_with_suffix():
    """带 .SZ 后缀的代码也能匹配"""
    node1 = get_kg_by_code("300174")
    node2 = get_kg_by_code("300174.SZ")
    assert node1 == node2

def test_get_kg_unknown_returns_none():
    """未知股票返回 None"""
    assert get_kg_by_code("999999") is None

def test_kg_stats_endpoint():
    """测试 stats API"""
    res = c.get("/api/knowledge_graph/stats")
    assert res.status_code == 200
    assert res.get_json()["loaded"] is True

def test_kg_by_code_endpoint():
    """测试 by_code API"""
    res = c.get("/api/knowledge_graph/300174")
    assert res.status_code == 200
    assert res.get_json()["found"] is True
```

---

## test_kg_ui.py

**位置**: [tests/test_kg_ui.py](../../tests/test_kg_ui.py)

### `TestKGUI` (测试 watchlist UI 与 KG 集成)

```python
def test_watchlist_shows_kg_tags():
    """watchlist 页面应显示 KG tags"""

def test_watchlist_add_uses_kg_lookup():
    """添加选股时自动从 KG 查找 name"""

def test_stock_lookup_api():
    """测试 /api/stock_lookup"""
```

---

## 🛠️ 测试约定

### 路径处理

```python
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
```

### 数据库隔离

测试使用相同的 SQLite 数据库（`data/stock.db`），不隔离。如需隔离：

```python
@pytest.fixture
def test_db():
    """使用临时数据库"""
    import tempfile
    db_fd, db_path = tempfile.mkstemp()
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    with app.app_context():
        db.create_all()
        yield db_path
    os.close(db_fd)
    os.unlink(db_path)
```

### Flask Test Client

```python
def test_api_endpoint():
    from app import app
    with app.test_client() as c:
        res = c.get("/api/...")
        assert res.status_code == 200
```

### App Context

```python
def test_with_app_context():
    from app import app, db
    with app.app_context():
        # 在应用上下文中执行
        result = SomeModel.query.all()
```

---

## 📊 覆盖率分析

### 当前覆盖

| 模块 | 覆盖状态 |
|------|---------|
| `utils.py` | ✅ 高（normalize + rate limiter + KG） |
| `app.py` API | ✅ 中（主要端点） |
| `database/models.py` | ✅ 高（CRUD 测试） |
| `database/db_manager.py` | ✅ 高 |
| `scripts/analyze.py` | ⚠️ 中（仅核心算法） |
| `engine/backtest_engine.py` | ⚠️ 低 |
| `engine/evolution_engine.py` | ⚠️ 低 |

### 待补充

- [ ] `BacktestEngine` 完整测试
- [ ] `EvolutionEngine` 完整测试
- [ ] `analyze.py` 8 大引擎全面测试
- [ ] `import_trades.py` 文件解析测试
- [ ] 端到端测试（API + 数据库 + 文件）

---

## 📝 测试开发指南

### TDD 流程

按项目约定：

1. **写测试先于实现**：新功能先写 pytest，再写实现
2. **小步快跑**：每个修复都要在测试通过后 commit
3. **不要破坏 watchlist.active 字段**：即使不再使用，保留字段避免 schema 迁移

### 命名规范

```python
class TestModuleName:
    """测试模块描述"""
    
    def test_specific_behavior(self):
        """具体行为描述"""
        # Arrange
        ...
        # Act
        ...
        # Assert
        assert ...
```

### Mock 外部依赖

```python
from unittest.mock import patch, MagicMock

def test_tushare_call():
    with patch("utils.get_tushare_pro") as mock:
        mock.return_value.stock_basic.return_value = pd.DataFrame([...])
        # 测试代码
```

### 参数化测试

```python
import pytest

@pytest.mark.parametrize("code,expected", [
    ("000066", "000066.SZ"),
    ("600519", "600519.SH"),
    ("830799", "830799.BJ"),
])
def test_normalize(code, expected):
    assert normalize_ts_code(code) == expected
```

---

## 📞 进一步阅读

- [pytest 文档](https://docs.pytest.org/)
- [Flask 测试文档](https://flask.palletsprojects.com/testing/)
- [SQLAlchemy 测试](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)