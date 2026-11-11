"""界面：一个窗口，主标签是「剪贴板历史」，第二个标签是「话术库」。

点任意一条 → 那段文字进剪贴板 → 自己去 Word 里按 Ctrl+V。
没有热键、没有托盘、不模拟按键、不往别的窗口里塞东西。
"""

import datetime
import logging
import os
import queue
import tkinter as tk
from tkinter import ttk

from . import clipboard, paths, win32
from .clipwatch import ClipboardWatcher
from .store import Store

log = logging.getLogger("clipmate")

BG = "#f3f4f6"
CARD = "#ffffff"
BORDER = "#e2e5e9"
TEXT = "#1f2937"
MUTED = "#6b7280"
FAINT = "#9ca3af"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
SEL = "#dbeafe"
OK = "#15803d"
WARN = "#b91c1c"
PIN_BG = "#fffdf3"

FONT = "Microsoft YaHei UI"


def _fmt_time(ts):
    dt = datetime.datetime.fromtimestamp(ts)
    now = datetime.datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if (now.date() - dt.date()).days == 1:
        return "昨天 " + dt.strftime("%H:%M")
    if dt.year == now.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def _preview(text, limit=120):
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = " ⏎ ".join(line.strip() for line in s.split("\n") if line.strip())
    if len(s) > limit:
        s = s[:limit] + "…"
    return s or "(空白)"


class Editor(tk.Toplevel):
    """新增 / 编辑话术的小窗，只在用户点按钮时出现。"""

    def __init__(self, app, snippet=None):
        super().__init__(app.root)
        self.app = app
        self.snippet = snippet
        self.title("编辑话术" if snippet else "新增话术")
        self.configure(bg=CARD)
        self.transient(app.root)
        self.resizable(True, True)

        w, h = app.px(540), app.px(400)
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - h) // 3
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, x), max(0, y)))
        self.minsize(app.px(420), app.px(300))

        pad = app.px(18)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=pad, pady=(pad, app.px(8)))

        tk.Label(body, text="名称", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")
        self.name_var = tk.StringVar(value=(snippet or {}).get("name", ""))
        self.name_entry = tk.Entry(
            body, textvariable=self.name_var, font=(FONT, 10), fg=TEXT,
            bg="#f7f8fa", relief="flat", insertbackground=TEXT,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.name_entry.pack(fill="x", ipady=app.px(5), pady=(app.px(5), app.px(12)))

        tk.Label(body, text="内容（点这一条时复制的就是下面这段）", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")

        wrap = tk.Frame(body, bg=CARD)
        wrap.pack(fill="both", expand=True, pady=(app.px(5), 0))
        self.text = tk.Text(
            wrap, wrap="word", font=(FONT, 10), fg=TEXT, bg="#f7f8fa",
            relief="flat", insertbackground=TEXT, undo=True,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT, padx=app.px(8), pady=app.px(8),
        )
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if snippet:
            self.text.insert("1.0", snippet.get("text", ""))

        foot = tk.Frame(self, bg=CARD)
        foot.pack(fill="x", padx=pad, pady=(app.px(6), pad))

        self.hint = tk.Label(foot, text="", bg=CARD, fg=WARN, font=(FONT, 9))
        self.hint.pack(side="left")

        ttk.Button(foot, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(foot, text="取消", style="Tool.TButton",
                   command=self.destroy).pack(side="right", padx=(0, app.px(8)))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self.save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.after(60, self._focus)

    def _focus(self):
        if self.snippet:
            self.text.focus_set()
        else:
            self.name_entry.focus_set()

    def save(self):
        text = self.text.get("1.0", "end-1c")
        if not text.strip():
            self.hint.configure(text="内容不能为空")
            return
        name = self.name_var.get().strip()
        if not name:
            name = text.strip().splitlines()[0][:24]
        if self.snippet:
            self.app.store.update_snippet(self.snippet["id"], name, text)
            sid = self.snippet["id"]
        else:
            sid = self.app.store.add_snippet(name, text)["id"]
        self.app.refresh_snippets(select=sid)
        self.destroy()


class App:
    def __init__(self, hidden=False):
        self.scale = win32.dpi_scale()
        self.store = Store()
        self.queue = queue.Queue()
        self._closed = False
        self._after_id = None
        self._flash_id = None
        self._armed = None
        self._last_query = ""

        self.root = tk.Tk()
        self.root.title("ClipMate")
        try:
            self.root.tk.call("tk", "scaling", self.scale * 96.0 / 72.0)
        except Exception:
            pass
        self.root.configure(bg=BG)
        self.root.minsize(self.px(720), self.px(460))
        self._center(self.px(1000), self.px(660))
        try:
            if os.path.exists(paths.ICON_FILE):
                self.root.iconbitmap(paths.ICON_FILE)
        except Exception:
            pass

        self._init_style()
        self._build()
        self.refresh_snippets()
        self.refresh_history()

        self.watcher = ClipboardWatcher(self.queue.put)
        self.watcher.start()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if hidden:
            self.root.withdraw()

    # ---------------------------------------------------------- 基础
    def px(self, value):
        return int(round(value * self.scale))

    def _center(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2),
                                           max(0, (sh - h) // 3)))

    def _init_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Tool.TButton", font=(FONT, 9), padding=(self.px(10), self.px(4)))
        style.configure(
            "Accent.TButton", font=(FONT, 9, "bold"), padding=(self.px(14), self.px(5)),
            background=ACCENT, foreground="#ffffff", borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", "#1e40af"), ("active", ACCENT_DARK)],
            foreground=[("disabled", "#dbeafe")],
        )
        style.configure(
            "Clip.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
            borderwidth=0, relief="flat", rowheight=self.px(34), font=(FONT, 10),
        )
        style.map(
            "Clip.Treeview",
            background=[("selected", SEL)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Clip.Treeview.Heading", background=CARD, foreground=FAINT,
            font=(FONT, 9), relief="flat", borderwidth=0,
            padding=(self.px(8), self.px(7)),
        )
        style.map("Clip.Treeview.Heading", background=[("active", CARD)])
        style.configure("Clip.Vertical.TScrollbar", background="#e5e7eb",
                        troughcolor=CARD, borderwidth=0, arrowsize=self.px(10))

    # ---------------------------------------------------------- 布局
    def _build(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        header = tk.Frame(self.root, bg=CARD)
        header.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(header, bg=CARD)
        inner.pack(fill="x", padx=self.px(20), pady=(self.px(12), self.px(10)))

        left = tk.Frame(inner, bg=CARD)
        left.pack(side="left")
        tk.Label(left, text="ClipMate", bg=CARD, fg=TEXT,
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(left, text="点一条 → 复制到剪贴板 → 回 Word 按 Ctrl+V（不自动粘贴）",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        self.hint = tk.Label(inner, text="", bg=CARD, fg=OK, font=(FONT, 9))
        self.hint.pack(side="right")

        tabbar = tk.Frame(self.root, bg=BG)
        tabbar.grid(row=1, column=0, sticky="ew", padx=self.px(20))
        self._tab_cols = {}
        for key, title in (("hist", "剪贴板历史"), ("snip", "话术库")):
            col = tk.Frame(tabbar, bg=BG)
            col.pack(side="left", padx=(0, self.px(6)))
            lbl = tk.Label(col, text=title, bg=BG, fg=MUTED, font=(FONT, 10),
                           padx=self.px(10), pady=self.px(6), cursor="hand2")
            lbl.pack()
            line = tk.Frame(col, bg=BG, height=max(2, self.px(2)))
            line.pack(fill="x")
            lbl.bind("<Button-1>", lambda e, k=key: self.show_tab(k))
            self._tab_cols[key] = (lbl, line)

        card = tk.Frame(self.root, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.grid(row=2, column=0, sticky="nsew",
                  padx=self.px(20), pady=(0, self.px(18)))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        self.hist_page = tk.Frame(card, bg=CARD)
        self.snip_page = tk.Frame(card, bg=CARD)
        for page in (self.hist_page, self.snip_page):
            page.grid(row=0, column=0, sticky="nsew")
        self._build_history_page(self.hist_page)
        self._build_snippets_page(self.snip_page)
        self.show_tab("hist")

        self.root.bind("<Control-f>", self._focus_search)

    def show_tab(self, name):
        self.tab = name
        for key, (lbl, line) in self._tab_cols.items():
            active = key == name
            lbl.configure(fg=ACCENT if active else MUTED,
                          font=(FONT, 10, "bold") if active else (FONT, 10))
            line.configure(bg=ACCENT if active else BG)
        (self.hist_page if name == "hist" else self.snip_page).tkraise()

    def _focus_search(self, event=None):
        self.show_tab("hist")
        self.hist_entry.focus_set()
        self.hist_entry.select_range(0, "end")
        return "break"

    # ---------------------------------------------------------- 剪贴板历史（主）
    def _build_history_page(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        bar = tk.Frame(page, bg=CARD)
        bar.grid(row=0, column=0, sticky="ew",
                 padx=self.px(14), pady=(self.px(10), self.px(6)))

        self.hist_count = tk.Label(bar, text="", bg=CARD, fg=FAINT, font=(FONT, 9))
        self.hist_count.pack(side="right")
        self.btn_clear = ttk.Button(bar, text="清空历史", style="Tool.TButton",
                                    command=self._clear_history)
        self.btn_clear.pack(side="right", padx=(0, self.px(10)))

        tk.Label(bar, text="搜索", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        self.hist_query = tk.StringVar()
        self.hist_entry = tk.Entry(
            bar, textvariable=self.hist_query, font=(FONT, 10), fg=TEXT,
            bg="#f7f8fa", relief="flat", insertbackground=TEXT,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.hist_entry.pack(side="left", fill="x", expand=True,
                             padx=(self.px(6), self.px(12)), ipady=self.px(4))
        self.hist_query.trace_add("write", lambda *a: self.refresh_history())
        self.hist_entry.bind("<Escape>", self._clear_search)

        wrap = tk.Frame(page, bg=CARD)
        wrap.grid(row=1, column=0, sticky="nsew", padx=self.px(10))

        tree = ttk.Treeview(wrap, show="headings", selectmode="browse",
                            style="Clip.Treeview")
        tree.configure(columns=("pin", "text", "time"))
        tree.heading("pin", text="")
        tree.heading("text", text="内容", anchor="w")
        tree.heading("time", text="时间", anchor="e")
        tree.column("pin", width=self.px(30), minwidth=self.px(24),
                    stretch=False, anchor="center")
        tree.column("text", width=self.px(560), minwidth=self.px(200),
                    stretch=True, anchor="w")
        tree.column("time", width=self.px(96), minwidth=self.px(70),
                    stretch=False, anchor="e")
        tree.tag_configure("pinned", background=PIN_BG)

        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview,
                           style="Clip.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.hist_tree = tree

        self.hist_empty = tk.Label(wrap, text="", bg=CARD, fg=FAINT,
                                   font=(FONT, 10), justify="center")

        tree.bind("<ButtonRelease-1>", self._on_hist_click)
        tree.bind("<Return>", lambda e: self._copy_selected_history())
        tree.bind("<<TreeviewSelect>>", lambda e: self._sync_buttons())

        foot = tk.Frame(page, bg=CARD)
        foot.grid(row=2, column=0, sticky="ew",
                  padx=self.px(14), pady=(self.px(8), self.px(10)))
        self.btn_pin = ttk.Button(foot, text="置顶", style="Tool.TButton",
                                  command=self._toggle_pin)
        self.btn_pin.pack(side="left")
        self.btn_hist_del = ttk.Button(foot, text="删除这条", style="Tool.TButton",
                                       command=self._delete_history)
        self.btn_hist_del.pack(side="left", padx=(self.px(8), 0))

        self.hist_hint = tk.Label(foot, text="", bg=CARD, fg=FAINT,
                                  font=(FONT, 9))
        self.hist_hint.pack(side="right")

    def _clear_search(self, event=None):
        self.hist_query.set("")
        return "break"

    # ---------------------------------------------------------- 话术库（次要）
    def _build_snippets_page(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        bar = tk.Frame(page, bg=CARD)
        bar.grid(row=0, column=0, sticky="ew",
                 padx=self.px(14), pady=(self.px(10), self.px(6)))
        tk.Label(bar, text="常用话术 · 点一条同样复制到剪贴板", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        self.snip_count = tk.Label(bar, text="", bg=CARD, fg=FAINT, font=(FONT, 9))
        self.snip_count.pack(side="right")

        wrap = tk.Frame(page, bg=CARD)
        wrap.grid(row=1, column=0, sticky="nsew", padx=self.px(10))

        tree = ttk.Treeview(wrap, show="headings", selectmode="browse",
                            style="Clip.Treeview")
        tree.configure(columns=("name", "text"))
        tree.heading("name", text="名称", anchor="w")
        tree.heading("text", text="内容", anchor="w")
        tree.column("name", width=self.px(170), minwidth=self.px(90),
                    stretch=False, anchor="w")
        tree.column("text", width=self.px(500), minwidth=self.px(150),
                    stretch=True, anchor="w")

        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview,
                           style="Clip.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.snip_tree = tree

        self.snip_empty = tk.Label(wrap, text="话术库还是空的，点左下角「新增」",
                                   bg=CARD, fg=FAINT, font=(FONT, 10))

        tree.bind("<ButtonRelease-1>", self._on_snip_click)
        tree.bind("<Return>", lambda e: self._copy_selected_snippet())
        tree.bind("<<TreeviewSelect>>", lambda e: self._sync_buttons())

        foot = tk.Frame(page, bg=CARD)
        foot.grid(row=2, column=0, sticky="ew",
                  padx=self.px(14), pady=(self.px(8), self.px(10)))
        ttk.Button(foot, text="新增", style="Accent.TButton",
                   command=self.new_snippet).pack(side="left")
        self.btn_edit = ttk.Button(foot, text="编辑", style="Tool.TButton",
                                   command=self.edit_snippet)
        self.btn_edit.pack(side="left", padx=(self.px(8), 0))
        self.btn_del = ttk.Button(foot, text="删除", style="Tool.TButton",
                                  command=self._delete_snippet)
        self.btn_del.pack(side="left", padx=(self.px(8), 0))

        self.btn_down = ttk.Button(foot, text="↓", width=3, style="Tool.TButton",
                                   command=lambda: self.move_snippet(1))
        self.btn_down.pack(side="right")
        self.btn_up = ttk.Button(foot, text="↑", width=3, style="Tool.TButton",
                                 command=lambda: self.move_snippet(-1))
        self.btn_up.pack(side="right", padx=(0, self.px(4)))

    # ---------------------------------------------------------- 列表刷新
    def refresh_snippets(self, select=None):
        tree = self.snip_tree
        keep = select
        if keep is None and tree.selection():
            keep = tree.selection()[0]
        y = tree.yview()[0]
        tree.delete(*tree.get_children())
        for s in self.store.snippets:
            tree.insert("", "end", iid=s["id"],
                        values=(s["name"], _preview(s["text"])))
        self.snip_count.configure(text="%d 条" % len(self.store.snippets))
        if keep and tree.exists(keep):
            tree.selection_set(keep)
            tree.see(keep)
        else:
            tree.yview_moveto(y)
        if self.store.snippets:
            self.snip_empty.place_forget()
        else:
            self.snip_empty.place(relx=0.5, rely=0.45, anchor="center")
        self._sync_buttons()

    def refresh_history(self):
        tree = self.hist_tree
        sel = tree.selection()
        query = self.hist_query.get().strip()
        y = 0.0 if query != self._last_query else tree.yview()[0]
        self._last_query = query

        items = self.store.ordered_history()
        if query:
            q = query.lower()
            items = [h for h in items if q in h["text"].lower()]

        tree.delete(*tree.get_children())
        for h in items:
            pinned = bool(h.get("pinned"))
            tree.insert("", "end", iid=h["id"],
                        values=("★" if pinned else "",
                                _preview(h["text"], 200),
                                _fmt_time(h["time"])),
                        tags=("pinned",) if pinned else ())

        total = len(self.store.history)
        if query:
            self.hist_count.configure(
                text="匹配 %d / 共 %d 条" % (len(items), total))
        else:
            self.hist_count.configure(text="%d 条" % total)

        if items:
            self.hist_empty.place_forget()
        else:
            self.hist_empty.configure(
                text=("没有匹配「%s」的内容" % query) if query else
                "还没有记录\n在 Word 里复制一段文字，它会自动出现在这里")
            self.hist_empty.place(relx=0.5, rely=0.45, anchor="center")

        alive = [i for i in sel if tree.exists(i)]
        if alive:
            tree.selection_set(alive)
        tree.yview_moveto(y)

        limit = int(self.store.config.get("max_history", 200))
        pinned = self.store.pinned_count()
        if pinned:
            self.hist_hint.configure(
                text="★ 置顶 %d 条（清空时保留） · 最多存 %d 条" % (pinned, limit))
        else:
            self.hist_hint.configure(text="最多存 %d 条" % limit)
        self._sync_buttons()

    def _sync_buttons(self):
        sid = self._sel(self.snip_tree)
        idx = None
        if sid:
            idx = next((i for i, s in enumerate(self.store.snippets)
                        if s["id"] == sid), None)
        state = "normal" if sid else "disabled"
        self.btn_edit.configure(state=state)
        self.btn_del.configure(state=state)
        self.btn_up.configure(
            state="normal" if idx not in (None, 0) else "disabled")
        self.btn_down.configure(
            state="normal" if idx is not None and idx < len(self.store.snippets) - 1
            else "disabled")

        hid = self._sel(self.hist_tree)
        self.btn_hist_del.configure(state="normal" if hid else "disabled")
        pinned = False
        if hid:
            item = next((h for h in self.store.history if h["id"] == hid), None)
            pinned = bool(item and item.get("pinned"))
        self.btn_pin.configure(state="normal" if hid else "disabled",
                               text="取消置顶" if pinned else "置顶")

    @staticmethod
    def _sel(tree):
        sel = tree.selection()
        return sel[0] if sel else None

    # ---------------------------------------------------------- 复制
    def copy(self, text):
        """点一条时走的就是这里：写剪贴板，然后什么都不做。"""
        if not text:
            return False
        ok = clipboard.clipboard_set(text)
        if ok:
            self.watcher.note_own_copy(text)
            self._flash("已复制到剪贴板 · 去 Word 里按 Ctrl+V")
        else:
            self._flash("复制失败：剪贴板正被别的程序占用", ok=False)
        return ok

    def _copy_selected_snippet(self):
        sid = self._sel(self.snip_tree)
        if sid:
            self.copy_item("snip", sid)

    def _copy_selected_history(self):
        hid = self._sel(self.hist_tree)
        if hid:
            self.copy_item("hist", hid)

    def copy_item(self, kind, iid):
        """点中某一条之后的全部动作：取原文 → 写剪贴板。"""
        if kind == "snip":
            item = self.store.get_snippet(iid)
        else:
            item = next((h for h in self.store.history if h["id"] == iid), None)
        if not item:
            return False
        return self.copy(item["text"])

    def _on_snip_click(self, event):
        if self.snip_tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        iid = self.snip_tree.identify_row(event.y)
        if not iid:
            return
        self.snip_tree.selection_set(iid)
        self.copy_item("snip", iid)

    def _on_hist_click(self, event):
        if self.hist_tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        iid = self.hist_tree.identify_row(event.y)
        if not iid:
            return
        self.hist_tree.selection_set(iid)
        self.copy_item("hist", iid)

    def _flash(self, text, ok=True):
        if self._flash_id is not None:
            try:
                self.root.after_cancel(self._flash_id)
            except Exception:
                pass
        self.hint.configure(text=text, fg=OK if ok else WARN)
        self._flash_id = self.root.after(1800, self._clear_flash)

    def _clear_flash(self):
        self._flash_id = None
        self.hint.configure(text="")

    # ---------------------------------------------------------- 话术库操作
    def new_snippet(self):
        Editor(self)

    def edit_snippet(self):
        sid = self._sel(self.snip_tree)
        item = self.store.get_snippet(sid) if sid else None
        if item:
            Editor(self, item)

    def _delete_snippet(self):
        sid = self._sel(self.snip_tree)
        if not sid:
            return

        def do():
            self.store.delete_snippet(sid)
            self.refresh_snippets()

        self._arm(self.btn_del, do, "确认删除？")

    def move_snippet(self, delta):
        sid = self._sel(self.snip_tree)
        if not sid:
            return
        if self.store.move_snippet(sid, delta):
            self.refresh_snippets(select=sid)

    # ---------------------------------------------------------- 历史操作
    def _toggle_pin(self):
        hid = self._sel(self.hist_tree)
        if not hid:
            return
        state = self.store.toggle_pin(hid)
        self.refresh_history()
        if state is None:
            return
        self._flash("已置顶，会一直排在最上面" if state else "已取消置顶")

    def _delete_history(self):
        hid = self._sel(self.hist_tree)
        if not hid:
            return

        def do():
            self.store.delete_history(hid)
            self.refresh_history()
            self._flash("已删除这条")

        self._arm(self.btn_hist_del, do, "确认删除？")

    def _clear_history(self):
        def do():
            removed = self.store.clear_history()
            kept = self.store.pinned_count()
            self.refresh_history()
            if removed == 0 and kept == 0:
                self._flash("历史已经是空的")
            elif kept:
                self._flash("已清空 %d 条，置顶的 %d 条保留" % (removed, kept))
            else:
                self._flash("已清空 %d 条历史" % removed)

        self._arm(self.btn_clear, do, "确认清空？")

    # ---------------------------------------------------------- 二次确认
    def _arm(self, btn, action, label):
        """同一个按钮点两次才执行，省掉一个弹窗。"""
        if self._armed and self._armed[0] is btn:
            self._disarm()
            action()
            return
        self._disarm()
        original = btn.cget("text")
        btn.configure(text=label)
        timer = self.root.after(2600, self._disarm)
        self._armed = (btn, original, timer)

    def _disarm(self):
        if not self._armed:
            return
        btn, original, timer = self._armed
        self._armed = None
        try:
            self.root.after_cancel(timer)
        except Exception:
            pass
        try:
            btn.configure(text=original)
        except Exception:
            pass

    # ---------------------------------------------------------- 运行 / 退出
    def run(self):
        self._after_id = self.root.after(100, self._drain)

        auto = os.environ.get("CLIPMATE_AUTOCLOSE_MS")
        if auto:
            try:
                self.root.after(max(200, int(auto)), self.close)
                log.info("自测模式：%s ms 后自动关窗", auto)
            except ValueError:
                log.warning("CLIPMATE_AUTOCLOSE_MS 不是数字：%r", auto)

        log.info("界面启动 scale=%.2f data=%s", self.scale, paths.DATA_DIR)
        try:
            self.root.mainloop()
        finally:
            self.close()

    def _drain(self):
        if self._closed:
            return
        changed = False
        while True:
            try:
                text = self.queue.get_nowait()
            except queue.Empty:
                break
            if self.store.add_history(text):
                changed = True
        if changed:
            self.refresh_history()
        self._after_id = self.root.after(100, self._drain)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.watcher.stop()
            self.watcher.join(1.0)
        except Exception:
            pass
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        try:
            self.store.save_config()
            self.store.save_history()
            self.store.save_snippets()
        except Exception:
            log.exception("退出保存失败")
        log.info("程序退出")
        try:
            self.root.destroy()
        except Exception:
            pass
