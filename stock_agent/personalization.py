"""User facts are inputs, never inferred by the language model."""
import math

FIELDS = ('capital', 'max_loss_pct', 'single_stock_cap_pct', 'cash_needed_days',
          'experience', 'emergency_fund_months', 'excluded_types', 'allowed_boards')
BOARDS = {'main', 'chinext', 'star'}
EXCLUSIONS = {'bank', 'real_estate', 'alcohol'}


def personalize(data, baseline):
    missing = [k for k in FIELDS if k not in data or data[k] is None]
    if missing:
        return {'status': 'needs_assessment', 'missing_fields': missing}
    for key in FIELDS[:6]:
        value = data[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{key} 必须为有限数字')
    if data['capital'] <= 0 or not 0 <= data['max_loss_pct'] <= 100:
        raise ValueError('资金必须大于0，最大可接受损失比例为0–100')
    if not 0 <= data['single_stock_cap_pct'] <= 100:
        raise ValueError('单股上限比例为0–100')
    if type(data['cash_needed_days']) is not int or data['cash_needed_days'] < 0:
        raise ValueError('资金取出天数必须为非负整数')
    if type(data['experience']) is not int or not 0 <= data['experience'] <= 4:
        raise ValueError('经验为0–4整数')
    if data['emergency_fund_months'] < 0:
        raise ValueError('应急储备月数不能为负')
    for key, choices in (('allowed_boards', BOARDS), ('excluded_types', EXCLUSIONS)):
        if not isinstance(data[key], list) or any(not isinstance(v, str) or v not in choices for v in data[key]):
            raise ValueError(f'{key} 包含不支持的类型')
    loss = data['max_loss_pct'] / 100
    single = min(baseline['per_stock_limit'], data['single_stock_cap_pct'] / 100)
    # Stress assumption: a 50% equity loss, not a guaranteed worst case.
    total = min(baseline['total_stock_limit'], loss / .5)
    blocked = (data['cash_needed_days'] < 180 or data['emergency_fund_months'] < 6
               or loss == 0 or single == 0 or not data['allowed_boards']
               or baseline['level'] == '保守' or baseline['questionnaire']['horizon'] < 2)
    if blocked:
        single = total = 0
    total = min(total, 5 * single)
    single = min(single, total)
    horizon = None if blocked else ([20, 60] if baseline['level'] == '进取' and min(data['experience'], baseline['questionnaire']['experience']) >= 3 else [60, 120])
    return {'status': 'observation_only' if blocked else 'assessed',
            'per_stock_limit': single, 'total_stock_limit': total,
            'capital': data['capital'], 'single_stock_amount_limit': round(data['capital'] * single, 2),
            'portfolio_amount_limit': round(data['capital'] * total, 2),
            'holding_days_range': horizon,
            'review_interval_days': 7 if horizon else None,
            'allowed_boards': data['allowed_boards'], 'excluded_types': data['excluded_types'],
            'reason': '短期用款、应急储备不足、零风险预算或保守评估时只观察；周期为待回测的政策建议，不是到期必卖。',
            'stress_assumption': '按股票资产损失50%压缩仓位，实际损失可能更大；最大可接受亏损并非可保证的止损上限。'}


def board(symbol):
    if symbol.startswith('sh688'):
        return 'star'
    if symbol.startswith(('sz300', 'sz301')):
        return 'chinext'
    if symbol.startswith(('sh600', 'sh601', 'sh603', 'sh605', 'sz000', 'sz001', 'sz002', 'sz003')):
        return 'main'
    return None


def select_five(report, quotes):
    """Rank only eligible, liquid A shares; max two in an industry."""
    policy = report['risk'].get('personalization', {})
    if policy.get('status') != 'assessed':
        return []
    metadata = {q.symbol: q for q in quotes}
    if len(metadata) != len(quotes):
        raise ValueError('重复股票行情，无法生成唯一候选')
    candidates = []
    for row in report['stocks']:
        q = metadata[row['symbol']]
        if row['status'] != '研究候选' or board(q.symbol) not in policy['allowed_boards']:
            continue
        if q.turnover < 100_000_000 or not q.industry:
            continue
        exclusions = {'bank': ('银行',), 'real_estate': ('房地产',), 'alcohol': ('白酒', '酿酒')}
        if any(any(word in q.industry for word in exclusions[t]) for t in policy['excluded_types']):
            continue
        budget = policy['capital'] * min(policy['per_stock_limit'], policy['total_stock_limit'] / 5)
        minimum_lot = 200 if board(q.symbol) == 'star' else 100
        if budget < q.price * minimum_lot * 1.002:  # reserve 0.2% for estimated fees
            continue
        # Transparent liquidity rank. Does not assert expected returns.
        candidates.append((q.turnover, q.symbol, row, q))
    selected, counts = [], {}
    for _, _, row, q in sorted(candidates, key=lambda x: (-x[0], x[1])):
        if counts.get(q.industry, 0) >= 2:
            continue
        counts[q.industry] = counts.get(q.industry, 0) + 1
        selected.append(dict(row, industry=q.industry, turnover=q.turnover,
                             selection_reason='通过风险和时效过滤，成交额排序，同一行业最多2只',
                             holding_days_range=policy['holding_days_range']))
        if len(selected) == 5:
            break
    # Allocate within a single combined cap, even with fewer than five names.
    if selected:
        weight = min(policy['per_stock_limit'], policy['total_stock_limit'] / 5)
        for row in selected:
            row['position_limit'] = weight
            row['amount_limit'] = round(policy['capital'] * weight, 2)
            row['standard_lot_feasible'] = row['amount_limit'] >= row['price'] * (200 if board(row['symbol']) == 'star' else 100)
            row['allocation_note'] = '金额仅为新组合上限，未扣除现有持仓和交易费用；不满足最小买入单位时不建议下单。'
    return selected
