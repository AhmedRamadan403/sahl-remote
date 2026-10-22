"""Real loopback HTTP transfers; no screen or input adapter is constructed."""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from downloads import DownloadServer, DownloadWorker


class DownloadsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.apk = self.directory / 'release.apk'
        self.exe = self.directory / 'release.exe'
        self.apk_bytes = b'PK\x03\x04' + bytes(range(256)) * 1000
        self.exe_bytes = b'MZ' + b'portable-test-release' * 1000
        self.apk.write_bytes(self.apk_bytes)
        self.exe.write_bytes(self.exe_bytes)
        self.server = DownloadServer(Path(__file__).resolve().parents[1] / 'web',
            files={'android': self.apk, 'windows': self.exe}, addresses=['127.0.0.1'])
        await self.server.start(host='127.0.0.1', port=0)
        self.url = f'http://127.0.0.1:{self.server.port}'
        self.client = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.stop()
        self.temporary.cleanup()

    async def test_downloads_match_release_bytes_and_types(self):
        for platform, expected, mime, name in (
            ('android', self.apk_bytes, 'application/vnd.android.package-archive', 'SahlRemote-Android.apk'),
            ('windows', self.exe_bytes, 'application/octet-stream', 'SahlRemote-Desktop.exe')):
            async with self.client.get(self.url + f'/files/{platform}') as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), expected)
                self.assertEqual(response.headers['Content-Type'], mime)
                self.assertIn(f'filename="{name}"', response.headers['Content-Disposition'])
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    async def test_resume_and_head_preserve_release_length(self):
        async with self.client.get(self.url + '/files/android', headers={'Range': 'bytes=999-1998'}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(await response.read(), self.apk_bytes[999:1999])
            self.assertEqual(response.headers['Content-Range'], f'bytes 999-1998/{len(self.apk_bytes)}')
        async with self.client.head(self.url + '/files/windows') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_length, len(self.exe_bytes))
            self.assertEqual(await response.read(), b'')

    async def test_unavailable_release_has_no_working_link(self):
        self.apk.unlink()
        async with self.client.get(self.url + '/api/releases') as response:
            data = await response.json()
            self.assertFalse(data['releases']['android']['available'])
            self.assertIsNone(data['releases']['android']['url'])
            self.assertTrue(data['releases']['windows']['available'])
            self.assertNotIn(str(self.directory), str(data))
        async with self.client.get(self.url + '/files/android') as response:
            self.assertEqual(response.status, 404)

    async def test_no_file_listing_traversal_or_control_routes(self):
        for path in ('/files/', '/files/private-key.pem', '/files/windows/../../main.py',
                     '/private-key.pem', '/ws', '/api/approve'):
            async with self.client.get(self.url + path) as response:
                self.assertEqual(response.status, 404, path)

    async def test_host_rebinding_and_wrong_port_blocked(self):
        for host in (f'attacker.example:{self.server.port}', '127.0.0.1:1'):
            async with self.client.get(self.url + '/', headers={'Host': host}) as response:
                self.assertEqual(response.status, 403)

    async def test_qr_contains_current_page_url(self):
        import zxingcpp
        from PIL import Image
        import io
        async with self.client.get(self.url + '/qr.png') as response:
            self.assertEqual(response.status, 200)
            result = zxingcpp.read_barcode(Image.open(io.BytesIO(await response.read())))
            self.assertEqual(result.text, self.url + '/download')

    async def test_page_assets_and_headers(self):
        for path in ('/', '/download', '/download/', '/downloads.css', '/downloads.js'):
            async with self.client.get(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        async with self.client.post(self.url + '/files/windows') as response:
            self.assertEqual(response.status, 405)

    async def test_stop_closes_listener(self):
        await self.server.stop()
        with self.assertRaises(aiohttp.ClientConnectorError):
            await self.client.get(self.url + '/download')


if __name__ == '__main__':
    unittest.main()
