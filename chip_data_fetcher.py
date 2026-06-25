#!/usr/bin/env python3
"""
筹码峰数据获取模块 (通用化)
===========================
封装Tushare cyq_chips数据获取，支持任意时间段的分段拉取。

使用示例:
    from chip_data_fetcher import fetch_chip_data

    # 获取单只股票完整筹码数据
    data = fetch_chip_data('603002.SH', start_date='20260301', end_date='20260624')

    # 获取K线数据
    kline = fetch_kline_data('603002.SH', start_date='20260301', end_date='20260624')

    # 获取筹码+K线+指标完整数据
    result = fetch_complete_data('603002.SH', start_date='20260301', end_date='20260624')
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np

# 加载 .env 环境变量
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

from utils import get_tushare_pro


# ═══════════════════════════════════════════════════════
# 1. 筹码峰数据获取
# ═══════════════════════════════════════════════════════

def fetch_cyq_chips(ts_code: str, start_date: str, end_date: str,
                    fields: str = 'ts_code,trade_date,price,percent') -> pd.DataFrame:
    """
    分段获取cyq_chips筹码数据，解决单次6000条限制。

    Args:
        ts_code: 股票代码，如 '603002.SH'
        start_date: 起始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'
        fields: 需要获取的字段，默认 'ts_code,trade_date,price,percent'

    Returns:
        pd.DataFrame: 筹码数据，包含 price 和 percent 列

    Raises:
        RuntimeError: 数据获取失败或返回空数据
    """
    pro = get_tushare_pro()
    start_dt = pd.to_datetime(start_date, format='%Y%m%d')
    end_dt = pd.to_datetime(end_date, format='%Y%m%d')

    all_data: List[pd.DataFrame] = []
    current_start = start_dt
    segment_days = 20  # 每段20天，避免超过6000条限制

    while current_start <= end_dt:
        current_end = min(current_start + timedelta(days=segment_days), end_dt)

        try:
            df = pro.cyq_chips(
                ts_code=ts_code,
                start_date=current_start.strftime('%Y%m%d'),
                end_date=current_end.strftime('%Y%m%d')
            )
            if df is not None and len(df) > 0:
                all_data.append(df)
        except Exception as e:
            print(f"[chip_data_fetcher] ⚠️ {current_start}~{current_end} 获取失败: {e}")

        current_start = current_end + timedelta(days=1)

    if not all_data:
        raise RuntimeError(f"无法获取 {ts_code} 的筹码数据 ({start_date}~{end_date})")

    # 合并并去重
    df_all = pd.concat(all_data, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=['ts_code', 'trade_date', 'price'])
    df_all['trade_date'] = pd.to_datetime(df_all['trade_date'])
    df_all = df_all.sort_values(['trade_date', 'price']).reset_index(drop=True)

    return df_all


def fetch_kline_data(ts_code: str, start_date: str, end_date: str,
                     fields: str = 'trade_date,open,high,low,close,vol,amount') -> pd.DataFrame:
    """
    获取日K线数据。

    Args:
        ts_code: 股票代码，如 '603002.SH'
        start_date: 起始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'
        fields: 需要获取的字段

    Returns:
        pd.DataFrame: K线数据，日期为升序
    """
    pro = get_tushare_pro()

    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)
    if df is None or len(df) == 0:
        raise RuntimeError(f"无法获取 {ts_code} 的K线数据 ({start_date}~{end_date})")

    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    return df


def fetch_technical_indicators(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取技术指标数据 (MACD, KDJ, RSI, BOLL)。

    Args:
        ts_code: 股票代码
        start_date: 起始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'

    Returns:
        pd.DataFrame: 包含技术指标的数据
    """
    pro = get_tushare_pro()

    df = pro.stk_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or len(df) == 0:
        raise RuntimeError(f"无法获取 {ts_code} 的技术指标数据")

    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    return df


def fetch_daily_basic(ts_code: str, start_date: str, end_date: str,
                      fields: str = 'trade_date,close,turnover_rate,volume_ratio,pe_ttm,pb') -> pd.DataFrame:
    """
    获取每日基本面数据。

    Args:
        ts_code: 股票代码
        start_date: 起始日期
        end_date: 结束日期
        fields: 需要获取的字段

    Returns:
        pd.DataFrame: 基本面数据
    """
    pro = get_tushare_pro()

    df = pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)
    if df is None or len(df) == 0:
        raise RuntimeError(f"无法获取 {ts_code} 的基本面数据")

    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    return df


def fetch_complete_data(ts_code: str, start_date: str, end_date: str,
                        include_indicators: bool = True) -> Dict:
    """
    获取完整的筹码+K线+指标数据。

    Args:
        ts_code: 股票代码
        start_date: 起始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'
        include_indicators: 是否包含技术指标

    Returns:
        Dict: {
            'ts_code': 股票代码,
            'start_date': 起始日期,
            'end_date': 结束日期,
            'chip_data': pd.DataFrame,  # 筹码数据
            'kline': pd.DataFrame,      # K线数据
            'indicators': pd.DataFrame, # 技术指标 (可选)
        }
    """
    print(f"[chip_data_fetcher] 📊 获取 {ts_code} 完整数据 ({start_date}~{end_date})...")

    # 1. 筹码数据
    chip_data = fetch_cyq_chips(ts_code, start_date, end_date)
    print(f"   筹码数据: {len(chip_data)}条 ({chip_data['trade_date'].min().date()}~{chip_data['trade_date'].max().date()})")

    # 2. K线数据
    kline = fetch_kline_data(ts_code, start_date, end_date)
    print(f"   K线数据: {len(kline)}条 ({kline['trade_date'].min().date()}~{kline['trade_date'].max().date()})")

    result = {
        'ts_code': ts_code,
        'start_date': start_date,
        'end_date': end_date,
        'chip_data': chip_data,
        'kline': kline,
        'indicators': None,
    }

    # 3. 技术指标 (可选)
    if include_indicators:
        try:
            indicators = fetch_technical_indicators(ts_code, start_date, end_date)
            result['indicators'] = indicators
            print(f"   技术指标: {len(indicators)}条")
        except Exception as e:
            print(f"   技术指标获取失败: {e}")

    return result


def get_chip_data_on_date(chip_data: pd.DataFrame, target_date: str) -> Optional[pd.DataFrame]:
    """
    获取指定日期的筹码分布数据。

    Args:
        chip_data: fetch_cyq_chips返回的筹码数据
        target_date: 目标日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'

    Returns:
        pd.DataFrame: 该日期的筹码分布，或 None 如果不存在
    """
    target = pd.to_datetime(target_date)
    day_data = chip_data[chip_data['trade_date'] == target]
    return day_data if len(day_data) > 0 else None


# ═══════════════════════════════════════════════════════
# 2. 交易记录读取
# ═══════════════════════════════════════════════════════

def load_trade_records(file_path: str = None) -> pd.DataFrame:
    """
    读取交易记录文件。

    默认从 stock-chip-quant/data/tradeHistroy.txt 读取。
    支持GBK编码。

    Args:
        file_path: 交易记录文件路径，默认 None（使用默认路径）

    Returns:
        pd.DataFrame: 交易记录，包含 columns: [date, ts_code, action, price, note]
    """
    if file_path is None:
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'tradeHistroy.txt'
        )

    with open(file_path, 'r', encoding='gbk') as f:
        lines = f.readlines()

    records = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('成交日期') or line.startswith('标题') or line.startswith('营业部') or line.startswith('期间') or line.startswith('股东') or line.startswith('-'):
            continue

        parts = line.split('\t')
        if len(parts) < 8:
            continue

        try:
            date_str = parts[0].strip()
            code = parts[2].strip()
            action_cn = parts[4].strip()
            price = float(parts[6].strip())
            name = parts[3].strip()

            # 标准化代码
            if '.' not in code:
                # 根据代码前缀判断市场
                if code.startswith('6'):
                    code = code + '.SH'
                elif code.startswith('0') or code.startswith('3'):
                    code = code + '.SZ'
                elif code.startswith('8') or code.startswith('4'):
                    code = code + '.BJ'

            # 标准化操作
            if '买入' in action_cn:
                action = 'buy'
            elif '卖出' in action_cn:
                action = 'sell'
            else:
                continue

            records.append({
                'date': date_str,      # 20260330
                'ts_code': code,
                'action': action,
                'price': price,
                'note': name,
            })
        except (ValueError, IndexError):
            continue

    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    return df.sort_values('date').reset_index(drop=True)


def get_trades_for_stock(trades_df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """
    获取指定股票的交易记录。

    Args:
        trades_df: load_trade_records返回的交易记录
        ts_code: 股票代码

    Returns:
        pd.DataFrame: 该股票的交易记录
    """
    return trades_df[trades_df['ts_code'] == ts_code].reset_index(drop=True)


# ═══════════════════════════════════════════════════════
# 3. 主函数（测试用）
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    # 测试数据获取
    ts_code = '603002.SH'
    start_date = '20260301'
    end_date = '20260624'

    print("=" * 60)
    print("测试筹码峰数据获取模块")
    print("=" * 60)

    try:
        data = fetch_complete_data(ts_code, start_date, end_date)
        print(f"\n✅ 成功获取数据:")
        print(f"   股票: {data['ts_code']}")
        print(f"   筹码数据: {len(data['chip_data'])}条")
        print(f"   K线数据: {len(data['kline'])}条")
        if data['indicators'] is not None:
            print(f"   技术指标: {len(data['indicators'])}条")

        # 测试单日期数据
        sample_date = data['chip_data']['trade_date'].iloc[0]
        day_data = get_chip_data_on_date(data['chip_data'], sample_date.strftime('%Y-%m-%d'))
        print(f"\n   示例日期 {sample_date.date()} 筹码分布: {len(day_data)}个价格档位")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")

    # 测试交易记录
    print("\n" + "=" * 60)
    print("测试交易记录读取")
    print("=" * 60)

    try:
        trades = load_trade_records()
        print(f"✅ 读取交易记录: {len(trades)}条")

        stock_trades = get_trades_for_stock(trades, ts_code)
        print(f"   {ts_code} 交易记录: {len(stock_trades)}条")
        if len(stock_trades) > 0:
            print(f"   首笔交易: {stock_trades.iloc[0]['date'].date()} {stock_trades.iloc[0]['action']} {stock_trades.iloc[0]['price']}")
    except Exception as e:
        print(f"❌ 读取交易记录失败: {e}")