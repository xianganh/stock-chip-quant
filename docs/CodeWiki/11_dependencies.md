# 11. 依赖说明

> 文件: [requirements.txt](../../requirements.txt) | [requirements-dev.txt](../../requirements-dev.txt)

## 📋 运行时依赖

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

### 依赖清单

| 库 | 版本 | 用途 | 在哪用 |
|----|------|------|--------|
| **Flask** | >= 3.0 | Web 框架 | [app.py](../../app.py) 整个 |
| **Flask-SQLAlchemy** | >= 3.1 | ORM 集成 | [app.py](../../app.py) + [database/](../../database/) |
| **python-dotenv** | >= 1.0 | .env 文件加载 | [app.py](../../app.py) 配置加载 |
| **pandas** | >= 2.0 | 数据处理 | [scripts/analyze.py](../../scripts/analyze.py) |
| **numpy** | >= 1.24 | 数值计算 | [scripts/analyze.py](../../scripts/analyze.py) |
| **tushare** | >= 1.4 | A 股数据 API | [utils.py](../../utils.py) + [analyze.py](../../scripts/analyze.py) |
| **plotly** | >= 5.18 | 前端图表（JS 库） | [templates/base.html](../../templates/base.html) |
| **kaleido** | >= 0.2 | 静态图表导出 | 未来静态图导出 |

## 🧪 开发依赖

[requirements-dev.txt](../../requirements-dev.txt):

```
pytest>=7.0
```

### 可选开发依赖

```bash
# 测试覆盖率
pip install pytest-cov

# 性能分析
pip install pytest-profiling

# Mock 库（如需）
pip install pytest-mock

# 并行测试
pip install pytest-xdist
```

---

## 🐍 Python 版本

- **最低**: Python 3.9
- **推荐**: Python 3.11+
- **测试环境**: Python 3.13

---

## 📦 依赖详解

### Flask 3.0

**核心 Web 框架**。

```python
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///data/stock.db"

@app.route("/")
def index():
    return render_template("index.html")
```

**使用的功能**:
- 路由系统
- Jinja2 模板
- JSON 响应（jsonify）
- 错误处理器（@app.errorhandler）
- before_request / after_request
- SECRET_KEY 配置

### Flask-SQLAlchemy 3.1

**ORM 集成层**。

```python
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

class Position(db.Model):
    __tablename__ = "positions"
    id = db.Column(db.Integer, primary_key=True)
    ...
```

**使用的功能**:
- 模型声明
- 查询接口（query.filter_by / query.first / query.all）
- 会话管理（db.session.add / db.session.commit）
- 关系（db.relationship）
- 索引（db.Index）
- 延迟加载（defer）

### python-dotenv 1.0

**.env 文件加载**。

```python
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 使用
token = os.environ.get("TUSHARE_TOKEN")
```

**.env.example 模板**:
```bash
FLASK_SECRET_KEY=
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=0
TUSHARE_TOKEN=
KNOWLEDGE_GRAPH_DIR=
```

### pandas 2.0

**数据处理核心库**。

```python
import pandas as pd

df = pro.cyq_chips(ts_code=ts_code, fields='ts_code,trade_date,price,percent')
df = df.sort_values("trade_date").reset_index(drop=True)
df["close"] = df["close"].astype(float)

# 合并
df_merged = df_factor.merge(df_mf, on=['ts_code', 'trade_date'], how='left')
```

**使用的功能**:
- DataFrame 创建
- 排序 / 重置索引
- 字段类型转换
- merge / join
- 缺失值处理（fillna）
- 布尔索引（df[df['price'] > close]）

### numpy 1.24

**数值计算核心库**。

```python
import numpy as np

# 局部极大值检测
for i in range(1, n - 1):
    if percents[i] > max(left_vals) and percents[i] > max(right_vals):
        raw_peaks.append((i, ...))

# 加权偏度
mu = np.average(prices, weights=percents)
sigma = np.sqrt(np.average((prices - mu) ** 2, weights=percents))
skewness = np.average((prices - mu) ** 3, weights=percents) / (sigma ** 3)

# 滚动分位数
ranks[i] = np.searchsorted(np.sort(lookback), series[i]) / len(lookback) * 100
```

**使用的功能**:
- ndarray 数组
- 向量化运算
- 加权平均（np.average）
- 排序（np.sort / np.argsort）
- 累积和（np.cumsum）
- 信息熵（-p * log2(p)）
- 峰度计算
- 滑动窗口

### tushare 1.4

**A 股数据 API**。

```python
import tushare as ts

ts.set_token(token)
pro = ts.pro_api()

# 筹码分布
df_chips = pro.cyq_chips(ts_code='000066.SZ', fields='ts_code,trade_date,price,percent')

# 技术指标
df_factor = pro.stk_factor(ts_code='000066.SZ', start_date='20240101', end_date='20260624')

# 资金流向
df_mf = pro.moneyflow(ts_code='000066.SZ', start_date='20240101', end_date='20260624')

# 每日基础指标
df_basic = pro.daily_basic(ts_code='000066.SZ', start_date='20240101', end_date='20260624')

# 日线
df = pro.daily(ts_code='000066.SZ', start_date='20240101', end_date='20260624',
               fields='ts_code,trade_date,open,high,low,close,vol,amount,pct_chg')

# 股票基础信息
df = pro.stock_basic(list_status='L', fields='ts_code,name,industry,area,market')
```

**使用的接口**:
- `cyq_chips` — 筹码分布直方图（5000 积分）
- `stk_factor` — K 线 + MACD/KDJ/RSI/BOLL
- `moneyflow` — 资金流向
- `daily_basic` — 换手率/量比/PE/PB
- `daily` — 日线行情
- `stock_basic` — 股票基础信息

**Token**: 通过 [utils.get_tushare_token()](../../utils.py#L19-L55) 加载

### plotly 5.18

**前端图表库**（仅 JS）。

```html
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
```

**用途**:
- 筹码分布图（histogram）
- 价格走势线（line）
- 趋势叠加（candlestick）
- 多子图布局

**不直接使用 Python plotly**，仅通过 CDN 引入 JS 版本。

### kaleido 0.2

**Plotly 静态图导出**（预留）。

```python
import plotly.io as pio
pio.kaleido.scope.default_format = "png"
fig.write_image("chart.png")
```

**当前状态**: 已声明依赖但未使用（未来用于导出静态图）。

---

## 🛠️ 内置 Python 模块

未在 requirements.txt 但代码中使用了：

| 模块 | 用途 |
|------|------|
| `argparse` | CLI 参数解析 |
| `json` | JSON 序列化/反序列化 |
| `os` | 文件路径 |
| `sys` | Python 路径 |
| `re` | 正则表达式 |
| `datetime` | 日期时间 |
| `time` | 时间戳 |
| `threading` | 线程锁（限流器）|
| `urllib.request` | HTTP 请求（LLM 调用）|
| `urllib.error` | HTTP 错误处理 |
| `functools` | lru_cache 缓存 |
| `pathlib` | 路径处理 |
| `itertools` | 参数组合（进化引擎）|
| `collections.defaultdict` | 默认字典 |
| `warnings` | 警告过滤 |

---

## 🌐 外部 CDN 资源

[templates/base.html](../../templates/base.html) 引入：

| 资源 | URL | 用途 |
|------|-----|------|
| Bootstrap CSS | `https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css` | UI 框架 |
| Bootstrap Icons | `https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css` | 图标 |
| Plotly JS | `https://cdn.plot.ly/plotly-2.32.0.min.js` | 图表 |

---

## 🔄 依赖升级策略

### 安全升级

```bash
# 检查过期依赖
pip list --outdated

# 升级（带测试）
pip install -U <package>
python -m pytest tests/ -v
```

### 大版本升级

| 包 | 当前 | 兼容性注意 |
|----|------|-----------|
| Flask | 3.0+ | breaking changes（较少）|
| pandas | 2.0+ | 弃用 append → concat |
| numpy | 1.24+ | np.float_ 已弃用 |
| tushare | 1.4+ | API 稳定 |

### 添加新依赖流程

1. 在 [requirements.txt](../../requirements.txt) 添加（带版本下限）
2. 更新本文件
3. 测试覆盖新功能
4. 提交说明

---

## 📊 依赖大小

| 类别 | 数量 | 备注 |
|------|------|------|
| 运行时依赖 | 8 | flask + flask-sqlalchemy + python-dotenv + pandas + numpy + tushare + plotly + kaleido |
| 开发依赖 | 1+ | pytest + 可选 |
| 内置模块 | ~15 | 标准库 |
| 外部 CDN | 3 | Bootstrap + Icons + Plotly |

---

## 🔐 依赖安全

### 已知 CVE

| 包 | CVE | 状态 |
|----|-----|------|
| Flask < 2.3.2 | CVE-2023-30861 | ✅ 已升级到 3.0+ |

### 定期检查

```bash
pip install safety
safety check
```

或使用 GitHub Dependabot 自动 PR。

---

## 📞 进一步阅读

- [Flask 文档](https://flask.palletsprojects.com/)
- [Flask-SQLAlchemy 文档](https://flask-sqlalchemy.palletsprojects.com/)
- [pandas 文档](https://pandas.pydata.org/)
- [numpy 文档](https://numpy.org/)
- [Tushare 文档](https://tushare.pro/document/1)
- [Plotly 文档](https://plotly.com/python/)