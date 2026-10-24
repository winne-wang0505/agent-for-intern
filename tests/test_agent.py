import datetime as dt
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from stock_agent.app import Quote, TZ, analyze, risk_profile, fetch_quotes, model_comment, main

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 22, 10, tzinfo=TZ)
        self.profile = risk_profile(json.loads(Path('examples/demo-profile.json').read_text()))

    def quote(self, **kw):
        fields = dict(symbol='sh600519', name='测试', price=101, previous_close=100,
                      timestamp=self.now, source='test')
        return Quote(**(fields | kw))

    def result(self, q, profile=None):
        return analyze([q], profile or self.profile, self.now)['stocks'][0]

    def test_candidate(self):
        r = self.result(self.quote())
        self.assertEqual(r['status'], '研究候选')
        self.assertEqual(r['position_limit'], .05)

    def test_stale_future_special_and_volatile_blocked(self):
        for q in (self.quote(timestamp=self.now-dt.timedelta(minutes=4)),
                  self.quote(timestamp=self.now+dt.timedelta(seconds=10)),
                  self.quote(name='*ST测试'), self.quote(price=110)):
            with self.subTest(q=q):
                self.assertEqual(self.result(q)['position_limit'], 0)

    def test_capacity_caps_risk(self):
        p = risk_profile(dict(experience=4, loss_tolerance=4, horizon=4, financial_capacity=0))
        self.assertEqual(p['level'], '保守')
        self.assertEqual(self.result(self.quote(), p)['position_limit'], 0)

    def test_invalid_input(self):
        for v in (float('nan'), float('inf'), -1, 0):
            with self.assertRaises(ValueError):
                self.quote(price=v)
        with self.assertRaises(ValueError):
            risk_profile(dict(experience=True, loss_tolerance=2, horizon=2, financial_capacity=2))
        with self.assertRaises(ValueError):
            fetch_quotes(['sh600519&bad'])

    def test_quote_parser(self):
        fields = [''] * 31
        fields[1:5] = ['测试', '600519', '101', '100']
        fields[30] = '20261022100000'
        body = ('v_sh600519="' + '~'.join(fields) + '";').encode('gbk')
        with patch('urllib.request.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = body
            q = fetch_quotes(['sh600519'])[0]
        self.assertEqual(q.price, 101)
        self.assertEqual(q.timestamp, self.now)

    def test_failed_cycle_clears_previous_report(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            output.write_text('{"stocks": [{"status": "研究候选"}]}')
            with patch('sys.argv', ['agent', '--profile', 'examples/demo-profile.json', '--symbols', 'sh600519', '--output', str(output)]), patch('stock_agent.app.fetch_quotes', side_effect=OSError('offline')), patch('builtins.print'):
                with self.assertRaises(SystemExit) as caught:
                    main()
            self.assertEqual(caught.exception.code, 1)
            self.assertEqual(json.loads(output.read_text())['stocks'], [])

    def test_model_optional(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(model_comment({})['status'], 'not_configured')

    def test_model_protocol(self):
        settings = dict(LLM_API_KEY='test-only', LLM_BASE_URL='https://example.com/v1', LLM_MODEL='test')
        with patch.dict('os.environ', settings, clear=True), patch('urllib.request.build_opener') as mock:
            response = mock.return_value.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps({'choices': [{'message': {'content': '说明'}}]}).encode()
            self.assertEqual(model_comment({})['text'], '说明')

if __name__ == '__main__':
    unittest.main()
