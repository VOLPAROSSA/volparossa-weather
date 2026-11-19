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
