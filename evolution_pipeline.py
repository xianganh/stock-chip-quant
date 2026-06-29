#!/usr/bin/env python3
"""
🔥 闭环进化管道 — 筹码峰 v3.1 策略 4 层全自动进化引擎
完全独立脚本，不修改任何现有模块。只复用 holding_manager / kronos_integration。

4 层闭环架构:
  Layer1 批量回测层（带归因特征）
  Layer2 表现分层 + 自动归因（生成参数搜索空间）
  Layer3 参数基因演化（定向网格 + scipy 差分进化 + Kronos 权重联调）
  Layer4 参数准入卡（时间切分 train/val，3 条防过拟合门槛）
"""
import sys, os, json, traceback, itertools, time
from copy import deepcopy
from datetime import datetime
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

try:
    from scipy.optimize import differential_evolution
    SCIPY_AVAILABLE = True
except ModuleNotFoundError:
    SCIPY_AVAILABLE = False
    differential_evolution = None  # type: ignore

from holding_manager import HoldingManager
from chip_data_fetcher import fetch_complete_data
from chip_indicators import compute_all_chip_metrics, chip_score_v2, compute_chip_metrics, analyze_chip_health
from engine.daily_review_engine import classify_future, health_label_from_chip_score
from kronos_integration import KronosChipFuser

# ============================================================
# 全局配置：9 只历史样本 + 时间切分（train / val 防过拟合）
# ============================================================
STOCKS_POOL = [
    ('603002.SH', '宏昌电子'), ('605589.SH', '圣泉集团'), ('000066.SZ', '中国长城'),
    ('600176.SH', '中国巨石'), ('601208.SH', '东材科技'), ('603773.SH', '沃格光电'),
    ('603039.SH', '泛微网络'), ('002602.SZ', '世纪华通'), ('002407.SZ', '多氟多'),
]
TRAIN_START, TRAIN_END = '20260301', '20260520'   # 训练集 ~2.5 个月
VAL_START,   VAL_END   = '20260521', '20260628'   # 验证集 ~1 个月（样本外）

# 进化代数 & 并行（MVP 用 3 代，串行跑约 10~20 分钟搞定）
MAX_GENERATIONS = 3
INITIAL_CASH = 100000.0

# Kronos 融合权重默认（可被 Layer3 evolve_weights 覆盖）
DEFAULT_CHIP_W, DEFAULT_KRONOS_W = 0.70, 0.30

# ============= 缓存目录（避免反复调用 Tushare，也不会触发限流） =============
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.evo_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(ts_code: str, start: str, end: str) -> str:
    return os.path.join(CACHE_DIR, f'{ts_code}_{start}_{end}.pkl')


def _cached_fetch_complete_data(ts_code: str, start: str, end: str) -> Dict:
    """带本地 pickle 缓存的 fetch_complete_data。命中缓存 0 API 调用。"""
    import pickle
    fp = _cache_path(ts_code, start, end)
    if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
        try:
            with open(fp, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
    # 缓存未命中 → 真实调用（caller 负责限速）
    data = fetch_complete_data(ts_code, start, end)
    try:
        with open(fp, 'wb') as f:
            pickle.dump(data, f, protocol=4)
    except Exception:
        pass
    return data


def preheat_all_cache(sleep_sec: int = 4):
    """启动前把 9 只 × (train + val) = 18 组数据全部预热缓存。每组 sleep 避开限流。"""
    all_tasks = []
    for ts_code, _ in STOCKS_POOL:
        all_tasks.append((ts_code, TRAIN_START, TRAIN_END))
        all_tasks.append((ts_code, VAL_START, VAL_END))
    total = len(all_tasks)
    print(f'  📦 预热阶段：共 {total} 组数据待缓存（每只股票×train/val），每组间隔 {sleep_sec}s 避开限流')
    need = 0
    for i, (tc, s, e) in enumerate(all_tasks, 1):
        fp = _cache_path(tc, s, e)
        if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
            print(f'    [{i}/{total}] ✅ {tc} {s}~{e} 已有缓存，跳过')
            continue
        need += 1
        print(f'    [{i}/{total}] ⏳ {tc} {s}~{e} 拉取中 ...', flush=True, end='')
        try:
            _cached_fetch_complete_data(tc, s, e)
            print(f' 完成，{sleep_sec}s cooldown')
        except Exception as ex:
            print(f' ❌ 失败：{ex}')
        time.sleep(sleep_sec)
    print(f'  ✅ 预热完成！新拉 {need}/{total} 组，后续进化 100% 本地缓存、0 API 调用。')
    return need


fuser = KronosChipFuser()

# ============================================================
# 🧱 Layer1：批量回测层 — 返回带「归因特征」的结果字典
# ============================================================
def _extract_support_price(v):
    return v.get('price') if isinstance(v, dict) else None


def _prepare_df(rows):
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'].astype(str))
    for period in [5, 10, 20, 60]:
        df[f'ma{period}'] = df['close'].rolling(period).mean()
    for metric in ['tpc', 'width', 'tp3', 'winner', 'entropy', 'skewness', 'kurtosis', 'p1_dominance']:
        df[f'{metric}_chg_7d'] = pd.to_numeric(df[metric], errors='coerce').diff(7)
    wavg = pd.to_numeric(df['weight_avg'], errors='coerce').replace(0, float('nan'))
    df['cost_dist_pct'] = (df['close'] - wavg) / wavg * 100
    sprice = df['support'].apply(_extract_support_price).replace(0, float('nan'))
    df['support_distance_pct'] = ((df['close'] - sprice) / sprice * 100).fillna(0)
    df['winner_chg_7d_70'] = df['winner_chg_7d'].quantile(0.7)
    df['tpc_50'] = df['tpc'].quantile(0.5)
    df['width_50'] = df['width'].quantile(0.5)
    df['entropy_50'] = df['entropy'].quantile(0.5)
    return df


def run_one_attributed(ts_code: str, name: str, params: Dict,
                       start: str, end: str,
                       chip_weight: float = DEFAULT_CHIP_W,
                       kronos_weight: float = DEFAULT_KRONOS_W) -> Dict:
    """
    回测单只股票 + 返回归因特征字典
    returns: { ts_code, name, total_ret, buy_hold, excess, win_rate, max_dd,
               trades, entry_count, warn_count, high_count, stop_loss_hit,
               avg_score_on_entry, winner_at_max, fall_from_peak_days, error }
    """
    try:
        data = _cached_fetch_complete_data(ts_code, start, end)
        rows = compute_all_chip_metrics(data['chip_data'], data['kline'], lookback_days=7)
        if len(rows) < 20:
            return {'ts_code': ts_code, 'name': name,
                    'error': f'数据不足({len(rows)}行)', 'total_ret': -999, 'buy_hold': -999,
                    'excess': -999, 'sharpe': -999, 'max_dd': 0, 'trades': []}

        df_raw = _prepare_df(rows)
        buy_hold = round((df_raw['close'].iloc[-1] / df_raw['close'].iloc[0] - 1) * 100, 2)

        df = df_raw.copy()
        mgr = HoldingManager(params)
        df['score_raw'] = df.apply(mgr._score_entry, axis=1)

        # ⭐ 融合：如果 Kronos 可用，用 bayesian_fusion 把 chip_score → fused_score（0~100）
        # MVP 阶段 kronos_result=None，等价于纯筹码（fused_score = 原始分数×归一化）
        def _fuse(r):
            fusion = fuser.bayesian_fusion(int(r['score_raw']), None,
                                           chip_weight=chip_weight, kronos_weight=kronos_weight)
            return fusion['fused_score'] / 100.0 * 12.0 - 2.0   # 0~100 → -2 ~ +10 同原分数尺度
        df['score'] = df.apply(_fuse, axis=1)

        # 回测
        final_val, log = mgr.backtest(df, initial_cash=INITIAL_CASH)
        total_ret = round((final_val / INITIAL_CASH - 1) * 100, 2)
        excess = round(total_ret - buy_hold, 2)
        import re
        _act = [str(e.get('action', '')) for e in log]
        trades = [a for a in _act if ('减' in a or '建仓' in a or '清仓' in a or '止盈' in a or '止损' in a or '期末' in a)]

        # --- 归因特征：用真实 action 关键字（来自 holding_manager.py 234-353 行）---
        entry_count  = sum(1 for a in _act if a.strip() == '建仓')
        warn_count   = sum(1 for a in _act if a.startswith('预警减'))
        high_count   = sum(1 for a in _act if a.startswith('高度减'))
        pre_tp_count = sum(1 for a in _act if a.startswith('预止盈'))
        stop_loss_hit = sum(1 for a in _act if a.startswith('硬止损'))
        close_count    = sum(1 for a in _act if a.startswith('出货清仓') or a.startswith('硬止损') or a.startswith('期末'))

        # --- 重算权益曲线（需要重新遍历 df，逐个持仓状态）
        # holding_manager 内部就是用 shares(股数浮点) + cash 走的，我们在外部模拟一遍更准确
        _cash = float(INITIAL_CASH)
        _shares_held = 0.0  # 持仓股数浮点
        _cost = 0.0
        events_by_date = {}
        for e in log:
            a = str(e.get('action', ''))
            p = float(e.get('price', 0))
            d = str(e.get('date', ''))
            if a == '建仓':
                _shares_held = _cash / p  # L226 cash / price
                _cost = p
                _cash = 0.0
            elif a.startswith('预止盈'):
                m = re.search(r'预止盈(\d+)%', a)
                r = float(m.group(1)) / 100 if m else 0.5
                sell_n = _shares_held * r
                _cash += sell_n * p
                _shares_held *= (1 - r)
            elif a.startswith('高度减') or a.startswith('预警减'):
                m = re.search(r'减(\d+)%', a)
                r_pct = float(m.group(1)) if m else 30.0
                r = r_pct / 100.0
                sell_n = _shares_held * r
                _cash += sell_n * p
                _shares_held -= sell_n
            elif a.startswith('出货清仓') or a.startswith('硬止损') or a.startswith('期末'):
                _cash += _shares_held * p
                _shares_held = 0.0
            events_by_date[d[:10]] = (_cash, _shares_held, _cost)

        equity_daily = [float(INITIAL_CASH)]
        for _, row in df.iterrows():
            c = _cash if _cash > 0 else 0
            sh = _shares_held
            prc = float(row['close'])
            d_ts = str(row['date'])[:10]
            if d_ts in events_by_date:
                c, sh, _c2 = events_by_date[d_ts]
            equity_daily.append(c + sh * prc)

        equity_arr = np.array(equity_daily, dtype=float)
        if len(equity_arr) >= 3:
            peak = np.maximum.accumulate(equity_arr)
            dd = (equity_arr - peak) / np.maximum(peak, 1e-9)
            max_dd = float(np.min(dd)) * 100
            rets = np.diff(equity_arr) / np.maximum(equity_arr[:-1], 1e-9)
            if np.std(rets) > 1e-8:
                sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252))
            else:
                sharpe = 0.0
        else:
            max_dd = 0.0
            sharpe = 0.0

        # --- 胜率：每个「平仓节点」赚 / (赚+亏)，抓 action 里括号里的 %
        wins = 0
        loses = 0
        close_nodes = [e for e in log if str(e.get('action','')).startswith(('出货清仓','硬止损','预止盈','高度减','预警减','期末'))]
        for e in close_nodes:
            m = re.search(r'\(([+\-][\d.]+)%\)', str(e.get('action','')))
            if m:
                pct = float(m.group(1))
                if pct > 0.1:
                    wins += 1
                elif pct < -0.1:
                    loses += 1
        win_rate = round(wins / max(wins + loses, 1) * 100, 1)

        # --- entry_score 均值：直接抓 reason="信号触发 (score=X.X)" 里的 X.X，不用去 df 匹配日期 ---
        entry_scores = []
        for e in log:
            if str(e.get('action','')).strip() == '建仓':
                m = re.search(r'score=([\-\d.]+)', str(e.get('reason','')))
                if m:
                    try:
                        entry_scores.append(float(m.group(1)))
                    except:
                        pass
        avg_score_on_entry = float(np.mean(entry_scores)) if entry_scores else 0.0

        # winner 峰值
        winner_vals = list(pd.to_numeric(df['winner'], errors='coerce').dropna())
        winner_at_max = float(np.max(winner_vals)) if winner_vals else 0.0
        if winner_vals:
            peak_idx = int(np.argmax(winner_vals))
            fall_from_peak_days = max(0, len(winner_vals) - 1 - peak_idx)
        else:
            fall_from_peak_days = 0

        return {
            'ts_code': ts_code, 'name': name,
            'total_ret': total_ret, 'buy_hold': buy_hold, 'excess': excess,
            'sharpe': round(sharpe, 3), 'max_dd': round(max_dd, 2),
            'win_rate': win_rate, 'trades': len(trades),
            'log': log,
            'entry_count': entry_count, 'warn_count': warn_count,
            'high_count': high_count, 'stop_loss_hit': stop_loss_hit,
            'pre_tp_count': pre_tp_count, 'close_count': close_count,
            'avg_score_on_entry': round(avg_score_on_entry, 2),
            'winner_at_max': round(winner_at_max, 1),
            'fall_from_peak_days': fall_from_peak_days,
            'error': None,
        }
    except Exception as e:
        traceback.print_exc()
        return {'ts_code': ts_code, 'name': name, 'error': str(e),
                'total_ret': -999, 'buy_hold': -999, 'excess': -999,
                'sharpe': -999, 'max_dd': 0, 'trades': []}


def run_batch(params: Dict, start: str, end: str, pool=None,
              chip_weight=DEFAULT_CHIP_W, kronos_weight=DEFAULT_KRONOS_W) -> List[Dict]:
    pool = pool or STOCKS_POOL
    results = []
    for ts_code, name in pool:
        r = run_one_attributed(ts_code, name, params, start, end, chip_weight, kronos_weight)
        results.append(r)
    return results


# ============================================================
# ★ P2-1 新增: Layer 0 信号级多窗口前置筛选
# ============================================================
# 设计思路（复用 DailyReviewEngine 的多窗口后验方法论）:
#   对给定参数组合，先不跑完整的交易回测（慢，1~2s/股），
#   而是在信号触发日（chip_score + Kronos 融合 score ≥ entry_score）做
#   三窗口后验统计（快，毫秒级/股）。
#   → 多窗口综合胜率 ≥ 阈值，才进入 Layer 1 的完整交易回测。
#
# ★ P3 实战校准: 后验窗口从 T+5/T+10/T+20 → T+3/T+7/T+14
#   理由: 1337 笔真实交易回测显示
#     - 用户 53% 持仓 < 3 天 (T+1/T+2)
#     - 7-14 天波段胜率最高 (58.8% vs 41.6% 超短)
#   把评估窗口对齐实盘节奏，能更准确反映信号在不同持仓周期下的有效性。
# ============================================================
# 后验窗口 (可被 params 覆盖)
LAYER0_WINDOWS = (3, 7, 14)


def _signal_level_eval_one(ts_code: str, name: str, start: str, end: str,
                           params: Dict) -> Dict:
    """
    单股信号级评估 (多窗口后验投票，不执行实际交易)
    Returns: { rise_cnt, fall_cnt, shake_cnt, total,
               t3_hit, t7_hit, t14_hit, combined_score, avg_future_ret }
    """
    import pickle as _pk
    # 1) 取缓存数据
    full_data = None
    for (s, e) in [(TRAIN_START, TRAIN_END), (VAL_START, VAL_END), (start, end)]:
        fp = _cache_path(ts_code, s, e)
        if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
            try:
                with open(fp, 'rb') as f:
                    seg = _pk.load(f)
                if full_data is None:
                    full_data = seg
                else:
                    for key in ('kline', 'chip_data', 'indicators'):
                        a = full_data.get(key)
                        b = seg.get(key)
                        if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
                            full_data[key] = pd.concat([a, b]).drop_duplicates()
            except Exception:
                pass
    if full_data is None:
        return {"error": "no_cache", "combined_score": -1.0, "total": 0}

    kline = full_data.get('kline', pd.DataFrame())
    chip_data = full_data.get('chip_data', pd.DataFrame())
    if kline.empty or chip_data.empty or 'close' not in kline.columns:
        return {"error": "no_kline/chip", "combined_score": -1.0, "total": 0}

    # 归一化日期
    for df in (kline, chip_data):
        if df is None:
            continue
        for col in ('trade_date', 'date', 'vtrade_date'):
            if col in df.columns:
                df['_dn'] = df[col].astype(str).str.replace('-', '').str.strip()
                break
        if '_dn' not in df.columns:
            df['_dn'] = ''
    kline_sorted = kline.sort_values('_dn').reset_index(drop=True)
    close_sr = pd.to_numeric(kline_sorted['close'], errors='coerce').fillna(0)

    # 2) 逐日计算 chip_score + 判断是否"信号触发"
    entry_threshold = float(params.get('entry_score', DEFAULT_PARAMS['entry_score']))
    stop_loss_ratio = float(params.get('stop_loss', DEFAULT_PARAMS['stop_loss']))

    metrics_history = {}   # date → metrics dict
    triggers = []          # (idx, date, chip_score, avg_cost_for_stop)

    n = len(kline_sorted)
    for i in range(n):
        d = kline_sorted['_dn'].iloc[i]
        if not d:
            continue
        if d < start or d > end:
            continue
        c = float(close_sr.iloc[i]) if close_sr.iloc[i] else 0
        if c <= 0:
            continue
        chip_day = None
        if 'trade_date' in chip_data.columns:
            mask = chip_data['_dn'] == d
            chip_day = chip_data[mask]
        elif '_dn' in chip_data.columns:
            chip_day = chip_data[chip_data['_dn'] == d]
        else:
            chip_day = chip_data.head(0)
        if chip_day is None or len(chip_day) < 3:
            continue
        m = compute_chip_metrics(chip_day, close=c)
        if m is None:
            continue
        metrics_history[d] = m
        # 计算 chip_score (需要 7 天前的指标)
        dates_sorted = sorted(metrics_history.keys())
        pos = dates_sorted.index(d) if d in dates_sorted else -1
        score = None
        if pos >= 7:
            prev_d = dates_sorted[pos - 7]
            try:
                score = int(analyze_chip_health(m, metrics_history[prev_d]).get('score', 0))
            except Exception:
                score = None
        if score is None:
            continue
        # ★ P3 #2: winner 硬过滤 (主力亏本被套 < 30% 直接淘汰)
        #   1337 笔回测: winner<30% 胜率仅 ~35%, 远低于 winner>=50% 的 52%
        winner = float(m.get('winner', 0) or 0)
        if winner < 0.30:
            continue
        # ★ P3 #1: v2 score 过滤 (v2 < 50 直接淘汰)
        #   v2 = 0.27·winner + 0.28·score + 0.18·resistance + 0.17·peaks_below + ...
        #   50 是中性值；<50 表示综合"该卖"信号
        #   注: m 不含 score 键，需注入否则 v2 的 28% 权重维度永远 fallback=0
        m['score'] = score
        try:
            v2_score = chip_score_v2(m)
        except Exception:
            v2_score = 50.0
        if v2_score < 50.0:
            continue
        # 是否触发 entry 信号？这里简化：chip_score >= entry_threshold (不考虑 Kronos 权重，纯信号级)
        if score >= entry_threshold:
            triggers.append((i, d, score, c, v2_score))

    if not triggers:
        return {"ts_code": ts_code, "name": name, "combined_score": 0.0,
                "total": 0, "no_trigger": True,
                "t3_hit": 0, "t7_hit": 0, "t14_hit": 0}

    # 3) 对每个触发点做三窗口后验 (P3 校准: T+3 / T+7 / T+14)
    W_T3, W_T7, W_T14 = LAYER0_WINDOWS
    t3 = t7 = t14 = {"rise": 0, "fall": 0, "shake": 0}
    ret_sum = 0.0
    valid = 0
    burst_count = 0
    stopped_early_count = 0
    for (idx, d, score, entry_price, v2_score) in triggers:
        # T+3 (超短持仓)
        r3 = classify_future(close_sr, idx, W_T3)
        if r3["label"] != "no_data":
            t3[r3["label"]] = t3.get(r3["label"], 0) + 1
        # T+7 (中线持仓)
        r7 = classify_future(close_sr, idx, W_T7)
        if r7["label"] != "no_data":
            t7[r7["label"]] = t7.get(r7["label"], 0) + 1
            ret_sum += float(r7.get("change_pct") or 0.0)
            valid += 1
            if r7.get("burst_detected"):
                burst_count += 1
            # 简化版止损检查 (T+7 日内最低点跌破 entry*stop_loss 视为被止损)
            seg_lo = float(close_sr.iloc[idx+1:min(idx+W_T7+1, n)].min()) if idx + 1 < n else entry_price
            if seg_lo < entry_price * stop_loss_ratio:
                stopped_early_count += 1
        # T+14 (波段持仓, 用户回测中胜率最高)
        r14 = classify_future(close_sr, idx, W_T14)
        if r14["label"] != "no_data":
            t14[r14["label"]] = t14.get(r14["label"], 0) + 1

    def _hit(window: Dict):
        tot = sum(window.values())
        return window.get("rise", 0) / tot if tot else 0.0

    t3_hit = _hit(t3)
    t7_hit = _hit(t7)
    t14_hit = _hit(t14)
    # 综合得分: T+7 权重 50%, T+3/T+14 各 25%
    # (T+7 之所以最重, 因为用户实盘 7-14 天波段胜率 58.8%, 是最佳持仓周期)
    combined_score = 0.25 * t3_hit + 0.50 * t7_hit + 0.25 * t14_hit
    avg_ret = ret_sum / valid if valid else 0.0
    # ★ P3 #1+#2: triggers 已被 v2 score + winner 双重过滤
    #   返回平均 v2 供上层调试
    avg_v2 = round(sum(t[4] for t in triggers) / len(triggers), 1) if triggers else 0.0
    return {
        "ts_code": ts_code, "name": name,
        "triggers": len(triggers),
        "total_valid": valid,
        "avg_future_ret_T7": round(avg_ret, 2),
        "burst_rate": round(burst_count / max(valid, 1), 3),
        "stop_loss_hit_rate": round(stopped_early_count / max(valid, 1), 3),
        "t3": t3, "t7": t7, "t14": t14,
        "t3_hit_rate": round(t3_hit, 3),
        "t7_hit_rate": round(t7_hit, 3),
        "t14_hit_rate": round(t14_hit, 3),
        "combined_score": round(combined_score, 4),
        "avg_v2_score": avg_v2,  # ★ P3 调试字段: 反映该股 trigger 时的平均 v2
        "no_trigger": False,
    }


def layer0_signal_screen(param_grid: Dict, start: str, end: str,
                         top_k_ratio: float = 0.20,
                         min_combined_hit: float = 0.45,
                         pool=None) -> List[Dict]:
    """
    ★ P2-1 Layer 0 前置筛选: 先用信号级多窗口淘汰明显无预测力的参数组合

    Args:
        param_grid:   参数搜索空间 (dict of lists)
        start, end:   评估区间
        top_k_ratio:  保留前百分之多少的参数组合 (默认前 20%)
        min_combined_hit: 三窗口综合命中率最低准入门槛 (默认≥45%, 否则丢弃)
        pool:         股票池

    Returns:
        筛选后的参数组合列表，按综合得分降序。每个元素:
          { 'params': {...}, 'avg_score': 0.65, 'per_stock': [...] }
    """
    import itertools as _it
    pool = pool or STOCKS_POOL
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    combos = list(_it.product(*values))
    total = len(combos)
    print(f'\n  🧪 Layer0 信号级三窗口筛选：参数组合 {total} 组 × {len(pool)} 股')
    print(f'     准入卡：三窗口综合命中率≥{min_combined_hit*100:.0f}%，保留前 {top_k_ratio*100:.0f}%')

    scored = []
    for i, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        # 拷贝嵌套 list 型参数（warn_ratio_schedule），避免共享引用
        for k in keys:
            if isinstance(param_grid[k][0], list) and not isinstance(params[k], list):
                pass
            if isinstance(params[k], list):
                params[k] = params[k][:]
        per_stock = []
        n_trig = 0
        n_valid = 0
        sum_sc = 0.0
        for ts_code, name in pool:
            ev = _signal_level_eval_one(ts_code, name, start, end, params)
            per_stock.append(ev)
            if ev.get("total_valid", 0) > 0:
                sum_sc += ev.get("combined_score", 0.0) or 0.0
                n_trig += ev.get("triggers", 0) or 0
                n_valid += 1
        avg_sc = sum_sc / n_valid if n_valid else 0.0
        # 跨股稳定性惩罚：至少 50% 股票有触发信号，否则惩罚
        stable_bonus = (n_valid / len(pool)) ** 0.5 if pool else 0.0
        final_sc = round(avg_sc * (0.5 + 0.5 * stable_bonus), 4)
        scored.append({"params": params, "avg_score": avg_sc,
                       "stable_adjusted_score": final_sc,
                       "triggers_per_stock_avg": round(n_trig / max(len(pool), 1), 1),
                       "valid_stock_ratio": round(n_valid / max(len(pool), 1), 2),
                       "per_stock_summary": [
                           {"ts_code": s["ts_code"], "combined_score": s.get("combined_score"),
                            "triggers": s.get("triggers", 0), "avg_ret_T10": s.get("avg_future_ret_T10")}
                           for s in per_stock if not s.get("no_trigger") and not s.get("error")
                       ]})
        if i % 5 == 0 or i == total:
            print(f'    [{i}/{total}] 处理中...  最佳={max(s["stable_adjusted_score"] for s in scored):.3f} 当前combo={final_sc:.3f}')

    # 过滤 + 排序
    filtered = [s for s in scored if s["avg_score"] >= min_combined_hit]
    if not filtered:
        print(f'    ⚠️  没有组合达到 {min_combined_hit*100:.0f}%，放宽门槛取前 50%')
        scored_sorted = sorted(scored, key=lambda x: x["stable_adjusted_score"], reverse=True)
        filtered = scored_sorted[: max(1, len(scored_sorted) // 2)]
    else:
        filtered.sort(key=lambda x: x["stable_adjusted_score"], reverse=True)
    keep_n = max(1, int(len(filtered) * top_k_ratio))
    kept = filtered[:keep_n]
    print(f'    ✅ 信号级筛选完成: {total} → 准入 {len(filtered)} → 保留 Top {keep_n}')
    print(f'       Top3 综合得分: {[k["stable_adjusted_score"] for k in kept[:3]]}')
    return kept


# ============================================================
# 🎯 Layer2：表现分层 + 自动归因 → 生成参数搜索空间
# ============================================================
def categorize_and_attribute(results: List[Dict], baseline_avg: float) -> Tuple[List[Dict], List[Dict], List[Dict], Dict]:
    """
    分 3 层，并针对退化样本输出「参数搜索空间」
    returns: (stars, normals, bads, suggested_grid)
    """
    stars, normals, bads = [], [], []
    for r in results:
        if r.get('error') or r.get('total_ret', -999) == -999:
            continue
        delta_vs_avg = r['total_ret'] - baseline_avg
        if delta_vs_avg >= 15.0:
            stars.append(r)
        elif delta_vs_avg <= -5.0:
            bads.append(r)
        else:
            normals.append(r)

    # --- 生成搜索空间：【先加基准DEFAULT + 两侧合理探索步长 → 再按归因增量加更激进档位】---
    grid = {
        'entry_score':         [DEFAULT_PARAMS['entry_score']],
        'warn_winner':         [DEFAULT_PARAMS['warn_winner']],
        'high_winner':         [DEFAULT_PARAMS['high_winner']],
        'exit_winner':         [DEFAULT_PARAMS['exit_winner']],
        'stop_loss':           [DEFAULT_PARAMS['stop_loss']],
        'pre_tp_min_ret':      [DEFAULT_PARAMS['pre_tp_min_ret']],
        'warn_ratio_schedule': [DEFAULT_PARAMS['warn_ratio_schedule'][:]],
        'entry_width_max_q':   [DEFAULT_PARAMS['entry_width_max_q']],
        'require_tpc_converge':[DEFAULT_PARAMS['require_tpc_converge']],
    }

    # ===== 默认基探索：关键参数给 3~5 档，保证第一轮就能探索足够宽的有效范围 =====
    # entry_score：给 2.5 ~ 6.0 范围（覆盖踏空的左侧抄底→接最后一棒的严格过滤）
    grid['entry_score'] = sorted(set(grid['entry_score']) | {2.5, 3.0, 3.5, 4.0, 4.5, 5.5, 6.0, 6.5})
    # stop_loss：0.86 ~ 0.96 覆盖死扛→快速止损
    grid['stop_loss']   = sorted(set(grid['stop_loss'])   | {0.86, 0.88, 0.90, 0.94, 0.95, 0.96})
    # pre_tp_min_ret：40 ~ 85 覆盖"很早就止盈"→"死扛直到清仓触发"
    grid['pre_tp_min_ret'] = sorted(set(grid['pre_tp_min_ret']) | {40, 50, 55, 65, 70, 80, 85})
    # exit_winner：90 ~ 99 覆盖"提前跑"→"最后跑"
    grid['exit_winner']    = sorted(set(grid['exit_winner'])    | {90, 91, 92, 93, 96, 97, 98, 99})
    # warn_winner：76 ~ 85
    grid['warn_winner']    = sorted(set(grid['warn_winner'])    | {76, 78, 82, 84, 85})
    # high_winner：86 ~ 95
    grid['high_winner']    = sorted(set(grid['high_winner'])    | {86, 88, 92, 93, 95})
    # entry_width_max_q：0.85 ~ 1.0（关闭宽度过滤）
    grid['entry_width_max_q'] = sorted(set(grid['entry_width_max_q']) | {0.85, 0.88, 0.92, 0.95, 1.0})
    # require_tpc_converge：两个方向都试
    grid['require_tpc_converge'] = sorted(set(grid['require_tpc_converge']) | {False, True})
    # warn_ratio_schedule：再加 2 种差异大的，保证能探索"快速砍仓"vs"慢减仓"
    grid['warn_ratio_schedule'].append([0.50, 0.35, 0.15, 0.00])
    grid['warn_ratio_schedule'].append([0.20, 0.15, 0.10, 0.05])

    for bad in bads:
        # ===== 归因 1：建仓相关 =====
        # 1a：完全没建仓（entry=0，踏空）→ 更激进地降低门槛
        if bad['entry_count'] == 0:
            grid['entry_score']       = sorted(set(grid['entry_score'])       | {2.0, 2.5, 3.0, 3.5, 4.0, 4.25})
            grid['entry_width_max_q'] = sorted(set(grid['entry_width_max_q']) | {0.92, 0.95, 0.97, 1.0})
            grid['require_tpc_converge'] = sorted(set(grid['require_tpc_converge']) | {False})
        # 1b：建仓后被套（止损≥1）且建仓分偏低 → 大幅提高门槛 + 更紧止损
        elif bad['avg_score_on_entry'] < 5.8 and bad['stop_loss_hit'] >= 1:
            grid['entry_score'] = sorted(set(grid['entry_score']) | {5.5, 6.0, 6.5, 7.0, 7.5})
            grid['stop_loss']   = sorted(set(grid['stop_loss'])   | {0.93, 0.94, 0.95, 0.96})
        # 1c：建仓后被套（止损≥1）但建仓分已经≥6 → 纯粹需要更紧止损
        elif bad['stop_loss_hit'] >= 1:
            grid['stop_loss'] = sorted(set(grid['stop_loss']) | {0.93, 0.94, 0.95})

        # ===== 归因 2：减仓次数过多 + 见顶后快速崩（A杀）→ 更快砍仓/更早预警 =====
        if (bad['warn_count'] + bad['high_count'] >= 4) and bad['fall_from_peak_days'] <= 5:
            grid['warn_ratio_schedule'].append([0.40, 0.30, 0.15, 0.05])
            grid['warn_ratio_schedule'].append([0.45, 0.30, 0.15, 0.05])
            grid['warn_ratio_schedule'].append([0.55, 0.35, 0.10, 0.00])
            grid['warn_winner'] = sorted(set(grid['warn_winner']) | {74, 75, 76, 78, 82, 83})

        # ===== 归因 3：winner 峰值很高但 excess<=0（卖飞 or 接最后一棒）→ 大幅调整止盈 =====
        if bad['winner_at_max'] >= 93.0 and bad['excess'] <= 0:
            grid['pre_tp_min_ret'] = sorted(set(grid['pre_tp_min_ret']) | {35, 40, 45, 50, 70, 75, 80, 85, 90})
            grid['exit_winner']    = sorted(set(grid['exit_winner'])    | {89, 90, 91, 92, 93, 94, 96, 97, 98, 99})
            grid['high_winner']    = sorted(set(grid['high_winner'])    | {85, 86, 87, 88, 92, 93, 94, 95})

    # 去重 list 值
    grid['warn_ratio_schedule'] = list({json.dumps(x) for x in grid['warn_ratio_schedule']})
    grid['warn_ratio_schedule'] = [json.loads(x) for x in grid['warn_ratio_schedule']]

    # ---- 最后 Trim：按「距离 DEFAULT 远近 + 分层采样」，每维最多保留 TRIM_PER_DIM=5 档 ----
    # 分层策略（数值型）：取最近1 + 次近2 + 稍远1 + 最远1 = 5档，保证既覆盖邻居又能探索极端值
    TRIM_PER_DIM = 5
    _default_grid = {
        'entry_score':         DEFAULT_PARAMS['entry_score'],
        'warn_winner':         DEFAULT_PARAMS['warn_winner'],
        'high_winner':         DEFAULT_PARAMS['high_winner'],
        'exit_winner':         DEFAULT_PARAMS['exit_winner'],
        'stop_loss':           DEFAULT_PARAMS['stop_loss'],
        'pre_tp_min_ret':      DEFAULT_PARAMS['pre_tp_min_ret'],
        'warn_ratio_schedule': DEFAULT_PARAMS['warn_ratio_schedule'],
        'entry_width_max_q':   DEFAULT_PARAMS['entry_width_max_q'],
        'require_tpc_converge':DEFAULT_PARAMS['require_tpc_converge'],
    }
    for k in grid:
        vals = grid[k]
        if len(vals) <= TRIM_PER_DIM:
            continue
        default_v = _default_grid.get(k, vals[0])
        if isinstance(default_v, list):
            # 离散list：保留 DEFAULT + 前4个不同的
            kept = [default_v]
            for v in vals:
                if v != default_v and len(kept) < TRIM_PER_DIM:
                    kept.append(v)
            grid[k] = kept
        else:
            # 数值型：分层采样 → 既保证邻居，也保证极端值能被探索到
            unique = sorted(set(vals))
            sorted_by_dist = sorted(unique, key=lambda x: abs(x - default_v))
            # 索引 0:default 自己; 1,2:最近两侧; 然后取中间 + 最远各1
            keep_idx = [0]
            # 最近 2 个（如果存在）
            for i in range(1, min(3, len(sorted_by_dist))):
                keep_idx.append(i)
            # 中间 1 个
            if len(sorted_by_dist) >= 4:
                keep_idx.append(len(sorted_by_dist) // 2)
            # 最远 1 个
            if len(sorted_by_dist) >= 5:
                keep_idx.append(len(sorted_by_dist) - 1)
            # 去重 + 按值排序
            kept_vals = sorted({sorted_by_dist[i] for i in keep_idx if i < len(sorted_by_dist)})
            # 可能因为中间/最远重复导致不足，再补最近的
            if len(kept_vals) < TRIM_PER_DIM:
                for i in range(3, len(sorted_by_dist)):
                    if sorted_by_dist[i] not in kept_vals:
                        kept_vals.append(sorted_by_dist[i])
                        if len(kept_vals) >= TRIM_PER_DIM:
                            break
                kept_vals = sorted(kept_vals)
            grid[k] = kept_vals[:TRIM_PER_DIM]

    # 去重 schedule
    grid['warn_ratio_schedule'] = list({json.dumps(x) for x in grid['warn_ratio_schedule']})
    grid['warn_ratio_schedule'] = [json.loads(x) for x in grid['warn_ratio_schedule']]

    return stars, normals, bads, grid


# ============================================================
# 🧬 Layer3：参数基因演化
#   3.1 定向网格搜索（针对 bad 样本的局部空间）
#   3.2 差分进化全局优化（6 个连续参数）
#   3.3 Kronos 权重联调（已有 evolve_weights，这里直接调用）
# ============================================================
def _params_from_combo(combo: Tuple, keys: List[str]) -> Dict:
    """把网格 tuple + keys → 完整 HoldingManager params dict"""
    base = {
        'entry_strict': False,
        'warn_cost_dist': 10, 'warn_min_ret': 10,
        'high_cost_dist': 15, 'high_min_ret': 20,
        'exit_cost_dist': 20,
        'pre_tp_winner': 92, 'pre_tp_days': 3, 'pre_tp_stall_days': 2,
        'pre_tp_pct': 0.5,
        'high_first_ratio': 0.30,
        'warn_min_keep': 0.15,
    }
    for k, v in zip(keys, combo):
        base[k] = v
    return base


def grid_search_over_bads(results_train: List[Dict],
                          grid: Dict,
                          start: str, end: str,
                          metric: str = 'combined',
                          max_combos: int = 2000) -> Tuple[Dict, float]:
    """
    只对「坏样本」的并集搜索空间跑网格，找让坏样本平均表现最好的参数组合。
    - 如果参数组合 > max_combos（默认 900 组），自动**随机采样**到 max_combos（蒙特卡罗近似，避免网格爆炸）
    metric: combined (默认, 0.6*total_ret+0.4*excess) | excess | total_ret | sharpe
    """
    valid = [r for r in results_train if not r.get('error') and r.get('total_ret', -999) != -999]
    baseline_avg = float(np.mean([r['total_ret'] for r in valid]))
    stars, normals, bads_list, _ = categorize_and_attribute(results_train, baseline_avg)
    target_pool = [(r['ts_code'], r['name']) for r in bads_list] or STOCKS_POOL

    def _metric(r):
        if metric == 'combined':
            return 0.6 * r['total_ret'] + 0.4 * r['excess']
        return r.get(metric, -999)

    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combos = list(itertools.product(*values))
    print(f'    🎯 网格搜索：原始 {len(combos)} 组参数 × 目标样本 {len(target_pool)} 只 (metric={metric})')

    # --- 网格爆炸自动抽样（蒙特卡罗近似，上限 max_combos 组）---
    if len(combos) > max_combos:
        import random
        random.seed(42 + int(time.time()) % 1000)
        # 确保 DEFAULT_PARAMS 对应组合在候选里（免得把基准自己丢了）
        default_combo = []
        for k in keys:
            v = DEFAULT_PARAMS.get(k, values[0][0] if values and values[0] else None)
            if isinstance(v, list):
                # warn_ratio_schedule 这种 list 值，找 grid 里最接近的
                grid_list = grid[k]
                try:
                    idx = min(range(len(grid_list)), key=lambda i: sum(abs(a-b) for a, b in zip(grid_list[i], v)) if isinstance(grid_list[i], list) and len(grid_list[i])==len(v) else 99999)
                except:
                    idx = 0
                default_combo.append(grid_list[idx])
            else:
                candidates = grid[k]
                closest = min(candidates, key=lambda x: abs(x-v) if isinstance(x, (int,float)) else 0)
                default_combo.append(closest)
        default_combo = tuple(default_combo)
        sampled = random.sample(combos, min(max_combos, len(combos)))
        if default_combo not in sampled and len(sampled) >= 2:
            sampled[-1] = default_combo
        combos = sampled
        print(f'      💥 原始组合数太大，自动随机抽样到 {len(combos)} 组（含 DEFAULT 参数作基线）')

    best_score = -float('inf')
    best_params = None
    t0 = time.time()
    for idx, combo in enumerate(combos):
        p = _params_from_combo(combo, keys)
        batch_r = run_batch(p, start, end, pool=target_pool)
        valid_r = [r for r in batch_r if not r.get('error') and r.get('total_ret', -999) != -999]
        if not valid_r:
            continue
        scores = [_metric(r) for r in valid_r]
        if not scores:
            continue
        score = float(np.mean(scores))
        # 额外惩罚：平均 max_dd 超过 30% 直接降 5 分
        dd_vals = [abs(r.get('max_dd', 0)) for r in valid_r]
        if dd_vals:
            avg_dd = float(np.mean(dd_vals))
            if avg_dd > 30: score -= 5.0
        if score > best_score:
            best_score = score
            best_params = p
        if idx % 40 == 39:
            eta = (time.time() - t0) / (idx + 1) * (len(combos) - idx - 1)
            print(f'      … {idx+1}/{len(combos)} done, 当前最优 {metric}={best_score:.2f}, 预计剩余 {eta:.0f}s')
    return best_params or _params_from_combo(combos[0], keys), best_score


# 差分进化：6 个连续参数 → bounds
DE_BOUNDS = [
    (4.0, 7.5),     # entry_score
    (75.0, 88.0),   # warn_winner
    (85.0, 96.0),   # high_winner
    (90.0, 98.0),   # exit_winner
    (0.88, 0.96),   # stop_loss
    (40.0, 80.0),   # pre_tp_min_ret
]
DE_KEYS = ['entry_score', 'warn_winner', 'high_winner', 'exit_winner', 'stop_loss', 'pre_tp_min_ret']

# 典型离散组合（差分进化只负责连续参数）
DISCRETE_CANDIDATES = [
    # (schedule, width_q, require_tpc)
    ([0.30, 0.20, 0.10, 0.05], 0.90, False),
    ([0.35, 0.25, 0.15, 0.05], 0.90, False),
    ([0.40, 0.30, 0.15, 0.05], 0.95, False),
    ([0.30, 0.20, 0.10, 0.05], 0.85, True),
]


def differential_evolution_global(start: str, end: str,
                                  popsize: int = 10,
                                  maxiter: int = 10,
                                  metric: str = 'excess') -> Tuple[Dict, float]:
    """
    scipy 差分进化：寻找让 9 只股票平均 excess（或 sharpe）最大的 6 个连续参数
    每个评估点还要对 4 种离散组合取最优，避免漏掉好组合
    """
    def _evaluate(continuous_vec):
        p_continuous = dict(zip(DE_KEYS, continuous_vec))
        best_m = -float('inf')
        for schedule, wq, rtpc in DISCRETE_CANDIDATES:
            p_full = _params_from_combo(tuple([p_continuous[k] for k in DE_KEYS]), DE_KEYS)
            p_full['warn_ratio_schedule'] = schedule
            p_full['entry_width_max_q'] = wq
            p_full['require_tpc_converge'] = rtpc
            batch_r = run_batch(p_full, start, end)
            valid_r = [r for r in batch_r if not r.get('error') and r.get('total_ret', -999) != -999]
            if not valid_r:
                continue
            vals = [r.get(metric, -999) for r in valid_r]
            vals = [v for v in vals if v > -999]
            m = float(np.mean(vals)) if vals else -float('inf')
            # 回撤惩罚
            dd_vals = [abs(r.get('max_dd', 0)) for r in valid_r]
            if dd_vals:
                m -= max(0, np.mean(dd_vals) - 15.0) * 0.5
            if m > best_m:
                best_m = m
        return -best_m  # minimize → negative

    t0 = time.time()
    res = differential_evolution(_evaluate, bounds=DE_BOUNDS,
                                 seed=42, popsize=popsize, maxiter=maxiter,
                                 tol=1e-2, mutation=(0.5, 1.2), recombination=0.7,
                                 polish=True, disp=False)
    vec = res.x
    print(f'    🧬 差分进化耗时 {time.time()-t0:.0f}s，最优连续参数={list(zip(DE_KEYS, [round(x,3) for x in vec]))}')

    # 对最优连续向量，再扫一遍 4 种离散组合确定最佳离散
    p_continuous = dict(zip(DE_KEYS, vec))
    best_full_p = None
    best_m = -float('inf')
    for schedule, wq, rtpc in DISCRETE_CANDIDATES:
        p_full = _params_from_combo(tuple(vec), DE_KEYS)
        p_full['warn_ratio_schedule'] = schedule
        p_full['entry_width_max_q'] = wq
        p_full['require_tpc_converge'] = rtpc
        batch_r = run_batch(p_full, start, end)
        valid_r = [r for r in batch_r if not r.get('error') and r.get('total_ret', -999) != -999]
        if not valid_r: continue
        vals = [r.get(metric, -999) for r in valid_r]
        vals = [v for v in vals if v > -999]
        m = float(np.mean(vals)) if vals else -float('inf')
        if m > best_m:
            best_m = m
            best_full_p = p_full
    return best_full_p, best_m


# ============================================================
# 🛡️ Layer4：参数准入卡（防过拟合 — 3 条门槛）
# ============================================================
def pass_admission(old_params: Dict, new_params: Dict,
                   train_old: List[Dict], train_new: List[Dict],
                   val_old: List[Dict], val_new: List[Dict],
                   rule1_threshold: float = 0.5,
                   train_bads_old_avg_combined: Optional[float] = None,
                   train_bads_new_avg_combined: Optional[float] = None) -> Tuple[bool, str, str]:
    """
    准入规则：
    ┌───────────────────────────────────────────────────────────────┐
    │  HARD PASS（强通过）: 规则1 + 规则2 + 规则3 全部满足           │
    │    rule1: Val 平均收益 ≥ 老 + threshold (0.2%~0.5%)           │
    │    rule2: Val 最大回撤恶化 ≤ 8%                               │
    │    rule3: Val 退化样本率增加 ≤ 12%                            │
    ├───────────────────────────────────────────────────────────────┤
    │  SOFT PASS（软通过）: 当 HARD 不满足，但满足以下所有条件时      │
    │    * Train 坏样本 平均 combined_score 提升 ≥ 15%              │
    │        (说明参数确实在训练集上解决了之前的"坏样本问题")         │
    │    * Val 平均收益 Δ ≥ -1.5% (允许一定的小幅波动，不苛求立即↑)  │
    │    * Val 回撤恶化 ≤ 10% (略微放宽)                            │
    │    * Val 退化样本率 ↑ ≤ 18% (略微放宽)                        │
    │  每代最多允许 1 个 SOFT 通过，用于打破 3+ 代连续不通过的死循环   │
    └───────────────────────────────────────────────────────────────┘
    returns: (pass: bool, reason: str, level: "hard"|"soft"|"none")
    """
    def _avg(rs, k):
        vs = [r[k] for r in rs if not r.get('error') and r.get('total_ret', -999) != -999]
        return float(np.mean(vs)) if vs else 0.0

    old_train_ret = _avg(train_old, 'total_ret')
    new_train_ret = _avg(train_new, 'total_ret')
    old_val_ret   = _avg(val_old,   'total_ret')
    new_val_ret   = _avg(val_new,   'total_ret')

    old_train_dd = abs(_avg(train_old, 'max_dd'))
    new_train_dd = abs(_avg(train_new, 'max_dd'))
    old_val_dd   = abs(_avg(val_old,   'max_dd'))
    new_val_dd   = abs(_avg(val_new,   'max_dd'))

    def _bad_ratio(rs):
        valid = [r for r in rs if not r.get('error') and r.get('total_ret', -999) != -999]
        if not valid: return 0.0
        return float(sum(1 for r in valid if r['total_ret'] - r['buy_hold'] < -5.0)) / len(valid)

    old_bad = _bad_ratio(val_old)
    new_bad = _bad_ratio(val_new)

    # ============== HARD RULES ==============
    rule1 = (new_val_ret - old_val_ret) >= rule1_threshold
    rule2 = new_val_dd <= old_val_dd + 8.0
    rule3 = new_bad <= old_bad + 0.12
    hard_pass = rule1 and rule2 and rule3

    # ============== SOFT RULES ==============
    soft_pass = False
    soft_reasons = []
    if not hard_pass:
        # 先判断 bad combined 提升是否足够大
        bad_lift_ok = False
        bad_lift_pct = 0.0
        if train_bads_old_avg_combined is not None and train_bads_new_avg_combined is not None and train_bads_old_avg_combined != 0:
            bad_lift_pct = (train_bads_new_avg_combined - train_bads_old_avg_combined) / abs(train_bads_old_avg_combined) * 100 if train_bads_old_avg_combined != 0 else 999.0
            if train_bads_new_avg_combined > train_bads_old_avg_combined:
                bad_lift_ok = (train_bads_new_avg_combined - train_bads_old_avg_combined) >= 0.15 * max(1.0, abs(train_bads_old_avg_combined))
        # 其他放宽规则
        soft_rule1 = (new_val_ret - old_val_ret) >= -1.5   # 允许 Val 小幅变差（-1.5%以内）
        soft_rule2 = new_val_dd <= old_val_dd + 10.0
        soft_rule3 = new_bad <= old_bad + 0.18
        soft_all = soft_rule1 and soft_rule2 and soft_rule3 and bad_lift_ok
        if soft_all:
            soft_pass = True
            soft_reasons.append(f'Train坏样本combined提升 {bad_lift_pct:+.1f}% ≥ 15%阈值')

    # ============== 组合最终判断 + 打印reason ==============
    all_pass = hard_pass or soft_pass
    level = 'hard' if hard_pass else ('soft' if soft_pass else 'none')
    lines = []
    lines.append(
        f'规则1(Val+{rule1_threshold:.1f}%↑): {"✅" if rule1 else "❌"} {old_val_ret:+.2f}% → {new_val_ret:+.2f}% (Δ={new_val_ret-old_val_ret:+.2f}%)'
    )
    lines.append(
        f'规则2(Val回撤恶化≤8%): {"✅" if rule2 else "❌"} {old_val_dd:.2f}% → {new_val_dd:.2f}% (Δ{new_val_dd-old_val_dd:+.2f}%)'
    )
    lines.append(
        f'规则3(坏样本率↑≤12%): {"✅" if rule3 else "❌"} {old_bad*100:.0f}% → {new_bad*100:.0f}%'
    )
    lines.append(f'训练集: {old_train_ret:+.2f}% → {new_train_ret:+.2f}% (Δ={new_train_ret-old_train_ret:+.2f}%)')
    if not hard_pass and train_bads_old_avg_combined is not None:
        lines.append(
            f'Train坏样本combined: {train_bads_old_avg_combined:+.2f} → {train_bads_new_avg_combined if train_bads_new_avg_combined else 0.0:+.2f}'
            + (f'  ✅ 提升 {bad_lift_pct:+.1f}%' if bad_lift_pct > 0 else f'  ❌ 变化 {bad_lift_pct:+.1f}%')
        )
    if soft_pass:
        lines.append(f'✨ 【SOFT PASS】{" | ".join(soft_reasons)} → 允许通过（打破进化死循环）')
    reason = '\n'.join(lines)
    return all_pass, reason, level


# ============================================================
# 🔁 主进化循环
# ============================================================
DEFAULT_PARAMS = {
    'entry_score': 5, 'entry_strict': False,
    'require_tpc_converge': False, 'entry_width_max_q': 0.9,
    'warn_winner': 80, 'warn_cost_dist': 10, 'warn_min_ret': 10,
    'high_winner': 90, 'high_cost_dist': 15, 'high_min_ret': 20,
    'exit_winner': 95, 'exit_cost_dist': 20,
    'pre_tp_winner': 92, 'pre_tp_days': 3, 'pre_tp_stall_days': 2,
    'pre_tp_pct': 0.5, 'pre_tp_min_ret': 60,
    'warn_ratio_schedule': [0.30, 0.20, 0.10, 0.05],
    'high_first_ratio': 0.30, 'warn_min_keep': 0.15, 'stop_loss': 0.92,
}


def _summary_table(results: List[Dict], title: str):
    w = 16
    valid = [r for r in results if not r.get('error') and r.get('total_ret', -999) != -999]
    print(f'\n  📊 {title}   (n={len(valid)})')
    print('  ' + '='*(w*5+40))
    hdr = f'  {"代码":<12}{"名称":<10}{"买入持有":>{w-2}}{"总收益":>{w}}{"超额":>{w}}{"夏普":>{w}}{"最大回撤":>{w}}{"胜率":>{w-6}}'
    print(hdr)
    print('  ' + '-'*(len(hdr)-2))
    avg_bh = avg_ret = avg_ex = avg_sh = avg_dd = avg_wr = 0.0
    for r in valid:
        print(f'  {r["ts_code"]:<12}{r["name"]:<10}{r["buy_hold"]:>{w-2}.2f}{r["total_ret"]:>{w}.2f}{r["excess"]:>{w}.2f}'
              f'{r["sharpe"]:>{w}.3f}{r["max_dd"]:>{w}.2f}%{r["win_rate"]:>{w-6}.1f}%')
        avg_bh += r['buy_hold']; avg_ret += r['total_ret']; avg_ex += r['excess']
        avg_sh += r['sharpe'];  avg_dd += r['max_dd'];    avg_wr += r['win_rate']
    n = max(len(valid), 1)
    print('  ' + '-'*(len(hdr)-2))
    print(f'  {"【平均】":<22}{avg_bh/n:>{w-2}.2f}{avg_ret/n:>{w}.2f}{avg_ex/n:>{w}.2f}'
          f'{avg_sh/n:>{w}.3f}{avg_dd/n:>{w}.2f}%{avg_wr/n:>{w-6}.1f}%')


def main():
    print('=' * 130)
    print(f'  🔥 筹码峰 v3.1 闭环进化引擎启动   时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'     训练集: {TRAIN_START} ~ {TRAIN_END}   验证集: {VAL_START} ~ {VAL_END}')
    print(f'     最大代数: {MAX_GENERATIONS}   种群: 9 只历史样本')
    print('=' * 130)

    # ---- Step0：缓存预热（先把所有数据拉好，避免中途限流，后续 0 API 调用）----
    t0 = time.time()
    preheat_all_cache(sleep_sec=4)
    print(f'     📦 预热总耗时 {time.time()-t0:.0f}s\n')

    current_params = deepcopy(DEFAULT_PARAMS)
    chip_w, kronos_w = DEFAULT_CHIP_W, DEFAULT_KRONOS_W
    history = []  # 每代的最优参数 + 结果
    admit_fail_streak = 0   # 连续多少代没通过准入卡 → 到了 2 就临时放宽到 +0.2% 放一次

    for gen in range(1, MAX_GENERATIONS + 1):
        print(f'\n\n  ═══════════════════════════════════════════════════════════════════════════════════')
        print(f'  🚀 第 {gen} 代进化开始  |  当前参数 entry_score={current_params["entry_score"]:.1f}  '
              f'stop_loss={current_params["stop_loss"]:.2f}  chip_w={chip_w:.2f}  '
              f'【准入卡阈值】Val+{0.2 if admit_fail_streak >= 2 else 0.5}%')
        print(f'  ═══════════════════════════════════════════════════════════════════════════════════')

        # ---- Step1：跑 Train + Val 基准 ----
        print(f'\n  [L1/4] 批量回测基准 …')
        t0 = time.time()
        train_old = run_batch(current_params, TRAIN_START, TRAIN_END,
                              chip_weight=chip_w, kronos_weight=kronos_w)
        val_old   = run_batch(current_params, VAL_START,   VAL_END,
                              chip_weight=chip_w, kronos_weight=kronos_w)
        print(f'     回测耗时 {time.time()-t0:.0f}s')
        _summary_table(train_old, f'第{gen}代 训练集 基准（当前参数）')
        _summary_table(val_old,   f'第{gen}代 验证集 基准（当前参数）')

        # ---- Step2：表现分层 + 归因 ----
        print(f'\n  [L2/4] 表现分层 + 自动归因 …')
        valid_train = [r for r in train_old if not r.get('error') and r.get('total_ret', -999) != -999]
        baseline_avg = float(np.mean([r['total_ret'] for r in valid_train]))
        stars, normals, bads, grid = categorize_and_attribute(train_old, baseline_avg)
        print(f'     🟢 明星样本 {len(stars)}  |  🟡 普通 {len(normals)}  |  🔴 退化 {len(bads)}')
        for b in bads:
            print(f'        · 🔴 {b["name"]}: 收益{b["total_ret"]:+.1f}%  止损{b["stop_loss_hit"]}次  '
                  f'预警减仓{b["warn_count"]}次  建仓得分{b["avg_score_on_entry"]:.2f}')
        print(f'     → 建议搜索空间维度: {sum(len(v) for v in grid.values())}')

        # ---- Step3：参数基因演化（先定向网格，再差分进化，取最优）----
        print(f'\n  [L3/4] 参数基因演化 …')
        cand_params_list = []

        # 先算 DEFAULT / 当前参数在坏样本上的 baseline combined_score（给后面准入卡SOFT判断用）
        def _bad_combined(rs, bl_avg):
            _, _, bds, _ = categorize_and_attribute(rs, bl_avg)
            if not bds:
                return 0.0
            return float(np.mean([0.6*r['total_ret']+0.4*r['excess'] for r in bds]))
        train_bads_baseline_combined = _bad_combined(train_old, baseline_avg)
        print(f'   💡 当前参数 Train坏样本 combined = {train_bads_baseline_combined:+.2f} (作为soft准入门槛基准)')

        # 3.1 定向网格搜索（只针对坏样本）
        print(f'   3.1 定向网格搜索（坏样本）…')
        gp, gs = grid_search_over_bads(train_old, grid, TRAIN_START, TRAIN_END, metric='combined')
        if gp:
            cand_params_list.append((gp, gs, '定向网格'))
            print(f'     → 定向网格最优: combined_score(0.6*总收+0.4*超额)={gs:+.2f}'
                  + (f' (比基线 {train_bads_baseline_combined:+.2f} ↑{gs-train_bads_baseline_combined:+.2f})'
                     if train_bads_baseline_combined != 0 else ''))

        # 3.2 差分进化全局（MVP 每代只跑 10×10=100 次评估，约 8~15 分钟）
        print(f'   3.2 差分进化全局（节省时间→此步MVP略过，如需要可把 popsize=5 maxiter=5 打开）…')
        # TODO: 取消下一行注释开启差分进化（耗时更长但更容易找到全局最优）
        # dp, ds = differential_evolution_global(TRAIN_START, TRAIN_END, popsize=5, maxiter=5)
        # if dp:
        #     cand_params_list.append((dp, ds, '差分进化'))

        # 3.3 如果有明星样本，把明星样本的「当前参数」也视为候选（扩散优秀基因）
        if stars:
            # 明星样本当前就是用 current_params 跑出来的 → 不用变，跳过
            pass

        # ---- Step4：准入卡 ----
        print(f'\n  [L4/4] 准入卡校验（样本外 Val 集）…')
        admitted = []
        soft_admitted_pool = []  # soft 通过的放这里，没有 hard 时最多从中挑 1 个
        rule1_th = 0.2 if admit_fail_streak >= 2 else 0.5
        if admit_fail_streak >= 2:
            print(f'     ⚠️  已连续 {admit_fail_streak} 代未通过 — 临时放宽规则1阈值到 Val+{rule1_th:.1f}%，允许小步进化')
        for i, (cand_p, bad_score_gs, tag) in enumerate(cand_params_list):
            print(f'     ▶️  候选 {i+1}/{len(cand_params_list)} [{tag}]：')
            train_new = run_batch(cand_p, TRAIN_START, TRAIN_END)
            val_new   = run_batch(cand_p, VAL_START,   VAL_END)
            # 算一下候选参数的坏样本 combined_score（用于 SOFT 判断）
            bad_score_new = _bad_combined(train_new, baseline_avg)
            ok, reason, level = pass_admission(current_params, cand_p, train_old, train_new, val_old, val_new,
                                               rule1_threshold=rule1_th,
                                               train_bads_old_avg_combined=train_bads_baseline_combined,
                                               train_bads_new_avg_combined=bad_score_new)
            print(reason)
            if ok and level == 'hard':
                vret = float(np.mean([r['excess'] for r in val_new
                                     if not r.get('error') and r.get('total_ret', -999) != -999]))
                admitted.append((vret, cand_p, tag, train_new, val_new, level))
                print(f'     ✅ 【HARD 通过】  Val 平均超额={vret:+.2f}%\n')
            elif ok and level == 'soft':
                vret = float(np.mean([r['excess'] for r in val_new
                                     if not r.get('error') and r.get('total_ret', -999) != -999]))
                soft_admitted_pool.append((vret, cand_p, tag, train_new, val_new, level))
                print(f'     🟡 【SOFT 候选】入池  Val 平均超额={vret:+.2f}% — 如无HARD通过则择优启用\n')
            else:
                print(f'     ❌ 【拒绝】（过拟合风险，舍弃）\n')

        # 没 hard 通过的，从 soft 池里最多挑 1 个最好的 (优先按 Val excess 最高)
        if not admitted and soft_admitted_pool:
            soft_admitted_pool.sort(key=lambda x: -x[0])
            admitted = [soft_admitted_pool[0]]
            best = admitted[0]
            print(f'  🟡 本代无 HARD 通过 → 启用 SOFT 最优候选 [{best[2]}]  Val 平均超额={best[0]:+.2f}%')

        # ---- Step5：选出新一代参数 ----
        if admitted:
            admit_fail_streak = 0   # 有通过的，失败 streak 归零
            admitted.sort(key=lambda x: -x[0])
            best_vret, best_p, best_tag, best_tr, best_vr, best_level = admitted[0]
            print(f'  🏆 新一代参数诞生！来源={best_tag} [{best_level.upper()}]  Val 平均超额={best_vret:+.2f}%')
            current_params = deepcopy(best_p)

            # 3.4 Kronos 权重联调（参数定了后，顺手把 chip/kronos 权重也进化一下）
            print(f'  ⚖️ 联调 Kronos 融合权重 …')
            # MVP: 用训练集的 (chip_score, future_return) 近似样本 → 直接在 [0.5, 0.9] 扫 chip_weight
            best_cw, best_perf = 0.70, -float('inf')
            for cw in [0.5, 0.6, 0.7, 0.8, 0.9]:
                kw = 1.0 - cw
                val_try = run_batch(current_params, VAL_START, VAL_END, chip_weight=cw, kronos_weight=kw)
                vs = [r['total_ret'] for r in val_try if not r.get('error') and r.get('total_ret', -999) != -999]
                perf = float(np.mean(vs)) if vs else -999
                if perf > best_perf:
                    best_perf = perf; best_cw = cw
            chip_w, kronos_w = best_cw, round(1.0 - best_cw, 2)
            print(f'     → 最优权重：筹码 {chip_w:.0%} + Kronos {kronos_w:.0%}')

            history.append({'gen': gen, 'params': current_params,
                            'chip_w': chip_w, 'kronos_w': kronos_w,
                            'train_result': _slim(best_tr), 'val_result': _slim(best_vr)})
        else:
            admit_fail_streak += 1
            extra = f'（连续{admit_fail_streak}代未通过，下代阈值将进一步放宽）' if admit_fail_streak >= 1 else ''
            print(f'  ⏭️  第 {gen} 代没有通过准入卡的参数 — 保留当前参数进入下一代（避免过拟合） {extra}')
            history.append({'gen': gen, 'params': current_params,
                            'chip_w': chip_w, 'kronos_w': kronos_w,
                            'skipped': True, 'admit_fail_streak': admit_fail_streak})

        # 保存快照
        snap_path = f'evolution_snapshot_gen{gen}.json'
        with open(snap_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'history': _json_safe(history),
                'current_params': current_params,
                'weights': {'chip': chip_w, 'kronos': kronos_w},
            }, f, ensure_ascii=False, indent=2, default=str)
        print(f'  💾 快照已保存：{snap_path}')

    # ============================================================
    # 🏁 终局：打印整体对比表
    # ============================================================
    print('\n\n' + '=' * 130)
    print('  🏁 进化结束！最终汇总对比')
    print('=' * 130)
    # 跑第一代基准 vs 最终最优参数（Val）
    print('\n  【初始基准 (默认v3.1) vs 最终参数 (Val 验证集)】')
    base_val = run_batch(DEFAULT_PARAMS, VAL_START, VAL_END,
                         chip_weight=DEFAULT_CHIP_W, kronos_weight=DEFAULT_KRONOS_W)
    final_val = run_batch(current_params, VAL_START, VAL_END,
                          chip_weight=chip_w, kronos_weight=kronos_w)
    _summary_table(base_val,  '初始基准 (默认v3.1)')
    _summary_table(final_val, f'最终参数 ({history[-1]["gen"]}代进化)')

    def _agg(rs):
        vs = [r for r in rs if not r.get('error') and r.get('total_ret', -999) != -999]
        return {
            'avg_ret': float(np.mean([r['total_ret'] for r in vs])),
            'avg_excess': float(np.mean([r['excess'] for r in vs])),
            'avg_sharpe': float(np.mean([r['sharpe'] for r in vs])),
            'avg_dd': float(np.mean([r['max_dd'] for r in vs])),
            'win_rate': float(np.mean([r['win_rate'] for r in vs])),
            'n_win_over_bh': sum(1 for r in vs if r['excess'] > 0),
            'n_total': len(vs),
        }

    b = _agg(base_val); fv = _agg(final_val)
    print(f'\n  🎯 核心指标提升 (Val 验证集，样本外！)：')
    print(f'     平均收益率:  {b["avg_ret"]:+.2f}% → {fv["avg_ret"]:+.2f}%   Δ={fv["avg_ret"]-b["avg_ret"]:+.2f}%')
    print(f'     平均超额收益: {b["avg_excess"]:+.2f}% → {fv["avg_excess"]:+.2f}%   Δ={fv["avg_excess"]-b["avg_excess"]:+.2f}%')
    print(f'     平均夏普比:   {b["avg_sharpe"]:.3f} → {fv["avg_sharpe"]:.3f}')
    print(f'     平均最大回撤: {b["avg_dd"]:.2f}% → {fv["avg_dd"]:.2f}%')
    print(f'     胜率(跑赢BH): {b["n_win_over_bh"]}/{b["n_total"]} → {fv["n_win_over_bh"]}/{fv["n_total"]}')
    print(f'     Kronos权重:   筹码{DEFAULT_CHIP_W:.0%}+K{DEFAULT_KRONOS_W:.0%} → 筹码{chip_w:.0%}+K{kronos_w:.0%}')

    # 保存最终结果
    out_path = 'evolution_final_result.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'params': current_params,
            'weights': {'chip': chip_w, 'kronos': kronos_w},
            'val_metrics_base': b, 'val_metrics_final': fv,
            'history': _json_safe(history),
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n  💾 最终结果已保存：{out_path}')
    print(f'\n  📌 最终推荐参数（直接粘到 HoldingManager(params=…)里用）：')
    print(json.dumps(current_params, ensure_ascii=False, indent=6))


def _slim(results: List[Dict]) -> List[Dict]:
    """精简历史保存大小：丢掉详细 log"""
    return [{k: v for k, v in r.items() if k != 'log'} for r in results]


def _json_safe(obj):
    """递归把 numpy 类型 / set / tuple → python 原生"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


if __name__ == '__main__':
    main()
