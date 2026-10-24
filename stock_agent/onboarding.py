"""Interactive assessment. No inferred personal financial facts."""
import json
from pathlib import Path


def create_profile(path, ask=input):
    target = Path(path).expanduser()
    # Exclusive creation preserves any existing user profile.
    if target.exists():
        raise ValueError('目标文件已存在，请使用新路径，避免覆盖用户资料')
    data = {}
    questions = {
        'experience': '投资经验 0无经验/1初学/2了解/3熟悉/4多年经验',
        'loss_tolerance': '接受亏损意愿 0不接受/1小幅/2中等/3较大/4很大',
        'horizon': '资金期限 0一个月内/1三个月内/2一年内/3三年内/4三年以上',
        'financial_capacity': '损失承受能力 0无闲钱/1负担重/2有储备/3储备充分/4不影响生活',
    }
    for name, question in questions.items():
        while True:
            try:
                value = int(ask(question + '：'))
                if value not in range(5):
                    raise ValueError()
                data[name] = value
                break
            except ValueError:
                print('请输入0–4的整数')
    personal = {'experience': data['experience']}
    for name, question, convert in (
        ('capital', '可投资资金（元，不含生活应急资金）', float),
        ('max_loss_pct', '最大可接受亏损（占可投资资金百分比，例如5）', float),
        ('single_stock_cap_pct', '单股仓位硬上限（百分比，例如3）', float),
        ('cash_needed_days', '距离最早需要取出资金的天数', int),
        ('emergency_fund_months', '额外应急储备可覆盖生活的月数', float),
    ):
        while True:
            try:
                personal[name] = convert(ask(question + '：'))
                break
            except ValueError:
                print('请输入数字')
    personal['allowed_boards'] = [v.strip() for v in ask('已开通且允许的板块，逗号分隔 main/chinext/star（空为不参与）：').split(',') if v.strip()]
    personal['excluded_types'] = [v.strip() for v in ask('禁止行业，逗号分隔 bank/real_estate/alcohol（空为无）：').split(',') if v.strip()]
    data['personalization'] = personal
    from .app import risk_profile
    risk_profile(data)  # Validate before creating a private file.
    target.parent.mkdir(parents=True, exist_ok=True)
    import os
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return target
