import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stock_agent.app import TZ, Quote, analyze, risk_profile, main, model_comment
from stock_agent.onboarding import create_profile
from stock_agent.personalization import select_five


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(Path('examples/demo-profile.json').read_text())

    def test_closed_market_never_selects_even_fresh_quotes(self):
        profile = risk_profile(self.data)
        for now in (dt.datetime(2026, 10, 24, 10, tzinfo=TZ),
                    dt.datetime(2026, 10, 22, 12, tzinfo=TZ)):
            q = Quote('sh600000', '测试', 10, 9.9, now, 'test', 200e6, '银行')
            report = analyze([q], profile, now)
            self.assertEqual(select_five(report, [q]), [])

    def test_short_questionnaire_horizon_overrides_conflicting_days(self):
        self.data['horizon'] = 0
        p = risk_profile(self.data)
        self.assertEqual(p['personalization']['status'], 'observation_only')

    def test_invalid_profile_replaces_old_report(self):
        with tempfile.TemporaryDirectory() as folder:
            profile, output = Path(folder)/'user.json', Path(folder)/'report.json'
            profile.write_text('{broken')
            output.write_text('{"selected":["old"]}')
            with patch('sys.argv', ['agent', '--profile', str(profile), '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    main()
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(json.loads(output.read_text())['selected'], [])

    def test_interactive_profile_private_and_no_overwrite(self):
        answers = iter(['2','2','2','2','100000','10','5','365','6','main','bank'])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'user.json'
            create_profile(target, lambda _: next(answers))
            self.assertEqual(risk_profile(json.loads(target.read_text()))['personalization']['status'], 'assessed')
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                create_profile(target)
            self.assertEqual(target.read_bytes(), before)

    def test_nonfinite_turnover_and_bad_names_rejected(self):
        now = dt.datetime.now(TZ)
        for values in ({'turnover': float('nan')}, {'name': ''}, {'turnover': -1}):
            q = dict(symbol='sh600000', name='测试', price=10, previous_close=9.9, timestamp=now, source='test')
            with self.assertRaises(ValueError):
                Quote(**(q | values))

    def test_model_request_omits_raw_finances(self):
        settings = dict(LLM_API_KEY='test-only', LLM_BASE_URL='https://example.com/v1', LLM_MODEL='test')
        with patch.dict('os.environ', settings, clear=True), patch('urllib.request.build_opener') as mock:
            response = mock.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
            model_comment({'risk': {'level': '稳健', 'capital': 123456},
                           'selected': [{'symbol': 'sh600000', 'amount_limit': 12345}]})
            request = mock.return_value.open.call_args.args[0]
            content = json.loads(json.loads(request.data)['messages'][1]['content'])
            self.assertNotIn('risk', content)
            self.assertNotIn('amount_limit', content['selected'][0])

    def test_duplicate_candidates_rejected(self):
        now = dt.datetime(2026, 10, 22, 10, tzinfo=TZ)
        q = Quote('sh600000', '测试', 10, 9.9, now, 'test', 200e6, '银行')
        report = analyze([q, q], risk_profile(self.data), now)
        with self.assertRaises(ValueError):
            select_five(report, [q, q])

if __name__ == '__main__':
    unittest.main()
