# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'iphone-signed/artifact.py'
spec = importlib.util.spec_from_file_location('iphone_artifact', source)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class IphoneHandoff(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(handoff.os.environ, GITHUB_RUN_ID='102', GITHUB_RUN_ATTEMPT='2',
            GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='example/weather'))
        self.item = dict(name='iphone-inputs-' + 'a' * 40 + '-2', id=37, size_in_bytes=341,
                         workflow_run={'id': 102}, expired=False)

    def test_accepts_only_the_current_run_and_attempt(self):
        previous = dict(self.item, name=self.item['name'][:-1] + '1', id=36)
        with patch.object(handoff, 'api', return_value={'artifacts': [previous, self.item]}):
            self.assertEqual(handoff.wait('inputs'), 37)
        with patch.object(handoff, 'api', return_value={'artifacts': [dict(self.item, workflow_run={'id': 101})]}):
            with self.assertRaises(AssertionError):
                handoff.wait('inputs')

    def test_failed_producer_releases_the_waiting_job(self):
        with patch.object(handoff, 'api', side_effect=[{'artifacts': [dict(self.item, expired=True)]},
            {'jobs': [dict(name='media', status='completed', conclusion='failure')]}]):
            with self.assertRaisesRegex(RuntimeError, 'media job stopped'):
                handoff.wait('inputs')
