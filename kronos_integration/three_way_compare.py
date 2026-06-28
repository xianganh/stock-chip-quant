#!/usr/bin/env python3
"""
三路策略对比回测引擎
======================

对比对象：
    A) 用户实盘交易（tradeHistroy.txt中的真实买卖点）
    B) 纯筹码 + 分级持仓 v3（holding_manager.py 的原始策略）
    C) Kronos 筹码贝叶斯融合 + 分级持仓 v3（新策略）

对比指标：
    - 累计收益率曲线
    - 总收益率、胜率、交易次数
    - 最大回撤、夏普比率
    - 超额Alpha（相对买入持有）
    - 每笔交易明细对比
"""
import os
import sys
import json
import re
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from kronos_integration import KronosChipFuser
from kronos_integration.backtest_adapter import KronosChipBacktestAdapter
from holding_manager import HoldingManager
from chip_data_fetcher import fetch_complete_data
from chip_indicators import compute_all_chip_metrics


# ═══════════════════════════════════════════════════════
# 1. 解析用户实盘交易（宏昌电子）
# ═══════════════════════════════════════════════════════

def _read_file_smart(path: str) -> List[str]:
    for enc in ['utf-8', 'gbk', 'gb18030']:
        try:
            with open(path, encoding=enc) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法解码 {path}")


def parse_user_real_trades(ts_code_suffix: str = "603002",
                           account_file: str = "tradeHistroy.txt") -> List[Dict]:
    """
    从券商交易对账单中解析指定股票的实盘买卖记录
    """
    fp = os.path.join(_ROOT, "data", account_file)
    if not os.path.exists(fp):
        print(f"[WARN] 找不到对账单 {fp}，将无法显示用户实盘")
        return []

    lines = _read_file_smart(fp)

    # 找表头
    header_idx = None
    for i, line in enumerate(lines):
        if '\t' in line and '成交日期' in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    trades = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        cols = line.strip().split('\t')
        if len(cols) < 6:
            continue
        try:
            code = cols[2].strip()
            if not code.startswith(ts_code_suffix):
                continue
            trade_date = cols[0].strip().replace('-', '')
            op_raw = cols[4].strip()
            qty = int(cols[5])
            price = float(cols[6]) if len(cols) > 6 and cols[6] else 0.0
            if price <= 0 or qty == 0:
                continue
            direction = 'buy' if qty > 0 else 'sell'
            trades.append({
                'trade_date': trade_date,
                'date_obj': datetime.strptime(trade_date, '%Y%m%d').date(),
                'direction': direction,
                'price': price,
                'qty': abs(qty),
                'op_raw': op_raw,
            })
        except (ValueError, IndexError):
            continue

    trades.sort(key=lambda t: (t['trade_date'], 0 if t['direction'] == 'buy' else 1))
    return trades


# ═══════════════════════════════════════════════════════
# 2. 统一模拟交易框架（三策略共用）
# ═══════════════════════════════════════════════════════

def simulate_from_trade_list(trade_signals: List[Dict],
                             df_prices: pd.DataFrame,
                             initial_capital: float = 100000.0,
                             label: str = "策略") -> Dict:
    """
    根据每日信号列表（买入/卖出）模拟交易，生成权益曲线和统计

    trade_signals: [{'date': 'YYYYMMDD', 'action': 'BUY'|'SELL', 'shares_pct': 1.0|0.3|0.5}]
    df_prices: 必须有 trade_date(str, YYYYMMDD), close, open 列
    """
    df = df_prices.copy()
    df = df.sort_values('trade_date').reset_index(drop=True)

    capital = initial_capital
    shares = 0.0
    cost_price = 0.0
    equity_curve = []
    executed_trades = []
    hold_days = 0

    signal_map = {}  # date -> signal
    for s in trade_signals:
        signal_map[s['date']] = s

    for i, row in df.iterrows():
        td = row['trade_date']
        price = float(row['close'])
        date_obj = datetime.strptime(td, '%Y%m%d').date()

        pos_value = shares * price
        total_equity = capital + pos_value

        sig = signal_map.get(td)
        if sig:
            action = sig['action']
            pct = sig.get('shares_pct', 1.0)

            if action == 'BUY' and shares == 0 and capital > 0:
                invest = capital * pct
                buy_shares = int(invest / price / 100) * 100  # 整手买入
                if buy_shares > 0:
                    shares += buy_shares
                    capital -= buy_shares * price
                    cost_price = price
                    hold_days = 0
                    executed_trades.append({
                        'date': date_obj,
                        'trade_date': td,
                        'action': '买入',
                        'price': price,
                        'shares': buy_shares,
                        'reason': sig.get('reason', label + '买入信号'),
                    })
                    pos_value = shares * price
                    total_equity = capital + pos_value

            elif action == 'PARTIAL_SELL' and shares > 0:
                sell_n = int(shares * pct / 100) * 100
                if sell_n > 0:
                    ret = (price / cost_price - 1) * 100 if cost_price > 0 else 0
                    capital += sell_n * price
                    shares -= sell_n
                    executed_trades.append({
                        'date': date_obj,
                        'trade_date': td,
                        'action': f'减仓{int(pct*100)}%',
                        'price': price,
                        'shares_remaining': shares,
                        'profit_pct': round(ret, 2),
                        'reason': sig.get('reason', label + '减仓信号'),
                    })
                    pos_value = shares * price
                    total_equity = capital + pos_value

            elif action == 'SELL' and shares > 0:
                ret = (price / cost_price - 1) * 100 if cost_price > 0 else 0
                capital += shares * price
                executed_trades.append({
                    'date': date_obj,
                    'trade_date': td,
                    'action': '卖出',
                    'price': price,
                    'profit_pct': round(ret, 2),
                    'hold_days': hold_days,
                    'reason': sig.get('reason', label + '卖出信号'),
                })
                shares = 0
                cost_price = 0
                hold_days = 0
                pos_value = 0
                total_equity = capital

        if shares > 0:
            hold_days += 1

        equity_curve.append({
            'trade_date': td,
            'date': date_obj,
            'equity': round(total_equity, 2),
            'return_pct': round((total_equity / initial_capital - 1) * 100, 2),
            'shares': shares,
            'close': price,
        })

    # 期末强制清算
    if shares > 0:
        final_price = float(df.iloc[-1]['close'])
        td = df.iloc[-1]['trade_date']
        ret = (final_price / cost_price - 1) * 100 if cost_price > 0 else 0
        capital += shares * final_price
        executed_trades.append({
            'date': datetime.strptime(td, '%Y%m%d').date(),
            'trade_date': td,
            'action': '期末清算',
            'price': final_price,
            'profit_pct': round(ret, 2),
            'hold_days': hold_days,
            'reason': '回测期末强制平仓',
        })
        # 更新最后一天权益
        equity_curve[-1]['equity'] = round(capital, 2)
        equity_curve[-1]['return_pct'] = round((capital / initial_capital - 1) * 100, 2)
        shares = 0

    # 统计指标
    eq_df = pd.DataFrame(equity_curve)
    total_return = round((capital / initial_capital - 1) * 100, 2)
    eq_df['drawdown_pct'] = (eq_df['equity'] / eq_df['equity'].cummax() - 1) * 100
    max_drawdown = round(eq_df['drawdown_pct'].min(), 2)

    closed_trades = [t for t in executed_trades if t['action'] in ('卖出', '期末清算')]
    if closed_trades:
        wins = [t for t in closed_trades if t.get('profit_pct', 0) > 0]
        win_rate = round(len(wins) / len(closed_trades) * 100, 1)
        avg_profit = round(np.mean([t.get('profit_pct', 0) for t in closed_trades]), 2)
    else:
        win_rate, avg_profit = 0, 0

    daily_returns = eq_df['equity'].pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = round(np.sqrt(252) * daily_returns.mean() / daily_returns.std(), 3)
    else:
        sharpe = 0

    first_close = float(df.iloc[0]['close'])
    last_close = float(df.iloc[-1]['close'])
    buy_hold = round((last_close / first_close - 1) * 100, 2)

    return {
        'label': label,
        'initial_capital': initial_capital,
        'final_capital': round(capital, 2),
        'total_return': total_return,
        'buy_hold_return': buy_hold,
        'alpha': round(total_return - buy_hold, 2),
        'win_rate': win_rate,
        'avg_profit_per_trade': avg_profit,
        'trade_count_buy': len([t for t in executed_trades if t['action'] == '买入']),
        'trade_count_sell': len(closed_trades),
        'max_drawdown': max_drawdown,
        'sharpe': sharpe,
        'trades': executed_trades,
        'equity_curve': equity_curve,
    }


# ═══════════════════════════════════════════════════════
# 3. 三策略信号生成
# ═══════════════════════════════════════════════════════

def generate_strategyA_user_real(user_trades: List[Dict]) -> List[Dict]:
    """策略A：用户实盘买卖点（100%跟随）"""
    signals = []
    for t in user_trades:
        if t['direction'] == 'buy':
            signals.append({
                'date': t['trade_date'],
                'action': 'BUY',
                'shares_pct': 1.0,
                'reason': f"用户实盘: {t['op_raw']} @ {t['price']}",
            })
        else:
            signals.append({
                'date': t['trade_date'],
                'action': 'SELL',
                'reason': f"用户实盘: {t['op_raw']} @ {t['price']}",
            })
    return signals


def generate_strategyB_chip_v3(df_data: pd.DataFrame) -> Tuple[List[Dict], Dict]:
    """策略B：纯筹码评分 + 分级持仓 v3（直接复用 HoldingManager）"""
    mgr = HoldingManager()

    # 复用 prepare_data 逻辑，但兼容 df_data 的列名
    df = df_data.copy()
    if 'trade_date' in df.columns:
        df['date'] = pd.to_datetime(df['trade_date'].astype(str))

    # 补全 HoldingManager 需要的列
    for period in [5, 10, 20, 60]:
        if f'ma{period}' not in df.columns:
            df[f'ma{period}'] = df['close'].rolling(period).mean()
    for metric in ['tpc', 'width', 'tp3', 'winner', 'entropy', 'skewness', 'kurtosis', 'p1_dominance']:
        if metric in df.columns and f'{metric}_chg_7d' not in df.columns:
            df[f'{metric}_chg_7d'] = df[metric].diff(7)
    if 'cost_dist_pct' not in df.columns and 'weight_avg' in df.columns:
        df['cost_dist_pct'] = (df['close'] - df['weight_avg']) / df['weight_avg'] * 100
    if 'support_distance_pct' not in df.columns and 'support' in df.columns:
        df['support_distance_pct'] = (df['close'] - df['support']) / df['support'] * 100

    if 'score' not in df.columns:
        df['score'] = df.apply(mgr._score_entry, axis=1)

    # 跑 backtest 直接拿到 log
    _, backtest_log = mgr.backtest(df, start_idx=0)

    # 将 log 转成统一的信号格式
    signals = []
    for entry in backtest_log:
        date_str = entry['date'].strftime('%Y%m%d') if hasattr(entry['date'], 'strftime') else str(entry['date'])
        action = entry['action']
        reason = entry.get('reason', '')
        if action.startswith('建仓'):
            signals.append({'date': date_str, 'action': 'BUY', 'shares_pct': 1.0, 'reason': f'纯筹码v3: {reason}'})
        elif action.startswith('预警减30%'):
            signals.append({'date': date_str, 'action': 'PARTIAL_SELL', 'shares_pct': 0.3, 'reason': f'纯筹码v3: {reason}'})
        elif action.startswith('高度减50%'):
            signals.append({'date': date_str, 'action': 'PARTIAL_SELL', 'shares_pct': 0.5, 'reason': f'纯筹码v3: {reason}'})
        elif action.startswith('出货清仓') or action.startswith('硬止损') or action.startswith('期末'):
            signals.append({'date': date_str, 'action': 'SELL', 'reason': f'纯筹码v3: {reason}'})
    return signals, backtest_log


def generate_strategyC_kronos_fused(df_data: pd.DataFrame,
                                    fuser: Optional[KronosChipFuser] = None) -> List[Dict]:
    """策略C：Kronos + 筹码贝叶斯融合 + 分级持仓 v3

    改动（相比策略B）：
        - 建仓条件：融合分 ≥ 68（而不是 score≥5）
        - 加仓（融合≥80时，若已持仓则不加，信号更严不激进）
        - 清仓条件：融合分 ≤ 30 或 破MA10 （更灵敏）
        - 其余：三级减仓逻辑完全保留（Winner/成本偏离）
    """
    if fuser is None:
        fuser = KronosChipFuser(model_name="NeoQuasar/Kronos-mini")

    df = df_data.copy()
    if 'trade_date' not in df.columns:
        df['trade_date'] = df['date'].dt.strftime('%Y%m%d')

    # 先算 Kronos 预测 + 融合
    price_cols = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
    fused_scores = []
    for i in range(len(df)):
        row = df.iloc[i]
        hist_df = df.iloc[:i + 1][price_cols].copy()
        kr = fuser.kronos_predict(hist_df, horizon=10, sample_count=3)
        chip_score = row.get('score')
        if chip_score is None or (isinstance(chip_score, float) and np.isnan(chip_score)):
            # 退化：算一个简单评分
            from holding_manager import HoldingManager
            chip_score = HoldingManager()._score_entry(row)
        fused = fuser.bayesian_fusion(int(chip_score) if not np.isnan(chip_score) else 0, kr)
        fused_scores.append(fused)

    df = df.assign(
        fused_score=[f['fused_score'] for f in fused_scores],
        fused_signal=[f['signal'] for f in fused_scores],
    )

    # 分级持仓 v3 的参数（保留三级减仓）
    p_warn_winner = 80
    p_warn_cd = 10
    p_warn_ret = 10
    p_high_winner = 90
    p_high_cd = 15
    p_high_ret = 20
    p_exit_winner = 95
    p_exit_cd = 20
    stop_loss = 0.92

    signals = []
    shares = 0.0
    cost_price = 0.0
    last_date_sell = None

    for i, (_, row) in enumerate(df.iterrows()):
        td = str(row['trade_date'])
        price = float(row['close'])
        fused = float(row['fused_score'])
        winner = float(row.get('winner', 0) if not pd.isna(row.get('winner', 0)) else 0)
        cd = float(row.get('cost_dist_pct', 0) if not pd.isna(row.get('cost_dist_pct', 0)) else 0)
        ma10 = float(row.get('ma10', price) if not pd.isna(row.get('ma10', price)) else price)

        if shares == 0:
            # 建仓：融合分 ≥ 68
            if fused >= 68:
                shares = 1.0  # 标记全仓
                cost_price = price
                signals.append({
                    'date': td,
                    'action': 'BUY',
                    'shares_pct': 1.0,
                    'reason': f'Kronos融合: score={fused:.0f}%'
                })
        else:
            current_ret = (price / cost_price - 1) * 100

            # 出货清仓：融合≤30 或 (W>95%+CD>20%+破MA10) 或 硬止损
            exit_cond = (
                fused <= 30
                or (winner > p_exit_winner and cd > p_exit_cd and price < ma10)
                or (price < cost_price * stop_loss)
            )
            if exit_cond:
                reason = []
                if fused <= 30: reason.append(f'融合分低={fused:.0f}%')
                if winner > p_exit_winner and cd > p_exit_cd: reason.append('W>95%+CD>20%+破MA10')
                if price < cost_price * stop_loss: reason.append(f'止损亏{(1-stop_loss)*100:.0f}%')
                signals.append({'date': td, 'action': 'SELL',
                                'reason': f'Kronos融合清仓: {"+".join(reason)} ({current_ret:+.1f}%)'})
                shares = 0
                last_date_sell = td
                continue

            # 高度预警减50%
            if winner > p_high_winner and cd > p_high_cd and current_ret > p_high_ret:
                signals.append({
                    'date': td,
                    'action': 'PARTIAL_SELL',
                    'shares_pct': 0.5,
                    'reason': f'Kronos融合高度预警: W>{p_high_winner}%+CD>{p_high_cd}% ({current_ret:+.1f}%)'
                })
                shares *= 0.5
            # 预警减30%
            elif winner > p_warn_winner and cd > p_warn_cd and current_ret > p_warn_ret:
                signals.append({
                    'date': td,
                    'action': 'PARTIAL_SELL',
                    'shares_pct': 0.3,
                    'reason': f'Kronos融合预警: W>{p_warn_winner}%+CD>{p_warn_cd}% ({current_ret:+.1f}%)'
                })
                shares *= 0.7

    return signals


# ═══════════════════════════════════════════════════════
# 4. 主对比引擎
# ═══════════════════════════════════════════════════════

def run_three_way_comparison(ts_code: str = "603002.SH",
                             start_date: str = "20260302",
                             end_date: str = "20260624",
                             initial_capital: float = 100000.0,
                             user_account_file: str = "tradeHistroy.txt",
                             user_code_prefix: str = "603002") -> Dict:
    """
    运行三路对比回测

    Returns:
        {
            "period": "...",
            "buy_hold": "...%",
            "strategy_A_user": {...},
            "strategy_B_chip_v3": {...},
            "strategy_C_kronos_fused": {...},
            "comparison_table": [{"metric", "A", "B", "C"} ...],
            "winner": "A/B/C"
        }
    """
    print("=" * 80)
    print(f"三路策略对比回测 — {ts_code}")
    print("=" * 80)

    # ---------- Step1: 准备基础数据（筹码+K线） ----------
    print("\n[1/5] 准备筹码+K线完整数据 ...")
    # 使用你项目里已验证正确的 fetch_complete_data + compute_all_chip_metrics 组合
    from chip_data_fetcher import fetch_complete_data
    from chip_indicators import compute_all_chip_metrics

    data = fetch_complete_data(ts_code, start_date, end_date)
    metric_rows = compute_all_chip_metrics(data['chip_data'], data['kline'], lookback_days=7)
    df = pd.DataFrame(metric_rows)

    # 统一 trade_date 列格式（YYYYMMDD str，不包含横杠）
    if 'date' in df.columns and 'trade_date' not in df.columns:
        df['trade_date'] = df['date'].astype(str).str.replace('-', '')

    # compute_all_chip_metrics 里成交量叫 vol，统一成 volume
    if 'vol' in df.columns and 'volume' not in df.columns:
        df['volume'] = df['vol']

    # 补全 HoldingManager 需要的衍生列
    for period in [5, 10, 20, 60]:
        df[f'ma{period}'] = df['close'].rolling(period).mean()
    for metric in ['tpc', 'width', 'tp3', 'winner', 'entropy', 'skewness', 'kurtosis', 'p1_dominance']:
        if metric in df.columns:
            # 先做安全转换：万一某些行是 dict 等，转成 NaN
            col_num = pd.to_numeric(df[metric], errors='coerce')
            df[f'{metric}_chg_7d'] = col_num.diff(7)
    if 'weight_avg' in df.columns:
        wavg_num = pd.to_numeric(df['weight_avg'], errors='coerce').replace(0, np.nan)
        df['cost_dist_pct'] = (df['close'] - wavg_num) / wavg_num * 100
    if 'support' in df.columns:
        # support 可能是 dict(price, percent)，尝试提取 price
        def _extract_support_price(val):
            if isinstance(val, dict):
                return val.get('price')
            try:
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None
        support_num = df['support'].apply(_extract_support_price).replace(0, np.nan)
        df['support_distance_pct'] = (df['close'] - support_num) / support_num * 100
    else:
        df['support_distance_pct'] = 0.0  # HoldingManager._score_entry 里用了这个，给个默认

    # 分位数列：holding_manager._score_entry 需要 winner_chg_7d_70 / tpc_50 / width_50 / entropy_50
    for col, q in [('winner_chg_7d', 0.7), ('tpc', 0.5), ('width', 0.5), ('entropy', 0.5)]:
        qcol = f"{col}_{int(q*100)}" if col == 'winner_chg_7d' else f"{col}_50"
        if col in df.columns and qcol not in df.columns:
            col_safe = pd.to_numeric(df[col], errors='coerce')
            val = col_safe.quantile(q) if len(col_safe.dropna()) > 5 else 0
            df[qcol] = val

    # 如果 compute_all_chip_metrics 没有填充 score，就用 HoldingManager 再算一遍
    if 'score' not in df.columns or df['score'].isna().all():
        from holding_manager import HoldingManager
        mgr_tmp = HoldingManager()
        df['score'] = df.apply(mgr_tmp._score_entry, axis=1)
    else:
        # 有健康度评分的话，对 NaN 做兜底（前7天没有历史）
        df['score'] = df['score'].fillna(0)

    df_price = df[['trade_date', 'open', 'high', 'low', 'close', 'volume']].copy()
    print(f"  → 有效交易日 {len(df)} 天")

    # ---------- Step2: 解析用户实盘 ----------
    print("\n[2/5] 解析用户实盘交易记录 ...")
    user_trades = parse_user_real_trades(user_code_prefix, user_account_file)
    print(f"  → 解析到宏昌电子实盘交易 {len(user_trades)} 笔")
    for t in user_trades:
        print(f"     {t['trade_date']} {'买入' if t['direction']=='buy' else '卖出'} "
              f"{t['qty']}股 @ {t['price']:.2f}")

    # ---------- Step3: 生成三个策略的每日信号 ----------
    print("\n[3/5] 生成三策略买卖信号 ...")
    sig_A = generate_strategyA_user_real(user_trades)
    sig_B, log_B = generate_strategyB_chip_v3(df)
    sig_C = generate_strategyC_kronos_fused(df)
    print(f"  → A 用户实盘: {len(sig_A)} 个信号")
    print(f"  → B 纯筹码v3: {len(sig_B)} 个信号 (含分级减仓)")
    print(f"  → C Kronos融合: {len(sig_C)} 个信号 (含分级减仓)")

    # ---------- Step4: 统一模拟交易 ----------
    print("\n[4/5] 统一模拟交易 (初始资金 ¥{:,.0f}) ...".format(initial_capital))
    res_A = simulate_from_trade_list(sig_A, df_price, initial_capital,
                                     label="A 用户实盘") if sig_A else {
        'label': 'A 用户实盘', 'total_return': None, 'note': '无数据（找不到tradeHistroy.txt或宏昌电子交易）'
    }
    res_B = simulate_from_trade_list(sig_B, df_price, initial_capital, label="B 纯筹码+分级v3")
    res_C = simulate_from_trade_list(sig_C, df_price, initial_capital, label="C Kronos融合+分级v3")

    # ---------- Step5: 对比汇总 ----------
    print("\n[5/5] 生成对比汇总 ...")
    results = {
        "ts_code": ts_code,
        "period": f"{start_date} ~ {end_date}",
        "trading_days": len(df_price),
        "buy_hold_return": res_B['buy_hold_return'] if 'buy_hold_return' in res_B else 0,
        "A_user_real": res_A,
        "B_chip_v3": res_B,
        "C_kronos_fused": res_C,
    }

    metrics = [
        ("总收益率", "total_return", "%", True),
        ("超额Alpha (vs买入持有)", "alpha", "%", True),
        ("期末资金", "final_capital", "¥", True),
        ("胜率", "win_rate", "%", True),
        ("平均每笔盈亏", "avg_profit_per_trade", "%", True),
        ("买入次数", "trade_count_buy", "次", False),
        ("卖出次数", "trade_count_sell", "次", False),
        ("最大回撤", "max_drawdown", "%", False),
        ("夏普比率", "sharpe", "", True),
    ]
    table = []
    for metric_name, key, unit, higher_better in metrics:
        def _get(r, k):
            if isinstance(r, dict):
                v = r.get(k)
                return (v is not None and not (isinstance(v, float) and np.isnan(v))) and v or None
            return None
        a, b, c = _get(res_A, key), _get(res_B, key), _get(res_C, key)
        vals = [x for x in (a, b, c) if x is not None]
        best = max(vals) if vals and higher_better else (min(vals) if vals else None)
        table.append({
            'metric': metric_name,
            'unit': unit,
            'A_user': a,
            'B_chip': b,
            'C_kronos': c,
            'higher_better': higher_better,
            'best': best,
        })
    results['comparison_table'] = table

    # 判定冠军
    def _score(r):
        if 'total_return' not in r or r.get('total_return') is None:
            return -9999
        return (r.get('alpha', 0) * 0.5
                + r.get('total_return', 0) * 0.3
                + r.get('sharpe', 0) * 10
                - r.get('max_drawdown', 0) * 0.5)

    scores = [('A', _score(res_A)), ('B', _score(res_B)), ('C', _score(res_C))]
    scores.sort(key=lambda x: -x[1])
    results['ranking'] = [s[0] for s in scores]
    results['winner'] = scores[0][0]

    return results


def print_comparison_report(res: Dict):
    """在终端打印格式化的对比报告"""
    print()
    print("=" * 80)
    print(f" 三路策略对比回测报告    {res['ts_code']}    {res['period']}")
    print("=" * 80)
    print(f" 交易日数: {res['trading_days']} 天    买入持有基准: {res['buy_hold_return']:+.2f}%")
    print("-" * 80)

    # 汇总表
    header = f"{'指标':<22} | {'A 用户实盘':>12} | {'B 纯筹码v3':>12} | {'C Kronos融合':>12} |"
    print(header)
    print("-" * len(header))

    for row in res['comparison_table']:
        def fmt(v, unit):
            if v is None:
                return "N/A"
            if unit == "¥":
                return f"{v:>10,.0f}"
            if unit == "次":
                return f"{v:>10d}" if isinstance(v, int) else f"{v:>10.0f}"
            return f"{v:>10.2f}{unit}"
        a = fmt(row['A_user'], row['unit'])
        b = fmt(row['B_chip'], row['unit'])
        c = fmt(row['C_kronos'], row['unit'])

        def mark(v, best):
            if v is None or best is None:
                return ""
            return " ★" if v == best else ""

        line = f"{row['metric']:<22} | {a}{mark(row['A_user'], row['best']):>3} | {b}{mark(row['B_chip'], row['best']):>3} | {c}{mark(row['C_kronos'], row['best']):>3} |"
        print(line)

    print("-" * len(header))
    print(f"\n🏆 综合排名: {', '.join(['第{}名={}'.format(i+1, {'A':'用户实盘','B':'纯筹码v3','C':'Kronos融合'}[r]) for i, r in enumerate(res['ranking'])])}")
    winner_label = {'A': '用户实盘', 'B': '纯筹码+分级v3', 'C': 'Kronos融合+分级v3'}[res['winner']]
    print(f"🏆 最优策略: {winner_label}")

    # 详细交易明细
    for tag, key, title in [('A', 'A_user_real', '用户实盘交易明细'),
                            ('B', 'B_chip_v3', '纯筹码v3 交易明细'),
                            ('C', 'C_kronos_fused', 'Kronos融合 交易明细')]:
        r = res.get(key)
        if not r or 'trades' not in r:
            continue
        print(f"\n{'─' * 60}")
        print(f" {tag}) {title}（共 {len(r['trades'])} 笔）")
        print(f"{'─' * 60}")
        for t in r['trades']:
            extras = []
            if 'profit_pct' in t:
                extras.append(f"盈亏{t['profit_pct']:+.2f}%")
            if 'hold_days' in t:
                extras.append(f"持仓{t['hold_days']}天")
            extras_str = "  ".join(extras)
            reason = t.get('reason', '')[:40]
            print(f"   {t['date']}  {t['action']:<8}  @¥{t['price']:<7.2f}  {extras_str:<18}  原因:{reason}")

    # 输出建议
    print(f"\n{'=' * 80}")
    a_ret = res['A_user_real'].get('total_return') if 'total_return' in res['A_user_real'] else None
    b_ret = res['B_chip_v3']['total_return']
    c_ret = res['C_kronos_fused']['total_return']
    print("💡 策略改进建议:")
    if a_ret is not None:
        if b_ret > a_ret:
            print(f"   · 纯筹码v3策略收益 ({b_ret:+.1f}%) 高于您的实盘 ({a_ret:+.1f}%)，"
                  f"可参考其『预警减30%/高度减50%/出货清仓』的三级节奏，避免过早卖出")
        if c_ret > a_ret:
            print(f"   · Kronos融合策略收益 ({c_ret:+.1f}%) 高于您的实盘 ({a_ret:+.1f}%)，"
                  f"建议将融合分≥68作为加仓参考，融合分≤30作为清仓预警")
    if c_ret > b_ret:
        print(f"   · ✅ Kronos融合产生正向增强: 纯筹码 {b_ret:+.1f}% → 融合 {c_ret:+.1f}%，"
              f"超额 +{c_ret - b_ret:.1f}%")
    elif c_ret < b_ret:
        print(f"   · ⚠️  Kronos融合弱于纯筹码: 建议降低 kronos_weight (当前30%→15%) 或暂时仅用筹码")
    print("=" * 80)


if __name__ == "__main__":
    res = run_three_way_comparison(
        ts_code="603002.SH",
        start_date="20260302",
        end_date="20260624",
        initial_capital=100000.0,
        user_account_file="tradeHistroy.txt",
        user_code_prefix="603002",
    )
    print_comparison_report(res)

    # 保存 JSON 结果
    save_path = os.path.join(_ROOT, "data", "three_way_comparison_603002.json")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    # equity_curve 大，另存为 CSV
    for key in ['A_user_real', 'B_chip_v3', 'C_kronos_fused']:
        if key in res and 'equity_curve' in res[key]:
            ec = res[key].pop('equity_curve')
            csv_path = save_path.replace('.json', f'_{key}_equity.csv')
            pd.DataFrame(ec).to_csv(csv_path, index=False, encoding='utf-8-sig')
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 完整结果已保存: {save_path}")
    print(f"📄 三条权益曲线 CSV: 同目录下 *_equity.csv")
