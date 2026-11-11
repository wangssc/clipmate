"""数据持久化：话术库 / 剪贴板历史 / 配置。

全部是程序目录 data 下的普通 JSON 文件（UTF-8、中文不转义），
方便备份，也方便自己打开看。
"""

import json
import os
import threading
import time
import uuid

from . import paths

DEFAULT_CONFIG = {
    "max_history": 200,
    "max_item_chars": 20000,
}

DEFAULT_SNIPPETS = [
    {"name": "方案未涉及", "text": "方案未涉及"},
    {"name": "符合", "text": "符合"},
    {"name": "部分符合", "text": "部分符合"},
    {"name": "不符合", "text": "不符合"},
    {"name": "重要程度：重要", "text": "重要程度：重要"},
    {"name": "重要程度：一般", "text": "重要程度：一般"},
]


def _load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except Exception:
        # 文件坏了不要连累程序启动，先留个备份
        try:
            os.replace(path, path + ".broken")
        except Exception:
            pass
        return fallback


def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _now():
    return time.time()


class Store:
    def __init__(self):
        paths.ensure_dirs()
        self._lock = threading.RLock()
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(_load_json(paths.CONFIG_FILE, {}) or {})

        raw = _load_json(paths.SNIPPETS_FILE, None)
        if raw is None:
            # 首次启动：没有数据文件也要能用，先铺一批默认话术
            self.snippets = [
                self._new_snippet(s["name"], s["text"]) for s in DEFAULT_SNIPPETS
            ]
            self.save_snippets()
        else:
            self.snippets = [s for s in raw.get("items", []) if s.get("text")]

        raw = _load_json(paths.HISTORY_FILE, None)
        self.history = [h for h in (raw or {}).get("items", []) if h.get("text")]
        self._seq = int((raw or {}).get("seq", len(self.history)))

    # ------------------------------------------------------------ 话术库
    @staticmethod
    def _new_snippet(name, text):
        return {
            "id": uuid.uuid4().hex[:12],
            "name": (name or "").strip() or "未命名",
            "text": text,
            "created": _now(),
        }

    def get_snippet(self, sid):
        for item in self.snippets:
            if item["id"] == sid:
                return item
        return None

    def add_snippet(self, name, text):
        with self._lock:
            item = self._new_snippet(name, text)
            self.snippets.append(item)
            self.save_snippets()
            return item

    def update_snippet(self, sid, name, text):
        with self._lock:
            item = self.get_snippet(sid)
            if item is None:
                return None
            item["name"] = (name or "").strip() or "未命名"
            item["text"] = text
            self.save_snippets()
            return item

    def delete_snippet(self, sid):
        with self._lock:
            before = len(self.snippets)
            self.snippets = [s for s in self.snippets if s["id"] != sid]
            if len(self.snippets) != before:
                self.save_snippets()
                return True
        return False

    def move_snippet(self, sid, delta):
        """delta = -1 上移，+1 下移。"""
        with self._lock:
            idx = next(
                (i for i, s in enumerate(self.snippets) if s["id"] == sid), None
            )
            if idx is None:
                return False
            new = idx + delta
            if not 0 <= new < len(self.snippets):
                return False
            self.snippets[idx], self.snippets[new] = (
                self.snippets[new],
                self.snippets[idx],
            )
            self.save_snippets()
            return True

    def save_snippets(self):
        with self._lock:
            _atomic_write_json(
                paths.SNIPPETS_FILE, {"version": 1, "items": self.snippets}
            )

    # ------------------------------------------------------------ 历史
    def add_history(self, text):
        """新内容进历史：提到最前、去重、超上限淘汰最老的。

        返回 True 表示历史发生了变化（新增或旧条目被提到最上面）。
        """
        if not text or not text.strip():
            return False
        limit = int(self.config.get("max_item_chars", 20000))
        if len(text) > limit:
            text = text[:limit]
        with self._lock:
            for item in self.history:
                if item["text"] == text:
                    # 同样的内容再复制一次：只留一条，并提到最上面
                    item["time"] = _now()
                    item["seq"] = self._next_seq()
                    self.save_history()
                    return True
            self.history.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "text": text,
                    "time": _now(),
                    "seq": self._next_seq(),
                }
            )
            self._trim()
            self.save_history()
            return True

    def _next_seq(self):
        self._seq += 1
        return self._seq

    def _trim(self):
        limit = max(1, int(self.config.get("max_history", 200)))
        if len(self.history) <= limit:
            return
        # 置顶的永远不淘汰；其余按时间从老到新丢，直到回到上限
        pinned = [h for h in self.history if h.get("pinned")]
        rest = [h for h in self.history if not h.get("pinned")]
        rest.sort(key=lambda h: (h.get("time", 0), h.get("seq", 0)))
        room = limit - len(pinned)
        self.history = pinned + (rest[-room:] if room > 0 else [])

    def ordered_history(self):
        """置顶的排在最上面，其余最新在最上面；时间戳相同时用 seq 兜底。"""
        def key(h):
            if h.get("pinned"):
                return (1, h.get("pin_time", 0), h.get("time", 0), h.get("seq", 0))
            return (0, 0, h.get("time", 0), h.get("seq", 0))

        with self._lock:
            return sorted(self.history, key=key, reverse=True)

    def toggle_pin(self, hid):
        """置顶 / 取消置顶。返回置顶后的状态；找不到返回 None。"""
        with self._lock:
            item = next((h for h in self.history if h["id"] == hid), None)
            if item is None:
                return None
            item["pinned"] = not item.get("pinned")
            item["pin_time"] = _now() if item["pinned"] else 0
            self.save_history()
            return item["pinned"]

    def pinned_count(self):
        with self._lock:
            return sum(1 for h in self.history if h.get("pinned"))

    def delete_history(self, hid):
        with self._lock:
            before = len(self.history)
            self.history = [h for h in self.history if h["id"] != hid]
            if len(self.history) != before:
                self.save_history()
                return True
        return False

    def clear_history(self, keep_pinned=True):
        """清空历史。置顶的默认保留，返回删掉的条数。"""
        with self._lock:
            before = len(self.history)
            if keep_pinned:
                self.history = [h for h in self.history if h.get("pinned")]
            else:
                self.history = []
            removed = before - len(self.history)
            if removed:
                self.save_history()
            return removed

    def save_history(self):
        with self._lock:
            _atomic_write_json(
                paths.HISTORY_FILE,
                {"version": 1, "seq": self._seq, "items": self.history},
            )

    # ------------------------------------------------------------ 配置
    def save_config(self):
        with self._lock:
            _atomic_write_json(paths.CONFIG_FILE, self.config)
