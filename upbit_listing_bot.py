import os
import requests
import re
from binance.client import Client
from datetime import datetime, timedelta, timezone
import pandas as pd
import time
import math
from dotenv import load_dotenv
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, ROUND_CEILING


load_dotenv()  # 从 .env 读取环境变量
# —— 配置 ——
API_KEY = os.environ['API_KEY']
API_SECRET = os.environ['API_SECRET']

client = Client(api_key=API_KEY, api_secret=API_SECRET)
account_balance = [x  for x in client.get_asset_balance() if float(x['free'])>0]
print("✅ Bot started")
print(account_balance)

kargs = {
    'order_value': 3000,
    'price_ratio': 1.15
}

order_value = kargs['order_value']
price_ratio = kargs['price_ratio']


# === Helper functions ===

def parse_asset_from_title(title: str) -> str:
    """
    从公告标题中提取币种代码，例如："칼데라(ERA)..." -> "ERA"
    """
    match = re.search(r"\(([^)]+)\)", title)
    return match.group(1) if match else None


def round_to_step(value: float, step: float, mode: str = 'round') -> float:
    """
    按照 stepSize 舍入价格或数量。
    :param value: 原始值
    :param step: 步长，例如 0.1、0.01 等
    :param mode: 'round'（四舍五入）、'floor'（向下取整）、'ceil'（向上取整）
    """
    dvalue = Decimal(str(value))
    dstep = Decimal(str(step))
    rounding = {
        'floor': ROUND_FLOOR,
        'ceil': ROUND_CEILING,
        'round': ROUND_HALF_UP
    }.get(mode, ROUND_HALF_UP)
    return float(dvalue.quantize(dstep, rounding=rounding))


# 缓存 symbol info，避免重复网络请求
_symbols_info_cache = None


def get_symbols_info() -> list:
    """获取并缓存 Binance futures 的 symbol 列表和其步长规则"""
    global _symbols_info_cache
    if _symbols_info_cache is None:
        info = client.futures_exchange_info().get('symbols', [])
        clean = []
        seen = set()
        for s in info:
            sym = s['symbol']
            step = float(next(f['stepSize'] for f in s['filters'] if f['filterType'] == 'LOT_SIZE'))
            tick = float(next(f['tickSize'] for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'))
            key = (sym, step, tick)
            if key not in seen:
                seen.add(key)
                clean.append({'symbol': sym, 'stepSize': step, 'tickSize': tick})
        _symbols_info_cache = clean
    return _symbols_info_cache


def get_qty_price(symbol: str, price_ratio: float, order_value: float) -> tuple:
    """
    返回下单的数量和价格：
    - 价格按最新价 * price_ratio 并对齐到 tickSize
    - 数量按 order_value/price 并对齐到 stepSize
    """
    last_price = float(client.futures_ticker(symbol=symbol)['lastPrice'])
    raw_price = last_price * price_ratio
    sym_info = next(x for x in get_symbols_info() if x['symbol'] == symbol)
    price = round_to_step(raw_price, sym_info['tickSize'], mode='round')
    qty = round_to_step(order_value / price, sym_info['stepSize'], mode='floor')
    if sym_info['stepSize'] >= 1:
        qty = int(qty)
    return qty, price


def place_limit_order(symbol: str, side: str, quantity: float, price: float) -> dict:
    """在 Binance futures 下一个限价单，并返回关键信息"""
    resp = client.futures_create_order(
        symbol=symbol,
        side=side,
        type='LIMIT',
        timeInForce='GTC',
        quantity=quantity,
        price=price
    )
    return {
        'orderId': resp['orderId'],
        'symbol': resp['symbol'],
        'status': resp['status'],
        'price': float(resp['price']),
        'origQty': float(resp['origQty']),
        'executedQty': float(resp['executedQty']),
        'updateTime': pd.to_datetime(resp['updateTime'], unit='ms')
    }


# === Upbit monitoring ===
# 使用时区感知的 datetime
# _last_check_time = datetime.now(timezone.utc) - timedelta(seconds=30)
_last_check_time = datetime.now(timezone.utc) - timedelta(minutes=10)


def fetch_latest_upbit_listing(since: datetime) -> dict:
    """拉取 Upbit 最新公告并返回新上市币种"""
    url = (
        'https://api-manager.upbit.com/api/v1/announcements'
        '?os=web&page=1&per_page=20&category=trade'
    )
    r = requests.get(url)
    r.raise_for_status()
    notices = r.json().get('data', {}).get('notices', [])
    if not notices:
        print("No notices returned from Upbit API. ")
    # 按发布时间倒序
    notices.sort(key=lambda x: x['first_listed_at'], reverse=True)
    # print(f"Fetched {len(notices)} notices from Upbit")

    for n in notices:
        # 转成 UTC 时区感知的 Timestamp
        ts = pd.to_datetime(n['first_listed_at']).tz_convert('UTC')
        if ts > since:
            asset = parse_asset_from_title(n['title'])
            if asset:
                return {'list_time': ts, 'symbol': asset + 'USDT'}
    return None


# # === 主循环 ===
if __name__ == '__main__':
    while True:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Starting listing scan")
        now = datetime.now(timezone.utc)
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        sleep_seconds = (next_hour - now).total_seconds()
        print(f"Sleeping {sleep_seconds:.1f} seconds until next hour: {next_hour}")
        time.sleep(sleep_seconds)

        start_time = datetime.now(timezone.utc)

        while (datetime.now(timezone.utc) - start_time).total_seconds() < 60:
            try:
                result = fetch_latest_upbit_listing(_last_check_time)
                print(f"result: {result}")
                if result:
                    _last_check_time = result['list_time']
                    sym = result['symbol']
                    print(f"Detected new listing: {sym} at {_last_check_time}")
                    qty, price = get_qty_price(sym, price_ratio=price_ratio, order_value=order_value)
                    try:
                        order = place_limit_order(sym, 'BUY', qty, price)
                        print(f"Order placed: {order}")
                        print(f'_last_check_time: {_last_check_time}')
                    except Exception as e:
                        print(f"Failed to place order for {sym}: {e}")
                    break
            except Exception as e:
                print("Error in loop:", e)
            time.sleep(1)