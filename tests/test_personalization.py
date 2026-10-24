import datetime as dt
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from stock_agent.app import Quote, TZ, risk_profile, analyze
from stock_agent.personalization import personalize, select_five
from stock_agent.universe import fetch_universe

class PersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(Path('examples/demo-profile.json').read_text())
        self.now = dt.datetime(2026, 10, 22, 10, tzinfo=TZ)

    def test_missing_facts_blocks(self):
        p = risk_profile(dict(self.data, personalization={}))
        self.assertEqual(p['personalization']['status'], 'needs_assessment')
        self.assertEqual(p['per_stock_limit'], 0)

    def test_near_cash_and_low_reserves(self):
        for changes in ({'cash_needed_days': 30}, {'emergency_fund_months': 2}, {'max_loss_pct': 0}):
            data = dict(self.data, personalization=self.data['personalization'] | changes)
            p = risk_profile(data)
            self.assertEqual(p['total_stock_limit'], 0)
            self.assertIsNone(p['personalization']['holding_days_range'])

    def test_user_caps_override(self):
        data = dict(self.data, personalization=self.data['personalization'] | {'single_stock_cap_pct': 1, 'max_loss_pct': 1})
        p = risk_profile(data)
        self.assertEqual(p['per_stock_limit'], .01)
        self.assertEqual(p['total_stock_limit'], .02)

    def test_select_five_diversified_with_combined_budget(self):
        p = risk_profile(self.data)
        qs = [Quote(f'sz{i:06}', f'公司{i}', 10, 9.9, self.now, 'test', 200e6+i*1e6, f'行业{i//2}') for i in range(1, 9)]
        selected = select_five(analyze(qs, p, self.now), qs)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected[0]['symbol'], 'sz000008')
        self.assertLessEqual(sum(x['position_limit'] for x in selected), p['total_stock_limit'])
        self.assertTrue(all(x['holding_days_range'] == [60, 120] for x in selected))

    def test_excluded_industry_and_unaffordable_lot(self):
        self.data['personalization']['excluded_types'] = ['bank']
        p = risk_profile(self.data)
        qs = [Quote('sh600000', '公司', 10, 9.9, self.now, 'test', 200e6, '银行'),
              Quote('sh600519', '公司', 1000, 990, self.now, 'test', 200e6, '白酒')]
        selected = select_five(analyze(qs, p, self.now), qs)
        self.assertEqual(selected, [])

    def test_universe_parser_and_inconsistent_pagination(self):
        row = dict(f2=10, f6=200e6, f12='600000', f13=1, f14='测试', f18=9.9,
                   f100='银行', f124=self.now.timestamp())
        with patch('urllib.request.urlopen') as mock:
            response = mock.return_value.__enter__.return_value
            response.read.return_value = json.dumps({'data': {'total': 1, 'diff': [row]}}).encode()
            qs, metadata = fetch_universe()
            self.assertEqual(len(qs), 1)
            self.assertEqual(metadata['scanned_count'], 1)
            response.read.return_value = json.dumps({'data': {'total': 2, 'diff': [row]}}).encode()
            with self.assertRaises(ValueError):
                fetch_universe()

if __name__ == '__main__':
    unittest.main()
