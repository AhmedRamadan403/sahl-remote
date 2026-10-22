"""The desktop window owns this worker; it never runs as a background service."""
import asyncio
import contextlib
import os
from pathlib import Path
import sys
import threading
import time

from server import RemoteServer, lan_addresses, make_tls_context
from pairing import start_discovery


def resource_directory():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "web"


class HostWorker:
    def __init__(self, events, desktop, port):
        self.events, self.desktop, self.port = events, desktop, port
        self.loop = self.server = self.stop_event = None
        self.stop_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, name="Sahl LAN host", daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception as error:
            self.events.put({"type": "failure", "message": str(error)[:300]})
        finally:
            with contextlib.suppress(Exception):
                self.desktop.release_all()
            self.events.put({"type": "stopped"})

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        addresses = lan_addresses()
        state_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SahlRemote"
        tls, fingerprint = await asyncio.to_thread(make_tls_context, state_path, addresses)
        self.events.put({"type": "certificate", "fingerprint": fingerprint})
        if self.stop_requested.is_set():
            return
        self.server = RemoteServer(self.desktop, resource_directory(), self.events.put, addresses)
        discovery = None
        try:
            await self.server.start(tls, port=self.port)
            def discoverable_state():
                if self.server.stopping or self.server.active or self.server.pending or time.monotonic() >= self.server.code_expires:
                    return None
                return self.server.code, self.server.port, fingerprint
            try:
                discovery, _ = await start_discovery(discoverable_state)
            except OSError:
                self.events.put({"type": "notice", "message": "Number lookup is busy on this PC. QR and address connections are available."})
            if self.stop_requested.is_set():
                self.stop_event.set()
            await self.stop_event.wait()
        finally:
            if discovery:
                discovery.close()
            await self.server.stop()

    def approve(self, request_id, accepted):
        if self.loop and self.server:
            self.loop.call_soon_threadsafe(self.server.approve, request_id, accepted)

    def disconnect(self):
        if self.loop and self.server:
            asyncio.run_coroutine_threadsafe(self.server.disconnect(), self.loop)

    def stop(self):
        self.stop_requested.set()
        if self.loop and self.stop_event:
            with contextlib.suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.stop_event.set)
