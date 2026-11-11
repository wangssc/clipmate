"""剪贴板监听：一条后台线程，轮询剪贴板变更序号。

只要序号变了就读一次纯文本，交给回调。默认 120ms 一次，
从"复制"到"出现在列表里"通常在 200ms 以内。
"""

import logging
import threading
import time

from . import win32

log = logging.getLogger("clipmate")


class ClipboardWatcher(threading.Thread):
    def __init__(self, on_text, interval=0.12):
        super().__init__(name="clipwatch", daemon=True)
        self._on_text = on_text
        self._interval = interval
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._own = {}
        self._own_lock = threading.Lock()

    # ---------------------------------------------------------- 对外
    def wait_ready(self, timeout=2.0):
        """等到线程记住当前剪贴板序号，测试用，避免起跑线没对齐。"""
        return self._ready.wait(timeout)

    def note_own_copy(self, text):
        """程序自己刚往剪贴板写过的内容，不要再记进历史。"""
        with self._own_lock:
            self._own[text] = time.monotonic()

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------- 线程主体
    def run(self):
        last = win32.clipboard_sequence()
        self._ready.set()
        while not self._stop.wait(self._interval):
            try:
                seq = win32.clipboard_sequence()
                if not seq or seq == last:
                    continue
                last = seq
                text = win32.get_clipboard_text()
                if not text or not text.strip():
                    continue
                if self._is_own(text):
                    continue
                self._on_text(text)
            except Exception:
                log.exception("剪贴板监听出错")

    def _is_own(self, text):
        now = time.monotonic()
        with self._own_lock:
            stamp = self._own.pop(text, None)
        return stamp is not None and now - stamp < 1.5
