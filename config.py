"""全局配置"""
import os

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
DB_PATH     = os.path.join(DATA_DIR, "stock.db")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

# 回测默认参数
BACKTEST_DEFAULTS = {
    "lookback_days": 60,
    "forward_days": [5, 10, 20],       # 前向收益窗口
    "max_holding_days": 30,
    "stop_loss_pct": -8,
    "take_profit_pct": 20,
}

# 进化引擎默认参数网格 (全局)
EVOLUTION_PARAM_GRID = {
    "tpc_percentile":     [65, 70, 75, 80, 85],
    "winner_percentile":  [75, 80, 85, 90, 95],
    "entropy_percentile": [20, 25, 30, 35, 40],
    "p1_stab_threshold":  [1.0, 1.5, 2.0, 2.5, 3.0],
    "cmf_threshold":      [0.03, 0.05, 0.08, 0.10, 0.15],
}

# 进化引擎按信号类型的默认参数网格
EVOLUTION_DEFAULT_GRIDS = {
    "locking": {
        "min_conditions": [4, 5, 6],
    },
    "divergence": {
        "divergence_threshold": [20, 30, 40, 50, 60],
    },
    "build_divergence": {
        "tpc_percentile_threshold": [60, 65, 70, 75],
        "entropy_percentile_threshold": [30, 35, 40, 45, 50],
    },
    "dispatch": {
        "min_dispatch_score": [2, 3, 4],
    },
}

DB_URI = f"sqlite:///{DB_PATH}"

# 知识图谱 (已纳入项目, 随 git 同步)
# 默认读项目内的 knowledgeGraph/ 目录
# 可通过环境变量 KNOWLEDGE_GRAPH_DIR 覆盖, 用于指向其他位置
KNOWLEDGE_GRAPH_DIR = os.environ.get(
    "KNOWLEDGE_GRAPH_DIR",
    os.path.join(BASE_DIR, "knowledgeGraph"),
)
