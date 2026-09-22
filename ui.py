"""
ui.py — Tkinter interface.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import queue
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk

from config import (
    C_BG, C_FG, C_FG_DIM, C_RED, C_RED_DIM, C_RED_SEL, C_RED_HOVER,
    F_TITLE, F_SUB, F_NORM, F_SMALL, F_BTN, F_HEAD, F_LOG, F_ROW, F_ROW_S,
    APP_NAME, APP_VERSION, CONFIG_FILE, LOG_FILE,
    DEFAULT_LANG, STRINGS,
    FILTER_DEBOUNCE_MS, PARALLEL_WORKERS, WATCH_POLL_SECONDS,
)
from core import (
    HAS_PYZIPPER, HAS_SOURCEPP, extractor_name, human_size, is_gmod_running,
    copy_tree, app_dir, open_folder, safe_name,
    GMAExtractor, GMAWriter, Analyzer,
    ZipIndex, Source,
    CacheManager, SessionManager, CollectionsManager, WhitelistManager,
    read_gma_metadata_file, resolve_gma_metadata_in_zip,
    resolve_folder_metadata, resolve_folder_metadata_in_zip,
    extract_workshop_id, download_workshop_gma,
    order_sources_by_deps, check_missing_deps, find_duplicates,
)


def make_panel(parent, title=None):
    outer = tk.Frame(parent, bg=C_RED, bd=0)
    outer.pack(fill="x", pady=(0, 8))
    inner = tk.Frame(outer, bg=C_BG)
    inner.pack(fill="x", padx=1, pady=1)
    if title:
        head = tk.Label(inner, text=title, bg=C_BG, fg=C_FG,
                        font=F_HEAD, anchor="w", padx=8, pady=4)
        head.pack(fill="x")
        tk.Frame(inner, bg=C_RED, height=1).pack(fill="x")
    body = tk.Frame(inner, bg=C_BG, padx=6, pady=6)
    body.pack(fill="both", expand=True)
    return body


def make_button(parent, text, command, style="normal"):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=C_BG, fg=C_FG,
        activebackground=C_RED, activeforeground=C_FG,
        relief="flat", bd=0, font=F_BTN,
        highlightbackground=C_RED, highlightcolor=C_RED,
        highlightthickness=1, padx=10, pady=6,
        cursor="hand2",
    )
    if style == "primary":
        btn.config(bg=C_RED, fg=C_FG, activebackground=C_RED_HOVER)
    return btn


def make_entry(parent, textvariable=None, **kw):
    return tk.Entry(
        parent, textvariable=textvariable,
        bg=C_BG, fg=C_FG, insertbackground=C_RED,
        relief="flat", bd=0, font=F_NORM,
        highlightbackground=C_RED, highlightcolor=C_RED,
        highlightthickness=1, **kw)


def make_scrollbar(parent, orient, command):
    return tk.Scrollbar(
        parent, orient=orient, command=command,
        bg=C_RED, troughcolor=C_BG,
        activebackground=C_RED_HOVER,
        highlightbackground=C_BG, highlightcolor=C_BG,
        bd=0, relief="flat", width=14,
        elementborderwidth=0, takefocus=0)


def bring_to_front(win):
    try:
        win.lift()
        win.attributes("-topmost", True)
        win.after(200, lambda: win.attributes("-topmost", False))
        win.focus_force()
    except Exception:
        pass


class GModAddonManager:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("560x960")
        self.root.resizable(False, False)
        self.root.configure(bg=C_BG)

        self.sources = []
        self.busy = False
        self.cancel_flag = threading.Event()
        self.last_results = None
        self.filter_text = tk.StringVar()
        self.group_mode = tk.BooleanVar(value=False)

        self._row_refs = {}
        self._row_frames = []
        self._click_timer = None
        self._pending_click_sid = None
        self._filter_timer = None
        self._rebuilding = False

        self.status = tk.StringVar(value="Ready.")
        self.lang = DEFAULT_LANG
        self.recent_paths = []
        self.whitelist = []
        self._watch_thread = None
        self._watch_stop = threading.Event()
        self._watch_seen = set()

        self.extractor = GMAExtractor()
        self.analyzer = Analyzer()
        self.cache = CacheManager()
        self.session = SessionManager()
        self.collections = CollectionsManager()
        self.whitelist_mgr = WhitelistManager()

        self.log_q = queue.Queue()
        self.name_q = queue.Queue()
        self._name_worker_running = True

        self._load_cfg()
        self.whitelist = self.whitelist_mgr.load()
        self._build()
        self._poll_log()
        self._start_name_worker()
        self._load_session()
        self._auto_detect_dest()

        self._log(f"[i] Extractor: {extractor_name()}")
        self._log(f"[i] pyzipper: {'yes' if HAS_PYZIPPER else 'no'}")
        self._log(f"[i] sourcepp: {'yes' if HAS_SOURCEPP else 'no'}")
        self._log(f"[i] language: {self.lang}")

    # ----- i18n -----
    def t(self, key, **fmt):
        d = STRINGS.get(self.lang, STRINGS[DEFAULT_LANG])
        s = d.get(key, STRINGS[DEFAULT_LANG].get(key, key))
        if fmt:
            try:
                s = s.format(**fmt)
            except Exception:
                pass
        return s

    def _toggle_lang(self):
        self.lang = "es" if self.lang == "en" else "en"
        self._save_cfg()
        self._rebuild_ui()
        self._log(f"[i] language: {self.lang}")

    def _rebuild_ui(self):
        self._rebuilding = True
        try:
            log_text = ""
            try:
                log_text = self.log.get("1.0", "end-1c")
            except Exception:
                pass
            for w in self.root.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            self._row_refs.clear()
            self._row_frames.clear()
            self._build()
            if log_text:
                try:
                    self.log.config(state="normal")
                    self.log.insert("1.0", log_text)
                    self.log.config(state="disabled")
                except Exception:
                    pass
            self._rebuild_list()
            self.status.set(self.t("ready"))
        finally:
            self._rebuilding = False

    # ----- Build -----
    def _build(self):
        top = tk.Frame(self.root, bg=C_BG)
        top.pack(fill="x", side="top")
        title_bar = tk.Frame(top, bg=C_RED)
        title_bar.pack(fill="x")
        title_inner = tk.Frame(title_bar, bg=C_BG)
        title_inner.pack(fill="x", padx=1, pady=1)
        tk.Label(title_inner, text=APP_NAME, bg=C_BG, fg=C_FG,
                 font=F_TITLE, pady=8).pack()
        meta_row = tk.Frame(title_inner, bg=C_BG)
        meta_row.pack(fill="x", pady=(0, 6))
        tk.Label(meta_row, text=f"v{APP_VERSION}", bg=C_BG, fg=C_FG_DIM,
                 font=F_SUB).pack(side="left", padx=(8, 0))
        tk.Button(meta_row, text=self.t("lang_button"),
                  command=self._toggle_lang,
                  bg=C_BG, fg=C_RED,
                  activebackground=C_RED, activeforeground=C_FG,
                  relief="flat", bd=0, font=F_SMALL,
                  highlightbackground=C_RED, highlightcolor=C_RED,
                  highlightthickness=1, padx=8, pady=1,
                  cursor="hand2").pack(side="right", padx=(0, 8))

        outer = tk.Frame(self.root, bg=C_BG)
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, bg=C_BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        vscroll = make_scrollbar(outer, "vertical", self.canvas.yview)
        vscroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.body = tk.Frame(self.canvas, bg=C_BG, padx=8, pady=8)
        self._cw = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(
                           scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._cw, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_wheel_linux)

        # Add
        body = make_panel(self.body, self.t("add_panel"))
        self.path_entry = make_entry(body)
        self.path_entry.pack(fill="x", pady=(0, 6))
        self.path_entry.bind("<Return>", lambda e: self._add_manual())
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        make_button(row, self.t("add_btn"), self._add_manual).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, self.t("files_btn"), self._browse).pack(
            side="left", expand=True, fill="x", padx=2)
        make_button(row, self.t("folder_btn"), self._browse_folder).pack(
            side="left", expand=True, fill="x", padx=(2, 0))
        row2 = tk.Frame(body, bg=C_BG)
        row2.pack(fill="x", pady=(4, 0))
        make_button(row2, self.t("from_url_btn"), self._add_from_url).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row2, self.t("history_btn"), self._show_history).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        # Filter
        body = make_panel(self.body, self.t("filter_panel"))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        tk.Label(row, text=self.t("search_label"), bg=C_BG, fg=C_FG,
                 font=F_NORM).pack(side="left")
        ent = make_entry(row, textvariable=self.filter_text)
        ent.pack(side="left", fill="x", expand=True, padx=(4, 4))
        make_button(row, "X", lambda: self.filter_text.set("")).pack(side="left")
        self.filter_text.trace_add("write", lambda *_: self._on_filter_change())
        tk.Checkbutton(body, text=self.t("group_dep"),
                        variable=self.group_mode, command=self._rebuild_list,
                        bg=C_BG, fg=C_FG, activebackground=C_BG,
                        activeforeground=C_FG, selectcolor=C_BG,
                        font=F_NORM, highlightthickness=0, bd=0
                        ).pack(anchor="w", pady=(6, 0))

        # Addons list
        list_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        list_panel.pack(fill="both", expand=True, pady=(0, 8))
        list_inner = tk.Frame(list_panel, bg=C_BG)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(list_inner, text=self.t("addons_panel"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, anchor="w", padx=8, pady=4).pack(fill="x")
        tk.Frame(list_inner, bg=C_RED, height=1).pack(fill="x")

        rows_wrap = tk.Frame(list_inner, bg=C_BG)
        rows_wrap.pack(fill="both", expand=True)
        self.rows_canvas = tk.Canvas(rows_wrap, bg=C_BG,
                                       highlightthickness=0, height=200)
        self.rows_canvas.pack(side="left", fill="both", expand=True)
        rows_sb = make_scrollbar(rows_wrap, "vertical", self.rows_canvas.yview)
        rows_sb.pack(side="right", fill="y")
        self.rows_canvas.configure(yscrollcommand=rows_sb.set)
        self.rows_frame = tk.Frame(self.rows_canvas, bg=C_BG)
        self._rows_cw = self.rows_canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>",
                             lambda e: self.rows_canvas.configure(
                                 scrollregion=self.rows_canvas.bbox("all")))
        self.rows_canvas.bind("<Configure>",
                              lambda e: self.rows_canvas.itemconfig(
                                  self._rows_cw, width=e.width))
        self.rows_canvas.bind("<MouseWheel>",
            lambda e: self.rows_canvas.yview_scroll(int(-e.delta/120), "units"))
        self.rows_canvas.bind("<Button-4>",
            lambda e: self.rows_canvas.yview_scroll(-1, "units"))
        self.rows_canvas.bind("<Button-5>",
            lambda e: self.rows_canvas.yview_scroll(1, "units"))

        lb1 = tk.Frame(list_inner, bg=C_BG)
        lb1.pack(fill="x", padx=4, pady=(6, 2))
        make_button(lb1, self.t("all_btn"),
                    lambda: self._set_all_selected(True)
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb1, self.t("none_btn"),
                    lambda: self._set_all_selected(False)
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb1, self.t("invert_btn"), self._invert_selection
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))
        lb2 = tk.Frame(list_inner, bg=C_BG)
        lb2.pack(fill="x", padx=4, pady=(0, 6))
        make_button(lb2, self.t("remove_btn"), self._remove_selected
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb2, self.t("clear_btn"), self._clear
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb2, self.t("export_btn"), self._export_menu
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # Destination
        body = make_panel(self.body, self.t("dest_panel"))
        self.dest_entry = make_entry(body)
        self.dest_entry.pack(fill="x", pady=(0, 6))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        make_button(row, self.t("choose_btn"), self._browse_dest
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, self.t("open_btn"), self._open_dest
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(row, self.t("backup_btn"), self._backup_dest
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # Actions
        act = tk.Frame(self.body, bg=C_BG)
        act.pack(fill="x", pady=(0, 4))
        self.btn_analyze = tk.Button(
            act, text=self.t("analyze_btn"), command=self._analyze,
            bg=C_RED, fg=C_FG, activebackground=C_RED_HOVER,
            activeforeground=C_FG, relief="flat", bd=0, font=F_BTN,
            padx=10, pady=12, highlightbackground=C_RED,
            highlightthickness=1, cursor="hand2")
        self.btn_analyze.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.btn_extract = tk.Button(
            act, text=self.t("extract_btn"), command=self._extract,
            bg=C_BG, fg=C_FG, activebackground=C_RED, activeforeground=C_FG,
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightcolor=C_RED,
            highlightthickness=1, cursor="hand2")
        self.btn_extract.pack(side="left", expand=True, fill="x", padx=(2, 0))

        act2 = tk.Frame(self.body, bg=C_BG)
        act2.pack(fill="x", pady=(0, 8))
        make_button(act2, self.t("summary_btn"), self._show_last_summary
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(act2, self.t("conflicts_btn"), self._detect_conflicts
                    ).pack(side="left", expand=True, fill="x", padx=2)
        self.btn_cancel = make_button(act2, self.t("cancel_btn"), self._cancel)
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(side="left", expand=True, fill="x", padx=(2, 0))

        # Tools
        body = make_panel(self.body, self.t("tools_panel"))
        r1 = tk.Frame(body, bg=C_BG); r1.pack(fill="x")
        make_button(r1, self.t("repack_btn"), self._repack
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(r1, self.t("grep_btn"), self._grep
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(r1, self.t("rename_all_btn"), self._rename_all
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))
        r2 = tk.Frame(body, bg=C_BG); r2.pack(fill="x", pady=(4, 0))
        make_button(r2, self.t("watch_btn"), self._toggle_watch
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(r2, self.t("collections_btn"), self._open_collections
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(r2, self.t("whitelist_btn"), self._open_whitelist
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))
        r3 = tk.Frame(body, bg=C_BG); r3.pack(fill="x", pady=(4, 0))
        make_button(r3, self.t("report_btn"), self._export_html
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(r3, self.t("sizes_btn"), self._show_sizes
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(r3, self.t("fastdl_btn"), self._fastdl
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # Progress
        prog_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        prog_panel.pack(fill="x", pady=(0, 4))
        prog_inner = tk.Frame(prog_panel, bg=C_BG)
        prog_inner.pack(fill="x", padx=1, pady=1)
        self.progress = tk.Canvas(prog_inner, bg=C_BG, height=14,
                                    highlightthickness=0)
        self.progress.pack(fill="x", padx=4, pady=4)
        self._progress_max = 100
        self._progress_val = 0
        self.progress_label = tk.Label(self.body, text=self.t("ready"),
                                         bg=C_BG, fg=C_FG_DIM,
                                         font=F_SMALL, anchor="w")
        self.progress_label.pack(fill="x", pady=(0, 8))

        # Log
        log_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        log_panel.pack(fill="both", expand=True, pady=(0, 0))
        log_inner = tk.Frame(log_panel, bg=C_BG)
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(log_inner, bg=C_BG)
        head.pack(fill="x")
        tk.Label(head, text=self.t("log_panel"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, anchor="w", padx=8, pady=4).pack(side="left")
        make_button(head, self.t("log_open_btn"), self._open_log_file
                    ).pack(side="right", padx=(0, 4))
        make_button(head, self.t("log_clear_btn"), self._clear_log
                    ).pack(side="right", padx=(0, 4))
        make_button(head, self.t("copy_btn"), self._copy_log
                    ).pack(side="right", padx=(0, 4))
        tk.Frame(log_inner, bg=C_RED, height=1).pack(fill="x")
        log_wrap = tk.Frame(log_inner, bg=C_BG)
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(log_wrap, height=12, wrap="word",
                            font=F_LOG, bg=C_BG, fg=C_FG,
                            insertbackground=C_RED, relief="flat",
                            padx=6, pady=4, bd=0,
                            highlightbackground=C_RED, highlightthickness=1)
        self.log.pack(side="left", fill="both", expand=True)
        lsb = make_scrollbar(log_wrap, "vertical", self.log.yview)
        lsb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=lsb.set, state="disabled")

        status = tk.Label(self.root, textvariable=self.status,
                           bg=C_RED, fg=C_FG, font=F_SMALL,
                           anchor="w", padx=8, pady=3)
        status.pack(side="bottom", fill="x")

    # ----- Scroll -----
    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # ----- Log -----
    def _log(self, msg):
        self.log_q.put(str(msg))

    def _poll_log(self):
        if self._rebuilding:
            self.root.after(120, self._poll_log)
            return
        try:
            while True:
                msg = self.log_q.get_nowait()
                try:
                    self.log.config(state="normal")
                    self.log.insert("end", msg + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)

    def _copy_log(self):
        text = self.log.get("1.0", "end-1c")
        if not text.strip():
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self._log("[OK] Log copied.")
        except Exception as e:
            self._log(f"[!] Copy failed: {e}")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _open_log_file(self):
        p = app_dir() / LOG_FILE
        if p.exists():
            open_folder(p.parent)
        else:
            messagebox.showinfo(self.t("no_log_title"), self.t("no_log_body"),
                                 parent=self.root)

    # ----- Progress -----
    def _set_progress(self, value, maximum=100, text=""):
        def upd():
            self._progress_max = max(1, maximum)
            self._progress_val = value
            self._draw_progress()
            if text:
                self.progress_label.config(text=text)
                self.status.set(text)
            else:
                pct = int(100 * value / max(1, maximum))
                label = f"{value}/{maximum} ({pct}%)"
                self.progress_label.config(text=label)
                self.status.set(label)
        self.root.after(0, upd)

    def _draw_progress(self):
        self.progress.delete("all")
        w = self.progress.winfo_width() or 300
        pct = max(0.0, min(1.0, self._progress_val / self._progress_max))
        self.progress.create_rectangle(0, 0, w, 14, fill=C_BG, outline=C_RED)
        if pct > 0:
            self.progress.create_rectangle(1, 1, w * pct, 13,
                                             fill=C_RED, outline="")

    def _reset_progress(self, final_text=None):
        if final_text is None:
            final_text = self.t("ready")
        def upd():
            self._progress_val = 0
            self._draw_progress()
            self.progress_label.config(text=final_text)
            self.status.set(final_text)
        self.root.after(0, upd)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    # ----- Config -----
    def _cfg_file(self):
        return app_dir() / CONFIG_FILE

    def _load_cfg(self):
        try:
            with open(self._cfg_file(), encoding="utf-8") as f:
                data = json.load(f)
            self._pending_dest = data.get("dest", "")
            lang = data.get("lang", DEFAULT_LANG)
            self.lang = lang if lang in STRINGS else DEFAULT_LANG
            self.recent_paths = data.get("recent", [])[:10]
        except Exception:
            self._pending_dest = ""
            self.lang = DEFAULT_LANG
            self.recent_paths = []

    def _apply_pending_dest(self):
        if getattr(self, "_pending_dest", ""):
            try:
                self.dest_entry.insert(0, self._pending_dest)
            except Exception:
                pass

    def _save_cfg(self):
        try:
            dest = ""
            try:
                dest = self.dest_entry.get()
            except Exception:
                pass
            with open(self._cfg_file(), "w", encoding="utf-8") as f:
                json.dump({"dest": dest, "lang": self.lang,
                            "recent": self.recent_paths[:10]}, f, indent=2)
        except Exception:
            pass

    def _push_recent(self, path):
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self.recent_paths.insert(0, path)
        self.recent_paths = self.recent_paths[:10]

    def _auto_detect_dest(self):
        self._apply_pending_dest()
        try:
            if self.dest_entry.get().strip():
                return
        except Exception:
            return
        for c in [app_dir() / "addons", app_dir() / "extracted_addons"]:
            try:
                if c.exists() and c.is_dir():
                    self.dest_entry.insert(0, str(c))
                    return
            except Exception:
                pass

    def _open_dest(self):
        d = self.dest_entry.get().strip()
        if not d:
            messagebox.showinfo(self.t("no_dest_title"),
                                 self.t("no_dest_body"), parent=self.root)
            return
        p = Path(d)
        if not p.exists():
            messagebox.showwarning(self.t("dest_missing_title"), f"{p}",
                                    parent=self.root)
            return
        open_folder(p)

    # ----- Session -----
    def _load_session(self):
        sources = self.session.load()
        for s in sources:
            self.sources.append(s)
            if s.kind in ("zip_gma", "zip_folder"):
                self.name_q.put(s)
            elif s.kind == "gma":
                s.metadata = read_gma_metadata_file(s.path)
            elif s.kind == "folder":
                s.metadata = resolve_folder_metadata(s.path)
        if sources:
            self._rebuild_list()
            self._log(f"[i] Session restored: {len(sources)} addon(s).")
            self._set_status(self.t("status_session", n=len(sources)))

    # ----- Add -----
    def _browse(self):
        try:
            files = filedialog.askopenfilenames(
                title="Select .gma or .zip",
                filetypes=[("Addons", "*.gma *.zip"), ("All", "*.*")])
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        for f in files:
            self._register(Path(f))
            self._push_recent(f)
        self._rebuild_list()

    def _browse_folder(self):
        try:
            d = filedialog.askdirectory(title="Select folder")
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        if d:
            self._register(Path(d))
            self._push_recent(d)
            self._rebuild_list()

    def _browse_dest(self):
        try:
            d = filedialog.askdirectory(title="Destination folder")
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        if d:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, d)

    def _add_manual(self):
        raw = self.path_entry.get().strip().strip('"').strip("'")
        if not raw:
            return
        p = Path(raw)
        if not p.exists():
            messagebox.showerror(self.t("not_found_title"),
                                  self.t("not_found_body", path=raw),
                                  parent=self.root)
            return
        self._register(p)
        self._push_recent(raw)
        self.path_entry.delete(0, "end")
        self._rebuild_list()

    def _show_history(self):
        if not self.recent_paths:
            messagebox.showinfo(self.t("history_btn"), "Empty.", parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title(self.t("history_btn"))
        win.geometry("500x400")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        frame = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(frame, font=F_NORM, bg=C_BG, fg=C_FG,
                              selectmode=tk.SINGLE, highlightthickness=1,
                              highlightbackground=C_RED,
                              selectbackground=C_RED,
                              selectforeground=C_FG, bd=0)
        listbox.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(frame, "vertical", listbox.yview)
        sb.pack(side="right", fill="y")
        listbox.config(yscrollcommand=sb.set)
        for p in self.recent_paths:
            listbox.insert("end", p)
        def use_selected():
            sel = listbox.curselection()
            if not sel:
                return
            val = listbox.get(sel[0])
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, val)
            win.destroy()
        def add_selected():
            sel = listbox.curselection()
            if not sel:
                return
            val = listbox.get(sel[0])
            p = Path(val)
            if p.exists():
                self._register(p)
                self._rebuild_list()
            win.destroy()
        btns = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        make_button(btns, "USE", use_selected).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(btns, "ADD", add_selected).pack(
            side="left", expand=True, fill="x", padx=(2, 0))
        btns.pack(side="bottom", fill="x")
        bring_to_front(win)

    def _add_from_url(self):
        url = simpledialog.askstring(self.t("url_title"),
                                      self.t("url_prompt"), parent=self.root)
        if not url:
            return
        item_id = extract_workshop_id(url)
        if not item_id:
            messagebox.showerror(self.t("error_title"),
                                  self.t("url_bad_body"), parent=self.root)
            return
        if self.whitelist and item_id not in self.whitelist:
            if not messagebox.askyesno(
                self.t("whitelist_title"),
                f"Item ID {item_id} is not in your whitelist.\n\n"
                f"Download anyway?", parent=self.root):
                return
        self._set_busy(True)
        threading.Thread(target=self._run_download_url,
                          args=(item_id,), daemon=True).start()

    def _run_download_url(self, item_id):
        try:
            self._log("")
            self._log(f"=== DOWNLOAD {item_id} ===")
            self._set_progress(0, 1, f"Downloading {item_id}...")
            tmp = app_dir() / "downloads"
            gma = download_workshop_gma(item_id, tmp)
            self._log(f"[OK] Downloaded: {gma}")
            self._log(f"[OK] Size: {human_size(gma.stat().st_size)}")
            self._set_progress(1, 1, self.t("url_ok", name=gma.name))
            self.root.after(0, lambda: self._register(gma))
            self.root.after(0, self._rebuild_list)
        except Exception as e:
            self._log(f"[ERROR] {e}")
            self.root.after(0, lambda: messagebox.showerror(
                self.t("error_title"), str(e), parent=self.root))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, lambda: self._reset_progress())

    def _register(self, path):
        path = Path(path)
        if path.is_dir():
            self._add_folder(path)
            return
        suf = path.suffix.lower()
        if suf == ".gma":
            self._add_gma(path)
        elif suf == ".zip":
            self._add_zip(path)
        else:
            self._log(f"[!] Unsupported format: {path.name}")

    def _add_gma(self, path, origin=""):
        if any(s.kind == "gma" and s.path == path for s in self.sources):
            return
        meta = read_gma_metadata_file(path)
        name = meta.get("name", "").strip()
        if not name:
            aj = meta.get("addon_json") or {}
            name = (aj.get("title") or aj.get("name") or "").strip()
        if not name:
            name = path.stem
        s = Source(kind="gma", path=path, name=name,
                   origin=origin, metadata=meta)
        self.sources.append(s)

    def _add_folder(self, path, origin="", name=""):
        if any(s.kind == "folder" and s.path == path for s in self.sources):
            return
        meta = resolve_folder_metadata(path)
        aj = meta.get("addon_json") or {}
        real = (aj.get("title") or aj.get("name") or "").strip()
        s = Source(kind="folder", path=path,
                   name=real or name or path.name,
                   origin=origin, metadata=meta)
        self.sources.append(s)

    def _add_zip_source(self, root_zip, chain, entry, kind, name, origin):
        for s in self.sources:
            if (s.kind == kind and s.root_zip == root_zip
                    and s.chain == list(chain) and s.entry == entry):
                return None
        s = Source(kind=kind, root_zip=root_zip, chain=list(chain),
                   entry=entry, name=name, origin=origin)
        self.sources.append(s)
        self.name_q.put(s)
        return s

    def _add_zip(self, zip_path):
        try:
            gmas, folders, nested = ZipIndex.peek_top(zip_path)
        except Exception as e:
            self._log(f"[ERROR] {zip_path.name}: {e}")
            messagebox.showerror(self.t("zip_error_title"),
                                  f"{zip_path.name}\n\n{e}", parent=self.root)
            return
        direct = 0
        for g in gmas:
            self._add_zip_source(zip_path, [], g, "zip_gma",
                                 name=Path(g).stem, origin=zip_path.name)
            direct += 1
        if not gmas:
            for f in folders:
                nm = f.rstrip("/").split("/")[-1] or zip_path.stem
                self._add_zip_source(zip_path, [], f, "zip_folder",
                                     name=nm, origin=zip_path.name)
                direct += 1
        if nested:
            self._log(f"[i] {zip_path.name}: {len(nested)} nested zip(s), "
                      f"indexing...")
            self._set_busy(True)
            threading.Thread(target=self._run_index_nested,
                              args=(zip_path, nested), daemon=True).start()
        else:
            self._log(f"[OK] {zip_path.name}: {direct} addon(s)")
            self._set_status(self.t("status_added_zip",
                                     name=zip_path.name, n=direct))

    def _run_index_nested(self, root_zip, nested_names):
        total = len(nested_names)
        added = 0
        cancelled = False
        try:
            self._log("")
            self._log(f"=== INDEXING {root_zip.name} ({total}) ===")
            for i, name in enumerate(nested_names, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelled.")
                    cancelled = True
                    break
                self._set_progress(i - 1, total,
                                   self.t("status_indexing",
                                           i=i, total=total, name=name))
                try:
                    entries = ZipIndex.build(root_zip, [name], depth=1)
                except Exception as e:
                    self._log(f"[!] {name}: {e}")
                    continue
                for e in entries:
                    self.root.after(
                        0, lambda e=e, r=root_zip:
                        self._register_from_entry(r, e))
                    added += 1
                self._set_progress(i, total,
                                   self.t("status_indexing",
                                           i=i, total=total, name=name))
            self._log(f"[OK] Nested index: {added} addon(s)")
            if cancelled:
                msg = self.t("status_index_cancelled", n=added)
            else:
                msg = self.t("status_index_ok", n=added)
            self.root.after(0, lambda m=msg: self._reset_progress(m))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(0, self._rebuild_list)

    def _register_from_entry(self, root_zip, e):
        if e.kind == "gma":
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_gma",
                                 name=Path(e.entry).stem, origin=root_zip.name)
        else:
            nm = e.entry.rstrip("/").split("/")[-1] or root_zip.stem
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_folder",
                                 name=nm, origin=root_zip.name)

    # ----- Filter -----
    def _on_filter_change(self):
        if self._filter_timer is not None:
            try:
                self.root.after_cancel(self._filter_timer)
            except Exception:
                pass
        self._filter_timer = self.root.after(FILTER_DEBOUNCE_MS,
                                              self._rebuild_list)

    # ----- List rebuild -----
    def _rebuild_list(self):
        self._filter_timer = None
        for w in self._row_frames:
            try:
                w.destroy()
            except Exception:
                pass
        self._row_frames.clear()
        self._row_refs.clear()

        f = self.filter_text.get().strip().lower()
        visible = [s for s in self.sources
                   if not f or f in (s.name or "").lower()
                   or f in (s.origin or "").lower()]

        if not self.group_mode.get():
            for s in visible:
                self._add_row(s)
        else:
            groups = {}
            for s in visible:
                deps = s.metadata.get("deps") if s.metadata else None
                key = " + ".join(deps) if deps else "No deps"
                groups.setdefault(key, []).append(s)
            for key in sorted(groups, key=lambda k: (k == "No deps", k)):
                self._add_group_header(f"{key} ({len(groups[key])})")
                for s in groups[key]:
                    self._add_row(s)

        self.rows_frame.update_idletasks()
        try:
            h = self.rows_frame.winfo_reqheight()
            self.rows_canvas.config(height=min(max(h, 80), 280))
        except Exception:
            pass

    def _add_group_header(self, text):
        h = tk.Label(self.rows_frame, text=text, bg=C_RED, fg=C_FG,
                     font=F_HEAD, anchor="w", padx=8, pady=4)
        h.pack(fill="x", pady=(6, 2))
        self._row_frames.append(h)

    def _add_row(self, s):
        sid = id(s)
        outer = tk.Frame(self.rows_frame,
                          bg=C_RED if s.selected else C_RED_DIM, bd=0)
        outer.pack(fill="x", pady=1)
        bg = C_RED_SEL if s.selected else C_BG
        inner = tk.Frame(outer, bg=bg, cursor="hand2")
        inner.pack(fill="x", padx=1, pady=1)
        indicator = tk.Label(inner, text="X" if s.selected else " ",
                              bg=bg, fg=C_RED if s.selected else C_FG_DIM,
                              font=F_ROW, width=2, anchor="w", padx=6, pady=6)
        indicator.pack(side="left", fill="y")
        name_lbl = tk.Label(inner, text=s.display, bg=bg, fg=C_FG,
                             font=F_ROW, anchor="w", padx=2, pady=6)
        name_lbl.pack(side="left", fill="x", expand=True)
        info_text = self._info_text(s)
        info_lbl = None
        if info_text:
            info_lbl = tk.Label(inner, text=info_text, bg=bg, fg=C_FG_DIM,
                                 font=F_ROW_S, anchor="e", padx=8, pady=6)
            info_lbl.pack(side="right", fill="y")
        refs = {"outer": outer, "inner": inner, "indicator": indicator,
                "name_lbl": name_lbl, "info_lbl": info_lbl}
        self._row_refs[sid] = refs
        self._row_frames.append(outer)
        widgets = [outer, inner, indicator, name_lbl]
        if info_lbl is not None:
            widgets.append(info_lbl)
        for w in widgets:
            w.bind("<Button-1>", lambda e, src=s: self._on_row_click(src), add="+")
            w.bind("<Double-Button-1>",
                    lambda e, src=s: self._on_row_double(src), add="+")

    def _info_text(self, s):
        m = s.metadata or {}
        parts = []
        deps = m.get("deps")
        if deps:
            parts.append(" | ".join(deps))
        files = m.get("file_count")
        if files:
            parts.append(f"{files}f")
        return "  ".join(parts)

    def _on_row_click(self, s):
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
            if self._pending_click_sid == id(s):
                self._pending_click_sid = None
                return
        self._pending_click_sid = id(s)
        self._click_timer = self.root.after(220, lambda: self._commit_click(s))

    def _commit_click(self, s):
        self._click_timer = None
        self._pending_click_sid = None
        s.selected = not s.selected
        self._refresh_row(s)

    def _on_row_double(self, s):
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
            self._pending_click_sid = None
        action = messagebox.askyesnocancel(
            self.t("action_title"),
            self.t("action_body", name=s.name), parent=self.root)
        if action is None:
            return
        if action:
            self._rename_source(s)
        else:
            self._open_source_temp(s)

    def _refresh_row(self, s):
        sid = id(s)
        refs = self._row_refs.get(sid)
        if not refs:
            return
        outer = refs["outer"]
        inner = refs["inner"]
        indicator = refs["indicator"]
        name_lbl = refs["name_lbl"]
        info_lbl = refs.get("info_lbl")
        if s.selected:
            bg = C_RED_SEL
            outer.config(bg=C_RED)
            indicator.config(text="X", fg=C_RED, bg=bg)
        else:
            bg = C_BG
            outer.config(bg=C_RED_DIM)
            indicator.config(text=" ", fg=C_FG_DIM, bg=bg)
        inner.config(bg=bg)
        name_lbl.config(bg=bg, text=s.display)
        new_info = self._info_text(s)
        if info_lbl is not None:
            info_lbl.config(bg=bg, text=new_info)
        elif new_info:
            info_lbl = tk.Label(inner, text=new_info, bg=bg, fg=C_FG_DIM,
                                 font=F_ROW_S, anchor="e", padx=8, pady=6)
            info_lbl.pack(side="right", fill="y")
            info_lbl.bind("<Button-1>",
                          lambda e, src=s: self._on_row_click(src), add="+")
            info_lbl.bind("<Double-Button-1>",
                          lambda e, src=s: self._on_row_double(src), add="+")
            refs["info_lbl"] = info_lbl

    def _rename_source(self, s):
        new = simpledialog.askstring(self.t("rename_title"),
                                      self.t("rename_prompt"),
                                      initialvalue=s.name, parent=self.root)
        if not new:
            return
        s.name = new.strip()
        self._refresh_row(s)

    def _rename_all(self):
        selected = [s for s in self.sources if s.selected]
        if not selected:
            messagebox.showinfo(self.t("empty_title"),
                                 self.t("empty_body"), parent=self.root)
            return
        pattern = simpledialog.askstring(
            self.t("rename_all_title"), self.t("rename_all_prompt"),
            initialvalue="{name}", parent=self.root)
        if not pattern:
            return
        for i, s in enumerate(selected, 1):
            try:
                new_name = pattern.format(i=i, name=s.name)
                s.name = new_name.strip()
                self._refresh_row(s)
            except Exception as e:
                self._log(f"[!] Rename {s.name}: {e}")
        self._log(f"[OK] Renamed {len(selected)} addon(s).")

    def _open_source_temp(self, s):
        try:
            tmp = Path(tempfile.mkdtemp(prefix="gmod_preview_"))
            kind, real = self._materialize(s, tmp)
            if kind == "gma":
                sub = tmp / "_extracted"
                self.extractor.extract(real, sub)
                open_folder(sub)
            else:
                open_folder(real)
        except Exception as e:
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    def _set_all_selected(self, val):
        for s in self.sources:
            s.selected = val
            self._refresh_row(s)
        n = len(self.sources)
        key = "status_selected_all" if val else "status_deselected_all"
        self._set_status(self.t(key, n=n))

    def _invert_selection(self):
        for s in self.sources:
            s.selected = not s.selected
            self._refresh_row(s)
        sel = sum(1 for s in self.sources if s.selected)
        self._set_status(self.t("status_inverted", sel=sel))

    def _remove_selected(self):
        n = len(self.sources)
        self.sources = [s for s in self.sources if not s.selected]
        removed = n - len(self.sources)
        self._rebuild_list()
        self._set_status(self.t("status_removed", n=removed))

    def _clear(self):
        n = len(self.sources)
        self.sources.clear()
        self._rebuild_list()
        self._set_status(self.t("status_cleared", n=n))

    # ----- Metadata worker -----
    def _start_name_worker(self):
        def worker():
            while self._name_worker_running:
                try:
                    source = self.name_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if source is None:
                    break
                try:
                    meta = {}
                    if source.kind == "zip_gma":
                        meta = resolve_gma_metadata_in_zip(
                            source.root_zip, source.chain, source.entry)
                    elif source.kind == "zip_folder":
                        meta = resolve_folder_metadata_in_zip(
                            source.root_zip, source.chain, source.entry)
                    self.root.after(
                        0, lambda sid=id(source), m=meta:
                        self._apply_metadata(sid, m))
                except Exception:
                    pass
                finally:
                    self.name_q.task_done()
        self._name_worker = threading.Thread(target=worker, daemon=True)
        self._name_worker.start()

    def _apply_metadata(self, source_id, meta):
        target = None
        for s in self.sources:
            if id(s) == source_id:
                target = s
                break
        if target is None:
            return
        target.metadata.update(meta or {})
        new_name = (meta.get("name") or "").strip() if meta else ""
        if not new_name:
            aj = meta.get("addon_json") if meta else None
            if aj:
                new_name = (aj.get("title") or aj.get("name") or "").strip()
        if new_name:
            target.name = new_name
        if self.group_mode.get():
            self._rebuild_list()
        else:
            self._refresh_row(target)

    # ----- Materialization -----
    def _materialize(self, source, tmp_dir):
        if source.kind == "gma":
            return ("gma", source.path)
        if source.kind == "folder":
            return ("folder", source.path)
        if source.kind in ("zip_gma", "zip_folder"):
            entry = ZipIndex.Entry(
                root_zip=source.root_zip, chain=list(source.chain),
                entry=source.entry,
                kind="gma" if source.kind == "zip_gma" else "folder")
            return ZipIndex.materialize(entry, tmp_dir)
        raise ValueError(f"unknown kind: {source.kind}")

    # ----- Busy -----
    def _set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        self.btn_analyze.config(state=st)
        self.btn_extract.config(state=st)
        try:
            self.btn_cancel.config(state=("normal" if busy else "disabled"))
        except Exception:
            pass
        if busy:
            self.cancel_flag.clear()
            self._set_status(self.t("working"))

    def _cancel(self):
        if not self.busy:
            self._log("[i] No operation in progress.")
            self._set_status(self.t("status_no_op"))
            return
        self.cancel_flag.set()
        self._log("[!] Cancel requested...")
        self._set_status(self.t("status_cancel_requested"))

    # ----- Analyze -----
    def _analyze(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            messagebox.showinfo(self.t("empty_title"),
                                 self.t("empty_body"), parent=self.root)
            return
        self._set_busy(True)
        threading.Thread(target=self._run_analyze,
                          args=(active,), daemon=True).start()

    def _run_analyze(self, sources):
        sources = order_sources_by_deps(sources)
        total = len(sources)
        results = []
        cancelled = False
        cache_hits = 0
        try:
            self._log("")
            self._log(f"=== ANALYSIS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log(f"[i] Parallel workers: {PARALLEL_WORKERS}")
            self._log("[i] Dependency order applied.")

            def analyze_one(s):
                display_name = s.name or (s.path.name if s.path else "?")
                fp = s.fingerprint()
                cached = self.cache.get(fp) if fp else None
                entry = {"name": display_name, "deps": [], "file_count": 0,
                         "refs": 0, "error": None, "cached": False,
                         "dangers": [], "by_ext": {}}
                if cached:
                    entry["deps"] = cached.get("deps", [])
                    entry["file_count"] = cached.get("file_count", 0)
                    entry["refs"] = cached.get("refs", 0)
                    entry["dangers"] = cached.get("dangers", [])
                    entry["by_ext"] = cached.get("by_ext", {})
                    entry["cached"] = True
                    return entry
                try:
                    def warn_cb(m, _n=display_name):
                        self._log(f"  [!] {_n}: {m}")
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2, on_warning=warn_cb)
                                r = self.analyzer.scan(t2)
                        else:
                            r = self.analyzer.scan(real)
                    entry["file_count"] = r["file_count"]
                    entry["deps"] = r["deps"]
                    entry["refs"] = len(r["refs"])
                    entry["dangers"] = r.get("dangers", [])
                    entry["by_ext"] = r.get("by_ext", {})
                    if fp:
                        self.cache.put(fp, {
                            "deps": r["deps"],
                            "file_count": r["file_count"],
                            "refs": len(r["refs"]),
                            "dangers": r.get("dangers", []),
                            "by_ext": r.get("by_ext", {}),
                        })
                except Exception as e:
                    entry["error"] = str(e)
                    logging.error("Analyze %s: %s\n%s", display_name, e,
                                   traceback.format_exc())
                return entry

            completed = 0
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
                futures = {ex.submit(analyze_one, s): s for s in sources}
                for fut in as_completed(futures):
                    s = futures[fut]
                    if self.cancel_flag.is_set():
                        cancelled = True
                        break
                    entry = fut.result()
                    if entry.get("cached"):
                        cache_hits += 1
                    results.append(entry)
                    s.metadata.update({
                        "deps": entry.get("deps", []),
                        "file_count": entry.get("file_count", 0),
                    })
                    completed += 1
                    self._log(f"[{completed}/{total}] {s.display}")
                    if entry.get("cached"):
                        self._log(f"  [CACHE] Files: {entry['file_count']}")
                    elif entry.get("error"):
                        self._log(f"  [ERROR] {entry['error']}")
                    else:
                        self._log(f"  Files: {entry['file_count']}")
                        if entry["deps"]:
                            self._log(f"  Deps: {', '.join(entry['deps'])}")
                        if entry["dangers"]:
                            self._log(f"  [!] Suspicious: {len(entry['dangers'])}")
                    self.root.after(0, lambda src=s: self._refresh_row(src))
                    self._set_progress(completed, total,
                                       self.t("status_analyzing",
                                              i=completed, total=total,
                                              name=s.name))

            self.cache.save()
            if cache_hits:
                self._log(f"[i] Cache: {cache_hits}/{total} hits")
            self._log("=== END ANALYSIS ===")
            if results:
                self.last_results = (results, cancelled)
                self.root.after(0, lambda: self._show_summary(results, cancelled))
            ok = sum(1 for r in results if r["error"] is None)
            fail = len(results) - ok
            if cancelled:
                final = self.t("status_analysis_cancelled",
                                n=len(results), total=total)
            elif fail:
                final = self.t("status_analysis_partial", ok=ok, fail=fail)
            else:
                final = self.t("status_analysis_ok", n=ok)
            self.root.after(0, lambda m=final: self._reset_progress(m))
        finally:
            self.root.after(0, lambda: self._set_busy(False))

    def _format_summary(self, results, cancelled):
        total = len(results)
        ok = sum(1 for r in results if r["error"] is None)
        failed = total - ok
        cached = sum(1 for r in results if r.get("cached"))
        dep_map = {}
        no_deps = []
        for r in results:
            if r["error"]:
                continue
            if r["deps"]:
                for d in r["deps"]:
                    dep_map.setdefault(d, []).append(r["name"])
            else:
                no_deps.append(r["name"])
        total_files = sum(r["file_count"] for r in results)
        total_refs = sum(r["refs"] for r in results)

        lines = []
        if cancelled:
            lines.append("ANALYSIS CANCELLED (partial)")
            lines.append("")
        lines.append(f"Analyzed: {total}  |  OK: {ok}  |  Errors: {failed}")
        if cached:
            lines.append(f"Cache: {cached}/{total}")
        lines.append(f"Files: {total_files}  |  Lua refs: {total_refs}")
        lines.append("")

        try:
            missing = check_missing_deps(
                results, self.sources, lambda: self.dest_entry.get())
        except Exception:
            missing = {}
        if missing:
            lines.append("=== MISSING DEPENDENCIES ===")
            for dep in sorted(missing, key=lambda k: -len(missing[k])):
                mods = missing[dep]
                plural = "s" if len(mods) != 1 else ""
                lines.append(f"\n! {dep}  required by {len(mods)} addon{plural}:")
                for m in mods:
                    lines.append(f"    {m}")
            lines.append("")

        try:
            dups = find_duplicates(self.sources)
        except Exception:
            dups = {}
        if dups:
            lines.append("=== DUPLICATES ===")
            for fp, srcs in dups.items():
                lines.append(f"\n! Same content ({fp[:12]}...):")
                for s in srcs:
                    lines.append(f"    {s.display}")
            lines.append("")

        dangers_by_addon = {}
        for r in results:
            ds = r.get("dangers") or []
            if ds:
                dangers_by_addon[r["name"]] = ds
        if dangers_by_addon:
            lines.append("=== SUSPICIOUS LUA ===")
            for name, ds in dangers_by_addon.items():
                lines.append(f"\n! {name}")
                grouped = {}
                for path, label, count in ds:
                    grouped.setdefault(label, []).append((path, count))
                for label in sorted(grouped):
                    entries_l = grouped[label]
                    total_matches = sum(c for _, c in entries_l)
                    lines.append(f"    {label}  ({total_matches} matches)")
                    for path, count in entries_l[:5]:
                        lines.append(f"        {path}  x{count}")
                    if len(entries_l) > 5:
                        lines.append(f"        ... and {len(entries_l) - 5} more")
            lines.append("")

        if dep_map:
            lines.append("=== DEPENDENCIES ===")
            for dep in sorted(dep_map, key=lambda k: -len(dep_map[k])):
                mods = dep_map[dep]
                plural = "s" if len(mods) != 1 else ""
                lines.append(f"\n> {dep}  ({len(mods)} addon{plural})")
                for m in mods:
                    lines.append(f"    {m}")
            lines.append("")
        else:
            lines.append("No known dependencies.")
            lines.append("")

        if no_deps:
            lines.append(f"=== NO DEPENDENCIES ({len(no_deps)}) ===")
            for m in no_deps:
                lines.append(f"    {m}")
            lines.append("")

        errors = [r for r in results if r["error"]]
        if errors:
            lines.append(f"=== ERRORS ({len(errors)}) ===")
            for r in errors:
                lines.append(f"    {r['name']}")
                lines.append(f"      {r['error']}")
            lines.append("")
        return "\n".join(lines)

    def _show_summary(self, results, cancelled):
        text = self._format_summary(results, cancelled)
        win = tk.Toplevel(self.root)
        win.title(self.t("summary_btn"))
        win.geometry("600x640")
        win.minsize(440, 400)
        win.configure(bg=C_BG)
        win.resizable(False, False)
        try:
            win.transient(self.root)
        except Exception:
            pass
        head = tk.Frame(win, bg=C_RED)
        head.pack(fill="x")
        head_in = tk.Frame(head, bg=C_BG)
        head_in.pack(fill="x", padx=1, pady=1)
        tk.Label(head_in, text=self.t("summary_btn"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, pady=8).pack()
        sub = "Partial results" if cancelled else f"{len(results)} addon(s)"
        tk.Label(head_in, text=sub, bg=C_BG, fg=C_FG_DIM,
                 font=F_SMALL).pack(pady=(0, 6))
        body = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        body.pack(fill="both", expand=True)
        tf = tk.Frame(body, bg=C_BG)
        tf.pack(fill="both", expand=True)
        txt = tk.Text(tf, wrap="word", font=F_LOG, bg=C_BG, fg=C_FG,
                      insertbackground=C_RED, relief="flat",
                      highlightbackground=C_RED, highlightthickness=1,
                      padx=6, pady=6)
        txt.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(tf, "vertical", txt.yview)
        sb.pack(side="right", fill="y")
        txt.config(yscrollcommand=sb.set)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        def _wheel(e):
            txt.yview_scroll(int(-e.delta / 120), "units")
        txt.bind("<MouseWheel>", _wheel)
        txt.bind("<Button-4>", lambda e: txt.yview_scroll(-1, "units"))
        txt.bind("<Button-5>", lambda e: txt.yview_scroll(1, "units"))
        footer = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        footer.pack(fill="x")
        def do_copy():
            try:
                win.clipboard_clear()
                win.clipboard_append(text)
                win.update()
                copy_btn.config(text="OK")
                win.after(1500, lambda: copy_btn.config(text=self.t("copy_btn")))
            except Exception as e:
                self._log(f"[!] {e}")
        make_button(footer, self.t("close_btn"), win.destroy).pack(
            side="right", expand=True, fill="x", padx=(3, 0))
        copy_btn = make_button(footer, self.t("copy_btn"), do_copy)
        copy_btn.pack(side="right", expand=True, fill="x", padx=(0, 3))
        bring_to_front(win)

    def _show_last_summary(self):
        if not self.last_results:
            messagebox.showinfo(self.t("summary_empty_title"),
                                 self.t("summary_empty_body"), parent=self.root)
            return
        r, c = self.last_results
        self._show_summary(r, c)

    # ----- Conflicts -----
    def _detect_conflicts(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if len(active) < 2:
            messagebox.showinfo(self.t("conflicts_need_title"),
                                 self.t("conflicts_need_body"), parent=self.root)
            return
        self._set_busy(True)
        threading.Thread(target=self._run_conflicts,
                          args=(active,), daemon=True).start()

    def _run_conflicts(self, sources):
        sources = order_sources_by_deps(sources)
        total = len(sources)
        files_per_source = {}
        try:
            self._log("")
            self._log(f"=== CONFLICTS ({total}) ===")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    break
                self._set_progress(i - 1, total,
                                   self.t("status_scanning",
                                           i=i, total=total, name=s.name))
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2)
                                base = Path(t2)
                        else:
                            base = real
                        rel = set()
                        for root, _, files in os.walk(base):
                            rp = Path(root)
                            for f in files:
                                try:
                                    rel.add(str((rp / f).relative_to(base))
                                            .replace("\\", "/"))
                                except Exception:
                                    pass
                        files_per_source[s.display] = rel
                except Exception as e:
                    self._log(f"[!] {s.display}: {e}")
            count = {}
            for name, files in files_per_source.items():
                for f in files:
                    count.setdefault(f, []).append(name)
            conflicts = {p: names for p, names in count.items() if len(names) > 1}
            self._log("")
            if not conflicts:
                self._log("[OK] No conflicts.")
                self.root.after(0, lambda: self._reset_progress(
                    self.t("status_conflicts_none")))
                self.root.after(0, lambda: messagebox.showinfo(
                    self.t("conflicts_none_title"),
                    self.t("conflicts_none_body"), parent=self.root))
            else:
                self._log(f"[!] {len(conflicts)} conflicting file(s).")
                lines = []
                for p, names in sorted(conflicts.items())[:200]:
                    lines.append(p)
                    for n in names:
                        lines.append(f"    <- {n}")
                    lines.append("")
                preview = "\n".join(lines)
                self.root.after(0, lambda: self._reset_progress(
                    self.t("status_conflicts_found", n=len(conflicts))))
                self.root.after(0, lambda: self._show_conflicts_window(
                    preview, len(conflicts)))
        finally:
            self.root.after(0, lambda: self._set_busy(False))

    def _show_conflicts_window(self, text, total):
        win = tk.Toplevel(self.root)
        win.title(f"{self.t('conflicts_btn')} ({total})")
        win.geometry("600x520")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        frame = tk.Frame(win, bg=C_BG, padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=f"{self.t('conflicts_btn')} ({total})",
                 bg=C_BG, fg=C_FG, font=F_HEAD).pack(anchor="w")
        tf = tk.Frame(frame, bg=C_BG)
        tf.pack(fill="both", expand=True, pady=(6, 0))
        txt = tk.Text(tf, wrap="word", font=F_LOG, bg=C_BG, fg=C_FG,
                      relief="flat", highlightbackground=C_RED,
                      highlightthickness=1)
        txt.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(tf, "vertical", txt.yview)
        sb.pack(side="right", fill="y")
        txt.config(yscrollcommand=sb.set)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        make_button(frame, self.t("close_btn"), win.destroy).pack(
            anchor="e", pady=(8, 0))
        bring_to_front(win)

    # ----- Export -----
    def _export_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=C_BG, fg=C_FG,
                        activebackground=C_RED, activeforeground=C_FG)
        menu.add_command(label="CSV", command=lambda: self._export("csv"))
        menu.add_command(label="JSON", command=lambda: self._export("json"))
        menu.add_command(label="TXT", command=lambda: self._export("txt"))
        try:
            menu.tk_popup(self.root.winfo_pointerx(),
                          self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _export(self, fmt):
        if not self.sources:
            messagebox.showinfo(self.t("export_empty_title"),
                                 self.t("export_empty_body"), parent=self.root)
            return
        if fmt == "csv":
            ext, types = ".csv", [("CSV", "*.csv")]
        elif fmt == "json":
            ext, types = ".json", [("JSON", "*.json")]
        else:
            ext, types = ".txt", [("Text", "*.txt")]
        path = filedialog.asksaveasfilename(
            title=self.t("save_as_title"), defaultextension=ext,
            filetypes=types + [("All", "*.*")])
        if not path:
            return
        try:
            if fmt == "csv":
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Name", "Type", "Origin",
                                 "Deps", "Files", "Author", "Description"])
                    for s in self.sources:
                        m = s.metadata or {}
                        w.writerow([s.name, s.kind, s.origin,
                                     ", ".join(m.get("deps", [])),
                                     m.get("file_count", ""),
                                     m.get("author", ""),
                                     (m.get("description", "") or "").replace("\n", " ")])
            elif fmt == "json":
                data = [{"name": s.name, "kind": s.kind, "origin": s.origin,
                          "selected": s.selected, "metadata": s.metadata or {}}
                         for s in self.sources]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    for s in self.sources:
                        f.write(f"{s.display}\n")
            self._log(f"[OK] Exported: {path}")
            self._set_status(self.t("status_exported", name=Path(path).name))
        except Exception as e:
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    def _export_html(self):
        if not self.sources:
            messagebox.showinfo(self.t("export_empty_title"),
                                 self.t("export_empty_body"), parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            title=self.t("save_as_title"), defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All", "*.*")])
        if not path:
            return
        try:
            rows = []
            for s in self.sources:
                m = s.metadata or {}
                deps = ", ".join(m.get("deps", [])) or "-"
                files = m.get("file_count", "-")
                author = m.get("author", "") or "-"
                rows.append(
                    f"<tr><td>{html.escape(s.name)}</td>"
                    f"<td>{html.escape(s.kind)}</td>"
                    f"<td>{html.escape(str(files))}</td>"
                    f"<td>{html.escape(deps)}</td>"
                    f"<td>{html.escape(author)}</td>"
                    f"<td>{html.escape(s.origin)}</td></tr>")
            doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GMod Addon Manager Report</title>
<style>
body {{ background:#000; color:#fff; font-family:Consolas, monospace; padding:20px; }}
h1 {{ color:#ff0000; border-bottom:2px solid #ff0000; padding-bottom:8px; }}
table {{ border-collapse:collapse; width:100%; margin-top:16px; }}
th {{ background:#ff0000; color:#fff; padding:8px; text-align:left; }}
td {{ border-bottom:1px solid #3a0000; padding:6px 8px; }}
tr:hover {{ background:#1a0000; }}
.meta {{ color:#a0a0a0; font-size:12px; }}
</style></head><body>
<h1>GMod Addon Manager Report</h1>
<p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &middot; {len(self.sources)} addon(s)</p>
<table><thead><tr>
<th>Name</th><th>Type</th><th>Files</th><th>Deps</th><th>Author</th><th>Origin</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
            with open(path, "w", encoding="utf-8") as f:
                f.write(doc)
            self._log(self.t("report_done", path=path))
            open_folder(Path(path).parent)
        except Exception as e:
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    # ----- Extract -----
    def _extract(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            messagebox.showinfo(self.t("empty_title"),
                                 self.t("empty_body"), parent=self.root)
            return
        dest = self.dest_entry.get().strip()
        if not dest:
            messagebox.showerror(self.t("no_dest_title"),
                                  self.t("no_dest_body"), parent=self.root)
            return
        dest_path = Path(dest)
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror(self.t("error_title"),
                                  f"Could not create:\n{e}", parent=self.root)
            return
        if is_gmod_running():
            if not messagebox.askyesno(self.t("gmod_open_title"),
                                        self.t("gmod_open_body"),
                                        parent=self.root):
                return
        try:
            results_for_check = [{"name": s.name or "?",
                                    "deps": (s.metadata or {}).get("deps", []),
                                    "error": None}
                                  for s in self.sources]
            missing = check_missing_deps(
                results_for_check, self.sources, lambda: self.dest_entry.get())
            active_deps = set()
            for s in active:
                for d in (s.metadata or {}).get("deps", []):
                    active_deps.add(d)
            missing = {d: mods for d, mods in missing.items()
                       if d in active_deps}
        except Exception:
            missing = {}
        if missing:
            dep_list = "\n".join(
                f"  - {d}  ({len(mods)} addon(s))"
                for d, mods in sorted(missing.items(),
                                       key=lambda kv: -len(kv[1])))
            if not messagebox.askyesno(
                "Missing dependencies",
                f"The following dependencies are required by the selected "
                f"addons but were not found in the list or the destination "
                f"folder:\n\n{dep_list}\n\n"
                f"Addons may appear as T-pose or with broken ragdolls "
                f"in-game without them.\n\nContinue extracting anyway?",
                parent=self.root):
                return
        self._set_busy(True)
        threading.Thread(target=self._run_extract,
                          args=(dest_path, active), daemon=True).start()

    def _run_extract(self, dest_root, sources):
        sources = order_sources_by_deps(sources)
        total = len(sources)
        ok = 0
        fail = 0
        cancelled = False
        try:
            self._log("")
            self._log(f"=== EXTRACTION -> {dest_root} ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log(f"[i] Parallel workers: {PARALLEL_WORKERS}")
            for k, s in enumerate(sources, 1):
                self._log(f"    {k:2d}. {s.name}")

            def extract_one(s):
                target = dest_root / s.target_name()
                with tempfile.TemporaryDirectory() as tmp:
                    kind, real = self._materialize(s, tmp)
                    if kind == "gma":
                        with tempfile.TemporaryDirectory() as t2:
                            self.extractor.extract(real, t2)
                            copy_tree(Path(t2), target)
                    else:
                        copy_tree(real, target)
                return target

            completed = 0
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
                futures = {ex.submit(extract_one, s): s for s in sources}
                for fut in as_completed(futures):
                    s = futures[fut]
                    if self.cancel_flag.is_set():
                        cancelled = True
                        break
                    label = s.name or (s.path.name if s.path else "?")
                    try:
                        target = fut.result()
                        self._log(f"[{completed+1}/{total}] {s.display} -> {target}")
                        ok += 1
                    except Exception as e:
                        self._log(f"[{completed+1}/{total}] {s.display}: [ERROR] {e}")
                        logging.error("Extract %s: %s\n%s", s.display, e,
                                       traceback.format_exc())
                        fail += 1
                    completed += 1
                    self._set_progress(completed, total,
                                       self.t("status_extracting",
                                              i=completed, total=total,
                                              name=label))

            self._log(f"=== END: {ok} ok, {fail} failed ===")
            if cancelled:
                final = self.t("status_extract_cancelled", ok=ok, fail=fail)
            elif fail:
                final = self.t("status_extract_partial", ok=ok, fail=fail)
            else:
                final = self.t("status_extract_ok", n=ok)
            self.root.after(0, lambda m=final: self._reset_progress(m))
            self.root.after(0, self._save_cfg)
        finally:
            self.root.after(0, lambda: self._set_busy(False))

    # ----- Backup -----
    def _backup_dest(self):
        d = self.dest_entry.get().strip()
        if not d:
            messagebox.showinfo(self.t("no_dest_title"),
                                 self.t("no_dest_body"), parent=self.root)
            return
        dest = Path(d)
        if not dest.is_dir():
            messagebox.showwarning(self.t("dest_missing_title"),
                                    str(dest), parent=self.root)
            return
        backup_root = dest / ".backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        count = 0
        try:
            for child in dest.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith("."):
                    continue
                target = backup_root / child.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(child, target)
                count += 1
            self._log(self.t("backup_done", n=count, path=str(backup_root)))
        except Exception as e:
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    # ----- Repack -----
    def _repack(self):
        folders = []
        for s in self.sources:
            if s.selected and s.kind == "folder" and s.path:
                folders.append(s.path)
        if len(folders) != 1:
            messagebox.showinfo(self.t("repack_title"),
                                 self.t("repack_need_folder"), parent=self.root)
            return
        src = folders[0]
        out = filedialog.asksaveasfilename(
            title=self.t("repack_prompt"), defaultextension=".gma",
            filetypes=[("GMA", "*.gma"), ("All", "*.*")])
        if not out:
            return
        try:
            meta = {}
            aj = src / "addon.json"
            if aj.exists():
                with open(aj, encoding="utf-8", errors="ignore") as f:
                    meta = json.load(f)
            self._log(f"[i] Repacking: {src} -> {out}")
            GMAWriter.write(src, Path(out), metadata=meta)
            self._log(f"[OK] Repacked: {out}")
        except Exception as e:
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    # ----- Grep -----
    def _grep(self):
        needle = simpledialog.askstring(self.t("grep_title"),
                                         self.t("grep_prompt"), parent=self.root)
        if not needle:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            return
        self._set_busy(True)
        threading.Thread(target=self._run_grep,
                          args=(active, needle), daemon=True).start()

    def _run_grep(self, sources, needle):
        total = len(sources)
        matches = 0
        addons_with = 0
        try:
            self._log("")
            self._log(f"=== GREP '{needle}' ({total}) ===")
            needle_low = needle.lower()
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    break
                self._set_progress(i - 1, total,
                                   self.t("status_scanning",
                                           i=i, total=total, name=s.name))
                local_matches = []
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2)
                                base = Path(t2)
                        else:
                            base = real
                        for root, _, files in os.walk(base):
                            rp = Path(root)
                            for f in files:
                                p = rp / f
                                if p.suffix.lower() not in TEXT_EXTENSIONS:
                                    continue
                                try:
                                    if p.stat().st_size > MAX_TEXT_SIZE:
                                        continue
                                    txt = p.read_text(encoding="utf-8",
                                                       errors="ignore")
                                except Exception:
                                    continue
                                if needle_low in txt.lower():
                                    try:
                                        rel = str(p.relative_to(base)).replace("\\", "/")
                                    except Exception:
                                        rel = p.name
                                    local_matches.append(rel)
                except Exception as e:
                    self._log(f"[!] {s.display}: {e}")
                    continue
                if local_matches:
                    addons_with += 1
                    matches += len(local_matches)
                    self._log(f"\n[{i}/{total}] {s.display}")
                    for rel in local_matches[:10]:
                        self._log(f"    {rel}")
                    if len(local_matches) > 10:
                        self._log(f"    ... and {len(local_matches) - 10} more")
                self._set_progress(i, total,
                                   self.t("status_scanning",
                                           i=i, total=total, name=s.name))
            if matches == 0:
                self._log(self.t("grep_empty"))
                self.root.after(0, lambda: self._reset_progress(self.t("grep_empty")))
            else:
                msg = self.t("grep_done", n=matches, m=addons_with)
                self._log(msg)
                self.root.after(0, lambda m=msg: self._reset_progress(m))
        finally:
            self.root.after(0, lambda: self._set_busy(False))

    # ----- Watch -----
    def _toggle_watch(self):
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_stop.set()
            self._log(self.t("watch_stopped"))
            self._set_status(self.t("watch_stopped"))
            return
        folder = filedialog.askdirectory(title=self.t("watch_prompt"))
        if not folder:
            return
        self._watch_stop.clear()
        self._watch_seen.clear()
        self._log(self.t("watch_started", path=folder))
        self._set_status(self.t("watch_started", path=folder))
        self._watch_thread = threading.Thread(
            target=self._watch_loop, args=(Path(folder),), daemon=True)
        self._watch_thread.start()

    def _watch_loop(self, folder):
        while not self._watch_stop.is_set():
            try:
                for p in folder.iterdir():
                    if p.is_file() and p.suffix.lower() in (".gma", ".zip"):
                        key = str(p)
                        if key not in self._watch_seen:
                            self._watch_seen.add(key)
                            self._log(self.t("watch_new", name=p.name))
                            self.root.after(0, lambda pp=p: self._register(pp))
                            self.root.after(0, self._rebuild_list)
            except Exception:
                pass
            time.sleep(WATCH_POLL_SECONDS)

    # ----- Collections -----
    def _open_collections(self):
        win = tk.Toplevel(self.root)
        win.title(self.t("collections_title"))
        win.geometry("480x460")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        frame = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(frame, font=F_NORM, bg=C_BG, fg=C_FG,
                              selectmode=tk.SINGLE, highlightthickness=1,
                              highlightbackground=C_RED,
                              selectbackground=C_RED,
                              selectforeground=C_FG, bd=0, height=14)
        listbox.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(frame, "vertical", listbox.yview)
        sb.pack(side="right", fill="y")
        listbox.config(yscrollcommand=sb.set)
        def refresh():
            listbox.delete(0, "end")
            for name in self.collections.list_collections():
                listbox.insert("end", name)
        refresh()
        def save_current():
            name = simpledialog.askstring(self.t("collections_title"),
                                           self.t("collections_name"),
                                           parent=win)
            if not name:
                return
            self.collections.save_collection(name, self.sources)
            self._log(self.t("collections_saved", name=name))
            refresh()
        def load_selected():
            sel = listbox.curselection()
            if not sel:
                return
            name = listbox.get(sel[0])
            loaded = self.collections.load_collection(name)
            existing = {(s.kind, str(s.path), s.entry) for s in self.sources}
            added = 0
            for s in loaded:
                key = (s.kind, str(s.path), s.entry)
                if key in existing:
                    continue
                self.sources.append(s)
                if s.kind in ("zip_gma", "zip_folder"):
                    self.name_q.put(s)
                added += 1
            self._rebuild_list()
            self._log(f"[OK] Loaded {added} addon(s) from '{name}'")
            win.destroy()
        def delete_selected():
            sel = listbox.curselection()
            if not sel:
                return
            name = listbox.get(sel[0])
            if messagebox.askyesno(self.t("collections_title"),
                                    f"Delete '{name}'?", parent=win):
                self.collections.delete_collection(name)
                refresh()
        row = tk.Frame(win, bg=C_BG, padx=8, pady=8)
        make_button(row, self.t("collections_save"), save_current).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, self.t("collections_load"), load_selected).pack(
            side="left", expand=True, fill="x", padx=2)
        make_button(row, "DEL", delete_selected).pack(
            side="left", expand=True, fill="x", padx=(2, 0))
        row.pack(side="bottom", fill="x")
        bring_to_front(win)

    # ----- Whitelist -----
    def _open_whitelist(self):
        current = "\n".join(self.whitelist)
        result = simpledialog.askstring(self.t("whitelist_title"),
                                         self.t("whitelist_body"),
                                         initialvalue=current,
                                         parent=self.root)
        if result is None:
            return
        ids = [line.strip() for line in result.splitlines() if line.strip()]
        self.whitelist = ids
        self.whitelist_mgr.save(ids)
        self._log(f"[OK] Whitelist saved: {len(ids)} ID(s)")

    # ----- Sizes -----
    def _show_sizes(self):
        if not self.sources:
            messagebox.showinfo(self.t("export_empty_title"),
                                 self.t("export_empty_body"), parent=self.root)
            return
        agg = {}
        for s in self.sources:
            by_ext = (s.metadata or {}).get("by_ext") or {}
            for ext, n in by_ext.items():
                agg[ext] = agg.get(ext, 0) + n
        if not agg:
            messagebox.showinfo(self.t("sizes_title"),
                                 "No analysis data. Run ANALYZE first.",
                                 parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title(self.t("sizes_title"))
        win.geometry("480x460")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        frame = tk.Frame(win, bg=C_BG, padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=self.t("sizes_title"), bg=C_BG, fg=C_FG,
                 font=F_HEAD).pack(anchor="w", pady=(0, 8))
        canvas = tk.Canvas(frame, bg=C_BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        win.update_idletasks()
        w = canvas.winfo_width() or 440
        row_h = 22
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:20]
        max_n = max(n for _, n in top) or 1
        for i, (ext, n) in enumerate(top):
            y = 20 + i * row_h
            canvas.create_text(6, y, text=ext, fill=C_FG, anchor="w",
                               font=("Consolas", 9))
            bar_w = (w - 160) * (n / max_n)
            canvas.create_rectangle(140, y - 7, 140 + bar_w, y + 7,
                                     fill=C_RED, outline="")
            canvas.create_text(140 + bar_w + 6, y, text=str(n),
                               fill=C_FG_DIM, anchor="w",
                               font=("Consolas", 9))
        bring_to_front(win)

    # ----- FastDL -----
    def _fastdl(self):
        active = [s for s in self.sources if s.selected]
        if not active:
            messagebox.showinfo(self.t("empty_title"),
                                 self.t("empty_body"), parent=self.root)
            return
        root = filedialog.askdirectory(title=self.t("fastdl_prompt"))
        if not root:
            return
        self._set_busy(True)
        threading.Thread(target=self._run_fastdl,
                          args=(Path(root), active), daemon=True).start()

    def _run_fastdl(self, fastdl_root, sources):
        total = len(sources)
        copied = 0
        dirs = ("materials", "models", "sound", "particles",
                "scenes", "resource")
        try:
            self._log("")
            self._log(f"=== FASTDL -> {fastdl_root} ===")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    break
                self._set_progress(i - 1, total,
                                   self.t("status_extracting",
                                           i=i, total=total, name=s.name))
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2)
                                base = Path(t2)
                        else:
                            base = real
                        for d in dirs:
                            src = base / d
                            if src.is_dir():
                                dst = fastdl_root / d
                                copy_tree(src, dst)
                                copied += 1
                except Exception as e:
                    self._log(f"[!] {s.display}: {e}")
            self._log(self.t("fastdl_done", n=copied, path=str(fastdl_root)))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(0, lambda: self._reset_progress())

    # ----- Close -----
    def on_close(self):
        self.cancel_flag.set()
        self._watch_stop.set()
        self._name_worker_running = False
        try:
            self.name_q.put(None)
        except Exception:
            pass
        for t in (self._click_timer, self._filter_timer):
            if t is not None:
                try:
                    self.root.after_cancel(t)
                except Exception:
                    pass
        self._save_cfg()
        try:
            self.session.save(self.sources)
        except Exception as e:
            logging.warning("Session save on close: %s", e)
        try:
            self.cache.save()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()
