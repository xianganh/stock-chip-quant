"""测试 KG UI 集成 (watchlist 列 + analysis 卡片)"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


class TestKGUIRendering:
    """测试 KG 在 UI 中的渲染"""

    def test_watchlist_has_kg_column(self):
        """watchlist.html 有图谱列"""
        path = os.path.join(_ROOT, "templates", "watchlist.html")
        content = open(path, encoding="utf-8").read()
        assert "kg-cell" in content, "watchlist 应有 kg-cell 容器"
        assert "loadWatchlistKG" in content, "应有 loadWatchlistKG 函数"
        assert "📚 图谱" in content, "表头应有'📚 图谱'"

    def test_analysis_has_kg_card(self):
        """analysis.html 有 KG 摘要卡片"""
        path = os.path.join(_ROOT, "templates", "analysis.html")
        content = open(path, encoding="utf-8").read()
        assert "kgCard" in content, "应有 kgCard 容器"
        assert "loadKnowledgeGraphCard" in content, "应有 loadKnowledgeGraphCard 函数"
        assert "kgSummary" in content, "应有摘要区域"
        assert "kgTags" in content, "应有标签区域"
        assert "kgRelated" in content, "应有关联公司区域"

    def test_related_api_endpoint(self):
        """测试 /api/knowledge_graph/<code>/related 端点"""
        from app import app
        # 强制重新加载 KG
        from utils import _KG_LOADED, load_knowledge_graph
        if not _KG_LOADED:
            load_knowledge_graph()

        with app.test_client() as c:
            # 已知股票: 300174 元力股份有多个 tag
            res = c.get("/api/knowledge_graph/300174/related")
            assert res.status_code == 200
            data = res.get_json()
            assert "related" in data
            assert "tags" in data
            # 应该返回至少 1 个 tag 的关联公司
            assert len(data["related"]) > 0, "应该有关联公司"

    def test_related_api_unknown(self):
        """未知股票的关联查询"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/knowledge_graph/999999/related")
            assert res.status_code == 200
            data = res.get_json()
            assert data["related"] == {}
            assert data["tags"] == []

    def test_related_excludes_self(self):
        """关联查询不应包含自己"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/knowledge_graph/300174/related")
            data = res.get_json()
            for tag, stocks in data["related"].items():
                for s in stocks:
                    assert s["code"] != "300174", f"不应包含自己: {tag}"

    def test_watchlist_page_renders(self):
        """watchlist 页面能加载 (不报模板错误)"""
        from app import app
        with app.test_client() as c:
            res = c.get("/watchlist")
            assert res.status_code == 200

    def test_analysis_page_renders_with_kg(self):
        """analysis 页面能加载 (含 KG 卡片)"""
        from app import app
        with app.test_client() as c:
            # 用知识图谱中存在的股票
            res = c.get("/analysis/300174")
            assert res.status_code == 200