"""程序入口（被 app.pyw 调用）。"""

import ctypes
import logging
import os
import sys

_MUTEX = None


def _acquire_single_instance():
    """同一时间只开一个窗口，避免两个实例抢着写同一份 JSON。"""
    global _MUTEX
    from . import win32

    _MUTEX = win32.kernel32.CreateMutexW(
        None, False, "Local\\ClipMate.SingleInstance.B")
    if not _MUTEX:
        return True
    return ctypes.get_last_error() != win32.ERROR_ALREADY_EXISTS


def main():
    from . import paths, win32

    paths.setup_logging()
    log = logging.getLogger("clipmate")
    win32.enable_dpi_awareness()
    log.info("启动 ClipMate，pid=%s python=%s", os.getpid(), sys.executable)

    if not _acquire_single_instance():
        log.info("已经有一个 ClipMate 在运行，本次启动直接退出")
        return

    from .ui import App

    App().run()
