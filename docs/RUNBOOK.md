# 运维手册

> 最后更新: 2026-06-24

## 🚀 启动服务

### 开发模式
```bash
cd D:\stock\Analysis
python app.py
# 或双击 start.bat
```
访问 http://127.0.0.1:5000

### 切换调试模式
```bash
# 在 app.py 末尾修改
app.run(debug=True, ...)  # 自动重载 + 详细错误
```

### 指定端口
```bash
# 环境变量
set FLASK_PORT=8080
python app.py
```

---

## 🧪 测试

### 全部测试
```bash
python -m pytest tests/ -v
```

### 单文件测试
```bash
python -m pytest tests/test_positions.py -v
```

### 失败时详细输出
```bash
python -m pytest tests/ -v --tb=long
```

### 覆盖率 (需要 pytest-cov)
```bash
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=html
# 查看 htmlcov/index.html
```

---

## 📊 数据导入

### 导入券商交易文件
```bash
# 真实导入 (会先清空该账户的旧数据)
python scripts/import_trades.py

# 预览 (不入库)
python scripts/import_trades.py --dry-run
```

### watchlist 数据迁移
```bash
# 预览
python scripts/migrate_watchlist.py --dry-run

# 真实迁移
python scripts/migrate_watchlist.py
```

---

## 🔄 多电脑同步

### 场景: 在家用 Mac, 在公司用 Windows

**方案 A: 云盘同步 data 文件夹 (推荐)**
```
将 D:\stock\Analysis\data\ 放在 OneDrive / iCloud / Dropbox
├── 多台电脑自动同步
└── 注意: 同时打开两个 app 可能冲突 SQLite
```

**方案 B: 导出/导入脚本**
```bash
# 电脑 A
python scripts/export_data.py data_dump_20260624.json

# 同步 data_dump_20260624.json 到电脑 B (git/微信/邮件)

# 电脑 B
python scripts/import_data.py data_dump_20260624.json
```

### Git 同步代码
```bash
git pull              # 获取最新代码
git add -A && git commit -m "..."   # 提交修改
git push              # 推送到 GitHub
```

---

## 🔧 常见操作

### 查看 watchlist
```bash
# 命令行
sqlite3 data/stock.db "SELECT ts_code, name, category FROM watchlist WHERE active=1"

# 或浏览器
http://127.0.0.1:5000/watchlist
```

### 重置数据库 (慎用!)
```bash
# 删除数据库, 重新启动 app 会自动重建
rm data/stock.db
python app.py
```

### 单独跑 analyze (不需要 Flask)
```bash
cd scripts
python analyze.py 000066.SZ --days 14
```

### 单独跑导入测试
```bash
# 在 app.py 里加个临时端点或用 test_client
python -c "
from app import app
with app.test_client() as c:
    res = c.get('/api/health')
    print(res.get_json())
"
```

---

## 🐛 故障排查

### "Address already in use"
5000 端口被占用:
```bash
# 查找占用进程
netstat -ano | findstr :5000
# 结束进程 (替换 PID)
taskkill /F /PID <PID>
```

### Tushare 限流/认证失败
- 检查 `~/.config/tushare/token` 文件
- 检查 token 是否过期
- 查看 `/api/health` 的 tushare_token 状态

### 数据库迁移失败
启动时如果看到 ALTER TABLE 错误:
```bash
# 手动运行迁移函数
python -c "
from app import app, db, _migrate_schema
with app.app_context():
    _migrate_schema()
"
```

### 测试失败
```bash
# 看具体哪个测试失败
python -m pytest tests/ -v --tb=short

# 单独跑失败的测试
python -m pytest tests/test_xxx.py::TestClass::test_method -v
```

---

## 📁 关键文件位置

| 文件 | 说明 |
|------|------|
| `data/stock.db` | SQLite 数据库 |
| `data/tradeHistroy.txt` | 衡祥安账户历史 |
| `data/tradeHistroy_fz.txt` | 邱磊账户历史 |
| `~/.codebuddy/models.json` | LLM 配置 (用于 AI 解读) |
| `~/.config/tushare/token` | Tushare API token |
| `app.py` | Flask 主应用 |
| `scripts/analyze.py` | 核心算法 (v2.5) |
| `utils.py` | 共享工具 |
| `tests/` | pytest 测试 |

---

## 🔐 环境变量

| 变量 | 用途 | 示例 |
|------|------|------|
| `TUSHARE_TOKEN` | Tushare API | `sk-abc123...` |
| `FLASK_SECRET_KEY` | Flask session | `random_hex_32_chars` |
| `FLASK_HOST` | 绑定地址 | `0.0.0.0` |
| `FLASK_PORT` | 端口 | `5000` |

---

## 📊 性能调优

### 数据库索引 (已配置)
- `watchlist (ts_code)` UNIQUE
- `positions (account, ts_code, status)` 
- `trade_logs (ts_code, trade_date)`
- `trade_logs (account_holder, trade_date)`

### 缓存
- Tushare `stock_basic` 用 `@lru_cache` (单进程内)
- LLM 调用可以用 Redis 缓存 (未来)
- analysis_snapshots 数据库缓存 (已有)

---

## 🔄 备份策略

### 自动备份脚本 (建议加入 cron)
```python
# scripts/backup_db.py
import shutil, datetime
src = 'data/stock.db'
dst = f'data/backups/stock_{datetime.now():%Y%m%d_%H%M%S}.db'
shutil.copy2(src, dst)
# 保留最近 30 天
```

### Git 备份关键文件
```bash
git add PROJECT.md docs/
git commit -m "docs: 更新项目文档"
```

---

## 📞 紧急联系人

(项目由个人维护, 无外部依赖)

- Tushare 官方: https://tushare.pro/document/1
- Plotly 文档: https://plotly.com/python/
- CodeBuddy 文档: https://www.codebuddy.ai/docs