"""测试知识图谱集成"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


class TestKnowledgeGraph:
    """知识图谱集成测试"""

    def test_kg_directory_exists(self):
        """知识图谱目录存在"""
        from config import KNOWLEDGE_GRAPH_DIR
        assert os.path.isdir(KNOWLEDGE_GRAPH_DIR), \
            f"知识图谱目录不存在: {KNOWLEDGE_GRAPH_DIR}"

    def test_load_kg_returns_stats(self):
        """load_knowledge_graph 返回统计"""
        from utils import load_knowledge_graph
        result = load_knowledge_graph()
        stats = result["stats"]
        assert stats["available"] is True
        assert stats["companies"] > 0, "应该至少索引一家公司"
        print(f"  索引 {stats['companies']} 家公司, {stats['tags_count']} 个 tags")

    def test_get_kg_by_code(self):
        """按代码查询返回节点"""
        from utils import load_knowledge_graph, get_kg_by_code
        load_knowledge_graph()
        # 测试已知股票 (元力股份 300174)
        node = get_kg_by_code("300174")
        assert node is not None, "300174 应能找到"
        assert node["name"] == "元力股份"
        assert "活性炭" in node["tags"], "元力股份应该有 '活性炭' tag"

    def test_get_kg_by_code_with_suffix(self):
        """带 .SZ 后缀的代码也能匹配"""
        from utils import load_knowledge_graph, get_kg_by_code
        load_knowledge_graph()
        node1 = get_kg_by_code("300174")
        node2 = get_kg_by_code("300174.SZ")
        assert node1 == node2, "带后缀应等同于无后缀"

    def test_get_kg_unknown_returns_none(self):
        """未知股票返回 None"""
        from utils import load_knowledge_graph, get_kg_by_code
        load_knowledge_graph()
        assert get_kg_by_code("999999") is None

    def test_kg_stats_endpoint(self):
        """测试 stats API"""
        from app import app
        with app.test_client() as c:
            res = c.get("/api/knowledge_graph/stats")
            assert res.status_code == 200
            data = res.get_json()
            assert data["loaded"] is True
            assert data["companies"] > 0

    def test_kg_by_code_endpoint(self):
        """测试 by_code API"""
        from app import app
        with app.test_client() as c:
            # 已知股票
            res = c.get("/api/knowledge_graph/300174")
            assert res.status_code == 200
            data = res.get_json()
            assert data["found"] is True
            assert "tags" in data
            assert isinstance(data["tags"], list)
            # 带后缀
            res2 = c.get("/api/knowledge_graph/300174.SZ")
            assert res2.status_code == 200
            # 未知
            res3 = c.get("/api/knowledge_graph/999999")
            assert res3.status_code == 404