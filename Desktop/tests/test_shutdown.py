"""Exercise shutdown without a real window, input API, or process termination."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shutdown import WindowShutdown


class Root:
    def __init__(self): self.destroyed, self.callbacks = False, []
    def destroy(self): self.destroyed = True
    def after(self, delay, callback): self.callbacks.append(callback)


class Worker:
    def __init__(self, stuck=False): self.thread, self.stuck, self.alive, self.stops = self, stuck, True, 0
    def is_alive(self): return self.alive
    def stop(self):
        self.stops += 1
        if not self.stuck: self.alive = False


class ShutdownTests(unittest.TestCase):
    def test_closes_idle_window(self):
        root, releases = Root(), []
        WindowShutdown(root, [None], lambda: releases.append(True)).start()
        self.assertTrue(root.destroyed)
        self.assertEqual(releases, [True])

    def test_stops_both_workers_without_event_poll(self):
        root, host, downloads = Root(), Worker(), Worker()
        WindowShutdown(root, [host, downloads], lambda: None).start()
        self.assertTrue(root.destroyed)
        self.assertEqual((host.stops, downloads.stops), (1, 1))

    def test_stuck_capture_cannot_leave_hidden_process(self):
        root, worker, now, forced = Root(), Worker(stuck=True), [0], []
        WindowShutdown(root, [worker], lambda: None, clock=lambda: now[0], force_exit=forced.append).start()
        self.assertFalse(root.destroyed)
        now[0] = 6
        root.callbacks.pop()()
        self.assertTrue(root.destroyed)
        self.assertEqual(forced, [0])

    def test_input_release_failure_does_not_prevent_exit(self):
        root = Root()
        def release(): raise OSError('protected desktop')
        WindowShutdown(root, [], release).start()
        self.assertTrue(root.destroyed)
