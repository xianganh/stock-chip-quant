"""
筹码峰量化投研平台 — Flask Web 应用
====================================
功能: 选股池管理 | 筹码峰分析 | 技术面辅助 | 回测验证 | 进化优化
"""
import json
import sys
import os
import logging
import numpy as np
from datetime import datetime

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("chip_quant")

# ── 加载 .env 文件（若存在）──
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass  # 未安装 python-dotenv 时跳过，使用系统环境变量

from flask import Flask, render_template, request, jsonify, Response

# 添加 scripts 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
from analyze import analyze as chip_analyze


def json_response(data, status=200):
    """处理 numpy 类型的 JSON 序列化"""
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.bool_,)): return bool(obj)
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return str(obj)
    return Response(json.dumps(data, ensure_ascii=False, cls=NpEncoder),
                    status=status, mimetype="application/json")


# normalize_ts_code 已在 utils.py 中定义
from utils import normalize_ts_code, SimpleRateLimiter, RateLimitExceeded

from database import db, DBManager
from database.models import (
    Watchlist, AnalysisSnapshot, BacktestRun,
    Position, TradeLog,
)
from engine import BacktestEngine, EvolutionEngine

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(os.path.dirname(__file__), "data", "stock.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# SECRET_KEY: 1.环境变量 2..secret_key 文件(自动生成,跨重启持久) 3.os.urandom
_sk = os.environ.get("FLASK_SECRET_KEY")
if not _sk:
    _sk_file = os.path.join(os.path.dirname(__file__), "data", ".secret_key")
    try:
        if os.path.exists(_sk_file):
            _sk = open(_sk_file).read().strip()
        else:
            _sk = os.urandom(32).hex()
            os.makedirs(os.path.dirname(_sk_file), exist_ok=True)
            with open(_sk_file, "w") as f:
                f.write(_sk)
    except OSError:
        _sk = os.urandom(32).hex()
app.config["SECRET_KEY"] = _sk

# 模块级单例: AI 解读 force 重新生成的限流器 (避免并发竞态)
_force_limiter = SimpleRateLimiter(window_seconds=60, max_calls=1)

db.init_app(app)


# ── 轻量级 schema 迁移函数 ── 必须在 app.app_context() 之前定义 ──
def _migrate_schema():
    """补齐 model 中已声明但 DB 中不存在的列(避免丢数据)"""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)

    # ── analysis_snapshots 表 ──
    if insp.has_table("analysis_snapshots"):
        existing_cols = {c["name"] for c in insp.get_columns("analysis_snapshots")}
        new_cols = {
            "interpretation":    "TEXT",
            "interpretation_at": "DATETIME",
        }
        for col, col_type in new_cols.items():
            if col not in existing_cols:
                logger.info("ADD COLUMN analysis_snapshots.%s %s", col, col_type)
                db.session.execute(text(f"ALTER TABLE analysis_snapshots ADD COLUMN {col} {col_type}"))
                db.session.commit()


# 创建表 + 自动迁移
with app.app_context():
    db.create_all()
    _migrate_schema()


# ══════════════════════════════════════════════════════
# 页面路由
# ══════════════════════════════════════════════════════

@app.route("/")
def index():
    """仪表盘主页"""
    watchlist = DBManager.get_watchlist()
    return render_template("index.html", watchlist=watchlist)


@app.route("/watchlist")
def watchlist_page():
    """选股池管理"""
    stocks = DBManager.get_watchlist()
    return render_template("watchlist.html", stocks=stocks)


# ══════════════════════════════════════════════════════
# 复盘中心 (Phase 3)
# ══════════════════════════════════════════════════════

@app.route("/review")
def review_page():
    """复盘中心 - 偏差分析仪表板"""
    return render_template("review.html")


@app.route("/api/review/stats", methods=["GET"])
def api_review_stats():
    """
    复盘统计总览

    返回:
      - total: 已回放 position 数
      - algorithmic_agree / disagree / warn / data_insufficient: 偏差分布
      - by_action: 入场 Action 分布
      - by_outcome: 实际盈亏分布
      - by_lock_score: 按锁仓评分分组的胜率
      - by_dispatch_score: 按派发评分分组的胜率
      - by_tpc_bucket: 按 TPC 分桶的胜率
    """
    positions = Position.query.filter(Position.algorithm_signal.isnot(None)).all()
    if not positions:
        return jsonify({"error": "尚无回放数据，请先运行批量回放", "total": 0})

    stats = {
        "total": len(positions),
        "algorithmic_agree": 0,
        "algorithmic_disagree": 0,
        "algorithmic_warn": 0,
        "data_insufficient": 0,
        "by_action": {},
        "by_outcome": {},
        "by_lock_score": {},
        "by_dispatch_score": {},
        "by_tpc_bucket": {},
        "total_pnl": 0,
    }

    for p in positions:
        if not p.algorithm_signal:
            continue
        try:
            sig = json.loads(p.algorithm_signal)
        except (json.JSONDecodeError, TypeError):
            continue

        dev = sig.get("deviation", {})
        verdict = dev.get("verdict", "data_insufficient")
        if verdict in stats:
            stats[verdict] += 1

        # Action 分布
        entry = sig.get("entry_signal", {})
        action = entry.get("action", "unknown") if entry else "unknown"
        stats["by_action"][action] = stats["by_action"].get(action, 0) + 1

        # Outcome 分布
        pnl = p.realized_pnl_pct or 0
        if pnl > 2:
            outcome = "盈利"
        elif pnl < -2:
            outcome = "亏损"
        else:
            outcome = "持平"
        stats["by_outcome"][outcome] = stats["by_outcome"].get(outcome, 0) + 1
        stats["total_pnl"] += pnl

        # 按入场日锁仓评分分组
        lock_score = "?"
        if entry and entry.get("scores"):
            lock_tuple = entry["scores"].get("lock", [0, 6])
            lock_score = f"{lock_tuple[0]}/{lock_tuple[1]}"
        if lock_score not in stats["by_lock_score"]:
            stats["by_lock_score"][lock_score] = {"count": 0, "pnl_sum": 0, "win_count": 0}
        stats["by_lock_score"][lock_score]["count"] += 1
        stats["by_lock_score"][lock_score]["pnl_sum"] += pnl
        if pnl > 0:
            stats["by_lock_score"][lock_score]["win_count"] += 1

        # 按派发评分分组
        dispatch = "?"
        if entry and entry.get("scores"):
            dispatch = entry["scores"].get("dispatch", 0)
        dispatch_bucket = f"D{dispatch}"
        if dispatch_bucket not in stats["by_dispatch_score"]:
            stats["by_dispatch_score"][dispatch_bucket] = {"count": 0, "pnl_sum": 0, "win_count": 0}
        stats["by_dispatch_score"][dispatch_bucket]["count"] += 1
        stats["by_dispatch_score"][dispatch_bucket]["pnl_sum"] += pnl
        if pnl > 0:
            stats["by_dispatch_score"][dispatch_bucket]["win_count"] += 1

        # 按 TPC 分桶
        tpc = 0
        if entry and entry.get("scores"):
            tpc = entry["scores"].get("tpc", 0)
        tpc_bucket = f"{int(tpc // 5) * 5}-{int(tpc // 5) * 5 + 5}%"
        if tpc_bucket not in stats["by_tpc_bucket"]:
            stats["by_tpc_bucket"][tpc_bucket] = {"count": 0, "pnl_sum": 0, "win_count": 0}
        stats["by_tpc_bucket"][tpc_bucket]["count"] += 1
        stats["by_tpc_bucket"][tpc_bucket]["pnl_sum"] += pnl
        if pnl > 0:
            stats["by_tpc_bucket"][tpc_bucket]["win_count"] += 1

    # 计算胜率
    for group in [stats["by_lock_score"], stats["by_dispatch_score"], stats["by_tpc_bucket"]]:
        for k, v in group.items():
            if v["count"] > 0:
                v["win_rate"] = round(v["win_count"] / v["count"] * 100, 1)
                v["avg_pnl"] = round(v["pnl_sum"] / v["count"], 2)
            else:
                v["win_rate"] = 0
                v["avg_pnl"] = 0

    return jsonify(stats)


@app.route("/api/review/list", methods=["GET"])
def api_review_list():
    """获取所有已回放 position 的列表"""
    account = request.args.get("account")
    verdict_filter = request.args.get("verdict")
    limit = request.args.get("limit", 100, type=int)

    query = Position.query.filter(Position.algorithm_signal.isnot(None))
    if account:
        query = query.filter_by(account=account)

    positions = query.order_by(Position.entry_date.desc()).limit(limit).all()

    results = []
    for p in positions:
        if not p.algorithm_signal:
            continue
        try:
            sig = json.loads(p.algorithm_signal)
        except (json.JSONDecodeError, TypeError):
            continue

        dev = sig.get("deviation", {})
        if verdict_filter and dev.get("verdict") != verdict_filter:
            continue

        entry = sig.get("entry_signal", {})
        results.append({
            "id": p.id,
            "ts_code": p.ts_code,
            "name": p.name or "",
            "account": p.account or "",
            "entry_date": p.entry_date,
            "exit_date": p.exit_date,
            "entry_action": entry.get("action", "?") if entry else "?",
            "entry_confidence": entry.get("confidence", 0) if entry else 0,
            "actual_pnl_pct": p.realized_pnl_pct or 0,
            "deviation_verdict": dev.get("verdict", "?"),
            "actual_outcome": dev.get("actual_outcome", "?"),
            "holding_days": sig.get("holding_days", 0),
            "replayed_at": sig.get("replayed_at", ""),
        })

    return jsonify(results)


@app.route("/api/review/detail/<int:position_id>", methods=["GET"])
def api_review_detail(position_id):
    """获取单个 position 的完整回放详情"""
    pos = Position.query.get(position_id)
    if not pos or not pos.algorithm_signal:
        return jsonify({"error": "Position 不存在或未回放"}), 404

    try:
        sig = json.loads(pos.algorithm_signal)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "algorithm_signal 数据损坏"}), 500

    return jsonify({
        "id": pos.id,
        "ts_code": pos.ts_code,
        "name": pos.name or "",
        "account": pos.account or "",
        "entry_date": pos.entry_date,
        "exit_date": pos.exit_date,
        "entry_price": pos.entry_price,
        "exit_price": pos.exit_price,
        "realized_pnl_pct": pos.realized_pnl_pct,
        "signal": sig,
    })


@app.route("/api/replay/run", methods=["POST"])
def api_replay_run():
    """
    触发批量回放 (同步执行，未来可改为异步任务)

    Body:
      {
        "ts_codes": ["603773.SH", "603039.SH"],   // 可选，逗号分隔或列表
        "account": "衡祥安",                       // 可选
        "status": "closed",                        // 可选
        "limit": 20,                               // 默认 20
        "dry_run": false                           // 默认 false
      }
    """
    from utils import normalize_ts_code
    from engine.replay_engine import ReplayEngine

    data = request.json or {}
    ts_codes = data.get("ts_codes", "")
    account = data.get("account", "")
    status = data.get("status", "closed")
    limit = data.get("limit", 20)
    dry_run = data.get("dry_run", False)

    # 筛选 positions
    query = Position.query.filter(Position.algorithm_signal.is_(None))  # 默认只回放未回放过的
    if account:
        query = query.filter_by(account=account)
    if status:
        query = query.filter_by(status=status)
    if ts_codes:
        if isinstance(ts_codes, str):
            codes = [normalize_ts_code(c.strip()) for c in ts_codes.split(",")]
        else:
            codes = [normalize_ts_code(c) for c in ts_codes]
        query = query.filter(Position.ts_code.in_(codes))
    query = query.order_by(Position.entry_date.desc())
    if limit:
        query = query.limit(limit)
    positions = query.all()

    if not positions:
        return jsonify({"ok": True, "replayed": 0, "message": "没有待回放的 position"})

    engine = ReplayEngine(verbose=False)
    replayed = 0
    errors = []
    for pos in positions:
        try:
            ts_code = normalize_ts_code(pos.ts_code)
            result = engine.replay_position(
                ts_code=ts_code,
                entry_date=pos.entry_date,
                exit_date=pos.exit_date,
            )
            if pos.realized_pnl_pct is not None:
                result.set_actual_pnl(pos.realized_pnl_pct)

            if not dry_run:
                payload = {
                    "version": "v1",
                    "replayed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_signal": result.entry_signal,
                    "exit_signal": result.exit_signal,
                    "daily_signals": result.daily_signals,
                    "action_distribution": result.get_action_distribution(),
                    "deviation": result.compute_deviation(),
                    "holding_days": result.holding_days,
                }
                pos.algorithm_signal = json.dumps(payload, ensure_ascii=False, default=str)
                if result.entry_signal:
                    pos.algorithm_verdict = result.entry_signal.get("action", "")
            replayed += 1
        except Exception as e:
            errors.append({"position_id": pos.id, "ts_code": pos.ts_code, "error": str(e)})

    if not dry_run:
        db.session.commit()

    return jsonify({
        "ok": True,
        "replayed": replayed,
        "errors": errors,
        "stats": engine.stats,
    })


@app.after_request
def add_no_cache_headers(response):
    """防止浏览器/IDE Preview 缓存分析页和 API"""
    if request.path.startswith('/analysis/') or request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.route("/analysis/<ts_code>")
def analysis_page(ts_code):
    """单只股票分析 — 服务端预渲染数据,绕过浏览器 fetch 阻塞问题"""
    from utils import compute_verdict, normalize_ts_code
    ts_code = normalize_ts_code(ts_code)
    page_version = datetime.now().strftime('%H%M%S')  # 版本戳 — 防止缓存
    initial_data = None
    initial_error = None
    stock_name = ""
    server_verdict_html = ""
    server_dim_html = ""
    server_snapshot_html = ""
    try:
        result = chip_analyze(ts_code, days=14)
        if "error" not in result:
            # 转换 numpy 类型 → Python 原生类型
            initial_data = _to_native(result)
            # 计算 verdict
            try:
                v = compute_verdict(result)
                v["confidence"] = int(v.get("confidence", 0))
                scores = v.get("scores", {})
                if isinstance(scores.get("lock"), (list, tuple)):
                    scores["lock"] = [int(scores["lock"][0]), int(scores["lock"][1])]
                for sk in ("dispatch","divergence_strong","divergence_active"):
                    scores[sk] = int(scores.get(sk, 0))
                scores["tpc"] = float(scores.get("tpc", 0))
                initial_data["verdict"] = v
                server_verdict_html = _render_verdict_html(v)
            except Exception as e2:
                logger.exception("verdict render failed: %s", e2)
            # 服务端渲染三维卡片 (不依赖 JS)
            try:
                server_dim_html = _render_dim_cards_html(initial_data)
            except Exception as e3:
                logger.exception("dim render failed: %s", e3)
            try:
                server_snapshot_html = _render_snapshot_html(initial_data)
            except Exception as e4:
                logger.exception("snapshot render failed: %s", e4)
        else:
            initial_error = result["error"]
    except Exception as e:
        initial_error = f"{type(e).__name__}: {e}"
    try:
        from utils import get_stock_basic_list
        for s in get_stock_basic_list():
            if s.get("ts_code") == ts_code:
                stock_name = s.get("name", "")
                break
    except Exception:
        pass
    return render_template(
        "analysis.html",
        ts_code=ts_code,
        stock_name=stock_name,
        initial_data=initial_data,
        initial_error=initial_error,
        page_version=page_version,
        server_verdict_html=server_verdict_html,
        server_dim_html=server_dim_html,
        server_snapshot_html=server_snapshot_html,
    )


def _to_native(obj):
    """递归转换 numpy/pandas 类型到 Python 原生类型,用于 JSON 序列化"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _render_verdict_html(verdict):
    """服务端渲染 verdict 卡片 HTML (不依赖 JS)"""
    action = verdict.get("action", "观望")
    confidence = verdict.get("confidence", 50)
    color = verdict.get("color", "gray")
    reasons = verdict.get("reasons", [])
    reasons_html = "".join(f"<li>{r}</li>" for r in reasons)
    reasons_li = f'<ul class="hero-reasons">{reasons_html}</ul>' if reasons_html else '<ul class="hero-reasons"></ul>'
    return f'''<div class="hero-left">
        <div class="hero-label">综合判定</div>
        <div class="hero-action {color}">{action}</div>
    </div>
    <div class="hero-right">
        <div class="hero-meta">
            <span class="hero-badge no-hold">数据已加载</span>
            <span class="hero-confidence">置信度 <b>{confidence}%</b></span>
        </div>
        <div class="hero-bar-wrap">
            <div class="hero-bar"><div class="hero-bar-fill {color}" style="width:{confidence}%"></div></div>
            <span class="hero-bar-pct text-muted">{confidence}%</span>
        </div>
        {reasons_li}
    </div>'''


def _render_snapshot_html(d):
    """服务端渲染行情快照条 HTML"""
    ps = d.get("price_summary", {})
    ce = d.get("chip_evolution", {})
    ta = d.get("tech_analysis", {})
    dv = d.get("divergence_signals", {})
    cls = "text-green" if ps.get("period_pct", 0) > 0 else "text-red"
    return f'''<div class="snap-item"><div class="snap-val text-green">{ps.get("latest_close","-")}</div><div class="snap-lbl">收盘价</div></div>
    <div class="snap-item"><div class="snap-val {cls}">{ps.get("period_pct",0):+.2f}%</div><div class="snap-lbl">区间涨幅</div></div>
    <div class="snap-item"><div class="snap-val text-yellow">{ce.get("locking_assessment",{}).get("overall","-")}</div><div class="snap-lbl">锁仓</div></div>
    <div class="snap-item"><div class="snap-val">{dv.get("verdict","-")}</div><div class="snap-lbl">背离</div></div>
    <div class="snap-item"><div class="snap-val">{ta.get("momentum",{}).get("score","-")}/5</div><div class="snap-lbl">动量</div></div>
    <div class="snap-item"><div class="snap-val">{ta.get("trend",{}).get("score","-")}/5</div><div class="snap-lbl">趋势</div></div>
    <div class="snap-item"><div class="snap-val text-red">{ps.get("period_high","-")}</div><div class="snap-lbl">最高</div></div>
    <div class="snap-item"><div class="snap-val text-green">{ps.get("period_low","-")}</div><div class="snap-lbl">最低</div></div>'''


def _render_dim_cards_html(d):
    """服务端渲染三维卡片 HTML (简化版, 关键指标 + 结论)"""
    ce = d.get("chip_evolution", {})
    records = ce.get("daily_records", [])
    latest = records[-1] if records else {}
    locking = ce.get("locking_assessment", {})
    dispatch = ce.get("dispatch_score", {})
    divergence = d.get("divergence_signals", {})
    ta = d.get("tech_analysis", {})
    ci = d.get("classic_indicators", {})
    tech_score = ta.get("weighted", 0)

    # 筹码结构卡片
    tpc = latest.get("tpc", 0)
    p1_pct = latest.get("p1_pct", 0)
    winner = latest.get("winner", 0)
    chip_lines = [
        f'<tr><td class="t-name">P1 主峰位<span class="t-abbr">p1</span></td><td class="t-val">{latest.get("p1","—")} 元</td><td class="t-mean">筹码最集中价位</td></tr>',
        f'<tr><td class="t-name">P1 主峰占比<span class="t-abbr">p1_pct</span></td><td class="t-val">{p1_pct:.2f}%</td><td class="t-mean">≥12% 强势控盘</td></tr>',
        f'<tr><td class="t-name">TPC 三峰集中度<span class="t-abbr">tpc</span></td><td class="t-val">{tpc:.2f}%</td><td class="t-mean">≥25% 高度集中</td></tr>',
        f'<tr><td class="t-name">Top5 集中度<span class="t-abbr">top5</span></td><td class="t-val">{latest.get("top5",0):.2f}%</td><td class="t-mean">前5价位筹码占比</td></tr>',
        f'<tr><td class="t-name">Winner 获利盘<span class="t-abbr">winner</span></td><td class="t-val">{winner:.2f}%</td><td class="t-mean">&gt;80% 有回调压力</td></tr>',
        f'<tr><td class="t-name">加权成本<span class="t-abbr">weight_avg</span></td><td class="t-val">{latest.get("weight_avg","—")} 元</td><td class="t-mean">筹码加权均价</td></tr>',
        f'<tr><td class="t-name">偏度<span class="t-abbr">skewness</span></td><td class="t-val">{latest.get("skewness","—")}</td><td class="t-mean">&gt;0右偏, &lt;0左偏</td></tr>',
        f'<tr><td class="t-name">熵<span class="t-abbr">entropy</span></td><td class="t-val">{latest.get("entropy","—")}</td><td class="t-mean">越小越有序集中</td></tr>',
        f'<tr><td class="t-name">形态<span class="t-abbr">morphology</span></td><td class="t-val">{latest.get("morphology","—")}</td><td class="t-mean">单峰/双峰/多峰发散</td></tr>',
    ]
    if tpc >= 25 and p1_pct >= 12:
        chip_concl = f"<b class='text-green'>筹码高度集中</b>, 主力建仓完毕, P1占比 {p1_pct:.1f}% 健康。"
    elif tpc >= 15:
        chip_concl = f"<b class='text-yellow'>筹码中等集中</b> (TPC {tpc:.1f}%), 主力仍在收集阶段。"
    else:
        chip_concl = f"<b class='text-red'>筹码分散</b> (TPC {tpc:.1f}%), 缺乏主力介入。"
    chip_html = f'''<div class="dim-card-header"><span class="dim-icon">🔬</span><span class="dim-title">筹码结构</span><span class="dim-sub">{latest.get("morphology","—")}</span></div>
    <div class="dim-card-body"><table class="mini-tbl"><thead><tr><th>指标</th><th>数值</th><th>含义</th></tr></thead><tbody>{"".join(chip_lines)}</tbody></table></div>
    <div class="dim-subsection"><div class="dim-subtitle">📝 结论</div><div class="dim-conclusion">{chip_concl}</div></div>'''

    # 主力动向卡片
    lock_score = locking.get("locked_score", "0/6")
    lock_overall = locking.get("overall", "—")
    lock_passed = int(lock_score.split("/")[0]) if "/" in lock_score else 0
    dim_names = {"p1":"P1集中度","tp3":"三峰集中","dist":"分布形状","top5":"Top5","winner":"获利盘","tpc":"TPC集中"}
    lock_lines = []
    for k, vn in dim_names.items():
        v = locking.get(k, {})
        if isinstance(v, dict):
            verdict_text = v.get("verdict", "")
            passed = "满足" in verdict_text
            mark = '✅' if passed else '❌'
            lock_lines.append(f'<tr><td class="t-name">{vn}</td><td class="t-val">{mark} {"满足" if passed else "不满足"}</td><td class="t-mean">{verdict_text[:50]}</td></tr>')
    if lock_passed >= 5:
        lock_concl = f"<b class='text-green'>主力高度锁仓</b> ({lock_score}), 适合持仓等待。"
    elif lock_passed >= 3:
        lock_concl = f"<b class='text-yellow'>主力基本控盘</b> ({lock_score}), 部分维度未满足。"
    else:
        lock_concl = f"<b class='text-red'>锁仓偏弱</b> ({lock_score}), 主力未稳定持仓。"
    main_html = f'''<div class="dim-card-header"><span class="dim-icon">🎯</span><span class="dim-title">主力动向</span><span class="dim-sub">{lock_score}</span></div>
    <div class="dim-card-body"><table class="mini-tbl"><thead><tr><th>维度</th><th>判定</th><th>解读</th></tr></thead><tbody>{"".join(lock_lines) if lock_lines else '<tr><td colspan="3" class="text-muted">无数据</td></tr>'}</tbody></table></div>
    <div class="dim-subsection"><div class="dim-subtitle">📝 结论</div><div class="dim-conclusion">{lock_concl}</div></div>'''

    # 风险评估卡片
    dispatch_total = dispatch.get("total", 0)
    div_strong = divergence.get("strong_count", 0)
    risk_lines = []
    for k, v in dispatch.items():
        if k in ("total","verdict") or not isinstance(v, dict):
            continue
        risk_lines.append(f'<tr><td class="t-name">{v.get("label",k)}</td><td class="t-val">{v.get("verdict","—")}</td><td class="t-mean">{(v.get("interpretation","") or "")[:40]}</td></tr>')
    if dispatch_total >= 4:
        risk_concl = f"<b class='text-red'>高风险</b>: 派发 {dispatch_total}/5, 建议减仓或清仓。"
    elif dispatch_total >= 2:
        risk_concl = f"<b class='text-yellow'>中等风险</b>: 派发 {dispatch_total}/5, 有出货迹象, 设好止损。"
    else:
        risk_concl = f"<b class='text-green'>低风险</b>: 派发 {dispatch_total}/5, 无明显顶部信号。"
    if div_strong >= 2:
        risk_concl += f" <span class='text-red'>背离信号 {div_strong} 类, 警惕方向。</span>"
    cmf = ci.get("cmf", {})
    adx = ci.get("adx", {})
    atr = ci.get("atr", {})
    tech_lines = [
        f'<tr><td class="t-name">动量</td><td class="t-val">{ta.get("momentum",{}).get("score","-")}/5</td><td class="t-mean">{ta.get("momentum",{}).get("label","—")}</td></tr>',
        f'<tr><td class="t-name">趋势</td><td class="t-val">{ta.get("trend",{}).get("score","-")}/5</td><td class="t-mean">{ta.get("trend",{}).get("label","—")}</td></tr>',
        f'<tr><td class="t-name">CMF 资金流</td><td class="t-val">{cmf.get("latest","—")}</td><td class="t-mean">{cmf.get("signal","—")}</td></tr>',
        f'<tr><td class="t-name">ADX 趋势</td><td class="t-val">{adx.get("latest_adx","—")}</td><td class="t-mean">{adx.get("direction","—")}</td></tr>',
    ]
    risk_html = f'''<div class="dim-card-header"><span class="dim-icon">🛡️</span><span class="dim-title">风险评估</span><span class="dim-sub">{dispatch.get("verdict","—")}</span></div>
    <div class="dim-card-body"><table class="mini-tbl"><thead><tr><th>指标</th><th>判定</th><th>解读</th></tr></thead><tbody>{"".join(risk_lines) if risk_lines else '<tr><td colspan="3" class="text-muted">无数据</td></tr>'}</tbody></table></div>
    <div class="dim-subsection"><div class="dim-subtitle">📈 技术面</div><table class="mini-tbl"><thead><tr><th>指标</th><th>数值</th><th>判定</th></tr></thead><tbody>{"".join(tech_lines)}</tbody></table></div>
    <div class="dim-subsection"><div class="dim-subtitle">📝 结论</div><div class="dim-conclusion">{risk_concl}</div></div>'''

    return chip_html + "|||" + main_html + "|||" + risk_html


@app.route("/backtest")
def backtest_page():
    """回测页面"""
    watchlist = DBManager.get_watchlist()
    return render_template("backtest.html", watchlist=watchlist, now=datetime.now().strftime("%Y%m%d"))


# ══════════════════════════════════════════════════════
# API 路由
# ══════════════════════════════════════════════════════

# ── 选股池 API ──

@app.route("/api/watchlist", methods=["GET"])
def api_get_watchlist():
    return jsonify(DBManager.get_watchlist())


@app.route("/api/watchlist", methods=["POST"])
def api_add_stock():
    data = request.json
    ts_code = data.get("ts_code", "").strip()
    if not ts_code:
        return jsonify({"error": "请输入股票代码"}), 400
    # ★ 自动 normalize: 000066 → 000066.SZ (确保存储格式一致)
    ts_code = normalize_ts_code(ts_code)
    DBManager.add_stock(
        ts_code=ts_code,
        name=data.get("name", ""),
        notes=data.get("notes", ""),
        category=data.get("category", ""),
    )
    return jsonify({"ok": True, "ts_code": ts_code})


@app.route("/api/watchlist/<ts_code>", methods=["DELETE"])
def api_remove_stock(ts_code):
    """
    删除选股 (一键硬删除, 历史交易记录保留)
    兼容带/不带后缀格式
    """
    # 统计关联数据 (告知用户)
    candidates = {ts_code, normalize_ts_code(ts_code)}
    target = None
    for code in candidates:
        target = Watchlist.query.filter_by(ts_code=code).first()
        if target:
            break
    if not target:
        return jsonify({"error": "未找到该股票"}), 404

    linked_positions = Position.query.filter_by(watchlist_id=target.id).count()
    trade_logs = TradeLog.query.filter_by(ts_code=target.ts_code).count()

    # 清除 FK 引用 (保留历史交易记录和持仓)
    if linked_positions > 0:
        Position.query.filter_by(watchlist_id=target.id).update(
            {Position.watchlist_id: None}, synchronize_session=False
        )

    deleted_code = target.ts_code
    db.session.delete(target)
    db.session.commit()

    return jsonify({
        "ok": True,
        "deleted": deleted_code,
        "positions_unlinked": linked_positions,
        "trade_logs_kept": trade_logs,
    })


@app.route("/api/watchlist/<ts_code>", methods=["PUT"])
def api_update_stock(ts_code):
    """
    更新自选股备注/分类/名称
    Body: {"name": "...", "notes": "...", "category": "..."}
    """
    data = request.json or {}
    candidates = {ts_code, normalize_ts_code(ts_code)}
    target = None
    for code in candidates:
        target = Watchlist.query.filter_by(ts_code=code).first()
        if target:
            break
    if not target:
        return jsonify({"error": "股票不在选股池中，请先添加"}), 404
    if data.get("name") is not None: target.name = data["name"]
    if data.get("notes") is not None: target.notes = data["notes"]
    if data.get("category") is not None: target.category = data["category"]
    db.session.commit()
    return jsonify({"ok": True})


# ── 分析 API ──

@app.route("/api/analyze/<ts_code>", methods=["GET"])
def api_analyze(ts_code):
    """运行筹码峰分析"""
    days = request.args.get("days", 14, type=int)
    # 自动补全交易所后缀 (兼容 000066 / 000066.SZ 两种输入)
    ts_code = normalize_ts_code(ts_code)
    try:
        result = chip_analyze(ts_code, days=days)
        if "error" in result:
            return jsonify(result), 400

        # 保存快照到数据库
        meta = result.get("meta", {})
        trade_date = meta.get("date_range", "").split(" ~ ")[-1] if "date_range" in meta else ""
        ce = result.get("chip_evolution", {})
        ta = result.get("tech_analysis", {})
        dv = result.get("divergence_signals", {})
        ci = result.get("classic_indicators", {})
        latest = ce.get("daily_records", [{}])[-1] if ce.get("daily_records") else {}

        metrics = {
            "p1": latest.get("p1"), "p1_pct": latest.get("p1_pct"),
            "tpc": latest.get("tpc"), "top5": latest.get("top5"),
            "width_90": latest.get("width_90"), "winner": latest.get("winner"),
            "dist": latest.get("dist"), "skewness": latest.get("skewness"),
            "kurtosis": latest.get("kurtosis"), "entropy": latest.get("entropy"),
            "morphology": latest.get("morphology"), "n_peaks": latest.get("n_peaks"),
            "cmf": ci.get("cmf", {}).get("latest"),
            "adx": ci.get("adx", {}).get("latest_adx"),
            "atr_pct": ci.get("atr", {}).get("atr_pct_of_price"),
            "momentum_score": ta.get("momentum", {}).get("score"),
            "trend_score": ta.get("trend", {}).get("score"),
            "reversal_score": ta.get("reversal", {}).get("score"),
            "weighted_score": ta.get("weighted"),
            "divergence_score": dv.get("total_score"),
            "divergence_verdict": dv.get("verdict"),
        }

        if trade_date:
            DBManager.save_snapshot(ts_code, trade_date, metrics, result)

        return json_response(result)
    except Exception as e:
        # 响应: debug 模式附带堆栈 (开发用), 生产环境仅暴露异常类型+消息
        import traceback
        payload = {"error": f"{type(e).__name__}: {e}", "ts_code": ts_code}
        if app.debug:
            payload["traceback"] = traceback.format_exc().split("\n")
        return json_response(payload, 500)


@app.route("/api/snapshots/<ts_code>", methods=["GET"])
def api_get_snapshots(ts_code):
    """获取历史快照"""
    limit = request.args.get("limit", 60, type=int)
    snaps = DBManager.get_snapshots(ts_code, limit=limit)
    return jsonify(snaps)


# ── AI 解读 API ──

@app.route("/api/interpret/<ts_code>", methods=["GET"])
def api_interpret(ts_code):
    """
    使用配置的 LLM 对最近一次分析结果生成中文解读

    Query params:
      force=1  强制重新生成（忽略缓存，60 秒内同一股票仅允许 1 次）

    Returns:
        {"interpretation": "...", "cached": bool, "trade_date": "...",
         "generated_at": "..."}
    """
    from utils import call_llm, SimpleRateLimiter, RateLimitExceeded

    ts_code = normalize_ts_code(ts_code)
    force = request.args.get("force", "0") == "1"

    # ── Rate limit: force 重新生成限流 (避免狂点浪费 token) ──
    if force:
        # _force_limiter 在模块加载时初始化 (避免并发竞态)
        try:
            if not _force_limiter.allow(ts_code):
                raise RateLimitExceeded(_force_limiter.retry_after(ts_code))
        except RateLimitExceeded as e:
            resp = jsonify({
                "error": str(e),
                "retry_after": e.retry_after,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(e.retry_after)
            return resp

    # ── 1. 先用轻量查询拿元数据 (不加载 full_data 大字段) ──
    snap = DBManager.get_latest_snapshot_meta(ts_code)
    if not snap:
        return jsonify({"error": "请先运行分析，再生成解读"}), 404

    # 命中缓存
    if not force and snap.interpretation:
        return jsonify({
            "interpretation": snap.interpretation,
            "cached": True,
            "trade_date": snap.trade_date,
            "generated_at": snap.interpretation_at.strftime("%Y-%m-%d %H:%M:%S") if snap.interpretation_at else None,
        })

    # ── 2. 缓存未命中,按需加载 full_data ──
    full_data_json = DBManager.get_snapshot_full_data(ts_code, snap.trade_date)
    if not full_data_json:
        return jsonify({"error": "快照缺少完整数据，请重新分析"}), 400

    try:
        full = json.loads(full_data_json)
    except (json.JSONDecodeError, TypeError):
        full = {}

    # 构造精简的 prompt (避免超出 token 限制)
    ps   = full.get("price_summary", {})
    ce   = full.get("chip_evolution", {})
    ci   = full.get("classic_indicators", {})
    ta   = full.get("tech_analysis", {})
    dv   = full.get("divergence_signals", {})

    latest_record = (ce.get("daily_records") or [{}])[-1]
    trends = ce.get("trends", {})

    summary = {
        "股票代码": ts_code,
        "分析区间": full.get("meta", {}).get("date_range"),
        "最新收盘价": ps.get("latest_close"),
        "区间涨幅(%)": ps.get("period_pct"),
        "最高/最低": ps.get("period_high"),
        "P1(主峰位)": latest_record.get("p1"),
        "P1占比(%)": latest_record.get("p1_pct"),
        "TPC(三峰集中度)": latest_record.get("tpc"),
        "Top5集中度(%)": latest_record.get("top5"),
        "Winner(获利盘%)": latest_record.get("winner"),
        "形态": latest_record.get("morphology"),
        "峰数": latest_record.get("n_peaks"),
        "偏度": latest_record.get("skewness"),
        "峰度": latest_record.get("kurtosis"),
        "分布熵": latest_record.get("entropy"),
        "90%集中宽度": latest_record.get("width_90"),
        "锁仓评估": (ce.get("locking_assessment") or {}).get("overall"),
        "派发评分": (ce.get("dispatch_score") or {}).get("total"),
        "派发判定": (ce.get("dispatch_score") or {}).get("verdict"),
        "动量评分": (ta.get("momentum") or {}).get("score"),
        "趋势评分": (ta.get("trend") or {}).get("score"),
        "反转评分": (ta.get("reversal") or {}).get("score"),
        "加权综合": ta.get("weighted"),
        "CMF资金流": (ci.get("cmf") or {}).get("latest"),
        "ADX趋势强度": (ci.get("adx") or {}).get("latest_adx"),
        "ADX方向": (ci.get("adx") or {}).get("direction"),
        "ATR波动率%": (ci.get("atr") or {}).get("atr_pct_of_price"),
        "背离总分": dv.get("total_score"),
        "背离判定": dv.get("verdict"),
        "P1趋势": trends.get("p1"),
        "Top5趋势": trends.get("top5"),
        "TPC趋势": trends.get("tpc"),
    }
    # 移除 None 字段, 保持 prompt 简洁
    summary = {k: v for k, v in summary.items() if v is not None}

    system_prompt = (
        "你是专业的 A 股量化投研分析师，专注筹码峰 + 技术面综合解读。"
        "输出使用 markdown 格式，分 4 个部分（中文）：\n"
        "1. **核心结论** (1-2 句话直接给方向判断)\n"
        "2. **筹码面解读** (基于 P1/TPC/形态/峰度等)\n"
        "3. **技术面 + 资金面** (基于 MACD/CMF/ADX/背离)\n"
        "4. **操作建议** (持有/观望/减仓，给出关键观察价位)\n\n"
        "要求：基于提供的 json 数据回答，不要编造未给出的数值；"
        "总长度控制在 400 字以内。"
    )
    user_prompt = f"以下是股票的最新分析数据，请给出专业解读：\n```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```"

    try:
        interpretation = call_llm(user_prompt, system=system_prompt,
                                  max_tokens=1200, temperature=0.4)
    except Exception as e:
        return jsonify({"error": f"LLM 调用失败: {e}"}), 500

    DBManager.save_interpretation(ts_code, snap.trade_date, interpretation)

    return jsonify({
        "interpretation": interpretation,
        "cached": False,
        "trade_date": snap.trade_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ── 回测 API ──

@app.route("/api/backtest/<ts_code>", methods=["POST"])
def api_run_backtest(ts_code):
    """运行回测"""
    data = request.json or {}
    signal_type     = data.get("signal_type", "locking")
    params          = data.get("params", {})
    max_holding     = data.get("max_holding_days", 20)
    stop_loss       = data.get("stop_loss_pct", -8)
    take_profit     = data.get("take_profit_pct", 20)
    start_date      = data.get("start_date", "20240101")
    end_date        = data.get("end_date", datetime.now().strftime("%Y%m%d"))

    engine = BacktestEngine(ts_code, start_date, end_date)
    engine.load_price_data()
    result = engine.run(signal_type, params, max_holding, stop_loss, take_profit)

    if "error" in result:
        return jsonify(result), 400

    # 存入数据库
    run_data = {
        "ts_code": ts_code,
        "name": f"{signal_type}_{datetime.now().strftime('%m%d_%H%M')}",
        "start_date": start_date, "end_date": end_date,
        "parameters": json.dumps(params),
        "total_trades": result["total_trades"],
        "win_rate": result["win_rate"],
        "avg_return": result["avg_return"],
        "max_return": result["max_return"],
        "min_return": result["min_return"],
        "sharpe": result["sharpe"],
        "max_drawdown": result["max_drawdown"],
        "total_return": result["total_return"],
        "signal_type": signal_type,
    }
    run_id = DBManager.save_backtest_run(run_data, result["trades"])
    result["run_id"] = run_id

    return jsonify(result)


@app.route("/api/backtest/runs", methods=["GET"])
def api_get_backtest_runs():
    ts_code = request.args.get("ts_code")
    limit   = request.args.get("limit", 20, type=int)
    runs    = DBManager.get_backtest_runs(ts_code=ts_code, limit=limit)
    return jsonify(runs)


@app.route("/api/backtest/trades/<int:run_id>", methods=["GET"])
def api_get_trades(run_id):
    trades = DBManager.get_backtest_trades(run_id)
    return jsonify(trades)


# ── 进化 API ──

@app.route("/api/evolve/<ts_code>", methods=["POST"])
def api_run_evolution(ts_code):
    """运行参数进化"""
    ts_code = normalize_ts_code(ts_code)
    data = request.json or {}
    signal_type  = data.get("signal_type", "locking")
    param_grid   = data.get("param_grid", None)               # 自定义网格(可选)
    metric       = data.get("metric", "sharpe")
    holding      = data.get("holding_params", {})
    start_date   = data.get("start_date", "20240101")
    end_date     = data.get("end_date", datetime.now().strftime("%Y%m%d"))

    evo = EvolutionEngine(ts_code, start_date, end_date)
    result = evo.evolve(signal_type, param_grid, metric, holding)

    if "error" in result:
        return jsonify(result), 400

    # 存入数据库
    run_data = {
        "ts_code": ts_code,
        "signal_type": signal_type,
        "param_grid": json.dumps(param_grid or EvolutionEngine.default_grid(signal_type)),
        "best_params": json.dumps(result.get("best_params")),
        "best_sharpe": next((r["sharpe"] for r in result.get("top_results", [{}]) if r.get("params") == result.get("best_params")), 0),
        "best_win_rate": next((r["win_rate"] for r in result.get("top_results", [{}]) if r.get("params") == result.get("best_params")), 0),
        "total_tested": result["total_tested"],
        "results_json": json.dumps(result),
    }
    evo_id = DBManager.save_evolution_run(run_data)
    result["run_id"] = evo_id

    return jsonify(result)


@app.route("/api/evolve/runs", methods=["GET"])
def api_get_evolution_runs():
    ts_code = request.args.get("ts_code")
    runs    = DBManager.get_evolution_runs(ts_code=ts_code)
    return jsonify(runs)


# ── 持仓 + 交易日志 API ──

@app.route("/api/positions", methods=["GET"])
@app.route("/api/stock_lookup", methods=["GET"])
def api_stock_lookup():
    """
    股票代码/名称 反查接口 (支持双向查找)
    Query params:
      q: 查询字符串 (代码或名称)
      mode: code | name | auto (默认 auto)
    Returns:
      list of {ts_code, name, industry, area, market}
    """
    from utils import search_stock
    q    = request.args.get("q", "").strip()
    mode = request.args.get("mode", "auto")
    if not q:
        return jsonify([])
    try:
        results = search_stock(q, mode=mode, limit=15)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": f"查询失败: {e}"}), 500


@app.route("/api/knowledge_graph/<ts_code>", methods=["GET"])
def api_knowledge_graph_by_code(ts_code):
    """
    按股票代码获取知识图谱节点
    返回: {code, name, tags, type, summary, file}
    """
    from utils import get_kg_by_code
    ts_code = normalize_ts_code(ts_code)
    node = get_kg_by_code(ts_code)
    if not node:
        return jsonify({"found": False, "ts_code": ts_code}), 404
    return jsonify({"found": True, **node})


@app.route("/api/knowledge_graph/<ts_code>/related", methods=["GET"])
def api_knowledge_graph_related(ts_code):
    """
    按 tag 找关联公司 (同一 tag 的其他股票)
    Returns: {tag: [{code, name}, ...], ...}
    """
    from utils import get_kg_by_code, _KG_TAGS_INDEX, _KG_INDEX
    ts_code = normalize_ts_code(ts_code)
    node = get_kg_by_code(ts_code)
    if not node:
        return jsonify({"related": {}, "tags": []})

    related = {}
    own_code = node["code"]
    for tag in node.get("tags", []):
        for code in _KG_TAGS_INDEX.get(tag, []):
            if code == own_code:
                continue
            other = _KG_INDEX.get(code)
            if other:
                related.setdefault(tag, []).append({
                    "code": code,
                    "name": other["name"],
                    "tags": other["tags"],
                })
    return jsonify({"related": related, "tags": node.get("tags", [])})


@app.route("/api/knowledge_graph/stats", methods=["GET"])
def api_knowledge_graph_stats():
    """知识图谱统计 (扫描状态, 公司数, tag 数)"""
    from utils import load_knowledge_graph, get_kg_stats
    load_knowledge_graph()
    return jsonify(get_kg_stats())


@app.route("/api/positions", methods=["GET"])
def api_list_positions():
    """获取持仓列表"""
    account = request.args.get("account")
    status  = request.args.get("status")
    return jsonify(DBManager.get_positions(account=account, status=status))


@app.route("/api/positions/<int:position_id>", methods=["GET"])
def api_get_position(position_id):
    """获取单个持仓"""
    pos = DBManager.get_position(position_id)
    if not pos:
        return jsonify({"error": "持仓不存在"}), 404
    return jsonify(pos)


@app.route("/api/analyze/<ts_code>/verdict", methods=["GET"])
def api_analyze_verdict(ts_code):
    """
    综合判定 (Phase 2 决策仪表盘核心)

    Returns:
        {action, confidence, color, reasons, scores}
    """
    from utils import compute_verdict
    ts_code = normalize_ts_code(ts_code)
    days = request.args.get("days", 14, type=int)
    try:
        result = chip_analyze(ts_code, days=days)
    except Exception as e:
        return json_response({"error": f"分析失败: {e}"}, 500)
    if "error" in result:
        return json_response(result, 400)
    verdict = compute_verdict(result)
    # 确保 python 原生类型 (compute_verdict 内部可能混入 numpy int64)
    verdict["ts_code"] = ts_code
    verdict["trade_date"] = result.get("meta", {}).get("date_range", "")
    verdict["confidence"] = int(verdict["confidence"])
    scores = verdict.get("scores", {})
    if isinstance(scores.get("lock"), (list, tuple)):
        scores["lock"] = [int(scores["lock"][0]), int(scores["lock"][1])]
    scores["dispatch"] = int(scores.get("dispatch", 0))
    scores["divergence_strong"] = int(scores.get("divergence_strong", 0))
    scores["divergence_active"] = int(scores.get("divergence_active", 0))
    scores["tpc"] = float(scores.get("tpc", 0))
    return json_response(verdict)


@app.route("/api/positions/by_code/<ts_code>", methods=["GET"])
def api_get_position_by_code(ts_code):
    """按股票代码查找活跃持仓 (同时尝试带/不带后缀)"""
    account = request.args.get("account")
    # 既尝试 normalize 后的代码, 也尝试原码 (兼容 import 时未 normalize 的数据)
    candidates = [ts_code, normalize_ts_code(ts_code)]
    pos = None
    for code in candidates:
        pos = DBManager.get_position_by_code(code, account=account, status='active')
        if pos:
            break
    if not pos:
        return jsonify({"error": "无活跃持仓"}), 404
    return jsonify(pos.to_dict())


@app.route("/api/trade_logs", methods=["GET"])
def api_list_trade_logs():
    """获取交易日志"""
    ts_code = normalize_ts_code(request.args.get("ts_code", ""))
    account = request.args.get("account")
    limit   = request.args.get("limit", 50, type=int)
    return jsonify(DBManager.get_trade_logs(ts_code=ts_code, account=account, limit=limit))


# ══════════════════════════════════════════════════════
# 系统端点 + 错误处理器
# ══════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def api_health():
    """
    健康检查端点
    返回数据库连接状态、tushare token 配置情况、watchlist 数量等
    """
    health = {
        "status": "ok",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "components": {}
    }
    # 数据库
    try:
        with app.app_context():
            watchlist_count = Watchlist.query.filter_by(active=True).count()
            snapshot_count  = AnalysisSnapshot.query.count()
            backtest_count  = BacktestRun.query.count()
        health["components"]["database"] = {
            "status": "ok",
            "watchlist_active": watchlist_count,
            "snapshots": snapshot_count,
            "backtest_runs": backtest_count,
        }
    except Exception as e:
        health["status"] = "degraded"
        health["components"]["database"] = {"status": "error", "message": str(e)}

    # Tushare token
    try:
        from utils import get_tushare_token
        get_tushare_token()  # 验证可读取, 不暴露任何 token 信息
        health["components"]["tushare_token"] = {
            "status": "ok",
        }
    except Exception as e:
        health["status"] = "degraded"
        health["components"]["tushare_token"] = {"status": "error", "message": str(e)}

    code = 200 if health["status"] == "ok" else 503
    return jsonify(health), code


@app.errorhandler(404)
def handle_404(e):
    """API 返回 JSON 404，页面返回 HTML"""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not Found", "path": request.path}), 404
    return render_template("base.html").replace(
        "{% block content %}{% endblock %}",
        '<div class="text-center py-5"><h2>404 - 页面未找到</h2>'
        '<p class="text-muted">访问的路径不存在</p>'
        '<a href="/" class="btn btn-primary mt-3">返回首页</a></div>'
    ), 404


@app.errorhandler(500)
def handle_500(e):
    """500 错误：API 返回 JSON，页面返回 HTML"""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500
    return render_template("base.html").replace(
        "{% block content %}{% endblock %}",
        '<div class="text-center py-5"><h2>500 - 服务器内部错误</h2>'
        '<p class="text-muted">请稍后重试</p>'
        '<a href="/" class="btn btn-primary mt-3">返回首页</a></div>'
    ), 500


# ══════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host  = os.environ.get("FLASK_HOST", "127.0.0.1")
    port  = int(os.environ.get("FLASK_PORT", "5000"))
    if not debug and host == "0.0.0.0":
        logger.warning("生产环境请设置 FLASK_DEBUG=0 且 FLASK_HOST=127.0.0.1")
    logger.info(f"筹码峰量化投研平台 v1.0  http://{host}:{port}  debug={debug}")
    app.run(debug=debug, host=host, port=port)
