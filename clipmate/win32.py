"""Win32 调用（只用 ctypes，不依赖 pywin32）。

这里只留三件事：剪贴板读写、DPI、窗口圆角。
不碰键盘、不碰鼠标、不碰别人的窗口。
"""

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # pragma: no cover - 老系统没有 shcore
    shcore = None

HANDLE = wt.HANDLE
HWND = wt.HWND
UINT = wt.UINT
DWORD = wt.DWORD

CF_TEXT = 1
CF_OEMTEXT = 7
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

PROCESS_PER_MONITOR_DPI_AWARE = 2
ERROR_ALREADY_EXISTS = 183


user32.OpenClipboard.argtypes = [HWND]
user32.CloseClipboard.argtypes = []
user32.EmptyClipboard.argtypes = []
user32.GetClipboardData.restype = HANDLE
user32.GetClipboardData.argtypes = [UINT]
user32.SetClipboardData.restype = HANDLE
user32.SetClipboardData.argtypes = [UINT, HANDLE]
user32.IsClipboardFormatAvailable.argtypes = [UINT]
user32.GetClipboardSequenceNumber.restype = DWORD
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetDpiForSystem.restype = UINT
user32.GetDpiForSystem.argtypes = []

kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [HANDLE]
kernel32.GlobalFree.argtypes = [HANDLE]
kernel32.CreateMutexW.restype = HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CloseHandle.argtypes = [HANDLE]

try:
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmSetWindowAttribute.argtypes = [HWND, DWORD, ctypes.c_void_p, DWORD]
except OSError:  # pragma: no cover
    dwmapi = None


# ---------------------------------------------------------------- DPI
def dpi_scale():
    """系统 DPI 缩放比例（96dpi = 1.0）。"""
    try:
        dpi = user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def enable_dpi_awareness():
    """让窗口在 125%/150% 缩放下保持清晰。"""
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def set_round_corners(hwnd):
    """Win11 圆角；老系统失败就算了。"""
    if dwmapi is None:
        return
    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        pass


# ---------------------------------------------------------------- 剪贴板
def _open_clipboard(retries=12, delay=0.03):
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def _read_hglobal(h):
    if not h:
        return None
    size = kernel32.GlobalSize(h)
    if not size:
        return None
    ptr = kernel32.GlobalLock(h)
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(h)


def get_clipboard_text():
    """读取剪贴板里的纯文本；没有文本返回 None。"""
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _open_clipboard():
        return None
    try:
        data = _read_hglobal(user32.GetClipboardData(CF_UNICODETEXT))
    finally:
        user32.CloseClipboard()
    if not data:
        return None
    try:
        return data.decode("utf-16-le", "replace").split("\x00", 1)[0]
    except Exception:
        return None


def set_clipboard_text(text):
    """只放 CF_UNICODETEXT —— 保证粘出去的是纯文本，逐字不变。"""
    if text is None:
        return False
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        raw = text.encode("utf-16-le") + b"\x00\x00"
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(ptr, raw, len(raw))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    finally:
        user32.CloseClipboard()


def clipboard_sequence():
    """剪贴板变更序号；内容一变这个数就变。"""
    try:
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0
