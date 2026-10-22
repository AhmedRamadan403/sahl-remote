"""Bounded shutdown independent of the window's network-event polling callback."""
import contextlib
import os
import time


class WindowShutdown:
    def __init__(self, root, workers, release, *, timeout=5, clock=time.monotonic, force_exit=os._exit):
        self.root, self.workers, self.release = root, [w for w in workers if w], release
        self.clock, self.force_exit = clock, force_exit
        self.deadline = clock() + timeout

    def start(self):
        for worker in self.workers:
            with contextlib.suppress(Exception):
                worker.stop()
        self.finish()

    def finish(self):
        alive = any(worker.thread.is_alive() for worker in self.workers)
        if not alive or self.clock() >= self.deadline:
            with contextlib.suppress(Exception):
                self.release()
            with contextlib.suppress(Exception):
                self.root.destroy()
            if alive:
                # An unresponsive screen-capture thread must not leave a hidden host running.
                self.force_exit(0)
        else:
            self.root.after(50, self.finish)
