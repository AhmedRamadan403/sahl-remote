"""A window-owned LAN download page, independent of desktop sharing."""
from __future__ import annotations

import asyncio
import contextlib
import io
from pathlib import Path
import sys
import threading

from aiohttp import web
import qrcode

from server import SECURITY_HEADERS, is_local_address, lan_addresses


def release_files():
    """Only offer named release files, never a browsable output directory."""
    frozen = bool(getattr(sys, "frozen", False))
    directory = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
    windows = Path(sys.executable).resolve() if frozen else directory / "SahlRemote-Desktop.exe"
    candidates = [directory / "SahlRemote-Android.apk", directory.parent / "SahlRemote-Android.apk"]
    android = next((path for path in candidates if path.is_file()), candidates[0])
    return {"android": android, "windows": windows}


class DownloadServer:
    def __init__(self, web_directory, files=None, addresses=None):
        self.directory = Path(web_directory) / "downloads"
        self.files = {key: Path(value) for key, value in (files if files is not None else release_files()).items()
                      if key in ("android", "windows")}
        self.addresses = lan_addresses() if addresses is None else addresses
        self.allowed_hosts = set(self.addresses) | {"127.0.0.1", "localhost", "::1"}
        self.port = 0
        self.runner = None

    @web.middleware
    async def boundary(self, request, handler):
        if not is_local_address(request.remote):
            raise web.HTTPForbidden(text="Local network only.")
        try:
            if request.url.host.lower() not in self.allowed_hosts or request.url.port != self.port:
                raise ValueError("host")
        except ValueError:
            raise web.HTTPForbidden(text="Unrecognized host.")
        return await handler(request)

    async def start(self, host="0.0.0.0", port=8088):
        app = web.Application(middlewares=[self.boundary], client_max_size=1024)
        async def headers(request, response):
            response.headers.update(SECURITY_HEADERS)
        app.on_response_prepare.append(headers)
        for route, name, mime in (("/", "index.html", "text/html"),
                                  ("/download", "index.html", "text/html"),
                                  ("/download/", "index.html", "text/html"),
                                  ("/downloads.css", "style.css", "text/css"),
                                  ("/downloads.js", "app.js", "application/javascript")):
            async def asset(request, filename=name, content_type=mime):
                return web.Response(body=(self.directory / filename).read_bytes(), content_type=content_type, charset="utf-8")
            app.router.add_get(route, asset)
        app.router.add_get("/api/releases", self.metadata)
        app.router.add_get("/qr.png", self.qr)
        app.router.add_get("/files/{platform:android|windows}", self.download)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await self.runner.setup()
        try:
            site = web.TCPSite(self.runner, host, port)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]
        except BaseException:
            await self.runner.cleanup()
            self.runner = None
            raise

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def metadata(self, request):
        releases = {}
        for platform, version in (("android", "0.2.0"), ("windows", "0.3.1")):
            path = self.files.get(platform)
            available = path is not None and path.is_file()
            releases[platform] = {"available": available, "version": version,
                "size_bytes": path.stat().st_size if available else 0,
                "url": f"/files/{platform}" if available else None}
        return web.json_response({"releases": releases, "network": "lan"})

    async def qr(self, request):
        url = str(request.url.origin()) + "/download"
        def encode():
            output = io.BytesIO()
            qrcode.make(url).save(output, format="PNG")
            return output.getvalue()
        return web.Response(body=await asyncio.to_thread(encode), content_type="image/png")

    async def download(self, request):
        platform = request.match_info["platform"]
        path = self.files.get(platform)
        if path is None or not path.is_file():
            raise web.HTTPNotFound(text="This release is not available on this computer.")
        name, mime = (("SahlRemote-Android.apk", "application/vnd.android.package-archive") if platform == "android"
                      else ("SahlRemote-Desktop.exe", "application/octet-stream"))
        return web.FileResponse(path, headers={"Content-Type": mime,
            "Content-Disposition": f'attachment; filename="{name}"'})


class DownloadWorker:
    def __init__(self, events, web_directory, port=8088):
        self.events, self.directory, self.port = events, web_directory, port
        self.stop_requested = threading.Event()
        self.loop = self.stop_event = None
        self.thread = threading.Thread(target=self._run, name="Sahl app downloads", daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception as error:
            self.events.put({"type": "downloads_failure", "message": str(error)[:240]})
        finally:
            self.events.put({"type": "downloads_stopped"})

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        addresses = lan_addresses()
        server = DownloadServer(self.directory, addresses=addresses)
        try:
            if self.stop_requested.is_set():
                return
            try:
                await server.start(port=self.port)
            except OSError:
                # Another instance may already own 8088. Never replace its listener.
                await server.start(port=0)
            ip = (addresses or ["127.0.0.1"])[0]
            self.events.put({"type": "downloads_ready", "url": f"http://{ip}:{server.port}/download"})
            if self.stop_requested.is_set():
                self.stop_event.set()
            await self.stop_event.wait()
        finally:
            await server.stop()

    def stop(self):
        self.stop_requested.set()
        if self.loop and self.stop_event:
            with contextlib.suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.stop_event.set)
