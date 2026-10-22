"""Primary-screen capture and visible, consent-gated Windows desktop input.

The server must enforce authentication and local approval before calling this
adapter. This module does not start a service, open a port, or capture anything
at import/initialization time. Input is limited by the permissions of this
process: an ordinary process cannot control UAC's secure desktop or elevated
applications. Capture is for the primary display only.
"""

from __future__ import annotations

import ctypes
import io
import sys
from typing import Any, Callable


# Fixed-width Windows types are intentional: ctypes.wintypes.LONG/ULONG vary
# with the host ABI when these structures are inspected on a non-Windows host.
WORD = ctypes.c_uint16
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


_EXPECTED_INPUT_SIZE = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
if ctypes.sizeof(INPUT) != _EXPECTED_INPUT_SIZE:
    raise RuntimeError("Unsupported Windows INPUT structure alignment.")

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}

# Each value is (virtual key, extended-key flag). Browser KeyboardEvent.code
# identifies keys independently of the remote browser's current text layout.
KEY_CODES: dict[str, tuple[int, bool]] = {
    **{f"Key{chr(value)}": (value, False) for value in range(65, 91)},
    **{f"Digit{value}": (0x30 + value, False) for value in range(10)},
    **{f"Numpad{value}": (0x60 + value, False) for value in range(10)},
    **{f"F{value}": (0x6F + value, False) for value in range(1, 13)},
    "Backspace": (0x08, False),
    "Tab": (0x09, False),
    "Enter": (0x0D, False),
    "NumpadEnter": (0x0D, True),
    "Pause": (0x13, False),
    "CapsLock": (0x14, False),
    "Escape": (0x1B, False),
    "Space": (0x20, False),
    "PageUp": (0x21, True),
    "PageDown": (0x22, True),
    "End": (0x23, True),
    "Home": (0x24, True),
    "ArrowLeft": (0x25, True),
    "ArrowUp": (0x26, True),
    "ArrowRight": (0x27, True),
    "ArrowDown": (0x28, True),
    "PrintScreen": (0x2C, True),
    "Insert": (0x2D, True),
    "Delete": (0x2E, True),
    "MetaLeft": (0x5B, True),
    "MetaRight": (0x5C, True),
    "ContextMenu": (0x5D, True),
    "NumpadMultiply": (0x6A, False),
    "NumpadAdd": (0x6B, False),
    "NumpadSubtract": (0x6D, False),
    "NumpadDecimal": (0x6E, False),
    "NumpadDivide": (0x6F, True),
    "NumLock": (0x90, True),
    "ScrollLock": (0x91, False),
    "ShiftLeft": (0xA0, False),
    "ShiftRight": (0xA1, False),
    "ControlLeft": (0xA2, False),
    "ControlRight": (0xA3, True),
    "AltLeft": (0xA4, False),
    "AltRight": (0xA5, True),
    "Semicolon": (0xBA, False),
    "Equal": (0xBB, False),
    "Comma": (0xBC, False),
    "Minus": (0xBD, False),
    "Period": (0xBE, False),
    "Slash": (0xBF, False),
    "Backquote": (0xC0, False),
    "BracketLeft": (0xDB, False),
    "Backslash": (0xDC, False),
    "BracketRight": (0xDD, False),
    "Quote": (0xDE, False),
    "IntlBackslash": (0xE2, False),
}


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a number.")
    # Range comparison also rejects NaN/infinity without converting an
    # attacker-controlled, arbitrarily large integer to a float first.
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return float(value)


def validate_message(message: Any) -> dict[str, Any]:
    """Return a validated copy; reject malformed/unsupported input messages.

    Scroll delta is an integer number of Windows wheel notches, positive up.
    Text is Unicode input (up to 500 characters) for mobile text entry. Physical
    key messages use ``key`` with a KeyboardEvent.code such as ``KeyA``.
    """
    if not isinstance(message, dict):
        raise ValueError("An input message must be an object.")
    kind = message.get("type")
    if kind == "move":
        return {
            "type": kind,
            "x": _number(message.get("x"), "x", 0, 1),
            "y": _number(message.get("y"), "y", 0, 1),
        }
    if kind == "button":
        button, down = message.get("button"), message.get("down")
        if not isinstance(button, str) or button not in _BUTTON_FLAGS:
            raise ValueError("button must be left, right, or middle.")
        if not isinstance(down, bool):
            raise ValueError("down must be a boolean.")
        validated = {"type": kind, "button": button, "down": down}
        if "x" in message or "y" in message:
            validated["x"] = _number(message.get("x"), "x", 0, 1)
            validated["y"] = _number(message.get("y"), "y", 0, 1)
        return validated
    if kind == "scroll":
        delta = message.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, int) or not -10 <= delta <= 10:
            raise ValueError("delta must be an integer from -10 to 10.")
        return {"type": kind, "delta": delta}
    if kind == "key":
        key, down = message.get("key"), message.get("down")
        if not isinstance(key, str) or key not in KEY_CODES:
            raise ValueError("Unsupported KeyboardEvent.code.")
        if not isinstance(down, bool):
            raise ValueError("down must be a boolean.")
        return {"type": kind, "key": key, "down": down}
    if kind == "text":
        value = message.get("text")
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError("text must be a string of at most 500 characters.")
        # Unpaired UTF-16 surrogate characters are invalid Unicode, and would
        # otherwise fail encoding after some input had already been processed.
        try:
            value.encode("utf-16-le")
        except UnicodeEncodeError as error:
            raise ValueError("text contains invalid Unicode.") from error
        return {"type": kind, "text": value}
    if kind == "release":
        return {"type": kind}
    raise ValueError("Unsupported input message type.")


def _mouse(flags: int, *, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    event = INPUT(type=INPUT_MOUSE)
    event.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags)
    return event


def _key(vk: int, extended: bool, down: bool) -> INPUT:
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    if not down:
        flags |= KEYEVENTF_KEYUP
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wVk=vk, dwFlags=flags)
    return event


def _unicode(unit: int, down: bool) -> INPUT:
    flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wScan=unit, dwFlags=flags)
    return event


def _signature(function: Any, argument_types: list[Any], result_type: Any) -> None:
    """Keep injected fake APIs usable without making live Win32 calls in tests."""
    try:
        function.argtypes = argument_types
        function.restype = result_type
    except (AttributeError, TypeError):
        pass


class WindowsDesktop:
    """Use from one serialized input loop; capture may use a worker thread.

    The underscored constructor arguments exist solely for isolated tests. No
    screenshot or input is taken until capture()/handle() is explicitly called.
    """

    def __init__(
        self,
        *,
        _user32: Any | None = None,
        _grab: Callable[..., Any] | None = None,
    ) -> None:
        if _user32 is None:
            if sys.platform != "win32":
                raise RuntimeError("Sahl Remote's desktop host requires Windows 10 or Windows 11.")
            _user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._api = _user32
        self._grab = _grab
        self._held_keys: set[str] = set()
        self._held_buttons: set[str] = set()
        _signature(self._api.SendInput, [ctypes.c_uint32, ctypes.POINTER(INPUT), ctypes.c_int], ctypes.c_uint32)
        _signature(self._api.GetSystemMetrics, [ctypes.c_int], ctypes.c_int)
        self._set_dpi_aware()

    def _set_dpi_aware(self) -> None:
        # A host may already have set process DPI awareness. Access-denied here
        # means that Windows kept the existing setting; it is not an input error.
        modern = getattr(self._api, "SetProcessDpiAwarenessContext", None)
        if modern is not None:
            _signature(modern, [ctypes.c_void_p], ctypes.c_int)
            if modern(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
                return
        legacy = getattr(self._api, "SetProcessDPIAware", None)
        if legacy is not None:
            _signature(legacy, [], ctypes.c_int)
            legacy()

    def size(self) -> tuple[int, int]:
        """Return the native primary display size in physical pixels."""
        width, height = self._api.GetSystemMetrics(0), self._api.GetSystemMetrics(1)
        if width <= 0 or height <= 0:
            raise RuntimeError("Windows did not report an available primary display.")
        return int(width), int(height)

    def desktop_available(self) -> bool:
        """Check access to the ordinary input desktop; never switch to a protected desktop."""
        opener = getattr(self._api, "OpenInputDesktop", None)
        if opener is None:  # Inert injected test APIs do not need a Windows desktop.
            return True
        closer, info = self._api.CloseDesktop, self._api.GetUserObjectInformationW
        _signature(opener, [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p)
        _signature(closer, [ctypes.c_void_p], ctypes.c_int)
        _signature(info, [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int)
        handle = opener(0, False, 0x0001)  # DESKTOP_READOBJECTS only.
        if not handle:
            return False
        try:
            name, required = ctypes.create_unicode_buffer(256), ctypes.c_uint32()
            return bool(info(handle, 2, name, ctypes.sizeof(name), ctypes.byref(required))) and name.value.casefold() == "default"
        finally:
            closer(handle)

    def capture(self) -> tuple[bytes, int, int]:
        """Capture the primary display as a bounded JPEG plus encoded dimensions."""
        if not self.desktop_available():
            raise OSError("The input desktop is temporarily protected or unavailable.")
        from PIL import Image, ImageGrab

        grab = self._grab or ImageGrab.grab
        with grab(all_screens=False) as screenshot:
            with screenshot.convert("RGB") as frame:
                frame.thumbnail((1600, 1000), Image.Resampling.BILINEAR)
                output = io.BytesIO()
                frame.save(output, format="JPEG", quality=65)
                return output.getvalue(), frame.width, frame.height

    def _send(self, events: list[INPUT]) -> None:
        if not events:
            return
        if not self.desktop_available():
            raise OSError("Input is paused while Windows uses a protected desktop.")
        array = (INPUT * len(events))(*events)
        sent = int(self._api.SendInput(len(events), array, ctypes.sizeof(INPUT)))
        if sent != len(events):
            get_error = getattr(ctypes, "get_last_error", lambda: 0)
            code = int(get_error())
            raise RuntimeError(
                f"Windows accepted {sent} of {len(events)} input events (error {code}). "
                "A normal Sahl Remote host cannot control an elevated application "
                "or a UAC prompt because Windows restricts input across privilege levels (UIPI)."
            )

    def _move(self, x: float, y: float) -> INPUT:
        # Omitting VIRTUALDESK deliberately maps to the primary display.
        return _mouse(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
            dx=round(x * 65535),
            dy=round(y * 65535),
        )

    def handle(self, message: dict[str, Any]) -> None:
        message = validate_message(message)
        kind = message["type"]
        if kind == "move":
            self._send([self._move(message["x"], message["y"])])
        elif kind == "button":
            name, down = message["button"], message["down"]
            events = []
            if "x" in message:
                events.append(self._move(message["x"], message["y"]))
            # A failed/partial SendInput can still press a key. Track presses
            # before sending, so the host can release them on disconnect/error.
            if down:
                self._held_buttons.add(name)
            events.append(_mouse(_BUTTON_FLAGS[name][0 if down else 1]))
            self._send(events)
            if not down:
                self._held_buttons.discard(name)
        elif kind == "scroll":
            self._send([_mouse(MOUSEEVENTF_WHEEL, data=message["delta"] * 120)])
        elif kind == "key":
            code, down = message["key"], message["down"]
            vk, extended = KEY_CODES[code]
            if down:
                self._held_keys.add(code)
            # Repeated down events intentionally support keyboard auto-repeat.
            self._send([_key(vk, extended, down)])
            if not down:
                self._held_keys.discard(code)
        elif kind == "text":
            encoded = message["text"].encode("utf-16-le")
            events = []
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset : offset + 2], "little")
                events.extend((_unicode(unit, True), _unicode(unit, False)))
            self._send(events)
        elif kind == "release":
            self.release_all()

    def release_all(self) -> None:
        """Release held remote keys/buttons on blur, disconnect, or host stop."""
        events = [
            _key(*KEY_CODES[code], down=False)
            for code in sorted(self._held_keys)
        ]
        events.extend(
            _mouse(_BUTTON_FLAGS[button][1])
            for button in sorted(self._held_buttons)
        )
        self._send(events)
        # Preserve pending releases when SendInput fails, so a later stop or
        # disconnect can retry instead of silently forgetting a held key.
        self._held_keys.clear()
        self._held_buttons.clear()
