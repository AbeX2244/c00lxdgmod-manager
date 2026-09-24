"""
ui.py — Tkinter interface. c00lgui style. Custom dialogs.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk

from config import (
    C_BG, C_FG, C_FG_DIM, C_RED, C_RED_DIM, C_RED_SEL, C_RED_HOVER,
    C_WARN, C_WARN_BG,
    F_TITLE, F_SUB, F_NORM, F_SMALL, F_BTN, F_HEAD, F_LOG, F_ROW, F_ROW_S,
    APP_NAME, APP_VERSION, CONFIG_FILE, LOG_FILE,
    DEFAULT_LANG, STRINGS,
    FILTER_DEBOUNCE_MS, PARALLEL_WORKERS, WATCH_POLL_SECONDS,
    NESTED_WORKERS, SCHEMA_CONFIG, RAW_FOLDER_MARKERS,
    PLACEHOLDER_AUTHORS, FOLDER_SCAN_WARN_THRESHOLD,
    MAX_SUMMARY_LINES,
)
from core import (
    HAS_PYZIPPER, HAS_SOURCEPP, extractor_name, human_size, is_gmod_running,
    copy_tree, app_dir, open_folder, safe_name,
    is_app_dir_writable, is_running_from_temp,
    load_json_schema,
    GMAExtractor, GMAWriter, Analyzer,
    ZipIndex, Source,
    CacheManager, SessionManager, CollectionsManager, BackupManager,
    read_gma_metadata_file, resolve_gma_metadata_in_zip,
    resolve_folder_metadata, resolve_folder_metadata_in_zip,
    order_sources_by_deps, check_missing_deps, find_duplicates,
    detect_cross_dependencies, detect_auto_conflicts,
)
from core import util as core_util


def _t_en(key, **fmt):
    d = STRINGS.get("en", {})
    s = d.get(key, key)
    if fmt:
        try:
            s = s.format(**fmt)
        except Exception:
            pass
    return s


def _filter_self_deps(display_name, deps):
    if not deps:
        return deps
    n = (display_name or "").lower() \
        .replace("'", "").replace(" ", "").replace("|", "")
    result = []
    for d in deps:
        dl = d.lower().replace("'", "").replace(" ", "")
        if dl and dl in n:
            continue
        result.append(d)
    return result


def _clean_author(author):
    a = (author or "").strip()
    if a.lower() in PLACEHOLDER_AUTHORS:
        return ""
    return a


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
        disabledforeground="#550000",
        relief="flat", bd=0, font=F_BTN,
        highlightbackground=C_RED, highlightcolor=C_RED,
        highlightthickness=1, padx=10, pady=6,
        cursor="hand2")
    if style == "primary":
        btn.config(bg=C_RED, fg=C_FG, activebackground=C_RED_HOVER)
    elif style == "danger":
        btn.config(fg=C_RED)
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


def center_on_parent(win, parent):
    try:
        win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{px + (pw - ww)//2}+{py + (ph - wh)//2}")
    except Exception:
        pass


def c00l_choice(parent, title, body, buttons, t):
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=C_BG)
    win.resizable(False, False)
    try:
        win.transient(parent)
    except Exception:
        pass

    result = {"value": None}

    head = tk.Frame(win, bg=C_RED, height=44)
    head.pack(side="top", fill="x")
    head.pack_propagate(False)
    head_in = tk.Frame(head, bg=C_BG)
    head_in.pack(fill="both", expand=True, padx=1, pady=1)
    tk.Label(head_in, text=title, bg=C_BG, fg=C_FG, font=F_HEAD,
             padx=16).pack(expand=True)

    btn_row = tk.Frame(win, bg=C_BG, height=60)
    btn_row.pack(side="bottom", fill="x", padx=20, pady=(0, 16))
    btn_row.pack_propagate(False)

    def choose(v):
        result["value"] = v
        win.destroy()

    for i, (label, value, style) in enumerate(buttons):
        pad_l = 0 if i == 0 else 5
        pad_r = 0 if i == len(buttons) - 1 else 5
        b = make_button(btn_row, label, lambda v=value: choose(v), style=style)
        b.pack(side="left", expand=True, fill="x",
               padx=(pad_l, pad_r), pady=8)

    body_frame = tk.Frame(win, bg=C_BG, padx=20, pady=20)
    body_frame.pack(side="top", fill="both", expand=True)
    tk.Label(body_frame, text=body, bg=C_BG, fg=C_FG, font=F_NORM,
             justify="left", anchor="nw", wraplength=460).pack(
        fill="both", expand=True)

    def on_escape(_e):
        result["value"] = None
        win.destroy()
    win.bind("<Escape>", on_escape)
    try:
        win.protocol("WM_DELETE_WINDOW", lambda: on_escape(None))
    except Exception:
        pass

    win.update_idletasks()
    center_on_parent(win, parent)
    bring_to_front(win)
    try:
        win.update()
    except Exception:
        pass
    win.wait_window()
    return result["value"]


def c00l_confirm(parent, title, body, ok_label, cancel_label, t):
    r = c00l_choice(parent, title, body, [
        (cancel_label, "cancel", "normal"),
        (ok_label, "ok", "primary"),
    ], t)
    return r == "ok"


def c00l_alert(parent, title, body, t):
    c00l_choice(parent, title, body, [
        (t("close_btn"), "ok", "primary"),
    ], t)


class GModAddonManager:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.minsize(560, 640)
        self.root.configure(bg=C_BG)

        self.sources = []
        self.busy = False
        self.cancel_flag = threading.Event()
        self.last_results = None
        self._analyzed = False
        self._analysis_stale = False
        self._last_cross_deps = {}
        self._last_auto_conflicts = []
        self._schema_warn = False
        self._manage_console = None

        self.filter_text = tk.StringVar()
        self.group_mode = tk.BooleanVar(value=False)
        self.compact_mode = tk.BooleanVar(value=False)
        self.autoscroll_log = tk.BooleanVar(value=True)

        self._row_refs = {}
        self._row_frames = []
        self._click_timer = None
        self._pending_click_sid = None
        self._filter_timer = None
        self._rebuilding = False
        self._last_dialog_dir = str(Path.home())
        self._cfg_writable = True
        self._last_watch_folder = ""
        self._pending_watch_folder = ""

        self.status = tk.StringVar(value="Ready.")
        self.lang = DEFAULT_LANG
        self.recent_paths = []
        self._watch_thread = None
        self._watch_stop = threading.Event()
        self._watch_seen = set()
        self._op_start_time = None
        self._op_total = 0

        self.extractor = GMAExtractor()
        self.analyzer = Analyzer()
        self.cache = CacheManager()
        self.session = SessionManager()
        self.collections = CollectionsManager()
        self.backups = BackupManager(lambda: self.dest_entry.get()
                                       if hasattr(self, "dest_entry") else "")

        self.log_q = queue.Queue()
        self.name_q = queue.Queue()
        self._name_worker_running = True

        self._nested_q = queue.Queue()
        self._nested_lock = threading.Lock()
        self._nested_total = 0
        self._nested_done = 0
        self._nested_added = 0
        self._nested_workers_started = False

        self._load_cfg()
        self._build()
        self._bind_shortcuts()
        self._poll_log()
        self._start_name_worker()
        self._load_session()
        self._auto_detect_dest()

        self._log(f"[i] Extractor: {extractor_name()}")
        self._log(f"[i] pyzipper: {'yes' if HAS_PYZIPPER else 'no'}")
        self._log(f"[i] sourcepp: {'yes' if HAS_SOURCEPP else 'no'}")
        self._log(f"[i] language: {self.lang}")
        self._log(f"[i] {self.t('help_hint')}")

        try:
            core_util.check_i18n_consistency()
        except Exception:
            pass

        if not core_util.HAS_LOG_FILE:
            self.root.after(400, self._show_log_missing_warning)
        if self._schema_warn:
            self.root.after(600, self._show_schema_warning)

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
            self._bind_shortcuts()
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

    def _show_log_missing_warning(self):
        try:
            c00l_alert(self.root, self.t("log_missing_title"),
                       self.t("log_missing_body"), self.t)
        except Exception:
            pass

    def _show_schema_warning(self):
        try:
            c00l_alert(self.root, self.t("schema_warning_title"),
                       self.t("schema_warning_body"), self.t)
        except Exception:
            pass

    def _build(self):
        menubar = tk.Menu(self.root, bg=C_BG, fg=C_FG,
                           activebackground=C_RED, activeforeground=C_FG,
                           tearoff=0, bd=0)
        file_menu = tk.Menu(menubar, tearoff=0, bg=C_BG, fg=C_FG,
                             activebackground=C_RED, activeforeground=C_FG)
        file_menu.add_command(label=self.t("menu_add_files"),
                               command=self._browse, accelerator="Ctrl+O")
        file_menu.add_command(label=self.t("menu_add_folder"),
                               command=self._browse_folder,
                               accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        file_menu.add_command(label=self.t("export_btn"),
                               command=self._export_menu)
        file_menu.add_separator()
        file_menu.add_command(label=self.t("menu_exit"),
                               command=self.on_close, accelerator="Ctrl+Q")
        menubar.add_cascade(label=self.t("menu_file"), menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0, bg=C_BG, fg=C_FG,
                             activebackground=C_RED, activeforeground=C_FG)
        edit_menu.add_command(label=self.t("menu_select_all"),
                               command=lambda: self._set_all_selected(True),
                               accelerator="Ctrl+A")
        edit_menu.add_command(label=self.t("menu_select_none"),
                               command=lambda: self._set_all_selected(False),
                               accelerator="Ctrl+D")
        edit_menu.add_command(label=self.t("menu_invert"),
                               command=self._invert_selection,
                               accelerator="Ctrl+I")
        edit_menu.add_separator()
        edit_menu.add_command(label=self.t("menu_remove"),
                               command=self._remove_selected,
                               accelerator="Del")
        edit_menu.add_command(label=self.t("menu_clear"),
                               command=self._clear)
        menubar.add_cascade(label=self.t("menu_edit"), menu=edit_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=C_BG, fg=C_FG,
                              activebackground=C_RED, activeforeground=C_FG)
        tools_menu.add_command(label=self.t("menu_analyze"),
                                command=self._analyze, accelerator="F5")
        tools_menu.add_command(label=self.t("menu_extract"),
                                command=self._extract, accelerator="F6")
        tools_menu.add_separator()
        tools_menu.add_command(label=self.t("menu_summary"),
                                command=self._show_last_summary, accelerator="F7")
        tools_menu.add_command(label=self.t("menu_conflicts"),
                                command=self._detect_conflicts, accelerator="F8")
        tools_menu.add_separator()
        tools_menu.add_command(label=self.t("manage_btn"),
                                command=self._open_manage)
        tools_menu.add_command(label=self.t("repack_btn"), command=self._repack)
        tools_menu.add_command(label=self.t("grep_btn"), command=self._grep)
        tools_menu.add_command(label=self.t("rename_all_btn"),
                                command=self._rename_all)
        tools_menu.add_command(label=self.t("report_btn"),
                                command=self._export_html)
        tools_menu.add_command(label=self.t("sizes_btn"),
                                command=self._show_sizes)
        tools_menu.add_command(label=self.t("fastdl_btn"), command=self._fastdl)
        menubar.add_cascade(label=self.t("menu_tools"), menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=C_BG, fg=C_FG,
                             activebackground=C_RED, activeforeground=C_FG)
        help_menu.add_command(label=self.t("menu_shortcuts"),
                               command=self._show_shortcuts)
        help_menu.add_command(label=self.t("menu_about"),
                               command=self._show_about)
        menubar.add_cascade(label=self.t("menu_help"), menu=help_menu)

        try:
            self.root.config(menu=menubar)
        except Exception:
            pass

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

        body = make_panel(self.body, self.t("add_panel"))
        self.path_entry = make_entry(body)
        self.path_entry.pack(fill="x", pady=(0, 6))
        self.path_entry.bind("<Return>", lambda e: self._add_manual())
        row = tk.Frame(body, bg=C_BG); row.pack(fill="x")
        b = make_button(row, self.t("add_btn"), self._add_manual)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_add_manual")
        b = make_button(row, self.t("files_btn"), self._browse)
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_browse")
        b = make_button(row, self.t("folder_btn"), self._browse_folder)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_browse_folder")
        row2 = tk.Frame(body, bg=C_BG); row2.pack(fill="x", pady=(4, 0))
        b = make_button(row2, self.t("history_btn"), self._show_history)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_history")

        body = make_panel(self.body, self.t("filter_panel"))
        row = tk.Frame(body, bg=C_BG); row.pack(fill="x")
        tk.Label(row, text=self.t("search_label"), bg=C_BG, fg=C_FG,
                 font=F_NORM).pack(side="left")
        ent = make_entry(row, textvariable=self.filter_text)
        ent.pack(side="left", fill="x", expand=True, padx=(4, 4))
        make_button(row, "X", lambda: self.filter_text.set("")).pack(side="left")
        self.filter_text.trace_add("write", lambda *_: self._on_filter_change())
        self.group_cb = tk.Checkbutton(
            body, text=self.t("group_dep"),
            variable=self.group_mode, command=self._rebuild_list,
            state=("normal" if self._analyzed else "disabled"),
            bg=C_BG, fg=C_FG, activebackground=C_BG, activeforeground=C_FG,
            selectcolor=C_BG, font=F_NORM, highlightthickness=0, bd=0,
            disabledforeground=C_FG_DIM)
        self.group_cb.pack(anchor="w", pady=(6, 0))

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

        lb1 = tk.Frame(list_inner, bg=C_BG); lb1.pack(fill="x", padx=4, pady=(6, 2))
        b = make_button(lb1, self.t("all_btn"), lambda: self._set_all_selected(True))
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_all")
        b = make_button(lb1, self.t("none_btn"), lambda: self._set_all_selected(False))
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_none")
        b = make_button(lb1, self.t("invert_btn"), self._invert_selection)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_invert")

        lb2 = tk.Frame(list_inner, bg=C_BG); lb2.pack(fill="x", padx=4, pady=(0, 6))
        b = make_button(lb2, self.t("remove_btn"), self._remove_selected)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_remove")
        b = make_button(lb2, self.t("clear_btn"), self._clear)
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_clear")
        b = make_button(lb2, self.t("export_btn"), self._export_menu)
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_export")
        self.btn_compact = make_button(lb2, self.t("compact_btn"), self._toggle_compact)
        self.btn_compact.pack(side="left", expand=True, fill="x", padx=(2, 0))
        self._wire_help(self.btn_compact, "help_compact")

        self.dest_panel = make_panel(self.body, self.t("dest_panel"))
        self.dest_entry = make_entry(self.dest_panel)
        self.dest_entry.pack(fill="x", pady=(0, 6))
        self.dest_entry.bind("<Double-Button-1>", lambda e: self._open_dest())
        row = tk.Frame(self.dest_panel, bg=C_BG); row.pack(fill="x")
        b = make_button(row, self.t("choose_btn"), self._browse_dest)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_choose_dest")
        b = make_button(row, self.t("open_btn"), self._open_dest)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_open_dest")

        act = tk.Frame(self.body, bg=C_BG); act.pack(fill="x", pady=(0, 4))
        self.btn_analyze = tk.Button(
            act, text=self.t("analyze_btn"), command=self._analyze,
            bg=C_BG, fg=C_FG, activebackground=C_RED, activeforeground=C_FG,
            disabledforeground="#550000",
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightcolor=C_RED,
            highlightthickness=1, cursor="hand2")
        self.btn_analyze.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self._wire_help(self.btn_analyze, "help_analyze")
        self.btn_extract = tk.Button(
            act, text=self.t("extract_btn"), command=self._extract,
            bg=C_BG, fg=C_FG, activebackground=C_RED, activeforeground=C_FG,
            disabledforeground="#550000",
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightcolor=C_RED,
            highlightthickness=1, cursor="hand2")
        self.btn_extract.pack(side="left", expand=True, fill="x", padx=(2, 0))
        self._wire_help(self.btn_extract, "help_extract")

        act2 = tk.Frame(self.body, bg=C_BG); act2.pack(fill="x", pady=(0, 8))
        b = make_button(act2, self.t("summary_btn"), self._show_last_summary)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_summary")
        b = make_button(act2, self.t("conflicts_btn"), self._detect_conflicts)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_conflicts")

        self.tools_panel = make_panel(self.body, self.t("tools_panel"))
        r1 = tk.Frame(self.tools_panel, bg=C_BG); r1.pack(fill="x")
        b = make_button(r1, self.t("manage_btn"), self._open_manage)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_manage")
        b = make_button(r1, self.t("repack_btn"), self._repack)
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_repack")
        b = make_button(r1, self.t("grep_btn"), self._grep)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_grep")
        r2 = tk.Frame(self.tools_panel, bg=C_BG); r2.pack(fill="x", pady=(4, 0))
        b = make_button(r2, self.t("rename_all_btn"), self._rename_all)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_rename_all")
        b = make_button(r2, self.t("report_btn"), self._export_html)
        b.pack(side="left", expand=True, fill="x", padx=2); self._wire_help(b, "help_report")
        b = make_button(r2, self.t("sizes_btn"), self._show_sizes)
        b.pack(side="left", expand=True, fill="x", padx=(2, 0)); self._wire_help(b, "help_sizes")
        r3 = tk.Frame(self.tools_panel, bg=C_BG); r3.pack(fill="x", pady=(4, 0))
        b = make_button(r3, self.t("fastdl_btn"), self._fastdl)
        b.pack(side="left", expand=True, fill="x", padx=(0, 2)); self._wire_help(b, "help_fastdl")

        prog_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        prog_panel.pack(fill="x", pady=(0, 4))
        prog_inner = tk.Frame(prog_panel, bg=C_BG)
        prog_inner.pack(fill="x", padx=1, pady=1)
        prog_row = tk.Frame(prog_inner, bg=C_BG)
        prog_row.pack(fill="x", padx=6, pady=6)
        self.progress = tk.Canvas(prog_row, bg=C_BG, height=14,
                                    highlightthickness=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.btn_cancel = make_button(prog_row, self.t("cancel_btn"), self._cancel)
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(side="right", padx=(8, 0))
        self._wire_help(self.btn_cancel, "help_cancel")

        self._progress_max = 100
        self._progress_val = 0
        self.progress_label = tk.Label(self.body, text=self.t("help_hint"),
                                         bg=C_BG, fg=C_FG_DIM, font=F_SMALL,
                                         anchor="w")
        self.progress_label.pack(fill="x", pady=(0, 8))

        log_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        log_panel.pack(fill="both", expand=True, pady=(0, 0))
        log_inner = tk.Frame(log_panel, bg=C_BG)
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(log_inner, bg=C_BG); head.pack(fill="x")
        tk.Label(head, text=self.t("log_panel"), bg=C_BG, fg=C_FG, font=F_HEAD,
                 anchor="w", padx=8, pady=4).pack(side="left")
        b = make_button(head, self.t("log_open_btn"), self._open_log_file)
        b.pack(side="right", padx=(0, 4))
        b = make_button(head, self.t("log_clear_btn"), self._clear_log)
        b.pack(side="right", padx=(0, 4))
        b = make_button(head, self.t("copy_btn"), self._copy_log)
        b.pack(side="right", padx=(0, 4))
        cb = tk.Checkbutton(head, text=self.t("log_autoscroll"),
                              variable=self.autoscroll_log,
                              bg=C_BG, fg=C_FG, activebackground=C_BG,
                              activeforeground=C_FG, selectcolor=C_BG,
                              font=F_SMALL, highlightthickness=0, bd=0)
        cb.pack(side="right", padx=(0, 4))
        tk.Frame(log_inner, bg=C_RED, height=1).pack(fill="x")
        log_wrap = tk.Frame(log_inner, bg=C_BG); log_wrap.pack(fill="both", expand=True)
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

        if self.compact_mode.get():
            try:
                self.tools_panel.master.master.pack_forget()
                self.btn_compact.config(bg=C_RED, fg=C_FG)
            except Exception:
                pass

        self._update_counts()

    def _bind_shortcuts(self):
        r = self.root
        for seq, cb in [
            ("<Control-o>", lambda e: self._browse()),
            ("<Control-O>", lambda e: self._browse_folder()),
            ("<Control-a>", lambda e: self._set_all_selected(True)),
            ("<Control-d>", lambda e: self._set_all_selected(False)),
            ("<Control-i>", lambda e: self._invert_selection()),
            ("<Control-q>", lambda e: self.on_close()),
            ("<Delete>", lambda e: self._remove_selected()),
            ("<F5>", lambda e: self._analyze()),
            ("<F6>", lambda e: self._extract()),
            ("<F7>", lambda e: self._show_last_summary()),
            ("<F8>", lambda e: self._detect_conflicts()),
            ("<Control-l>", lambda e: self.log.focus_set()),
        ]:
            try:
                r.bind_all(seq, cb)
            except Exception:
                pass

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    def _wire_help(self, widget, help_key):
        def on_enter(_e):
            try:
                self.status.set(self.t(help_key))
            except Exception:
                pass
        def on_leave(_e):
            if not self.busy:
                try:
                    self._update_counts()
                except Exception:
                    pass
        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")

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
                    if self.autoscroll_log.get():
                        self.log.see("end")
                    self.log.config(state="disabled")
                except Exception:
                    pass
                if self._manage_console is not None:
                    try:
                        self._manage_console.config(state="normal")
                        self._manage_console.insert("end", msg + "\n")
                        self._manage_console.see("end")
                        self._manage_console.config(state="disabled")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        try:
            self._check_nested_completion()
        except Exception:
            pass
        try:
            if hasattr(self, "_watch_status_lbl"):
                self._refresh_watch_status()
        except Exception:
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
            c00l_alert(self.root, self.t("no_log_title"),
                       self.t("no_log_body"), self.t)

    def _set_progress(self, value, maximum=100, text=""):
        def upd():
            self._progress_max = max(1, maximum)
            self._progress_val = value
            self._draw_progress()
            if text:
                eta = self._eta_text(value, maximum)
                label = text
                if eta:
                    label = f"{label}   {self.t('eta_prefix', eta=eta)}"
                self.progress_label.config(text=label)
                self.status.set(label)
            else:
                pct = int(100 * value / max(1, maximum))
                label = f"{value}/{maximum} ({pct}%)"
                self.progress_label.config(text=label)
                self.status.set(label)
        self.root.after(0, upd)

    def _eta_text(self, value, maximum):
        if not self._op_start_time or value <= 0 or maximum <= 0:
            return ""
        elapsed = time.time() - self._op_start_time
        rate = value / elapsed if elapsed > 0 else 0
        if rate <= 0:
            return ""
        remaining = max(0, (maximum - value) / rate)
        if remaining < 1:
            return ""
        m = int(remaining // 60)
        s = int(remaining % 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

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
            self._op_start_time = None
            self._draw_progress()
            self.progress_label.config(text=final_text)
            self.status.set(final_text)
        self.root.after(0, upd)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def _update_counts(self):
        if self.busy:
            return
        try:
            total = len(self.sources)
            marked = sum(1 for s in self.sources if s.selected)
            size_bytes = 0
            for s in self.sources:
                if not s.selected:
                    continue
                try:
                    if s.kind == "gma" and s.path:
                        size_bytes += s.path.stat().st_size
                except Exception:
                    pass
            size_str = human_size(size_bytes) if size_bytes else "0 B"
            self.status.set(self.t("status_counts", total=total,
                                    marked=marked, size=size_str))
        except Exception:
            pass

    def _cfg_file(self):
        return app_dir() / CONFIG_FILE

    def _load_cfg(self):
        data, ok = load_json_schema(self._cfg_file(), SCHEMA_CONFIG, "config")
        self._cfg_writable = ok
        if not ok:
            self._pending_dest = ""
            self.lang = DEFAULT_LANG
            self.recent_paths = []
            self._pending_geometry = None
            self._last_dialog_dir = str(Path.home())
            self._schema_warn = True
        else:
            self._pending_dest = data.get("dest", "")
            lang = data.get("lang", DEFAULT_LANG)
            self.lang = lang if lang in STRINGS else DEFAULT_LANG
            self.recent_paths = data.get("recent", [])[:10]
            self._pending_geometry = data.get("geometry")
            self._last_dialog_dir = data.get("last_dir", str(Path.home()))
            self._schema_warn = False

        geo = getattr(self, "_pending_geometry", None)
        if geo:
            try:
                self.root.geometry(geo)
            except Exception:
                self.root.geometry("640x820")
        else:
            self.root.geometry("640x820")

    def _apply_pending_dest(self):
        if getattr(self, "_pending_dest", ""):
            try:
                self.dest_entry.insert(0, self._pending_dest)
            except Exception:
                pass

    def _save_cfg(self):
        if not getattr(self, "_cfg_writable", True):
            return
        try:
            dest = ""
            try:
                dest = self.dest_entry.get()
            except Exception:
                pass
            try:
                geo = self.root.geometry()
            except Exception:
                geo = ""
            with open(self._cfg_file(), "w", encoding="utf-8") as f:
                json.dump({
                    "schema": SCHEMA_CONFIG,
                    "dest": dest,
                    "lang": self.lang,
                    "recent": self.recent_paths[:10],
                    "geometry": geo,
                    "last_dir": self._last_dialog_dir,
                }, f, indent=2)
        except Exception:
            pass

    def _push_recent(self, path):
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self.recent_paths.insert(0, path)
        self.recent_paths = self.recent_paths[:10]
        try:
            self._last_dialog_dir = str(Path(path).parent)
        except Exception:
            pass

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
            c00l_alert(self.root, self.t("no_dest_title"),
                       self.t("no_dest_body"), self.t)
            return
        p = Path(d)
        if not p.exists():
            c00l_alert(self.root, self.t("dest_missing_title"),
                       f"{p}", self.t)
            return
        open_folder(p)

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

    def _browse(self):
        try:
            files = filedialog.askopenfilenames(
                title="Select .gma or .zip",
                initialdir=self._last_dialog_dir,
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
            d = filedialog.askdirectory(title="Select folder",
                                          initialdir=self._last_dialog_dir)
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        if d:
            self._register(Path(d))
            self._push_recent(d)
            self._rebuild_list()

    def _browse_dest(self):
        try:
            d = filedialog.askdirectory(title="Destination folder",
                                          initialdir=self._last_dialog_dir)
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        if d:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, d)
            self._push_recent(d)

    def _add_manual(self):
        raw = self.path_entry.get().strip().strip('"').strip("'")
        if not raw:
            return
        p = Path(raw)
        if not p.exists():
            c00l_alert(self.root, self.t("not_found_title"),
                       self.t("not_found_body", path=raw), self.t)
            return
        self._register(p)
        self._push_recent(raw)
        self.path_entry.delete(0, "end")
        self._rebuild_list()

    def _show_history(self):
        if not self.recent_paths:
            c00l_alert(self.root, self.t("history_btn"), "Empty.", self.t)
            return
        win = tk.Toplevel(self.root)
        win.title(self.t("history_btn"))
        win.geometry("560x400")
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
        center_on_parent(win, self.root)
        bring_to_front(win)

    def _mark_stale(self):
        if self._analyzed:
            self._analysis_stale = True
        if self.group_mode.get():
            self.group_mode.set(False)
        try:
            self.group_cb.config(state="disabled")
        except Exception:
            pass

    def _looks_like_raw_addon(self, folder: Path) -> bool:
        try:
            if (folder / "addon.json").exists():
                return True
            children = {p.name.lower() for p in folder.iterdir()
                        if p.is_dir()}
        except OSError:
            return False
        return bool(children & RAW_FOLDER_MARKERS)

    def _scan_folder_for_addons(self, folder: Path) -> list:
        results = []
        try:
            for root, _, files in os.walk(folder):
                for f in files:
                    low = f.lower()
                    if low.endswith(".gma") or low.endswith(".zip"):
                        results.append(Path(root) / f)
        except Exception as e:
            self._log(f"[!] Error scanning {folder}: {e}")
        results.sort()
        return results

    def _register(self, path):
        path = Path(path)
        if path.is_dir():
            if self._looks_like_raw_addon(path):
                self._add_folder(path)
                return
            found = self._scan_folder_for_addons(path)
            if found:
                n = len(found)
                if n > FOLDER_SCAN_WARN_THRESHOLD:
                    if not c00l_confirm(
                            self.root, self.t("folder_scan_title"),
                            self.t("folder_scan_body",
                                   name=path.name, n=n),
                            self.t("folder_scan_yes"),
                            self.t("cancel_btn"), self.t):
                        return
                self._log(f"[OK] {path.name}: {n} addon file(s) found")
                self._set_status(self.t("status_folder_scanned",
                                         name=path.name, n=n))
                for f in found:
                    self._register_file(f)
                return
            self._add_folder(path)
            return
        self._register_file(path)

    def _register_file(self, path: Path):
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
        self._mark_stale()

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
        self._mark_stale()

    def _add_zip_source(self, root_zip, chain, entry, kind, name, origin):
        for s in self.sources:
            if (s.kind == kind and s.root_zip == root_zip
                    and s.chain == list(chain) and s.entry == entry):
                return None
        s = Source(kind=kind, root_zip=root_zip, chain=list(chain),
                   entry=entry, name=name, origin=origin)
        self.sources.append(s)
        self.name_q.put(s)
        self._mark_stale()
        return s

    def _add_zip(self, zip_path):
        try:
            gmas, folders, nested = ZipIndex.peek_top(zip_path)
        except Exception as e:
            self._log(f"[ERROR] {zip_path.name}: {e}")
            c00l_alert(self.root, self.t("zip_error_title"),
                       f"{zip_path.name}\n\n{e}", self.t)
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
            with self._nested_lock:
                if self._nested_total == 0:
                    self._op_start_time = time.time()
                self._nested_total += len(nested)
                total_now = self._nested_total
            for name in nested:
                self._nested_q.put((zip_path, name))
            self._start_nested_workers()
            self._set_progress(0, total_now,
                               self.t("status_indexing",
                                      i=0, total=total_now, name="..."))
        else:
            self._log(f"[OK] {zip_path.name}: {direct} addon(s)")
            self._set_status(self.t("status_added_zip",
                                     name=zip_path.name, n=direct))

    def _start_nested_workers(self):
        with self._nested_lock:
            if self._nested_workers_started:
                return
            self._nested_workers_started = True
        for i in range(NESTED_WORKERS):
            t = threading.Thread(target=self._nested_worker,
                                  args=(i,), daemon=True)
            t.start()

    def _nested_worker(self, worker_id):
        while self._name_worker_running:
            try:
                task = self._nested_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                try:
                    self._nested_q.task_done()
                except Exception:
                    pass
                break
            root_zip, zip_name = task

            if self.cancel_flag.is_set():
                with self._nested_lock:
                    self._nested_done += 1
                try:
                    self._nested_q.task_done()
                except Exception:
                    pass
                continue

            try:
                entries = ZipIndex.build(root_zip, [zip_name], depth=1)
                for e in entries:
                    self.root.after(
                        0, lambda e=e, r=root_zip:
                        self._register_from_entry(r, e))
                with self._nested_lock:
                    self._nested_added += len(entries)
            except Exception as e:
                self._log(f"[!] {zip_name}: {e}")
            finally:
                with self._nested_lock:
                    self._nested_done += 1
                    done = self._nested_done
                    total = self._nested_total
                if done == total or (done % 5 == 0):
                    try:
                        self._set_progress(
                            done, total,
                            self.t("status_indexing",
                                   i=done, total=total, name=zip_name))
                    except Exception:
                        pass
                try:
                    self._nested_q.task_done()
                except Exception:
                    pass

    def _check_nested_completion(self):
        try:
            with self._nested_lock:
                total = self._nested_total
        except AttributeError:
            return
        if not total:
            return
        try:
            pending = self._nested_q.unfinished_tasks
        except Exception:
            pending = 0
        if pending > 0:
            return
        with self._nested_lock:
            done = self._nested_done
            total = self._nested_total
            added = self._nested_added
            if done < total:
                return
            had_work = (added > 0 or done > 0)
            self._nested_done = 0
            self._nested_total = 0
            self._nested_added = 0
        if had_work:
            self._log(f"[OK] Nested index complete: {added} addon(s)")
            msg = self.t("status_index_ok", n=added)
            self._reset_progress(msg)
            self._rebuild_list()
        self._set_busy(False)

    def _register_from_entry(self, root_zip, e):
        if e.kind == "gma":
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_gma",
                                 name=Path(e.entry).stem, origin=root_zip.name)
        else:
            nm = e.entry.rstrip("/").split("/")[-1] or root_zip.stem
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_folder",
                                 name=nm, origin=root_zip.name)

    def _on_filter_change(self):
        if self._filter_timer is not None:
            try:
                self.root.after_cancel(self._filter_timer)
            except Exception:
                pass
        self._filter_timer = self.root.after(FILTER_DEBOUNCE_MS,
                                              self._rebuild_list)

    def _toggle_compact(self):
        self.compact_mode.set(not self.compact_mode.get())
        try:
            panel = self.tools_panel
            outer = panel.master.master
            if self.compact_mode.get():
                outer.pack_forget()
                self.btn_compact.config(bg=C_RED, fg=C_FG)
            else:
                outer.pack(fill="x", pady=(0, 8))
                self.btn_compact.config(bg=C_BG, fg=C_FG)
        except Exception:
            pass

    def _rebuild_list(self):
        self._filter_timer = None
        try:
            prev_yview = self.rows_canvas.yview()
        except Exception:
            prev_yview = (0.0, 1.0)

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
            self.rows_canvas.config(height=min(max(h, 80), 320))
        except Exception:
            pass
        try:
            self.rows_canvas.yview_moveto(prev_yview[0])
        except Exception:
            pass
        self._update_counts()

    def _add_group_header(self, text):
        h = tk.Label(self.rows_frame, text=text, bg=C_RED, fg=C_FG,
                     font=F_HEAD, anchor="w", padx=8, pady=4)
        h.pack(fill="x", pady=(6, 2))
        self._row_frames.append(h)

    def _add_row(self, s):
        sid = id(s)
        orph = (s.metadata or {}).get("orphan_refs") or set()
        has_warn = bool(orph) and len(orph) >= 5

        border_color = C_RED if s.selected else C_RED_DIM
        outer = tk.Frame(self.rows_frame, bg=border_color, bd=0)
        outer.pack(fill="x", pady=1)
        bg = C_RED_SEL if s.selected else (C_WARN_BG if has_warn else C_BG)
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
            w.bind("<Button-3>", lambda e, src=s: self._on_row_right_click(e, src), add="+")
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
        self._update_counts()

    def _on_row_right_click(self, event, s):
        menu = tk.Menu(self.root, tearoff=0, bg=C_BG, fg=C_FG,
                        activebackground=C_RED, activeforeground=C_FG)
        menu.add_command(label=self.t("row_menu_rename"),
                          command=lambda: self._rename_source(s))
        menu.add_command(label=self.t("row_menu_temp"),
                          command=lambda: self._open_source_temp(s))
        menu.add_separator()
        menu.add_command(label=self.t("row_menu_copy"),
                          command=lambda: self._copy_to_clip(
                              str(s.path) if s.path else (str(s.root_zip) if s.root_zip else "")))
        menu.add_command(label=self.t("row_menu_copy_name"),
                          command=lambda: self._copy_to_clip(s.name or ""))
        menu.add_separator()
        menu.add_command(label=self.t("row_menu_remove"),
                          command=lambda: self._remove_single(s))
        menu.bind("<FocusOut>", lambda e: menu.unpost())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_to_clip(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
        except Exception:
            pass

    def _remove_single(self, s):
        try:
            self.sources.remove(s)
        except ValueError:
            return
        self._mark_stale()
        self._rebuild_list()

    def _on_row_double(self, s):
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
            self._pending_click_sid = None
        result = c00l_choice(
            self.root,
            self.t("action_title"),
            f"{s.name}",
            [
                (self.t("row_menu_rename"), "rename", "normal"),
                (self.t("row_menu_temp"), "temp", "primary"),
            ],
            self.t)
        if result == "rename":
            self._rename_source(s)
        elif result == "temp":
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

        orph = (s.metadata or {}).get("orphan_refs") or set()
        has_warn = bool(orph) and len(orph) >= 5

        if s.selected:
            bg = C_RED_SEL
            outer.config(bg=C_RED)
            indicator.config(text="X", fg=C_RED, bg=bg)
        else:
            bg = C_WARN_BG if has_warn else C_BG
            outer.config(bg=C_RED_DIM)
            indicator.config(text=" ", fg=C_FG_DIM, bg=bg)
        try:
            inner.config(bg=bg)
            name_lbl.config(bg=bg, text=s.display)
        except Exception:
            return

        new_info = self._info_text(s)
        if info_lbl is not None:
            try:
                info_lbl.config(bg=bg, text=new_info)
            except Exception:
                pass
        elif new_info:
            try:
                info_lbl = tk.Label(inner, text=new_info, bg=bg, fg=C_FG_DIM,
                                     font=F_ROW_S, anchor="e", padx=8, pady=6)
                info_lbl.pack(side="right", fill="y")
                info_lbl.bind("<Button-1>",
                              lambda e, src=s: self._on_row_click(src), add="+")
                info_lbl.bind("<Button-3>",
                              lambda e, src=s: self._on_row_right_click(e, src), add="+")
                info_lbl.bind("<Double-Button-1>",
                              lambda e, src=s: self._on_row_double(src), add="+")
                refs["info_lbl"] = info_lbl
            except Exception:
                pass

    def _rename_source(self, s):
        new = simpledialog.askstring(self.t("rename_title"),
                                      self.t("rename_prompt"),
                                      initialvalue=s.name, parent=self.root)
        if not new:
            return
        s.name = new.strip()
        self._mark_stale()
        self._refresh_row(s)

    def _rename_all(self):
        selected = [s for s in self.sources if s.selected]
        if not selected:
            c00l_alert(self.root, self.t("empty_title"),
                       self.t("empty_body"), self.t)
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
        self._mark_stale()
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
            c00l_alert(self.root, self.t("error_title"), str(e), self.t)

    def _set_all_selected(self, val):
        for s in self.sources:
            s.selected = val
            self._refresh_row(s)
        n = len(self.sources)
        key = "status_selected_all" if val else "status_deselected_all"
        self._set_status(self.t(key, n=n))
        self._update_counts()

    def _invert_selection(self):
        for s in self.sources:
            s.selected = not s.selected
            self._refresh_row(s)
        sel = sum(1 for s in self.sources if s.selected)
        self._set_status(self.t("status_inverted", sel=sel))
        self._update_counts()

    def _remove_selected(self):
        n = len(self.sources)
        self.sources = [s for s in self.sources if not s.selected]
        removed = n - len(self.sources)
        if removed:
            self._mark_stale()
        self._rebuild_list()
        self._set_status(self.t("status_removed", n=removed))

    def _clear(self):
        n = len(self.sources)
        self.sources.clear()
        self._analyzed = False
        self._analysis_stale = False
        try:
            self.group_cb.config(state="disabled")
        except Exception:
            pass
        self._rebuild_list()
        self._set_status(self.t("status_cleared", n=n))

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

    def _set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        try:
            self.btn_analyze.config(state=st)
            self.btn_extract.config(state=st)
        except Exception:
            pass
        try:
            if busy:
                self.btn_cancel.config(state="normal", bg=C_RED, fg=C_FG)
            else:
                self.btn_cancel.config(state="disabled", bg=C_BG, fg="#550000")
        except Exception:
            pass
        if busy:
            self.cancel_flag.clear()
            self._set_status(self.t("working"))
            if self._op_start_time is None:
                self._op_start_time = time.time()
        else:
            self._update_counts()

    def _cancel(self):
        if not self.busy:
            self._log("[i] No operation in progress.")
            return
        self.cancel_flag.set()
        self._log("[!] Cancel requested...")
        self._set_status(self.t("status_cancel_requested"))

    def _analyze(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            c00l_alert(self.root, self.t("empty_title"),
                       self.t("empty_body"), self.t)
            return
        self._set_busy(True)
        self._op_total = len(active)
        threading.Thread(target=self._run_analyze,
                          args=(active,), daemon=True).start()

    def _run_analyze(self, sources):
        sources = order_sources_by_deps(sources)
        total = len(sources)
        results = []
        cancelled = False
        cache_hits = 0

        def analyze_one(s):
            display_name = s.name or (s.path.name if s.path else "?")
            fp = s.fingerprint()
            cached = self.cache.get(fp) if fp else None
            entry = {"name": display_name, "deps": [], "file_count": 0,
                     "refs": 0, "error": None, "cached": False,
                     "dangers": [], "by_ext": {},
                     "files_provided": set(), "asset_refs": set(),
                     "orphan_refs": set(),
                     "global_defs": [], "external_uses": [],
                     "hook_ids": [], "net_strings": [],
                     "concommands": [], "cvars": [],
                     "lua_file_count": 0}
            if cached:
                entry["deps"] = cached.get("deps", [])
                entry["file_count"] = cached.get("file_count", 0)
                entry["refs"] = cached.get("refs", 0)
                entry["dangers"] = cached.get("dangers", [])
                entry["by_ext"] = cached.get("by_ext", {})
                entry["files_provided"] = set(cached.get("files_provided", []))
                entry["asset_refs"] = set(cached.get("asset_refs", []))
                entry["orphan_refs"] = set(cached.get("orphan_refs", []))
                entry["global_defs"] = cached.get("global_defs", [])
                entry["external_uses"] = cached.get("external_uses", [])
                entry["hook_ids"] = cached.get("hook_ids", [])
                entry["net_strings"] = cached.get("net_strings", [])
                entry["concommands"] = cached.get("concommands", [])
                entry["cvars"] = cached.get("cvars", [])
                entry["lua_file_count"] = cached.get("lua_file_count", 0)
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
                entry["deps"] = _filter_self_deps(display_name, r["deps"])
                entry["refs"] = len(r["refs"])
                entry["dangers"] = r.get("dangers", [])
                entry["by_ext"] = r.get("by_ext", {})
                entry["files_provided"] = r.get("files_provided", set())
                entry["asset_refs"] = r.get("asset_refs", set())
                entry["orphan_refs"] = r.get("orphan_refs", set())
                entry["global_defs"] = r.get("global_defs", [])
                entry["external_uses"] = r.get("external_uses", [])
                entry["hook_ids"] = r.get("hook_ids", [])
                entry["net_strings"] = r.get("net_strings", [])
                entry["concommands"] = r.get("concommands", [])
                entry["cvars"] = r.get("cvars", [])
                entry["lua_file_count"] = r.get("lua_file_count", 0)
                if fp:
                    self.cache.put(fp, {
                        "deps": entry["deps"],
                        "file_count": r["file_count"],
                        "refs": len(r["refs"]),
                        "dangers": r.get("dangers", []),
                        "by_ext": r.get("by_ext", {}),
                        "files_provided": list(r.get("files_provided", set()))[:5000],
                        "asset_refs": list(r.get("asset_refs", set()))[:5000],
                        "orphan_refs": list(r.get("orphan_refs", set()))[:2000],
                        "global_defs": r.get("global_defs", []),
                        "external_uses": r.get("external_uses", []),
                        "hook_ids": r.get("hook_ids", []),
                        "net_strings": r.get("net_strings", []),
                        "concommands": r.get("concommands", []),
                        "cvars": r.get("cvars", []),
                        "lua_file_count": r.get("lua_file_count", 0),
                    })
            except Exception as e:
                entry["error"] = str(e)
                logging.error("Analyze %s: %s\n%s", display_name, e,
                               traceback.format_exc())
            return entry

        try:
            self._log("")
            self._log(f"=== ANALYSIS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log(f"[i] Parallel workers: {PARALLEL_WORKERS}")
            self._log("[i] Dependency order applied.")

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
                        "orphan_refs": entry.get("orphan_refs", set()),
                        "by_ext": entry.get("by_ext", {}),
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

            self._log("[i] Detecting cross-addon dependencies...")
            analyses_for_cross = []
            for entry in results:
                analyses_for_cross.append({
                    "name": entry["name"],
                    "files_provided": entry.get("files_provided", set()),
                    "asset_refs": entry.get("asset_refs", set()),
                    "lua_file_count": entry.get("lua_file_count", 0),
                    "global_defs": entry.get("global_defs", []),
                    "hook_ids": entry.get("hook_ids", []),
                    "net_strings": entry.get("net_strings", []),
                    "concommands": entry.get("concommands", []),
                    "cvars": entry.get("cvars", []),
                })
            try:
                cross_deps = detect_cross_dependencies(analyses_for_cross)
                self._last_cross_deps = cross_deps
                if cross_deps:
                    self._log(f"[i] Found {len(cross_deps)} cross-dependency link(s).")
            except Exception as e:
                self._log(f"[!] Cross-dep detection failed: {e}")
                self._last_cross_deps = {}

            try:
                auto_conflicts = detect_auto_conflicts(analyses_for_cross)
                self._last_auto_conflicts = auto_conflicts
                if auto_conflicts:
                    self._log(f"[i] Auto-conflicts: {len(auto_conflicts)} detected.")
            except Exception as e:
                self._log(f"[!] Auto-conflict detection failed: {e}")
                self._last_auto_conflicts = []

            self._log("=== END ANALYSIS ===")
            if results:
                self.last_results = (results, cancelled)
                self._analyzed = True
                self._analysis_stale = False
                self.root.after(0, lambda: self.group_cb.config(state="normal"))
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

        try:
            cross_deps = getattr(self, "_last_cross_deps", {}) or {}
        except Exception:
            cross_deps = {}

        try:
            missing = check_missing_deps(
                results, self.sources, lambda: self.dest_entry.get(),
                cross_deps=cross_deps)
        except Exception:
            missing = {}

        try:
            dups = find_duplicates(self.sources)
        except Exception:
            dups = {}

        try:
            auto_conflicts = getattr(self, "_last_auto_conflicts", []) or []
        except Exception:
            auto_conflicts = []

        total_files = sum(r["file_count"] for r in results)
        total_refs = sum(r["refs"] for r in results)

        lines = []

        if missing:
            lines.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            lines.append(f"!!!   {self.t('missing_deps_title')}")
            lines.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            lines.append("")
            lines.append(self.t("missing_deps_header"))
            lines.append("")
            for dep in sorted(missing, key=lambda k: -len(missing[k])):
                mods = missing[dep]
                plural = "s" if len(mods) != 1 else ""
                lines.append(f"  > {dep}   (needed by {len(mods)} addon{plural})")
                for m in mods:
                    lines.append(f"      - {m}")
            lines.append("")
            lines.append(self.t("missing_deps_footer"))
            lines.append("")
            lines.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            lines.append("")

        if auto_conflicts:
            lines.append("=== " + self.t("auto_conflicts_title") + " ===")
            lines.append("")
            for c in sorted(auto_conflicts,
                             key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(
                                 x.get("severity"), 3)):
                sev = {"high": "!!!", "medium": "!", "low": " "}.get(
                    c.get("severity"), " ")
                lines.append(f"  {sev} [{c['kind']}] {c['identifier']}")
                for o in c["owners"]:
                    lines.append(f"      - {o}")
                if c.get("note"):
                    lines.append(f"      note: {c['note']}")
                lines.append("")

        if cancelled:
            lines.append("ANALYSIS CANCELLED (partial)")
            lines.append("")
        lines.append(f"Analyzed: {total}  |  OK: {ok}  |  Errors: {failed}")
        if cached:
            lines.append(f"Cache: {cached}/{total}")
        lines.append(f"Files: {total_files}  |  Lua refs: {total_refs}")
        lines.append("")

        if dep_map:
            lines.append("=== DEPENDENCIES (detected) ===")
            for dep in sorted(dep_map, key=lambda k: -len(dep_map[k])):
                mods = dep_map[dep]
                plural = "s" if len(mods) != 1 else ""
                lines.append(f"\n> {dep}  ({len(mods)} addon{plural})")
                for m in mods:
                    lines.append(f"    {m}")
            lines.append("")

        if cross_deps:
            lines.append("=== ADDON-TO-ADDON DEPENDENCIES ===")
            for name in sorted(cross_deps):
                deps = cross_deps[name]
                lines.append(f"\n> {name}  depends on:")
                for d in sorted(deps):
                    marker = "" if any(r["name"] == d for r in results) else "  [NOT IN LIST]"
                    lines.append(f"    -> {d}{marker}")
            lines.append("")

        orphan_map = {}
        for r in results:
            if r.get("error"):
                continue
            orph = r.get("orphan_refs") or set()
            if len(orph) >= 5:
                orphan_map[r["name"]] = sorted(orph)
        if orphan_map:
            lines.append("=== " + self.t("orphan_title") + " ===")
            lines.append("")
            lines.append(self.t("orphan_body"))
            lines.append("")
            for name in sorted(orphan_map):
                refs = orphan_map[name]
                lines.append(f"  ! {name}")
                lines.append(f"      {len(refs)} asset ref(s) not found locally:")
                for ref in refs[:8]:
                    lines.append(f"        {ref}")
                if len(refs) > 8:
                    lines.append(f"        ... and {len(refs) - 8} more")
                lines.append("")
            lines.append(self.t("orphan_hint"))
            lines.append("")

        if no_deps:
            lines.append(f"=== NO DEPENDENCIES ({len(no_deps)}) ===")
            for m in no_deps:
                lines.append(f"    {m}")
            lines.append("")

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

        errors = [r for r in results if r["error"]]
        if errors:
            lines.append(f"=== ERRORS ({len(errors)}) ===")
            for r in errors:
                lines.append(f"    {r['name']}")
                lines.append(f"      {r['error']}")
            lines.append("")

        text = "\n".join(lines)
        if len(lines) > MAX_SUMMARY_LINES:
            text = ("... (truncated, too many lines)\n\n" + text)
        return text

    def _show_summary(self, results, cancelled):
        try:
            text = self._format_summary(results, cancelled)
        except Exception:
            text = "ERROR building summary:\n\n" + traceback.format_exc()
        if not text or not text.strip():
            text = "(summary is empty — internal error)\n\n"
            text += f"results={len(results)} cancelled={cancelled}\n"

        self._log(f"[i] Summary: {len(text)} chars, "
                  f"{text.count(chr(10)) + 1} lines")

        win = tk.Toplevel(self.root)
        win.title(self.t("summary_btn"))
        win.geometry("760x640")
        win.configure(bg=C_BG)
        try:
            win.transient(self.root)
        except Exception:
            pass

        header = tk.Frame(win, bg=C_RED, height=48)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=self.t("summary_btn"), bg=C_RED, fg=C_FG,
                 font=F_HEAD).pack(expand=True)

        footer = tk.Frame(win, bg=C_BG, height=48)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)

        body = tk.Frame(win, bg=C_BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=10)

        txt = tk.Text(body, wrap="word", font=F_LOG,
                      bg=C_BG, fg=C_FG, insertbackground=C_RED,
                      relief="flat", borderwidth=0,
                      highlightbackground=C_RED, highlightthickness=1,
                      padx=8, pady=8)
        scrollbar = make_scrollbar(body, "vertical", txt.yview)
        scrollbar.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.config(yscrollcommand=scrollbar.set)
        txt.insert("1.0", text)
        txt.config(state="disabled")

        def do_copy():
            try:
                win.clipboard_clear()
                win.clipboard_append(text)
                win.update()
            except Exception:
                pass

        btn_close = make_button(footer, self.t("close_btn"), win.destroy)
        btn_close.pack(side="right", padx=(6, 12), pady=8)
        btn_copy = make_button(footer, self.t("copy_btn"), do_copy)
        btn_copy.pack(side="right", pady=8)

        center_on_parent(win, self.root)
        bring_to_front(win)
        try:
            win.update_idletasks()
            win.update()
        except Exception:
            pass

    def _show_last_summary(self):
        if not self.last_results:
            c00l_alert(self.root, self.t("summary_empty_title"),
                       self.t("summary_empty_body"), self.t)
            return
        r, c = self.last_results
        self._show_summary(r, c)

    def _detect_conflicts(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if len(active) < 2:
            c00l_alert(self.root, self.t("conflicts_need_title"),
                       self.t("conflicts_need_body"), self.t)
            return
        self._set_busy(True)
        self._op_total = len(active)
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
                self.root.after(0, lambda: c00l_alert(
                    self.root, self.t("conflicts_none_title"),
                    self.t("conflicts_none_body"), self.t))
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
        win.geometry("640x540")
        win.configure(bg=C_BG)

        header = tk.Frame(win, bg=C_RED, height=44)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=f"{self.t('conflicts_btn')} ({total})",
                 bg=C_RED, fg=C_FG, font=F_HEAD).pack(expand=True)

        footer = tk.Frame(win, bg=C_BG, height=48)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        make_button(footer, self.t("close_btn"), win.destroy).pack(
            side="right", padx=(6, 12), pady=8)

        body = tk.Frame(win, bg=C_BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        txt = tk.Text(body, wrap="word", font=F_LOG, bg=C_BG, fg=C_FG,
                      relief="flat", highlightbackground=C_RED,
                      highlightthickness=1)
        scrollbar = make_scrollbar(body, "vertical", txt.yview)
        scrollbar.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.config(yscrollcommand=scrollbar.set)
        txt.insert("1.0", text)
        txt.config(state="disabled")

        center_on_parent(win, self.root)
        bring_to_front(win)

    def _export_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=C_BG, fg=C_FG,
                        activebackground=C_RED, activeforeground=C_FG)
        menu.add_command(label="CSV", command=lambda: self._export("csv"))
        menu.add_command(label="JSON", command=lambda: self._export("json"))
        menu.add_command(label="TXT", command=lambda: self._export("txt"))
        menu.bind("<FocusOut>", lambda e: menu.unpost())
        try:
            menu.tk_popup(self.root.winfo_pointerx(),
                          self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _export(self, fmt):
        if not self.sources:
            c00l_alert(self.root, self.t("export_empty_title"),
                       self.t("export_empty_body"), self.t)
            return
        if fmt == "csv":
            ext, types = ".csv", [("CSV", "*.csv")]
        elif fmt == "json":
            ext, types = ".json", [("JSON", "*.json")]
        else:
            ext, types = ".txt", [("Text", "*.txt")]
        path = filedialog.asksaveasfilename(
            title=self.t("save_as_title"), defaultextension=ext,
            initialdir=self._last_dialog_dir,
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
                                     _clean_author(m.get("author", "")),
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
            c00l_alert(self.root, self.t("error_title"), str(e), self.t)

    def _export_html(self):
        if not self.sources:
            c00l_alert(self.root, self.t("export_empty_title"),
                       self.t("export_empty_body"), self.t)
            return
        default_name = f"gmod_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path = filedialog.asksaveasfilename(
            title=self.t("save_as_title"), defaultextension=".html",
            initialdir=self._last_dialog_dir,
            initialfile=default_name,
            filetypes=[("HTML", "*.html"), ("All", "*.*")])
        if not path:
            return
        try:
            rows = []
            for s in self.sources:
                m = s.metadata or {}
                deps = ", ".join(m.get("deps", [])) or "-"
                files = m.get("file_count", "-")
                author = _clean_author(m.get("author", "")) or "-"
                rows.append(
                    f"<tr><td>{html.escape(s.name)}</td>"
                    f"<td>{html.escape(s.kind)}</td>"
                    f"<td>{html.escape(str(files))}</td>"
                    f"<td>{html.escape(deps)}</td>"
                    f"<td>{html.escape(author)}</td>"
                    f"<td>{html.escape(s.origin)}</td></tr>")

            # Include the full summary (if available)
            summary_html = ""
            if self.last_results:
                try:
                    summary_text = self._format_summary(self.last_results[0],
                                                          self.last_results[1])
                    summary_html = (
                        "<h2>Analysis summary</h2>"
                        "<pre class=\"summary\">" +
                        html.escape(summary_text) +
                        "</pre>")
                except Exception:
                    pass

            doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GMod Addon Manager Report</title>
<style>
body {{ background:#000; color:#fff; font-family:Consolas, monospace; padding:20px; }}
h1 {{ color:#ff0000; border-bottom:2px solid #ff0000; padding-bottom:8px; }}
h2 {{ color:#ff0000; margin-top:32px; }}
pre.summary {{ background:#1a0000; border-left:3px solid #ff0000; padding:12px;
  white-space:pre-wrap; font-size:12px; line-height:1.4; color:#e0e0e0; }}
table {{ border-collapse:collapse; width:100%; margin-top:16px; }}
th {{ background:#ff0000; color:#fff; padding:8px; text-align:left; }}
td {{ border-bottom:1px solid #3a0000; padding:6px 8px; }}
tr:hover {{ background:#1a0000; }}
.meta {{ color:#a0a0a0; font-size:12px; }}
</style></head><body>
<h1>GMod Addon Manager Report</h1>
<p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &middot; {len(self.sources)} addon(s)</p>
{summary_html}
<table><thead><tr>
<th>Name</th><th>Type</th><th>Files</th><th>Deps</th><th>Author</th><th>Origin</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
            with open(path, "w", encoding="utf-8") as f:
                f.write(doc)
            self._log(self.t("report_done", path=path))
            open_folder(Path(path).parent)
        except Exception as e:
            c00l_alert(self.root, self.t("error_title"), str(e), self.t)

    def _extract(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            c00l_alert(self.root, self.t("empty_title"),
                       self.t("empty_body"), self.t)
            return
        dest = self.dest_entry.get().strip()
        if not dest:
            c00l_alert(self.root, self.t("no_dest_title"),
                       self.t("no_dest_body"), self.t)
            return
        dest_path = Path(dest)
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            c00l_alert(self.root, self.t("error_title"),
                       f"Could not create:\n{e}", self.t)
            return

        if not self._analyzed:
            if c00l_confirm(self.root, self.t("auto_analyze_title"),
                             self.t("auto_analyze_body"),
                             self.t("analyze_btn"),
                             self.t("cancel_btn"), self.t):
                self._analyze()
            return
        if self._analysis_stale:
            if not c00l_confirm(
                    self.root, self.t("auto_analyze_title"),
                    self.t("analysis_stale") + "\n\n" +
                    self.t("auto_analyze_body"),
                    self.t("analyze_btn"),
                    self.t("cancel_btn"), self.t):
                return
            self._analyze()
            return

        if is_gmod_running():
            if not c00l_confirm(self.root, self.t("gmod_open_title"),
                                 self.t("gmod_open_body"),
                                 self.t("extract_btn"),
                                 self.t("cancel_btn"), self.t):
                return

        try:
            results_for_check = [{"name": s.name or "?",
                                    "deps": (s.metadata or {}).get("deps", []),
                                    "error": None}
                                  for s in self.sources]
            cross_deps = getattr(self, "_last_cross_deps", {}) or {}
            missing = check_missing_deps(
                results_for_check, self.sources,
                lambda: self.dest_entry.get(),
                cross_deps=cross_deps)
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
                f"  > {d}   ({len(mods)} addon(s))"
                for d, mods in sorted(missing.items(),
                                       key=lambda kv: -len(kv[1])))
            body = (f"{self.t('missing_deps_header')}\n\n"
                    f"{dep_list}\n\n"
                    f"{self.t('missing_deps_footer')}\n\n"
                    f"{self.t('missing_deps_question')}")
            if not c00l_confirm(self.root, self.t("missing_deps_title"),
                                 body,
                                 self.t("extract_btn"),
                                 self.t("cancel_btn"), self.t):
                return

        targets = {}
        collisions = []
        for s in active:
            tname = s.target_name()
            if tname in targets:
                collisions.append((tname, targets[tname].display, s.display))
            else:
                targets[tname] = s
        if collisions:
            lines = []
            for tname, a, b in collisions[:20]:
                lines.append(f"  {tname}")
                lines.append(f"      - {a}")
                lines.append(f"      - {b}")
            body = ("Multiple addons would extract to the same folder. "
                    "The later one would overwrite the earlier one.\n\n"
                    + "\n".join(lines))
            if not c00l_confirm(self.root, "Output folder collisions",
                                 body,
                                 self.t("extract_btn"),
                                 self.t("cancel_btn"), self.t):
                return

        self._set_busy(True)
        self._op_total = len(active)
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

    def _repack(self):
        folders = []
        for s in self.sources:
            if s.selected and s.kind == "folder" and s.path:
                folders.append(s.path)
        if len(folders) != 1:
            c00l_alert(self.root, self.t("repack_title"),
                       self.t("repack_need_folder"), self.t)
            return
        src = folders[0]
        out = filedialog.asksaveasfilename(
            title=self.t("repack_prompt"), defaultextension=".gma",
            initialdir=self._last_dialog_dir,
            initialfile=f"{src.name}.gma",
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
            c00l_alert(self.root, self.t("error_title"), str(e), self.t)

    def _grep(self):
        needle = simpledialog.askstring(self.t("grep_title"),
                                         self.t("grep_prompt"), parent=self.root)
        if not needle:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            return
        self._set_busy(True)
        self._op_total = len(active)
        threading.Thread(target=self._run_grep,
                          args=(active, needle), daemon=True).start()

    def _run_grep(self, sources, needle):
        from config import TEXT_EXTENSIONS, MAX_TEXT_SIZE
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

    def _show_sizes(self):
        if not self.sources:
            c00l_alert(self.root, self.t("export_empty_title"),
                       self.t("export_empty_body"), self.t)
            return
        if self._analysis_stale or not self._analyzed:
            c00l_alert(self.root, self.t("stale_title"),
                       self.t("stale_body"), self.t)
            return
        agg = {}
        for s in self.sources:
            by_ext = (s.metadata or {}).get("by_ext") or {}
            for ext, n in by_ext.items():
                agg[ext] = agg.get(ext, 0) + n
        if not agg:
            c00l_alert(self.root, self.t("sizes_title"),
                       "No analysis data. Run ANALYZE first.", self.t)
            return
        win = tk.Toplevel(self.root)
        win.title(self.t("sizes_title"))
        win.geometry("520x500")
        win.configure(bg=C_BG)
        frame = tk.Frame(win, bg=C_BG, padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=self.t("sizes_title"), bg=C_BG, fg=C_FG,
                 font=F_HEAD).pack(side="top", anchor="w", pady=(0, 8))
        canvas = tk.Canvas(frame, bg=C_BG, highlightthickness=0)
        canvas.pack(side="top", fill="both", expand=True)
        win.update_idletasks()
        w = canvas.winfo_width() or 480
        row_h = 22
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:25]
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
        center_on_parent(win, self.root)
        bring_to_front(win)

    def _fastdl(self):
        active = [s for s in self.sources if s.selected]
        if not active:
            c00l_alert(self.root, self.t("empty_title"),
                       self.t("empty_body"), self.t)
            return
        root = filedialog.askdirectory(title=self.t("fastdl_prompt"),
                                        initialdir=self._last_dialog_dir)
        if not root:
            return
        self._set_busy(True)
        self._op_total = len(active)
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
                                try:
                                    if str(dst.resolve()).startswith(str(src.resolve())):
                                        continue
                                except Exception:
                                    pass
                                copy_tree(src, dst)
                                copied += 1
                except Exception as e:
                    self._log(f"[!] {s.display}: {e}")
            self._log(self.t("fastdl_done", n=copied, path=str(fastdl_root)))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(0, lambda: self._reset_progress())

    # ------------------- MANAGE dialog -------------------

    def _open_manage(self, initial_tab="backups"):
        win = tk.Toplevel(self.root)
        win.title(self.t("manage_btn"))
        win.geometry("760x680")
        win.minsize(620, 540)
        win.configure(bg=C_BG)
        try:
            win.transient(self.root)
        except Exception:
            pass

        header = tk.Frame(win, bg=C_RED, height=44)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=self.t("manage_btn"), bg=C_RED, fg=C_FG,
                 font=F_HEAD).pack(expand=True)

        footer = tk.Frame(win, bg=C_BG, height=48)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)

        def close_manage():
            self._manage_console = None
            win.destroy()

        make_button(footer, self.t("close_btn"), close_manage).pack(
            side="right", padx=(6, 12), pady=8)

        console_frame = tk.Frame(win, bg=C_BG)
        console_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 6))

        tk.Label(console_frame, text=self.t("log_panel"), bg=C_BG,
                 fg=C_FG_DIM, font=F_SMALL, anchor="w").pack(fill="x")

        console_inner = tk.Frame(console_frame, bg=C_BG)
        console_inner.pack(fill="x", pady=(2, 0))

        console = tk.Text(console_inner, height=6, wrap="word",
                          font=F_LOG, bg=C_BG, fg=C_FG,
                          insertbackground=C_RED, relief="flat",
                          padx=6, pady=4, bd=0,
                          highlightbackground=C_RED,
                          highlightthickness=1, state="disabled")
        console.pack(side="left", fill="both", expand=True)
        csb = make_scrollbar(console_inner, "vertical", console.yview)
        csb.pack(side="right", fill="y")
        console.config(yscrollcommand=csb.set)

        try:
            content = self.log.get("1.0", "end-1c")
            lines = content.splitlines()[-50:]
            console.config(state="normal")
            console.insert("1.0", "\n".join(lines))
            console.see("end")
            console.config(state="disabled")
        except Exception:
            pass

        self._manage_console = console

        tab_bar = tk.Frame(win, bg=C_BG)
        tab_bar.pack(side="top", fill="x")

        tk.Frame(win, bg=C_RED_DIM, height=1).pack(side="top", fill="x")

        body = tk.Frame(win, bg=C_BG)
        body.pack(side="top", fill="both", expand=True)

        tab_defs = [
            ("backups", self.t("tab_backups")),
            ("watch", self.t("tab_watch")),
            ("collections", self.t("tab_collections")),
            ("maintenance", self.t("tab_maintenance")),
        ]

        tab_btns = {}
        builders = {
            "backups": self._build_backups_tab,
            "watch": self._build_watch_tab,
            "collections": self._build_collections_tab,
            "maintenance": self._build_maintenance_tab,
        }

        def show(key):
            for k, b in tab_btns.items():
                if k == key:
                    b.config(bg=C_RED, fg=C_FG)
                else:
                    b.config(bg=C_BG, fg=C_FG_DIM)
            for w in body.winfo_children():
                w.destroy()
            builders[key](body)

        for key, label in tab_defs:
            btn = tk.Button(tab_bar, text=label,
                            bg=C_BG, fg=C_FG_DIM,
                            activebackground=C_BG,
                            activeforeground=C_FG,
                            relief="flat", bd=0, font=F_HEAD,
                            padx=16, pady=8, cursor="hand2",
                            command=lambda k=key: show(k))
            btn.pack(side="left")
            tab_btns[key] = btn

        show(initial_tab)

        try:
            win.protocol("WM_DELETE_WINDOW", close_manage)
        except Exception:
            pass

        center_on_parent(win, self.root)
        bring_to_front(win)

    def _build_backups_tab(self, parent):
        frame = tk.Frame(parent, bg=C_BG, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=self.t("backups_info"), bg=C_BG, fg=C_FG_DIM,
                 font=F_SMALL, anchor="w", justify="left", wraplength=650
                 ).pack(fill="x", pady=(0, 12))

        actions = tk.Frame(frame, bg=C_BG)
        actions.pack(fill="x", pady=(0, 12))

        make_button(actions, self.t("btn_create_backup"),
                    self._start_backup).pack(side="left")
        make_button(actions, self.t("btn_open_backup_folder"),
                    self._open_backup_folder).pack(side="left", padx=(8, 0))
        make_button(actions, self.t("btn_refresh") if "btn_refresh" in STRINGS.get("en", {}) else "REFRESH",
                    lambda: self._refresh_backups_tab(parent)).pack(side="left", padx=(8, 0))

        list_frame = tk.Frame(frame, bg=C_BG)
        list_frame.pack(fill="both", expand=True)

        listbox = tk.Listbox(list_frame, font=F_LOG, bg=C_BG, fg=C_FG,
                              selectmode=tk.SINGLE, bd=0,
                              highlightthickness=1,
                              highlightbackground=C_RED,
                              selectbackground=C_RED_SEL,
                              selectforeground=C_FG)
        listbox.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(list_frame, "vertical", listbox.yview)
        sb.pack(side="right", fill="y")
        listbox.config(yscrollcommand=sb.set)

        self._backups_listbox = listbox
        self._backups_entries = self.backups.list_backups()
        if not self._backups_entries:
            listbox.insert("end", "  " + self.t("backups_empty"))
        else:
            for b in self._backups_entries:
                line = f"  {b['created']}    {b['addon_count']} addon(s)    {b['size_human']}"
                listbox.insert("end", line)

        btn_row = tk.Frame(frame, bg=C_BG)
        btn_row.pack(fill="x", pady=(8, 0))
        make_button(btn_row, self.t("btn_restore_selected") if "btn_restore_selected" in STRINGS.get("en", {}) else "RESTORE",
                    lambda: self._restore_selected_backup(listbox)).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(btn_row, self.t("btn_delete_selected") if "btn_delete_selected" in STRINGS.get("en", {}) else "DELETE",
                    lambda: self._delete_selected_backup(listbox)).pack(
            side="left", expand=True, fill="x", padx=(2, 2))
        make_button(btn_row, self.t("btn_delete_all") if "btn_delete_all" in STRINGS.get("en", {}) else "DELETE ALL",
                    lambda: self._delete_all_backups(listbox)).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

    def _refresh_backups_tab(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        self._build_backups_tab(parent)

    def _open_backup_folder(self):
        d = self.dest_entry.get().strip()
        if not d:
            c00l_alert(self.root, self.t("no_dest_title"),
                       self.t("no_dest_body"), self.t)
            return
        backup_root = Path(d) / ".backup"
        if not backup_root.is_dir():
            c00l_alert(self.root, self.t("backups_empty"),
                       self.t("backups_empty"), self.t)
            return
        open_folder(backup_root)

    def _start_backup(self):
        d = self.dest_entry.get().strip()
        if not d:
            c00l_alert(self.root, self.t("no_dest_title"),
                       self.t("no_dest_body"), self.t)
            return
        dest = Path(d)
        if not dest.is_dir():
            c00l_alert(self.root, self.t("dest_missing_title"),
                       str(dest), self.t)
            return
        if self.busy:
            return
        if not c00l_confirm(
                self.root, self.t("btn_create_backup"),
                "Copy the entire destination folder into .backup/.\n\n"
                "This may take a while if the folder is large.",
                self.t("btn_create_backup"), self.t("cancel_btn"), self.t):
            return
        self._set_busy(True)
        threading.Thread(target=self._run_backup, args=(dest,),
                          daemon=True).start()

    def _run_backup(self, dest):
        try:
            self._log("")
            self._log(f"=== BACKUP ===")
            path = self.backups.create(
                progress_cb=lambda cur, tot, name: self._set_progress(
                    cur, tot, f"Backing up {cur + 1}/{tot}: {name}"
                    if cur < tot else f"Backing up {tot}/{tot}"),
                cancel_flag=self.cancel_flag,
            )
            self._log(f"[OK] Backup created: {path}")
            self.root.after(0, lambda: self._set_status(
                self.t("backup_done", n=0, path=str(path))))
        except Exception as e:
            self._log(f"[ERROR] Backup failed: {e}")
            logging.error("Backup: %s\n%s", e, traceback.format_exc())
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, lambda: self._reset_progress())

    def _restore_selected_backup(self, listbox):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        entries = getattr(self, "_backups_entries", [])
        if idx >= len(entries):
            return
        entry = entries[idx]

        if not c00l_confirm(
                self.root, "Restore backup",
                f"Restore backup from {entry['created']}?\n\n"
                f"This will copy its {entry['addon_count']} addon(s) back into "
                f"the destination folder, overwriting existing files.",
                "Restore", self.t("cancel_btn"), self.t):
            return

        if self.busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._run_restore, args=(entry,),
                          daemon=True).start()

    def _run_restore(self, entry):
        try:
            self._log("")
            self._log(f"=== RESTORE {entry['name']} ===")
            restored = self.backups.restore(
                entry["path"],
                progress_cb=lambda cur, tot, name: self._set_progress(
                    cur, tot, f"Restoring {cur + 1}/{tot}: {name}"
                    if cur < tot else f"Restoring {tot}/{tot}"),
                cancel_flag=self.cancel_flag,
            )
            self._log(f"[OK] Restored {restored} addon(s).")
            self.root.after(0, lambda: self._set_status(
                f"Restored {restored} addon(s)"))
        except Exception as e:
            self._log(f"[ERROR] Restore failed: {e}")
            logging.error("Restore: %s\n%s", e, traceback.format_exc())
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, lambda: self._reset_progress())

    def _delete_selected_backup(self, listbox):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        entries = getattr(self, "_backups_entries", [])
        if idx >= len(entries):
            return
        entry = entries[idx]
        if not c00l_confirm(
                self.root, "Delete backup",
                f"Delete backup from {entry['created']}?",
                "Delete", self.t("cancel_btn"), self.t):
            return
        try:
            self.backups.delete(entry["path"])
            self._log(f"[OK] Deleted backup: {entry['name']}")
        except Exception as e:
            self._log(f"[!] {e}")
        # Refresh
        parent = listbox.master.master
        self._refresh_backups_tab(parent)

    def _delete_all_backups(self, listbox):
        entries = getattr(self, "_backups_entries", [])
        if not entries:
            return
        if not c00l_confirm(
                self.root, "Delete all backups",
                f"Delete ALL {len(entries)} backup(s)?\n\n"
                "This cannot be undone.",
                "Delete all", self.t("cancel_btn"), self.t):
            return
        n = self.backups.delete_all()
        self._log(f"[OK] Deleted {n} backup(s).")
        parent = listbox.master.master
        self._refresh_backups_tab(parent)

    def _build_watch_tab(self, parent):
        frame = tk.Frame(parent, bg=C_BG, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        self._watch_status_lbl = tk.Label(
            frame, text="", bg=C_BG, fg=C_FG, font=F_NORM, anchor="w")
        self._watch_status_lbl.pack(fill="x", pady=(0, 12))

        actions = tk.Frame(frame, bg=C_BG)
        actions.pack(fill="x", pady=(0, 12))
        make_button(actions, self.t("btn_choose_watch"),
                    self._choose_watch_folder).pack(side="left")
        self._watch_toggle_btn = make_button(
            actions, self.t("btn_start_watch"), self._toggle_watch_from_tab)
        self._watch_toggle_btn.pack(side="left", padx=(8, 0))

        tk.Label(frame, text=self.t("watch_recent"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, anchor="w").pack(fill="x", pady=(0, 4))

        recent_frame = tk.Frame(frame, bg=C_BG)
        recent_frame.pack(fill="both", expand=True)
        self._watch_recent_list = tk.Listbox(
            recent_frame, font=F_LOG, bg=C_BG, fg=C_FG,
            selectmode=tk.SINGLE, bd=0,
            highlightthickness=1, highlightbackground=C_RED)
        self._watch_recent_list.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(recent_frame, "vertical",
                             self._watch_recent_list.yview)
        sb.pack(side="right", fill="y")
        self._watch_recent_list.config(yscrollcommand=sb.set)

        self._refresh_watch_status()

    def _choose_watch_folder(self):
        folder = filedialog.askdirectory(title=self.t("watch_prompt"),
                                          initialdir=self._last_dialog_dir)
        if not folder:
            return
        self._pending_watch_folder = folder
        self._refresh_watch_status()

    def _toggle_watch_from_tab(self):
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_stop.set()
            self._log(self.t("watch_stopped"))
            self._refresh_watch_status()
            return
        folder = getattr(self, "_pending_watch_folder", "") or \
                 getattr(self, "_last_watch_folder", "")
        if not folder:
            folder = filedialog.askdirectory(title=self.t("watch_prompt"),
                                              initialdir=self._last_dialog_dir)
            if not folder:
                return
            self._pending_watch_folder = folder
        self._last_watch_folder = folder
        self._watch_stop.clear()
        self._watch_seen.clear()
        self._log(self.t("watch_started", path=folder))
        self._watch_thread = threading.Thread(
            target=self._watch_loop, args=(Path(folder),), daemon=True)
        self._watch_thread.start()
        self._refresh_watch_status()

    def _refresh_watch_status(self):
        try:
            active = self._watch_thread and self._watch_thread.is_alive()
        except Exception:
            active = False
        folder = getattr(self, "_last_watch_folder", "")
        if hasattr(self, "_watch_status_lbl"):
            try:
                if active and folder:
                    self._watch_status_lbl.config(
                        text=self.t("watch_active", path=folder), fg=C_FG)
                elif folder:
                    self._watch_status_lbl.config(
                        text=f"{self.t('watch_idle')}  ({folder})", fg=C_FG_DIM)
                else:
                    self._watch_status_lbl.config(
                        text=self.t("watch_no_folder"), fg=C_FG_DIM)
            except Exception:
                pass
        if hasattr(self, "_watch_toggle_btn"):
            try:
                if active:
                    self._watch_toggle_btn.config(text=self.t("btn_stop_watch"))
                else:
                    self._watch_toggle_btn.config(text=self.t("btn_start_watch"))
            except Exception:
                pass
        if hasattr(self, "_watch_recent_list"):
            try:
                self._watch_recent_list.delete(0, "end")
                for p in list(self._watch_seen)[-50:]:
                    self._watch_recent_list.insert("end", f"  {p}")
            except Exception:
                pass

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

    def _build_collections_tab(self, parent):
        frame = tk.Frame(parent, bg=C_BG, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        actions = tk.Frame(frame, bg=C_BG)
        actions.pack(fill="x", pady=(0, 12))
        make_button(actions, self.t("collections_save"),
                    self._collection_save_current).pack(side="left")

        list_frame = tk.Frame(frame, bg=C_BG)
        list_frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(list_frame, font=F_NORM, bg=C_BG, fg=C_FG,
                              selectmode=tk.SINGLE, bd=0,
                              highlightthickness=1,
                              highlightbackground=C_RED,
                              selectbackground=C_RED_SEL,
                              selectforeground=C_FG)
        listbox.pack(side="left", fill="both", expand=True)
        sb = make_scrollbar(list_frame, "vertical", listbox.yview)
        sb.pack(side="right", fill="y")
        listbox.config(yscrollcommand=sb.set)
        self._collections_listbox = listbox

        def refresh():
            listbox.delete(0, "end")
            for name in self.collections.list_collections():
                listbox.insert("end", name)
        refresh()

        btn_row = tk.Frame(frame, bg=C_BG)
        btn_row.pack(fill="x", pady=(8, 0))
        make_button(btn_row, self.t("collections_load"),
                    lambda: self._collection_load(listbox)).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(btn_row, "DEL",
                    lambda: self._collection_delete(listbox, refresh)).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

    def _collection_save_current(self):
        name = simpledialog.askstring(self.t("collections_title"),
                                       self.t("collections_name"),
                                       parent=self.root)
        if not name:
            return
        self.collections.save_collection(name, self.sources)
        self._log(self.t("collections_saved", name=name))
        if hasattr(self, "_collections_listbox"):
            self._collections_listbox.insert("end", name)

    def _collection_load(self, listbox):
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
        self._mark_stale()
        self._rebuild_list()
        self._log(f"[OK] Loaded {added} addon(s) from '{name}'")

    def _collection_delete(self, listbox, refresh):
        sel = listbox.curselection()
        if not sel:
            return
        name = listbox.get(sel[0])
        if c00l_confirm(self.root, self.t("collections_title"),
                         f"Delete '{name}'?",
                         "Delete", self.t("cancel_btn"), self.t):
            self.collections.delete_collection(name)
            refresh()

    def _build_maintenance_tab(self, parent):
        frame = tk.Frame(parent, bg=C_BG, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=self.t("maintenance_info"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, anchor="w").pack(fill="x", pady=(0, 8))

        listbox = tk.Listbox(frame, font=F_LOG, bg=C_BG, fg=C_FG,
                              selectmode=tk.NONE, bd=0,
                              highlightthickness=1, highlightbackground=C_RED)
        listbox.pack(fill="both", expand=True, pady=(0, 12))

        files = [
            ("gmod_manager.json", app_dir() / CONFIG_FILE),
            ("gmod_session.json", app_dir() / "gmod_session.json"),
            ("gmod_cache.json", app_dir() / "gmod_cache.json"),
            ("gmod_collections.json", app_dir() / "gmod_collections.json"),
            ("gmod_manager.log", app_dir() / LOG_FILE),
        ]
        for name, path in files:
            try:
                size = human_size(path.stat().st_size) if path.exists() else "-"
            except Exception:
                size = "-"
            listbox.insert("end", f"  {name:<28}  {size:>10}")

        actions = tk.Frame(frame, bg=C_BG)
        actions.pack(fill="x")
        make_button(actions, self.t("btn_open_app_folder"),
                    lambda: open_folder(app_dir())).pack(side="left")
        make_button(actions, self.t("btn_clear_cache"),
                    self._clear_cache_file).pack(side="left", padx=(8, 0))
        make_button(actions, self.t("btn_clear_session"),
                    self._clear_session_file).pack(side="left", padx=(8, 0))
        make_button(actions, self.t("btn_reset_config"),
                    self._reset_config_file).pack(side="left", padx=(8, 0))

    def _clear_cache_file(self):
        if not c00l_confirm(self.root, self.t("btn_clear_cache"),
                             self.t("confirm_clear_cache"),
                             "Delete", self.t("cancel_btn"), self.t):
            return
        p = app_dir() / "gmod_cache.json"
        try:
            if p.exists():
                p.unlink()
            self.cache = CacheManager()
            self._log("[OK] Cache cleared.")
        except Exception as e:
            self._log(f"[!] {e}")

    def _clear_session_file(self):
        if not c00l_confirm(self.root, self.t("btn_clear_session"),
                             self.t("confirm_clear_session"),
                             "Delete", self.t("cancel_btn"), self.t):
            return
        p = app_dir() / "gmod_session.json"
        try:
            if p.exists():
                p.unlink()
            self._log("[OK] Session cleared.")
        except Exception as e:
            self._log(f"[!] {e}")

    def _reset_config_file(self):
        if not c00l_confirm(self.root, self.t("btn_reset_config"),
                             self.t("confirm_reset_config"),
                             "Reset", self.t("cancel_btn"), self.t):
            return
        p = app_dir() / CONFIG_FILE
        try:
            if p.exists():
                p.unlink()
            self._log("[OK] Config reset.")
        except Exception as e:
            self._log(f"[!] {e}")

    def _show_about(self):
        c00l_choice(
            self.root, self.t("menu_about"),
            self.t("about_body", version=APP_VERSION),
            [(self.t("close_btn"), "ok", "primary")], self.t)

    def _show_shortcuts(self):
        c00l_choice(
            self.root, self.t("menu_shortcuts"),
            self.t("shortcuts_body"),
            [(self.t("close_btn"), "ok", "primary")], self.t)

    def on_close(self):
        if self.busy:
            if not c00l_confirm(
                    self.root, self.t("menu_exit"),
                    "An operation is in progress. Cancel it and exit?",
                    self.t("menu_exit"), self.t("cancel_btn"), self.t):
                return
        self.cancel_flag.set()
        self._watch_stop.set()
        self._name_worker_running = False
        try:
            self.name_q.put(None)
        except Exception:
            pass
        for _ in range(NESTED_WORKERS):
            try:
                self._nested_q.put(None)
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