"""QR pairing and scoped local-network discovery. Never broadcast the code."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import socket
import time
from urllib.parse import urlencode

from server import is_local_address

DISCOVERY_PORT = 38443
SERVICE = "sahl-remote"


def normalize_code(value: str) -> str:
    translated = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    return "".join(c for c in translated if c in "0123456789")[:8]


def pairing_url(host: str, port: int, code: str, fingerprint: str) -> str:
    pin = fingerprint.replace(":", "").lower()
    if not is_local_address(host) or not 1024 <= port <= 65535:
        raise ValueError("A local-network address and valid port are required.")
    if not re.fullmatch(r"[0-9]{8}", code) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("A current pairing code and certificate fingerprint are required.")
    return f"https://{host}:{port}/#" + urlencode({"v": "1", "code": code, "fp": pin})


def discovery_proof(code: str, nonce: str, port: int, fingerprint: str) -> str:
    message = f"{nonce}|{port}|{fingerprint}".encode("ascii")
    return hmac.new(code.encode("ascii"), message, hashlib.sha256).hexdigest()


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, current_state):
        self.current_state = current_state
        self.transport = None
        self.last_reply = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        if len(data) > 512 or not is_local_address(address[0]):
            return
        now = time.monotonic()
        if now - self.last_reply.get(address[0], 0) < 0.25:
            return
        try:
            query = json.loads(data)
            if not isinstance(query, dict) or query.get("service") != SERVICE or query.get("v") != 1:
                return
            nonce = query.get("nonce", "")
            if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
                return
            state = self.current_state()
            if not state:
                return
            code, port, fingerprint = state
            pin = fingerprint.replace(":", "").lower()
            response = {"service": SERVICE, "v": 1, "nonce": nonce, "port": port,
                        "fp": pin, "name": socket.gethostname()[:60],
                        "proof": discovery_proof(code, nonce, port, pin)}
            self.last_reply[address[0]] = now
            if len(self.last_reply) > 256:
                self.last_reply = {k: v for k, v in self.last_reply.items() if v > now - 10}
            self.transport.sendto(json.dumps(response).encode("ascii"), address)
        except (ValueError, TypeError, KeyError, UnicodeError):
            return


async def start_discovery(current_state, host="0.0.0.0", port=DISCOVERY_PORT):
    return await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: DiscoveryProtocol(current_state), local_addr=(host, port), family=socket.AF_INET,
        allow_broadcast=True)


def discover_host(code: str, timeout=4.0, targets=None, discovery_port=DISCOVERY_PORT):
    code = normalize_code(code)
    if len(code) != 8:
        raise ValueError("Enter the complete 8-digit code.")
    nonce = secrets.token_hex(16)
    query = json.dumps({"service": SERVICE, "v": 1, "nonce": nonce}).encode("ascii")
    destinations = targets or ["255.255.255.255", "127.0.0.1"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        channel.bind(("0.0.0.0", 0))
        channel.settimeout(0.15)
        deadline, next_send = time.monotonic() + timeout, 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:
                for host in destinations:
                    try:
                        channel.sendto(query, (host, discovery_port))
                    except OSError:
                        pass
                next_send = time.monotonic() + 1
            try:
                data, address = channel.recvfrom(2048)
                response = json.loads(data)
                if not isinstance(response, dict) or not is_local_address(address[0]):
                    continue
                port, pin = response.get("port"), response.get("fp")
                if (response.get("service") != SERVICE or response.get("v") != 1 or response.get("nonce") != nonce or
                    type(port) is not int or not 1024 <= port <= 65535 or
                    not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin)):
                    continue
                proof = discovery_proof(code, nonce, port, pin)
                if not isinstance(response.get("proof"), str) or not hmac.compare_digest(proof, response["proof"]):
                    continue
                return {"host": address[0], "port": port, "fingerprint": pin,
                        "url": pairing_url(address[0], port, code, pin),
                        "name": str(response.get("name", "Computer"))[:60]}
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
    raise TimeoutError("No matching computer found. Start sharing on the other PC and use the same Wi-Fi.")
