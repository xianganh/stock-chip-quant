"""验证 Position 和 TradeLog 的 Phase 1 功能"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))


# ═══════════════════════════════════════════════════════
# DBManager CRUD 测试
# ═══════════════════════════════════════════════════════

class TestPositions:
    """测试 Position CRUD"""

    def test_get_positions_all(self):
        """获取所有持仓 (不限账户)"""
        from app import app, db
        from database.models import Position
        with app.app_context():
            count = Position.query.count()
            assert count > 0, "应该有持仓数据 (Phase 1 已导入)"

    def test_get_positions_by_account(self):
        """按账户分开查询"""
        from app import app
        with app.test_client() as c:
            res1 = c.get("/api/positions?account=衡祥安")
            res2 = c.get("/api/positions?account=邱磊")
            assert res1.status_code == 200
            assert res2.status_code == 200
            d1 = res1.get_json()
            d2 = res2.get_json()
            # 验证两个账户确实分开
            for p in d1:
                assert p["account"] == "衡祥安"
            for p in d2:
                assert p["account"] == "邱磊"

    def test_get_positions_active_only(self):
        """只看活跃持仓"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/positions?status=active")
            assert res.status_code == 200
            positions = res.get_json()
            for p in positions:
                assert p["status"] == "active"

    def test_get_position_by_code(self):
        """按股票代码查找活跃持仓"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/positions/by_code/603039")
            assert res.status_code == 200
            data = res.get_json()
            assert data["ts_code"] in ("603039", "603039.SH")
            assert data["status"] == "active"


class TestTradeLogs:
    """测试 TradeLog 查询"""

    def test_get_trade_logs(self):
        from app import app
        with app.test_client() as c:
            res = c.get("/api/trade_logs?limit=10")
            assert res.status_code == 200
            logs = res.get_json()
            assert len(logs) > 0
            assert "trade_date" in logs[0]
            assert "direction" in logs[0]

    def test_get_trade_logs_by_account(self):
        from app import app
        with app.test_client() as c:
            res = c.get("/api/trade_logs?account=衡祥安&limit=5")
            logs = res.get_json()
            for log in logs:
                assert log["account_holder"] == "衡祥安"


class TestImportScript:
    """测试 import_trades 脚本的导入功能"""

    def test_data_files_exist(self):
        """两个交易文件存在"""
        import os
        for f in ["tradeHistroy.txt", "tradeHistroy_fz.txt"]:
            path = os.path.join(_ROOT, "data", f)
            assert os.path.exists(path), f"缺少交易文件: {path}"

    def test_database_has_imported_data(self):
        """数据库有导入的数据"""
        from app import app
        from database.models import TradeLog, Position
        with app.app_context():
            trades = TradeLog.query.count()
            positions = Position.query.count()
            assert trades >= 1000, f"trade_logs 应该 ≥1000, 实际 {trades}"
            assert positions >= 100, f"positions 应该 ≥100, 实际 {positions}"

    def test_two_accounts_separated(self):
        """两个账户的 trades 完全分开 (没有串台)"""
        from app import app
        from database.models import TradeLog
        with app.app_context():
            heng = TradeLog.query.filter_by(account_holder="衡祥安").count()
            qiu  = TradeLog.query.filter_by(account_holder="邱磊").count()
            assert heng > 0, "衡祥安账户应该有交易"
            assert qiu > 0, "邱磊账户应该有交易"
            # 比例应该接近 dry-run 显示的 641/1489
            assert 0.3 < heng / qiu < 0.6, f"比例异常: {heng}/{qiu}"


class TestParser:
    """测试交易文件解析器的过滤功能"""

    def test_parser_skips_invalid(self):
        """无效交易 (配号/申购/价格=0) 被过滤"""
        import sys
        sys.path.insert(0, os.path.join(_ROOT, "scripts"))
        from import_trades import parse_trades, read_file_smart

        path = os.path.join(_ROOT, "data", "tradeHistroy.txt")
        lines = read_file_smart(path)
        trades, skipped = parse_trades(lines)

        # 没有价格 ≤ 0 的交易
        for t in trades:
            assert t["price"] > 0, f"价格 ≤ 0 未被过滤: {t}"

        # 没有配号
        for t in trades:
            assert "申购配号" not in t.get("ts_code", ""), "配号未过滤"