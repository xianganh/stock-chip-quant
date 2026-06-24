"""
项目共享工具模块
集中处理 token 加载、Tushare/LLM 实例化、HTTP 限流等通用逻辑
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path


# ═══════════════════════════════════════════════════════
# Tushare
# ═══════════════════════════════════════════════════════

def get_tushare_token() -> str:
    """
    按优先级读取 Tushare token:
      1. 环境变量 TUSHARE_TOKEN
      2. ~/.config/tushare/token
      3. ~/.tushare_token

    Raises:
        FileNotFoundError: 未找到任何 token 配置
    """
    # 1. 环境变量优先 (便于部署/CI)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token

    # 2. XDG 标准路径
    token_path = os.path.expanduser("~/.config/tushare/token")
    if os.path.exists(token_path):
        with open(token_path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token

    # 3. 旧路径兼容
    alt_path = os.path.expanduser("~/.tushare_token")
    if os.path.exists(alt_path):
        with open(alt_path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token

    raise FileNotFoundError(
        "Tushare token 未找到。请通过以下任一方式配置：\n"
        "  1) 设置环境变量 TUSHARE_TOKEN\n"
        "  2) 创建文件 ~/.config/tushare/token 并写入 token\n"
        "  3) 创建文件 ~/.tushare_token 并写入 token"
    )


@lru_cache(maxsize=1)
def get_tushare_pro():
    """
    获取 Tushare pro_api 实例 (单例缓存)
    整个进程内只初始化一次，避免重复设置 token
    """
    import tushare as ts
    ts.set_token(get_tushare_token())
    return ts.pro_api()


@lru_cache(maxsize=1)
def get_stock_basic_list():
    """
    获取所有 A 股股票基础信息 (代码+名称+行业)
    单进程内只拉一次, 缓存使用
    Returns:
        list[dict]: [{ts_code, name, industry, ...}, ...]
    """
    pro = get_tushare_pro()
    df = pro.stock_basic(list_status='L', fields='ts_code,name,industry,area,market')
    return df.to_dict('records') if df is not None else []


def search_stock(query: str, mode: str = 'auto', limit: int = 10) -> list[dict]:
    """
    在股票基础信息里搜索

    Args:
        query: 代码 (如 '000066') 或 名称 (如 '中国长城') 或 带后缀 (如 '000066.SZ')
        mode: 'code' | 'name' | 'auto'
              auto: 优先按代码匹配, 再按名称
        limit: 返回数量上限
    """
    if not query:
        return []
    query = query.strip()
    stocks = get_stock_basic_list()
    if not stocks:
        return []
    q_lower = query.lower()
    matches = []

    if mode == 'auto':
        # 先按代码精确匹配
        for s in stocks:
            if s['ts_code'].lower() == q_lower or s['ts_code'].lower().startswith(q_lower):
                matches.append(s)
        # 然后按代码前 6 位数字匹配 (用户可能没输入后缀)
        if not matches:
            q6 = q_lower.split('.')[0]
            for s in stocks:
                if s['ts_code'].lower().startswith(q6):
                    matches.append(s)
        # 最后按名称模糊匹配
        if not matches:
            for s in stocks:
                if q_lower in s['name'].lower():
                    matches.append(s)
        if not matches:
            # 部分名称匹配
            for s in stocks:
                if any(part in s['name'].lower() for part in q_lower):
                    matches.append(s)
    elif mode == 'code':
        for s in stocks:
            if q_lower in s['ts_code'].lower():
                matches.append(s)
    elif mode == 'name':
        for s in stocks:
            if q_lower in s['name'].lower():
                matches.append(s)

    return matches[:limit]


# ═══════════════════════════════════════════════════════
# 综合判定 (供 Phase 2 决策仪表盘使用)
# ═══════════════════════════════════════════════════════

def _parse_lock_score(lock_score: str) -> tuple:
    """'5/6' -> (5, 6); '0/6' -> (0, 6)

    对 None / 空串 / 非字符串 均返回 (0, 6), 与其他无效输入一致。
    """
    if not lock_score:
        return 0, 6
    if "/" not in lock_score:
        return 0, 6
    try:
        a, b = lock_score.split("/", 1)
        return int(a), int(b)
    except (ValueError, TypeError):
        return 0, 6


def compute_verdict(analysis: dict) -> dict:
    """
    基于分析结果计算综合判定 (持有 / 减仓 / 清仓 / 观望)

    判定规则 (按优先级):
      1. 派发评分 >= 4/5              → 清仓风险 (硬指标)
      2. 锁仓评分 >= 5/6              → 坚定持有 (主力稳定)
      3. 锁仓评分 >= 3/6 + 强背离   → 持有 (等待机会)
      4. 锁仓评分 < 3/6 + 派发 >= 2  → 减仓 (信号走弱)
      5. 其他                            → 观望

    Returns:
        {
            "action": "持有" | "减仓" | "清仓" | "观望",
            "confidence": 0-100,
            "color": "green" | "yellow" | "red" | "gray",
            "reasons": [str, ...],          # 综合理由
            "scores": {                     # 各维度分数
                "lock": (passed, total),
                "dispatch": total,
                "divergence_strong": int,
                "divergence_active": int,
                "tpc": float,
                "morphology": str,
            }
        }
    """
    ce = analysis.get("chip_evolution", {})
    locking = ce.get("locking_assessment", {})
    dispatch = ce.get("dispatch_score", {})
    divergence = analysis.get("divergence_signals", {})

    lock_passed, lock_total = _parse_lock_score(locking.get("locked_score", "0/6"))
    dispatch_total = dispatch.get("total", 0)
    div_strong = divergence.get("strong_count", 0)
    div_active = divergence.get("active_count", 0)

    # 取最新一天的指标 (用于筹码结构)
    daily_records = ce.get("daily_records", [])
    latest = daily_records[-1] if daily_records else {}
    tpc = latest.get("tpc", 0)
    morphology = latest.get("morphology", "")
    p1_pct = latest.get("p1_pct", 0)

    reasons = []
    action = "观望"
    confidence = 50
    color = "gray"

    # 规则 1: 派发 >= 4 → 清仓风险
    if dispatch_total >= 4:
        action = "清仓"
        confidence = 85
        color = "red"
        reasons.append(f"派发评分 {dispatch_total}/5 已达危险阈值 (>=4), 主力可能在系统性出货")
        if div_strong >= 2:
            reasons.append(f"背离强信号 {div_strong} 类, 价格与筹码严重背离")
    # 规则 2: 锁仓 >= 5 → 坚定持有
    elif lock_passed >= 5:
        action = "持有"
        confidence = 80
        color = "green"
        reasons.append(f"锁仓评分 {lock_passed}/{lock_total} 条件满足, 主力稳定锁仓中")
        if p1_pct >= 10:
            reasons.append(f"P1 主峰占比 {p1_pct}%, 筹码集中度健康")
    # 规则 3: 锁仓 3-4 + 强背离 → 持有 (等待机会)
    elif lock_passed >= 3 and div_strong >= 1:
        action = "持有"
        confidence = 60
        color = "green"
        reasons.append(f"锁仓 {lock_passed}/{lock_total}, 有 {div_strong} 类强背离 (筹码领先价格)")
    # 规则 4: 锁仓弱 + 派发中 → 减仓
    elif lock_passed < 3 and dispatch_total >= 2:
        action = "减仓"
        confidence = 65
        color = "yellow"
        reasons.append(f"锁仓仅 {lock_passed}/{lock_total}, 派发 {dispatch_total}/5 有出货迹象")
    # 规则 5: 其他 → 观望
    else:
        action = "观望"
        confidence = 50
        color = "gray"
        reasons.append("信号不明确, 建议等待更多确认")

    return {
        "action": action,
        "confidence": confidence,
        "color": color,
        "reasons": reasons,
        "scores": {
            "lock": (lock_passed, lock_total),
            "dispatch": dispatch_total,
            "divergence_strong": div_strong,
            "divergence_active": div_active,
            "tpc": tpc,
            "morphology": morphology,
        },
    }


# ═══════════════════════════════════════════════════════
# 股票代码标准化 (供 app.py / db_manager.py 共享)
# ═══════════════════════════════════════════════════════

def normalize_ts_code(code: str) -> str:
    """
    自动补全 Tushare 股票代码的交易所后缀

    规则:
      - 6xxxxx, 9xxxxx → 上交所 .SH
      - 0xxxxx, 3xxxxx → 深交所 .SZ
      - 8xxxxx, 4xxxxx, 2xxxxx → 北交所 .BJ

    已带后缀、非6位数字、非纯数字等异常输入则原样返回
    """
    if not code:
        return code
    code = code.strip()
    if "." in code:
        head, _, suffix = code.rpartition(".")
        return head + "." + suffix.upper()
    if not code.isdigit() or len(code) != 6:
        return code
    code = code.upper()
    first = code[0]
    if first in ("6", "9"):
        return code + ".SH"
    elif first in ("0", "3"):
        return code + ".SZ"
    elif first in ("8", "4", "2"):
        return code + ".BJ"
    return code


# ═══════════════════════════════════════════════════════
# 知识图谱 (外部目录, 运行时只读)
# ═══════════════════════════════════════════════════════

import re as _re_kg
from pathlib import Path as _Path_kg

_KG_INDEX: dict = {}        # ts_code → {name, code, tags, abstract, file}
_KG_NAME_TO_CODE: dict = {} # name → ts_code (用于模糊搜索)
_KG_TAGS_INDEX: dict = {}   # tag → [ts_code] (反向索引)
_KG_LOADED = False


def _parse_frontmatter(text: str) -> dict:
    """解析 .md 文件的 YAML frontmatter (简化版)"""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end < 0:
        return {}
    fm_block = text[3:end].strip()
    result = {}
    current_list_key = None
    for line in fm_block.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        # 数组项
        if line.lstrip().startswith("- ") and current_list_key:
            val = line.lstrip()[2:].strip().strip('"').strip("'")
            # ★ 确保 result[current_list_key] 是 list
            if current_list_key not in result or not isinstance(result[current_list_key], list):
                result[current_list_key] = []
            result[current_list_key].append(val)
            continue
        # 数组开始 (key: [val1, val2])
        m = _re_kg.match(r'^(\w+):\s*\[(.*)\]\s*$', line)
        if m:
            key = m.group(1)
            vals = [v.strip().strip('"').strip("'") for v in m.group(2).split(",") if v.strip()]
            result[key] = vals
            current_list_key = None
            continue
        # key: value
        m = _re_kg.match(r'^(\w+):\s*(.+)$', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            result[key] = val
            current_list_key = key
            continue
    return result


def _parse_filename_code(name: str) -> str:
    """从文件名提取股票代码 (如 '元力股份_300174.md' → '300174')"""
    m = _re_kg.search(r'_(\d{6})\.md$', name)
    return m.group(1) if m else ""


def load_knowledge_graph(kg_dir: str = None) -> dict:
    """
    扫描知识图谱目录, 建立索引
    返回: {
        "by_code": {"300174": {name, code, tags, abstract, file}, ...},
        "by_name": {"元力股份": "300174", ...},
        "by_tag":  {"活性炭": ["300174", ...], ...},
        "stats":   {total_files, total_companies, all_tags, ...},
        "kg_dir":  str
    }
    """
    global _KG_INDEX, _KG_NAME_TO_CODE, _KG_TAGS_INDEX, _KG_LOADED

    if kg_dir is None:
        from config import KNOWLEDGE_GRAPH_DIR
        kg_dir = KNOWLEDGE_GRAPH_DIR

    result = {
        "by_code": {},
        "by_name": {},
        "by_tag": {},
        "stats": {"total_files": 0, "companies": 0, "tags_count": 0, "available": False},
        "kg_dir": kg_dir,
    }

    if not kg_dir or not os.path.isdir(kg_dir):
        return result

    kg_path = _Path_kg(kg_dir)
    # 扫描 company/ 和根目录的 .md 文件
    md_files = list(kg_path.rglob("*.md"))
    result["stats"]["total_files"] = len(md_files)
    result["stats"]["available"] = True

    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(text)
        if not fm:
            continue

        # 优先用 frontmatter 的 code, 否则从文件名提取
        code = str(fm.get("code", "")).strip()
        if not code or len(code) != 6 or not code.isdigit():
            code = _parse_filename_code(md_file.name)
        if not code:
            continue

        name = str(fm.get("name", "")).strip()
        if not name:
            # 从文件名提取 (如 '元力股份_300174' → '元力股份')
            name = md_file.stem.rsplit("_", 1)[0]

        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        record = {
            "code": code,
            "name": name,
            "tags": tags,
            "type": str(fm.get("type", "")),
            "abstract": str(fm.get("abstract_level", "")),
            "file": str(md_file.relative_to(kg_path)).replace("\\", "/"),
            "summary": _extract_summary(text),
        }
        result["by_code"][code] = record
        result["by_name"][name] = code
        for tag in tags:
            result["by_tag"].setdefault(tag, []).append(code)

    result["stats"]["companies"] = len(result["by_code"])
    result["stats"]["tags_count"] = len(result["by_tag"])
    _KG_INDEX = result["by_code"]
    _KG_NAME_TO_CODE = result["by_name"]
    _KG_TAGS_INDEX = result["by_tag"]
    _KG_LOADED = True
    return result


def _extract_summary(text: str, max_len: int = 200) -> str:
    """从 markdown 提取摘要 (找 ## 基本信息 下面的内容)"""
    m = _re_kg.search(r"##\s*基本信息\s*\n(.*?)(?:\n##|\Z)", text, _re_kg.DOTALL)
    if m:
        text = m.group(1)
    # 去掉 markdown 格式符号
    text = _re_kg.sub(r"[#*`>|]", "", text)
    text = _re_kg.sub(r"\n+", " ", text).strip()
    return text[:max_len] + ("..." if len(text) > max_len else "")


def get_kg_by_code(ts_code: str) -> dict:
    """按股票代码获取知识图谱节点 (自动补全交易所后缀)"""
    if not _KG_LOADED:
        load_knowledge_graph()
    code6 = ts_code.split(".")[0]
    return _KG_INDEX.get(code6)


def get_kg_stats() -> dict:
    """获取知识图谱统计信息"""
    if not _KG_LOADED:
        load_knowledge_graph()
    return {
        "loaded": _KG_LOADED,
        "companies": len(_KG_INDEX),
        "tags": len(_KG_TAGS_INDEX),
    }


# ═══════════════════════════════════════════════════════
# LLM (CodeBuddy 配置的 models.json)
# ═══════════════════════════════════════════════════════

def get_configured_llm():
    """
    读取 CodeBuddy 配置的 LLM (models.json)

    Returns:
        dict: {name, url, apiKey, model} 或 None
    """
    candidates = [
        Path.home() / ".codebuddy" / "models.json",
        Path(__file__).resolve().parent / "models.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        models = cfg.get("models", [])
        available = cfg.get("availableModels") or [m.get("id") for m in models]
        for m in models:
            if m.get("id") in available and m.get("apiKey") and m.get("url"):
                url = m["url"].rstrip("/")
                if not url.endswith("/chat/completions"):
                    url += "/chat/completions"
                return {
                    "name": m.get("name", m.get("id")),
                    "url": url,
                    "apiKey": m["apiKey"],
                    "model": m["id"],
                }
    return None


def call_llm(prompt: str, system: str = "", max_tokens: int = 1500,
             temperature: float = 0.5, timeout: int = 60) -> str:
    """
    调用 CodeBuddy 配置的 LLM (OpenAI 兼容协议)

    Raises:
        RuntimeError: LLM 未配置 / HTTP 错误 / 响应解析失败
    """
    llm = get_configured_llm()
    if llm is None:
        raise RuntimeError(
            "未找到可用的 LLM 配置。请在 ~/.codebuddy/models.json 中配置模型。"
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": llm["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    req = urllib.request.Request(
        llm["url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm['apiKey']}",
        },
        method="POST",
    )

    raw = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = ""
        raise RuntimeError(f"LLM 调用失败 (HTTP {e.code}): {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 调用网络错误: {e.reason}") from e

    # 解析响应 (健壮性: 处理非 JSON 响应)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 响应不是合法 JSON: {raw[:200]}") from e

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"LLM 响应结构异常: {data}") from e


# ═══════════════════════════════════════════════════════
# 简易内存限流器 (替代 flask-limiter,避免增加依赖)
# ═══════════════════════════════════════════════════════

class SimpleRateLimiter:
    """
    基于内存字典的滑动窗口限流器 (单实例多线程安全)

    用法:
        limiter = SimpleRateLimiter(window_seconds=60, max_calls=1)
        if not limiter.allow("user_or_key_123"):
            raise RateLimitExceeded("60 秒内最多调用 1 次")
    """
    def __init__(self, window_seconds: int = 60, max_calls: int = 1):
        self.window = window_seconds
        self.max_calls = max_calls
        self._calls: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """检查并记录一次调用,返回 True 表示允许"""
        now = time.time()
        with self._lock:
            history = self._calls.setdefault(key, [])
            # 清理窗口外的旧记录
            cutoff = now - self.window
            while history and history[0] < cutoff:
                history.pop(0)
            if len(history) >= self.max_calls:
                return False
            history.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """返回距离下次允许还需等待的秒数"""
        history = self._calls.get(key, [])
        if not history or len(history) < self.max_calls:
            return 0
        return max(0, int(self.window - (time.time() - history[0])) + 1)


class RateLimitExceeded(Exception):
    """限流异常, 由调用方转换为 HTTP 429"""
    def __init__(self, retry_after: int):
        super().__init__(f"请求过于频繁, 请 {retry_after} 秒后重试")
        self.retry_after = retry_after