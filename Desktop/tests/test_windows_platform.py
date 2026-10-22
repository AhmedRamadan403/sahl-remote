"""Isolated adapter tests: never access the desktop or real Win32 input API."""
import ctypes
import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "windows_platform.py"
spec = importlib.util.spec_from_file_location("sahl_windows_platform", MODULE_PATH)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class FakeUser32:
    def __init__(self):
        self.events = []
        self.return_count = None
        self.dpi = []

    def SetProcessDpiAwarenessContext(self, context):
        self.dpi.append(context.value)
        return True

    def GetSystemMetrics(self, metric):
        return (3840, 2160)[metric]

    def SendInput(self, count, array, size):
        assert size == ctypes.sizeof(adapter.INPUT)
        for index in range(count):
            self.events.append(adapter.INPUT.from_buffer_copy(array[index]))
        return count if self.return_count is None else self.return_count


class WindowsDesktopTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeUser32()
        self.desktop = adapter.WindowsDesktop(_user32=self.api)

    def test_abi_matches_windows_64_or_32(self):
        is64 = ctypes.sizeof(ctypes.c_void_p) == 8
        self.assertEqual(ctypes.sizeof(adapter.INPUT), 40 if is64 else 28)
        self.assertEqual(ctypes.sizeof(adapter.MOUSEINPUT), 32 if is64 else 24)
        self.assertEqual(ctypes.sizeof(adapter.KEYBDINPUT), 24 if is64 else 16)
        self.assertEqual(adapter.INPUT.u.offset, 8 if is64 else 4)

    def test_construction_never_sends_input(self):
        self.assertEqual(self.api.events, [])
        self.assertEqual(self.desktop.size(), (3840, 2160))

    def test_protected_desktop_never_captures_or_sends_input(self):
        self.api.OpenInputDesktop = lambda *args: 0
        self.api.CloseDesktop = lambda handle: None
        self.api.GetUserObjectInformationW = lambda *args: True
        def forbidden_grab(**kwargs):self.fail('Protected desktop was captured')
        self.desktop._grab = forbidden_grab
        self.assertFalse(self.desktop.desktop_available())
        with self.assertRaises(OSError):self.desktop.capture()
        with self.assertRaises(OSError):self.desktop.handle({'type': 'move', 'x': .5, 'y': .5})
        self.assertEqual(self.api.events, [])

    def test_input_desktop_handles_are_closed_and_only_default_allowed(self):
        closed, desktop_name = [], ['Default']
        self.api.OpenInputDesktop = lambda *args: 123
        self.api.CloseDesktop = closed.append
        def info(handle, index, buffer, length, required):
            buffer.value = desktop_name[0]
            return True
        self.api.GetUserObjectInformationW = info
        self.assertTrue(self.desktop.desktop_available())
        desktop_name[0] = 'Winlogon'
        self.assertFalse(self.desktop.desktop_available())
        self.assertEqual(closed, [123, 123])

    def test_absolute_primary_screen_coordinates(self):
        self.desktop.handle({"type": "move", "x": 1, "y": 0.5})
        event = self.api.events[-1]
        self.assertEqual((event.mi.dx, event.mi.dy), (65535, 32768))
        self.assertEqual(event.mi.dwFlags, 0x8001)

    def test_optional_position_and_release_button(self):
        self.desktop.handle({"type": "button", "button": "right", "down": True, "x": 0, "y": 1})
        self.assertEqual(self.api.events[-1].mi.dwFlags, 0x0008)
        self.desktop.release_all()
        self.assertEqual(self.api.events[-1].mi.dwFlags, 0x0010)
        count = len(self.api.events)
        self.desktop.release_all()
        self.assertEqual(len(self.api.events), count)

    def test_wheel_signed_data(self):
        self.desktop.handle({"type": "scroll", "delta": -3})
        event = self.api.events[-1]
        self.assertEqual(event.mi.dwFlags, 0x0800)
        self.assertEqual(ctypes.c_int32(event.mi.mouseData).value, -360)

    def test_extended_key_and_repeat_then_release(self):
        self.desktop.handle({"type": "key", "key": "ControlRight", "down": True})
        self.desktop.handle({"type": "key", "key": "ControlRight", "down": True})
        self.assertEqual(len(self.api.events), 2)
        self.assertEqual(self.api.events[-1].ki.wVk, 0xA3)
        self.assertEqual(self.api.events[-1].ki.dwFlags, 1)
        self.desktop.release_all()
        self.assertEqual(self.api.events[-1].ki.dwFlags, 3)

    def test_keyup_prevents_extra_release(self):
        self.desktop.handle({"type": "key", "key": "KeyA", "down": True})
        self.desktop.handle({"type": "key", "key": "KeyA", "down": False})
        self.desktop.release_all()
        self.assertEqual(len(self.api.events), 2)

    def test_unicode_arabic_and_surrogate_pair(self):
        self.desktop.handle({"type": "text", "text": "ش😀"})
        self.assertEqual([event.ki.wScan for event in self.api.events], [0x634, 0x634, 0xD83D, 0xD83D, 0xDE00, 0xDE00])
        self.assertEqual([event.ki.dwFlags for event in self.api.events], [4, 6, 4, 6, 4, 6])
        self.assertTrue(all(event.ki.wVk == 0 for event in self.api.events))

    def test_failed_press_remains_releaseable(self):
        self.api.return_count = 0
        with self.assertRaisesRegex(RuntimeError, "UIPI"):
            self.desktop.handle({"type": "key", "key": "ShiftLeft", "down": True})
        self.api.return_count = None
        self.desktop.release_all()
        self.assertEqual(self.api.events[-1].ki.dwFlags, 2)
        self.assertEqual(self.api.events[-1].ki.wVk, 0xA0)

    def test_failed_release_retains_pending_state(self):
        self.desktop.handle({"type": "button", "button": "middle", "down": True})
        self.api.return_count = 0
        with self.assertRaises(RuntimeError):
            self.desktop.release_all()
        self.api.return_count = None
        self.desktop.release_all()
        self.assertEqual(self.api.events[-1].mi.dwFlags, 0x40)

    def test_capture_synthetic_image_only(self):
        from PIL import Image
        calls = []
        def fake_grab(**kwargs):
            calls.append(kwargs)
            return Image.new("RGB", (3840, 2160), (64, 100, 150))
        desktop = adapter.WindowsDesktop(_user32=FakeUser32(), _grab=fake_grab)
        data, width, height = desktop.capture()
        self.assertEqual((width, height), (1600, 900))
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertEqual(calls, [{"all_screens": False}])

    def test_invalid_messages_never_send(self):
        invalid = [
            None, [], {}, {"type": "unknown"},
            {"type": "move", "x": True, "y": 0},
            {"type": "move", "x": float("nan"), "y": 0},
            {"type": "move", "x": float("inf"), "y": 0},
            {"type": "move", "x": 10 ** 1000, "y": 0},
            {"type": "move", "x": -0.01, "y": 0},
            {"type": "move", "x": 1, "y": 1.01},
            {"type": "button", "button": [], "down": True},
            {"type": "button", "button": "left", "down": 1},
            {"type": "button", "button": "left", "down": True, "x": 0},
            {"type": "scroll", "delta": True},
            {"type": "scroll", "delta": 10.0},
            {"type": "scroll", "delta": 11},
            {"type": "key", "key": [], "down": True},
            {"type": "key", "key": "A", "down": True},
            {"type": "key", "key": "KeyA", "down": "true"},
            {"type": "text", "text": "a" * 501},
            {"type": "text", "text": "\ud800"},
        ]
        for message in invalid:
            with self.subTest(message=repr(message)[:100]):
                with self.assertRaises(ValueError):
                    self.desktop.handle(message)
        self.assertEqual(self.api.events, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
