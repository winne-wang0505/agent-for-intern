"""Bounded, fail-closed Eastmoney public market snapshot adapter."""
import datetime as dt
import json
import math
import urllib.parse
import urllib.request

from .app import Quote, TZ
from .personalization import board


def fetch_universe():
    quotes, seen, expected = [], set(), None
    for page in range(1, 101):
        params = dict(pn=page, pz=100, po=1, np=1, fltt=2, invt=2,
                      fid='f12', fs='m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80',
                      fields='f2,f6,f12,f13,f14,f18,f100,f124')
        url = 'https://push2.eastmoney.com/api/qt/clist/get?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={'User-Agent': 'StockResearchAssistant/0.2'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read(5_000_000))['data']
        total, rows = data['total'], data['diff']
        if type(total) is not int or not 0 < total <= 10000 or not isinstance(rows, list):
            raise ValueError('全市场行情结构错误')
        if expected is None:
            expected = total
        if total != expected or not rows:
            raise ValueError('扫描期间股票总数变化或分页缺失，请重试')
        for row in rows:
            symbol = ('sh' if row['f13'] == 1 else 'sz' if row['f13'] == 0 else 'invalid') + row['f12']
            if symbol in seen or board(symbol) is None:
                raise ValueError('全市场返回重复或非A股代码')
            seen.add(symbol)
            # Unpriced/suspended stocks are counted but cannot become candidates.
            if any(row.get(k) in (None, '-', '') for k in ('f2', 'f18', 'f124', 'f6', 'f100')):
                continue
            turnover = float(row['f6'])
            if turnover < 0 or not math.isfinite(turnover):
                raise ValueError('成交额无效')
            quotes.append(Quote(symbol, row['f14'], float(row['f2']), float(row['f18']),
                                dt.datetime.fromtimestamp(float(row['f124']), TZ),
                                '东方财富公开行情（可能延迟）', turnover, str(row['f100'])))
        if len(seen) == expected:
            return quotes, {'provider': 'eastmoney-public', 'reported_total': expected,
                            'scanned_count': len(seen), 'usable_count': len(quotes),
                            'coverage': 'provider_reported_universe', 'atomic_snapshot': False}
        if len(seen) > expected:
            raise ValueError('分页数量不一致')
    raise ValueError('全市场扫描超过页数上限')
