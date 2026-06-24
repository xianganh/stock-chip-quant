# 筹码峰量化投研平台

基于 Tushare cyq_chips 全量筹码分布数据的量化分析平台，支持：

- **选股池管理** — 按预期差类型分类（涨价/订单/卡脖子/周期反转/估值调整）
- **筹码峰演化分析** — P1/P2/P3 峰位追踪、TPC 集中度、偏度/峰度/熵、形态识别
- **价格-筹码背离检测** — 三重背离验证 Layer1 逻辑预期差
- **经典量化指标** — CMF/ADX/ATR 辅助研判
- **回测引擎** — 事件驱动止损/止盈回测
- **进化引擎** — 参数网格搜索自动优化

## 快速启动

```bash
# 安装依赖
pip install flask flask-sqlalchemy plotly pandas numpy tushare

# 启动
cd D:\stock\Analysis
python app.py

# 或双击 start.bat
```

浏览器打开 http://127.0.0.1:5000

## 项目结构

```
Analysis/
├── app.py              # Flask Web 应用
├── config.py           # 全局配置
├── start.bat           # 一键启动
├── database/           # SQLite 数据层
├── engine/             # 回测引擎 + 进化引擎
├── scripts/            # 筹码分析核心 (analyze.py)
└── templates/          # Web 前端
```

## 数据源

Tushare Pro — cyq_chips / stk_factor / moneyflow / daily_basic
