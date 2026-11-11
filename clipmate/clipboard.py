"""剪贴板读写（纯文本）。

对外只有两个函数：clipboard_get() / clipboard_set()。
界面上"点一条"调用的就是 clipboard_set()。
"""

from . import win32


def clipboard_get():
    """读回剪贴板里的纯文本；没有则返回 None。"""
    return win32.get_clipboard_text()


def clipboard_set(text):
    """把 text 原样写进剪贴板（只写纯文本）。"""
    return win32.set_clipboard_text(text)


def clipboard_sequence():
    return win32.clipboard_sequence()
