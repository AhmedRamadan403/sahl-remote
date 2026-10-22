"""Loopback HTTPS tests with synthetic frames and an inert desktop double."""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest

import aiohttp
from PIL import Image

SERVER_PATH = Path(__file__).resolve().parents[1] / 'server.py'
sys.path.insert(0, str(SERVER_PATH.parent))
spec = importlib.util.spec_from_file_location('sahl_remote_server_under_test', SERVER_PATH)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class FakeDesktop:
    def __init__(self):
        image = io.BytesIO()
        Image.new('RGB', (16, 12), (25, 40, 75)).save(image, 'JPEG')
        self.jpeg = image.getvalue()
        self.captures = 0
        self.size_calls = 0
        self.inputs = []
        self.held = set()
        self.releases = 0
        self.protected = self.input_blocked = False

    def size(self):
        self.size_calls += 1
        return 16, 12

    def capture(self):
        self.captures += 1
        if self.protected:raise OSError('Synthetic protected desktop')
        return self.jpeg, 16, 12

    def handle(self, message):
        if self.input_blocked:raise RuntimeError('Synthetic UIPI restriction')
        self.inputs.append(message)
        if message['type'] in ('key', 'button'):
            identity = (message['type'], message.get('key', message.get('button')))
            if message['down']:
                self.held.add(identity)
            else:
                self.held.discard(identity)

    def release_all(self):
        self.releases += 1
        self.held.clear()


class RemoteServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sahl-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        web_directory = self.directory / 'web'
        web_directory.mkdir()
        for name, body in [('index.html', '<!doctype html><title>synthetic</title>'),
                           ('app.js', '"use strict";'), ('styles.css', 'body{}')]:
            (web_directory / name).write_text(body, encoding='utf-8')
        self.events = []
        self.desktop = FakeDesktop()
        self.server = server_module.RemoteServer(self.desktop, web_directory, self.events.append,
                                                 addresses=['127.0.0.1'])
        server_tls, self.fingerprint = server_module.make_tls_context(self.directory / 'tls', ['127.0.0.1'])
        await self.server.start(server_tls, host='127.0.0.1', port=0)
        self.origin = f'https://127.0.0.1:{self.server.port}'
        client_tls = ssl.create_default_context(cafile=str(self.directory / 'tls' / 'certificate.pem'))
        self.client = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=client_tls))
        self.websockets = []

    async def asyncTearDown(self):
        for ws in self.websockets:
            await ws.close()
        await self.client.close()
        await self.server.stop()

    async def wait_for(self, predicate, timeout=2):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.01)
        self.fail('Condition did not become true before timeout')

    async def connect(self):
        ws = await self.client.ws_connect(self.origin + '/ws', origin=self.origin)
        self.websockets.append(ws)
        return ws

    async def pair_pending(self, ws=None):
        ws = ws or await self.connect()
        await ws.send_json({'type': 'pair', 'code': self.server.code, 'name': 'Synthetic client'})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'waiting')
        await self.wait_for(lambda: self.server.pending is not None)
        event = next(event for event in reversed(self.events) if event['type'] == 'approval')
        return ws, event

    async def approved(self):
        ws, event = await self.pair_pending()
        self.server.approve(event['id'], True)
        message = await ws.receive_json(timeout=2)
        self.assertEqual(message['type'], 'approved')
        self.assertEqual((message['width'], message['height']), (16, 12))
        return ws

    async def receive_text(self, ws):
        while True:
            message = await ws.receive(timeout=2)
            if message.type == aiohttp.WSMsgType.TEXT:
                return json.loads(message.data)
            if message.type != aiohttp.WSMsgType.BINARY:
                self.fail(f'Expected JSON before WebSocket closed: {message.type}')

    async def test_consent_precedes_capture_input_and_streams_synthetic_jpeg(self):
        ws, approval = await self.pair_pending()
        await asyncio.sleep(0.15)
        self.assertEqual(self.desktop.captures, 0)
        self.assertEqual(self.desktop.size_calls, 0)
        self.assertEqual(self.desktop.inputs, [])
        self.server.approve('wrong-request-id', True)
        await asyncio.sleep(0.02)
        self.assertIsNone(self.server.active)
        self.server.approve(approval['id'], True)
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'approved')
        frame = await ws.receive(timeout=2)
        self.assertEqual(frame.type, aiohttp.WSMsgType.BINARY)
        self.assertEqual(frame.data, self.desktop.jpeg)
        await ws.send_json({'type': 'move', 'x': .25, 'y': .75})
        await self.wait_for(lambda: bool(self.desktop.inputs))
        self.assertEqual(self.desktop.inputs[-1], {'type': 'move', 'x': .25, 'y': .75})

    async def test_protected_desktop_pauses_and_recovers_same_approved_session(self):
        ws = await self.approved()
        code = self.server.code
        self.desktop.protected = True
        self.assertEqual((await self.receive_text(ws))['type'], 'paused')
        count = len(self.desktop.inputs)
        await ws.send_json({'type': 'key', 'key': 'KeyA', 'down': True})
        await ws.send_json({'type': 'ping'})
        self.assertEqual((await self.receive_text(ws))['type'], 'pong')
        self.assertEqual(len(self.desktop.inputs), count)
        self.assertFalse(ws.closed)
        self.desktop.protected = False
        self.assertEqual((await self.receive_text(ws))['type'], 'resumed')
        frame = await ws.receive(timeout=2)
        self.assertEqual(frame.type, aiohttp.WSMsgType.BINARY)
        self.assertEqual(frame.data, self.desktop.jpeg)
        await ws.send_json({'type': 'move', 'x': .5, 'y': .5})
        await self.wait_for(lambda: len(self.desktop.inputs) > count)
        self.assertEqual(self.server.code, code)
        self.assertIsNotNone(self.server.active)

    async def test_uipi_input_error_does_not_close_session(self):
        ws = await self.approved()
        self.desktop.input_blocked = True
        await ws.send_json({'type': 'key', 'key': 'KeyA', 'down': True})
        self.assertEqual((await self.receive_text(ws))['type'], 'notice')
        await ws.send_json({'type': 'ping'})
        self.assertEqual((await self.receive_text(ws))['type'], 'pong')
        self.assertFalse(ws.closed)
        self.desktop.input_blocked = False
        await ws.send_json({'type': 'text', 'text': 'بعد رجوع الصلاحيات'})
        await self.wait_for(lambda: bool(self.desktop.inputs))
        self.assertEqual(self.desktop.inputs[-1]['type'], 'text')

    async def test_stop_while_desktop_is_protected_closes_connection(self):
        self.desktop.protected = True
        ws = await self.approved()
        self.assertEqual((await self.receive_text(ws))['type'], 'paused')
        await self.server.stop()
        message = await ws.receive(timeout=2)
        self.assertIn(message.type, (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED))
        self.assertIsNone(self.server.runner)

    async def test_pending_input_cannot_bypass_host_consent(self):
        ws, event = await self.pair_pending()
        await ws.send_json({'type': 'button', 'button': 'left', 'down': True})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'ended')
        await self.wait_for(lambda: self.server.pending is None)
        self.assertEqual(self.desktop.inputs, [])
        self.assertEqual(self.desktop.captures, 0)

    async def test_malformed_pending_json_is_rejected_cleanly(self):
        for malformed in ([], None, True, 'unexpected'):
            with self.subTest(message=repr(malformed)):
                ws, event = await self.pair_pending()
                await ws.send_json(malformed)
                message = await ws.receive(timeout=2)
                self.assertEqual(message.type, aiohttp.WSMsgType.TEXT)
                self.assertEqual(json.loads(message.data)['type'], 'ended')
                await ws.close()
                await self.wait_for(lambda: self.server.pending is None)
        self.assertEqual(self.desktop.captures, 0)
        self.assertEqual(self.desktop.inputs, [])

    async def test_host_can_reject_connection(self):
        ws, event = await self.pair_pending()
        self.server.approve(event['id'], False)
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'ended')
        await self.wait_for(lambda: self.server.pending is None)
        self.assertEqual(self.desktop.captures, 0)
        self.assertIsNone(self.server.active)

    async def test_wrong_pairing_code_rejected(self):
        ws = await self.connect()
        wrong = '11111111' if self.server.code != '11111111' else '22222222'
        await ws.send_json({'type': 'pair', 'code': wrong})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'error')
        self.assertFalse(any(event['type'] == 'approval' for event in self.events))
        self.assertEqual(self.desktop.captures, 0)

    async def test_expired_code_rejected(self):
        self.server.code_expires = 0
        ws = await self.connect()
        await ws.send_json({'type': 'pair', 'code': self.server.code})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'error')
        self.assertEqual(self.desktop.captures, 0)

    async def test_foreign_and_missing_origin_rejected(self):
        for origin in ('https://foreign.invalid', None):
            with self.subTest(origin=origin):
                with self.assertRaises(aiohttp.WSServerHandshakeError) as failure:
                    await self.client.ws_connect(self.origin + '/ws', origin=origin)
                self.assertEqual(failure.exception.status, 403)
        self.assertFalse(self.server.sockets)

    async def test_unrecognized_host_rejected(self):
        async with self.client.get(self.origin + '/', headers={'Host': 'foreign.invalid'}) as response:
            self.assertEqual(response.status, 403)

    async def test_sixth_pairing_connection_is_rate_limited(self):
        for _ in range(5):
            ws = await self.connect()
            await ws.send_json({'type': 'pair', 'code': 'incorrect'})
            self.assertEqual((await ws.receive_json(timeout=2))['type'], 'error')
            await ws.close()
        with self.assertRaises(aiohttp.WSServerHandshakeError) as failure:
            await self.connect()
        self.assertEqual(failure.exception.status, 429)
        self.assertEqual(self.desktop.captures, 0)

    async def test_single_pending_then_single_active_controller(self):
        first, event = await self.pair_pending()
        second = await self.connect()
        await second.send_json({'type': 'pair', 'code': self.server.code})
        self.assertEqual((await second.receive_json(timeout=2))['type'], 'error')
        self.server.approve(event['id'], True)
        self.assertEqual((await first.receive_json(timeout=2))['type'], 'approved')
        third = await self.connect()
        await third.send_json({'type': 'pair', 'code': self.server.code})
        self.assertEqual((await third.receive_json(timeout=2))['type'], 'error')
        self.assertIsNotNone(self.server.active)
        self.assertEqual(sum(event['type'] == 'approval' for event in self.events), 1)

    async def hold_input(self, ws):
        await ws.send_json({'type': 'key', 'key': 'ControlLeft', 'down': True})
        await ws.send_json({'type': 'button', 'button': 'left', 'down': True})
        await self.wait_for(lambda: len(self.desktop.held) == 2)

    async def test_disconnect_releases_held_input_and_rotates_code(self):
        old_code = self.server.code
        ws = await self.approved()
        self.assertNotEqual(old_code, self.server.code)
        code_during_session = self.server.code
        await self.hold_input(ws)
        await ws.close()
        await self.wait_for(lambda: self.server.active is None)
        self.assertFalse(self.desktop.held)
        self.assertGreaterEqual(self.desktop.releases, 1)
        self.assertNotEqual(code_during_session, self.server.code)

    async def test_host_stop_releases_input_and_closes_listener(self):
        ws = await self.approved()
        await self.hold_input(ws)
        await self.server.stop()
        self.assertFalse(self.desktop.held)
        self.assertIsNone(self.server.active)
        self.assertIsNone(self.server.runner)
        self.assertFalse(self.server.sockets)
        self.assertTrue(self.server.stopping)

    async def test_release_message_releases_held_input(self):
        ws = await self.approved()
        await self.hold_input(ws)
        await ws.send_json({'type': 'release'})
        await self.wait_for(lambda: not self.desktop.held)
        self.assertGreaterEqual(self.desktop.releases, 1)

    async def test_nan_input_rejected_without_reaching_desktop(self):
        ws = await self.approved()
        await ws.send_json({'type': 'move', 'x': float('nan'), 'y': .5})
        self.assertEqual((await self.receive_text(ws))['type'], 'error')
        await self.wait_for(lambda: self.server.active is None)
        self.assertEqual(self.desktop.inputs, [])

    async def test_boolean_coordinate_rejected_without_reaching_desktop(self):
        ws = await self.approved()
        await ws.send_json({'type': 'move', 'x': True, 'y': .5})
        self.assertEqual((await self.receive_text(ws))['type'], 'error')
        await self.wait_for(lambda: self.server.active is None)
        self.assertEqual(self.desktop.inputs, [])

    async def test_oversize_text_rejected_without_reaching_desktop(self):
        ws = await self.approved()
        await ws.send_json({'type': 'text', 'text': 'A' * 501})
        self.assertEqual((await self.receive_text(ws))['type'], 'error')
        await self.wait_for(lambda: self.server.active is None)
        self.assertEqual(self.desktop.inputs, [])

    async def test_input_validator_bounds_and_unicode(self):
        invalid = [
            {'type': 'move', 'x': float('inf'), 'y': .5},
            {'type': 'move', 'x': -.1, 'y': .5},
            {'type': 'scroll', 'delta': True},
            {'type': 'scroll', 'delta': 11},
            {'type': 'key', 'key': 'A', 'down': 1},
            {'type': 'key', 'key': 'A' * 25, 'down': True},
            {'type': 'text', 'text': '\ud800'},
            {'type': 'button', 'button': 'other', 'down': True},
            {'type': 'unknown'},
        ]
        for message in invalid:
            with self.subTest(message=repr(message)):
                self.assertFalse(server_module.validate_input(message))
        self.assertTrue(server_module.validate_input({'type': 'text', 'text': 'تجربة 😀'}))

    async def test_security_headers_on_browser_assets(self):
        for path in ('/', '/app.js', '/styles.css'):
            with self.subTest(path=path):
                async with self.client.get(self.origin + path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                    self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                    self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    async def test_websocket_upgrade_headers(self):
        ws = await self.connect()
        self.assertEqual(ws._response.headers.get('Cache-Control'), 'no-store')
        self.assertEqual(ws._response.headers.get('X-Content-Type-Options'), 'nosniff')


if __name__ == '__main__':
    unittest.main(verbosity=2)
