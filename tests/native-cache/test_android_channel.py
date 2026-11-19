# SPDX-License-Identifier: GPL-3.0-only
import io
import unittest

from android_channel import ROUTES, exchange


class Port(io.BytesIO):
    def __init__(self, commands):
        super().__init__(commands)
        self.output = io.BytesIO()

    def write(self, data):
        return self.output.write(data)


class SignedAppRequests(unittest.TestCase):
    def test_every_phase_requires_both_original_requests_and_ui_confirmation(self):
        for phase, weather_status, revision in [('initial', 200, 1), ('refused', 503, 1), ('recovered', 200, 2)]:
            routes = []
            def read(origin, path):
                routes.append(path)
                weather = path == ROUTES['weather']
                if weather and weather_status == 503:
                    return 503, {'error': 'FORECAST_UNAVAILABLE'}
                return (weather_status if weather else 200,
                        {'delivery': {'cache_only': True, 'revision': revision if weather else 1}})
            port = Port(f'weather\nair\n{phase}-observed\n'.encode())
            self.assertEqual(exchange(port, phase, None, read), [weather_status, 200])
            self.assertEqual(routes, list(ROUTES.values()))
            self.assertEqual(len(port.output.getvalue().splitlines()), 3)

    def test_stale_success_or_out_of_order_requests_cannot_unlock_the_replacement(self):
        for commands in (b'air\nweather\nrefused-observed\n', b'weather\nair\nrefused-observed\n'):
            with self.assertRaises(AssertionError):
                exchange(Port(commands), 'refused', None,
                         lambda _, path: (200, {'delivery': {'cache_only': True, 'revision': 1}}))

    def test_mobile_guest_config_matches_the_real_bridge_and_source_model(self):
        import json
        import subprocess
        from expiry import ROOT, NODE, bridge_config

        core = dict(mode='core-cache', executable='/usr/bin/volparossa', controlSocket='/run/agent.sock',
                    cache='/var/lib/volparossa/forecast-cache', scratchParent='/tmp/owner-scratch',
                    name='weather.public-community-cache-trial', minRevision=1, cacheMode='cache-only',
                    publisherKey='a' * 64)
        forecast = {'source': {'model_run_at': '2026-11-18T00:00:00.000Z'}}
        quality = {'source': {'model_run_at': '2026-11-17T18:00:00.000Z', 'model': 'gefs-aerosols'}}
        config = bridge_config(core, forecast, quality)
        js = """import {providerHttpConfiguration} from './src/provider-http.mjs';
                const config = providerHttpConfiguration(JSON.parse(process.argv[1]));
                process.stdout.write(JSON.stringify(config.airQuality.core.query));"""
        def parse():
            return subprocess.run([NODE, '--input-type=module', '-e', js, json.dumps(config)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=10)
        checked = parse()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        query = json.loads(checked.stdout)
        self.assertEqual(query['model'], quality['source']['model'])
        self.assertEqual(query['run'], quality['source']['model_run_at'])
        del config['airQuality']['core']['query']['model']
        rejected = parse()
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('BRIDGE_CONFIG_INVALID', rejected.stderr)
