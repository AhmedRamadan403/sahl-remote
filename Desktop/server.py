"""Consent-based, TLS-only, single-controller LAN transport for Sahl Remote."""
from __future__ import annotations

import asyncio
import collections
import contextlib
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import time
from typing import Callable

from aiohttp import WSMsgType, web
from windows_platform import validate_message

LAN_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
    "::1/128", "fc00::/7", "fe80::/10",
))

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


def is_local_address(value: str | None) -> bool:
    try:
        address = ipaddress.ip_address((value or "").split("%")[0])
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        return any(address.version == network.version and address in network
                   for network in LAN_NETWORKS)
    except ValueError:
        return False


def lan_addresses() -> list[str]:
    addresses = set()
    with contextlib.suppress(OSError):
        for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = row[4][0]
            if is_local_address(address) and not address.startswith("127."):
                addresses.add(address)
    return sorted(addresses)


def make_tls_context(directory: Path, addresses: list[str]) -> tuple[ssl.SSLContext, str]:
    """Generate a per-computer certificate, never a shared bundled private key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "certificate.pem", directory / "private-key.pem"
    required_names = set(addresses) | {"127.0.0.1"}
    certificate = None
    if cert_path.exists() and key_path.exists():
        with contextlib.suppress(Exception):
            candidate = x509.load_pem_x509_certificate(cert_path.read_bytes())
            sans = candidate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            existing = {str(value) for value in sans.get_values_for_type(x509.IPAddress)}
            if required_names <= existing and candidate.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
                certificate = candidate
    if certificate is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sahl Remote local computer")])
        now = dt.datetime.now(dt.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), *[x509.IPAddress(ipaddress.ip_address(value)) for value in sorted(required_names)]
            ]), critical=False)
            .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with contextlib.suppress(OSError):
            os.chmod(key_path, 0o600)
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path)
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
    return context, ":".join(fingerprint[i:i+2] for i in range(0, len(fingerprint), 2))


def validate_input(message: dict) -> bool:
    try:
        validate_message(message)
        return True
    except ValueError:
        return False


class RemoteServer:
    def __init__(self, desktop, web_directory: Path, emit: Callable[[dict], None],
                 addresses: list[str] | None = None, code_lifetime: float = 300):
        self.desktop, self.web_directory, self.emit = desktop, Path(web_directory), emit
        self.addresses = addresses if addresses is not None else lan_addresses()
        self.allowed_hosts = set(self.addresses) | {"localhost", "127.0.0.1", "::1"}
        self.code_lifetime = code_lifetime
        self.code = ""
        self.code_expires = 0.0
        self.port = 0
        self.runner = None
        self.stopping = False
        self.revoking = False
        self.active = None
        self.pending = None
        self.sockets = set()
        self.attempts = collections.defaultdict(collections.deque)
        self.global_attempts = collections.deque()
        self.rotation_task = None
        self.screen_paused = False

    def rotate_code(self):
        self.code = f"{secrets.randbelow(100_000_000):08d}"
        self.code_expires = time.monotonic() + self.code_lifetime
        self.emit({"type": "code", "code": self.code})

    def approve(self, request_id: str, accepted: bool):
        if self.pending and self.pending["id"] == request_id and not self.pending["future"].done():
            self.pending["future"].set_result(bool(accepted))

    def _rate_limit(self, remote: str) -> bool:
        now = time.monotonic()
        attempts = self.attempts[remote]
        for queue in (attempts, self.global_attempts):
            while queue and queue[0] < now - 60:
                queue.popleft()
        # Bound bookkeeping even on a network with many spoofed clients.
        if len(self.attempts) > 512:
            for key in list(self.attempts):
                if not self.attempts[key] or self.attempts[key][-1] < now - 60:
                    del self.attempts[key]
        if len(attempts) >= 5 or len(self.global_attempts) >= 40:
            return False
        attempts.append(now)
        self.global_attempts.append(now)
        return True

    @web.middleware
    async def boundary(self, request, handler):
        if not is_local_address(request.remote):
            raise web.HTTPForbidden(text="Only local-network clients are accepted.")
        try:
            hostname = request.host.rsplit(":", 1)[0] if ":" in request.host else request.host
            hostname = hostname.strip("[]").lower()
            if hostname not in self.allowed_hosts:
                raise ValueError("host")
        except ValueError:
            raise web.HTTPForbidden(text="Unrecognized host.")
        origin = request.headers.get("Origin")
        if request.path == "/ws" and origin != f"https://{request.host}":
            raise web.HTTPForbidden(text="A same-origin HTTPS browser is required.")
        response = await handler(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    async def start(self, ssl_context: ssl.SSLContext, host="0.0.0.0", port=8443):
        self.stopping = False
        self.rotate_code()
        application = web.Application(middlewares=[self.boundary], client_max_size=8192)
        async def security_headers(request, response):
            # A WebSocket's headers are sent by prepare(), before the handler returns.
            response.headers.update(SECURITY_HEADERS)
        application.on_response_prepare.append(security_headers)
        for route, name, content_type in (("/", "index.html", "text/html"),
                ("/app.js", "app.js", "application/javascript"), ("/styles.css", "styles.css", "text/css")):
            async def asset(request, asset_name=name, mime=content_type):
                return web.Response(body=(self.web_directory / asset_name).read_bytes(), content_type=mime, charset="utf-8")
            application.router.add_get(route, asset)
        application.router.add_get("/ws", self.websocket)
        self.runner = web.AppRunner(application, access_log=None, shutdown_timeout=2)
        await self.runner.setup()
        try:
            site = web.TCPSite(self.runner, host, port, ssl_context=ssl_context)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]
        except Exception:
            await self.runner.cleanup()
            self.runner = None
            raise
        self.rotation_task = asyncio.create_task(self._rotate_expired())
        self.emit({"type": "listening", "port": self.port, "addresses": self.addresses})

    async def _rotate_expired(self):
        while not self.stopping:
            await asyncio.sleep(1)
            if time.monotonic() >= self.code_expires and not self.pending:
                self.rotate_code()

    async def disconnect(self):
        # Release immediately, before waiting for the peer's close handshake.
        self.revoking = True
        self._release_input()
        for ws in list(self.sockets):
            with contextlib.suppress(Exception):
                await ws.close(code=1000, message=b"Host ended the session")

    def _release_input(self):
        try:
            self.desktop.release_all()
        except (OSError, RuntimeError) as error:
            # An OS input error must not prevent listener/socket cleanup.
            self.emit({"type": "notice", "message": "Windows could not release input: " + str(error)[:160]})

    async def stop(self):
        self.stopping = True
        if self.pending and not self.pending["future"].done():
            self.pending["future"].set_result(False)
        if self.rotation_task:
            self.rotation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.rotation_task
        await self.disconnect()
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def _consent(self, ws, future):
        deadline = time.monotonic() + 45
        while not ws.closed:
            receive = asyncio.create_task(ws.receive())
            try:
                done, _ = await asyncio.wait([future, receive], timeout=max(0, deadline-time.monotonic()), return_when=asyncio.FIRST_COMPLETED)
                if future in done:
                    return bool(future.result())
                if receive not in done:
                    return False
                msg = receive.result()
                if msg.type != WSMsgType.TEXT:
                    return False
                with contextlib.suppress(ValueError, TypeError):
                    message = json.loads(msg.data)
                    if isinstance(message, dict) and message.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                        continue
                return False
            finally:
                if not receive.done():
                    receive.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await receive
        return False

    async def _stream(self, ws):
        try:
            while not ws.closed and self.active is ws and not self.stopping and not self.revoking:
                began = time.monotonic()
                try:
                    jpeg, width, height = await asyncio.to_thread(self.desktop.capture)
                except (OSError, RuntimeError):
                    if not self.screen_paused:
                        self.screen_paused = True
                        self._release_input()
                        message = "ويندوز يعرض شاشة محمية أو نافذة صلاحيات. تعامل معها على الكمبيوتر؛ الجلسة ما زالت متصلة."
                        await ws.send_json({"type": "paused", "message": message})
                        self.emit({"type": "screen_paused", "message": message})
                    await asyncio.sleep(0.5)
                    continue
                if self.stopping or self.revoking or self.active is not ws:
                    break
                if self.screen_paused:
                    self._release_input()
                    self.screen_paused = False
                    await ws.send_json({"type": "resumed"})
                    self.emit({"type": "screen_resumed"})
                await asyncio.wait_for(ws.send_bytes(jpeg), timeout=4)
                await asyncio.sleep(max(0.01, 0.125 - (time.monotonic()-began)))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.emit({"type": "notice", "message": "Screen streaming stopped: " + str(error)[:180]})
            await ws.close(code=1011, message=b"Screen streaming failed")

    async def websocket(self, request):
        if self.stopping:
            raise web.HTTPServiceUnavailable()
        if not self._rate_limit(request.remote):
            raise web.HTTPTooManyRequests(text="Too many pairing requests. Wait one minute.")
        if len(self.sockets) >= 8:
            raise web.HTTPServiceUnavailable(text="Too many connections.")
        ws = web.WebSocketResponse(max_msg_size=8192, heartbeat=15, receive_timeout=60)
        await ws.prepare(request)
        self.sockets.add(ws)
        stream = None
        request_id = secrets.token_hex(12)
        try:
            first = await ws.receive(timeout=10)
            try:
                data = json.loads(first.data) if first.type == WSMsgType.TEXT else None
            except (ValueError, TypeError):
                data = None
            if (not isinstance(data, dict) or data.get("type") != "pair" or
                    not isinstance(data.get("code"), str) or len(data["code"]) != 8 or
                    not data["code"].isascii() or not data["code"].isdigit() or
                    time.monotonic() >= self.code_expires or not secrets.compare_digest(data["code"], self.code)):
                await ws.send_json({"type": "error", "message": "كود الاتصال غير صحيح أو انتهت صلاحيته."})
                return ws
            if self.pending or self.active:
                await ws.send_json({"type": "error", "message": "هناك جهاز متصل أو طلب ينتظر الموافقة."})
                return ws
            name = data.get("name", "Browser")
            name = "".join(c for c in str(name) if c.isprintable())[:60] or "Browser"
            future = asyncio.get_running_loop().create_future()
            self.pending = {"id": request_id, "future": future}
            await ws.send_json({"type": "waiting"})
            self.emit({"type": "approval", "id": request_id, "name": name, "ip": request.remote})
            accepted = await self._consent(ws, future)
            self.emit({"type": "approval_expired", "id": request_id})
            if self.pending and self.pending["id"] == request_id:
                self.pending = None
            if not accepted or self.stopping or ws.closed:
                if not ws.closed:
                    await ws.send_json({"type": "ended", "message": "لم تتم الموافقة على الاتصال أو انتهت مهلة الطلب."})
                return ws
            self.active = ws
            self.revoking = False
            self.screen_paused = False
            self.rotate_code()
            width, height = self.desktop.size()
            await ws.send_json({"type": "approved", "width": width, "height": height, "host": socket.gethostname()})
            self.emit({"type": "connected", "name": name, "ip": request.remote})
            stream = asyncio.create_task(self._stream(ws))
            received = collections.deque()
            last_input_notice = -float("inf")
            began = time.monotonic()
            async for msg in ws:
                if self.stopping or self.revoking or self.active is not ws:
                    break
                if msg.type != WSMsgType.TEXT:
                    break
                now = time.monotonic()
                if now - began > 3600:
                    await ws.send_json({"type": "ended", "message": "انتهت مدة الجلسة. اتصل من جديد."})
                    break
                while received and received[0] < now - 1:
                    received.popleft()
                received.append(now)
                if len(received) > 200:
                    break
                try:
                    message = json.loads(msg.data)
                    if not isinstance(message, dict):
                        break
                    if message.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    elif validate_input(message):
                        if message["type"] == "release":
                            self.desktop.release_all()
                        elif not self.screen_paused:
                            self.desktop.handle(message)
                    else:
                        await ws.send_json({"type": "error", "message": "أمر تحكم غير صالح."})
                        break
                except (OSError, RuntimeError) as error:
                    # UIPI/secure-desktop failures are temporary OS restrictions,
                    # not a malformed command or a lost network connection.
                    self._release_input()
                    if now - last_input_notice >= 3:
                        last_input_notice = now
                        self.emit({"type": "notice", "message": "Windows temporarily blocked remote input: " + str(error)[:160]})
                        await ws.send_json({"type": "notice", "message": "ويندوز منع التحكم في النافذة الحالية. الجلسة مستمرة؛ أغلق نافذة الصلاحيات من الكمبيوتر."})
                    continue
                except (ValueError, TypeError) as error:
                    self.emit({"type": "notice", "message": "Input stopped: " + str(error)[:160]})
                    with contextlib.suppress(Exception):
                        await ws.send_json({"type": "error", "message": "تعذر إرسال الأمر إلى ويندوز. راجع نافذة البرنامج."})
                    break
            return ws
        except (asyncio.TimeoutError, ConnectionError):
            return ws
        finally:
            if stream:
                stream.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await stream
            if self.pending and self.pending["id"] == request_id:
                if not self.pending["future"].done():
                    self.pending["future"].set_result(False)
                self.pending = None
                self.emit({"type": "approval_expired", "id": request_id})
            if self.active is ws:
                self.active = None
                self.screen_paused = False
                self._release_input()
                if not self.stopping:
                    self.rotate_code()
                self.emit({"type": "disconnected"})
            self.sockets.discard(ws)
            await ws.close()
