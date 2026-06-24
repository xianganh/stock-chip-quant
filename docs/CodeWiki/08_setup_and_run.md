# 08. 安装与运行

## 📋 系统要求

| 项目 | 最低要求 | 推荐 |
|------|---------|------|
| 操作系统 | Windows 10 / macOS / Linux | Windows 11 |
| Python | 3.9 | 3.11+ |
| 内存 | 2 GB | 4 GB+ |
| 磁盘 | 500 MB | 1 GB+ |
| 网络 | 需要访问 Tushare API | 稳定网络 |

## 📦 依赖清单

完整列表见 [requirements.txt](../../requirements.txt)

```
flask>=3.0
flask-sqlalchemy>=3.1
python-dotenv>=1.0
pandas>=2.0
numpy>=1.24
tushare>=1.4
plotly>=5.18
kaleido>=0.2
```

开发依赖（[requirements-dev.txt](../../requirements-dev.txt)）：
```
pytest>=7.0
```

## 🔧 安装步骤

### 1. 克隆代码

```bash
git clone <repo-url> D:\stock\Analysis
cd D:\stock\Analysis
```

### 2. 创建虚拟环境（推荐）

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### 4. 配置 Tushare Token

**方式 1**: 环境变量（推荐）

```bash
# Windows PowerShell
$env:TUSHARE_TOKEN = "your_token_here"

# Windows CMD
set TUSHARE_TOKEN=your_token_here

# macOS / Linux
export TUSHARE_TOKEN="your_token_here"
```

**方式 2**: 配置文件

```bash
# 创建 ~/.config/tushare/token
mkdir -p ~/.config/tushare
echo "your_token_here" > ~/.config/tushare/token
```

**方式 3**: 旧路径

```bash
# 创建 ~/.tushare_token
echo "your_token_here" > ~/.tushare_token
```

**Token 来源**: https://tushare.pro/register

### 5. 配置 LLM（可选，仅 AI 解读需要）

创建 `~/.codebuddy/models.json`：

```json
{
  "models": [
    {
      "id": "gpt-4",
      "name": "GPT-4",
      "url": "https://api.openai.com/v1",
      "apiKey": "sk-..."
    }
  ],
  "availableModels": ["gpt-4"]
}
```

### 6. 配置 .env（可选）

复制模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
# Flask
FLASK_SECRET_KEY=auto-generated-if-not-set
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=0

# Tushare
TUSHARE_TOKEN=your_token_here

# Knowledge Graph
KNOWLEDGE_GRAPH_DIR=D:/stock/Analysis/knowledgeGraph
```

## 🚀 启动方式

### 方式 1: 直接启动

```bash
python app.py
```

### 方式 2: Windows 一键启动

双击 [start.bat](../../start.bat) 或：

```bash
start.bat
```

### 方式 3: 自定义配置

```bash
# 开发模式（自动 reload）
FLASK_DEBUG=1 python app.py

# 自定义端口
FLASK_PORT=8080 python app.py

# 允许外部访问（仅开发环境）
FLASK_HOST=0.0.0.0 FLASK_DEBUG=1 python app.py
```

## 🌐 访问应用

打开浏览器：

```
http://127.0.0.1:5000
```

### 页面导航

| 路径 | 功能 |
|------|------|
| `/` | 仪表盘主页（watchlist 概览） |
| `/watchlist` | 选股池管理 |
| `/analysis/<ts_code>` | 单只股票分析（如 `/analysis/000066.SZ`） |
| `/backtest` | 回测参数配置与结果 |

## 🧪 验证安装

### 1. 健康检查

```bash
curl http://127.0.0.1:5000/api/health
```

**期望响应**：
```json
{
  "status": "ok",
  "components": {
    "database": { "status": "ok", "watchlist_active": 0 },
    "tushare_token": { "status": "ok" }
  }
}
```

### 2. 测试套件

```bash
python -m pytest tests/ -v
```

**期望**: 38 个测试全部通过

### 3. 知识图谱检查

```bash
curl http://127.0.0.1:5000/api/knowledge_graph/stats
```

**期望**:
```json
{ "loaded": true, "companies": 50, "tags": 187 }
```

## 📊 数据初始化

### 首次运行

启动时 Flask 会自动：
1. 创建 `data/stock.db` SQLite 文件
2. 创建所有 7 张表（watchlist / analysis_snapshots / backtest_runs / backtest_trades / evolution_runs / positions / trade_logs）
3. 执行 `_migrate_schema()` 补齐缺失列
4. 生成 `.secret_key` 文件（如不存在）

### 导入历史交易（可选）

```bash
# 预览
python scripts/import_trades.py --dry-run

# 真实导入（先清空该账户的旧数据）
python scripts/import_trades.py
```

### 知识图谱初始化（可选）

如果 `knowledgeGraph/` 为空：

```bash
python scripts/setup_knowledge_graph.py
```

## 🔧 配置参考

### `config.py` 全局配置

```python
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
DB_PATH     = os.path.join(DATA_DIR, "stock.db")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

# 回测默认参数
BACKTEST_DEFAULTS = {
    "lookback_days": 60,
    "forward_days": [5, 10, 20],
    "max_holding_days": 30,
    "stop_loss_pct": -8,
    "take_profit_pct": 20,
}

# 进化引擎默认参数网格
EVOLUTION_PARAM_GRID = {
    "tpc_percentile":     [65, 70, 75, 80, 85],
    "winner_percentile":  [75, 80, 85, 90, 95],
    "entropy_percentile": [20, 25, 30, 35, 40],
    "p1_stab_threshold":  [1.0, 1.5, 2.0, 2.5, 3.0],
    "cmf_threshold":      [0.03, 0.05, 0.08, 0.10, 0.15],
}

EVOLUTION_DEFAULT_GRIDS = {
    "locking":         {"min_conditions": [4, 5, 6]},
    "divergence":      {"divergence_threshold": [20, 30, 40, 50, 60]},
    "build_divergence":{
        "tpc_percentile_threshold":   [60, 65, 70, 75],
        "entropy_percentile_threshold":[30, 35, 40, 45, 50],
    },
    "dispatch":        {"min_dispatch_score": [2, 3, 4]},
}

KNOWLEDGE_GRAPH_DIR = os.environ.get(
    "KNOWLEDGE_GRAPH_DIR",
    os.path.join(BASE_DIR, "knowledgeGraph"),
)
```

## 🐛 故障排查

### 错误: `ModuleNotFoundError: No module named 'flask'`

**原因**: 依赖未安装

**解决**:
```bash
pip install -r requirements.txt
```

### 错误: `Tushare token 未找到`

**原因**: Tushare token 未配置

**解决**: 见上文「配置 Tushare Token」

### 错误: `database is locked`

**原因**: SQLite 文件被其他进程占用

**解决**:
```bash
# 关闭所有访问 data/stock.db 的进程
# 或重启电脑
```

### 错误: `Address already in use`

**原因**: 5000 端口被占用

**解决**:
```bash
# 方式 1: 换端口
FLASK_PORT=8080 python app.py

# 方式 2: 杀掉占用进程
# Windows
netstat -ano | findstr :5000
taskkill /PID <pid> /F

# macOS / Linux
lsof -i :5000
kill -9 <pid>
```

### 错误: `LLM 调用失败 (HTTP 401)`

**原因**: CodeBuddy LLM API Key 无效

**解决**:
1. 检查 `~/.codebuddy/models.json` 配置
2. 重新获取 API Key

### 错误: 页面显示 500

**解决**:
1. 查看终端错误堆栈
2. 启动 debug 模式：`FLASK_DEBUG=1 python app.py`
3. API 错误会附带 `traceback` 字段

### 错误: `cyq_chips` 接口返回空

**原因**: 股票代码无效或 Tushare 权限不足

**解决**:
1. 验证股票代码（如 `curl http://127.0.0.1:5000/api/stock_lookup?q=000066`）
2. 检查 Tushare 账户权限（cyq_chips 需要 5000 积分）

## 🔄 重置数据库

```bash
# 关闭 Flask
# 删除数据库
rm data/stock.db
# 重启（自动重建）
python app.py
```

## 📦 部署到生产

### 使用 Gunicorn（Linux/macOS）

```bash
pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:5000 app:app
```

### 使用 Waitress（Windows）

```bash
pip install waitress
waitress-serve --port=5000 app:app
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name stock.example.com;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🔐 安全建议

1. **生产环境必须设置** `FLASK_SECRET_KEY`（环境变量）
2. **不要暴露** `0.0.0.0`（仅本地使用）
3. **定期备份** `data/stock.db`
4. **不要提交** `.env` 到 git（已在 .gitignore）
5. **LLM API Key** 存放在用户目录，不要硬编码

## 📞 进一步帮助

- 详细文档: [docs/RUNBOOK.md](../RUNBOOK.md)
- 数据模型: [docs/DATA_MODEL.md](../DATA_MODEL.md)
- 路线图: [docs/ROADMAP.md](../ROADMAP.md)
- Tushare 文档: https://tushare.pro/document/1
- Flask 文档: https://flask.palletsprojects.com/