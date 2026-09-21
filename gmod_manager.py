"""
GMod Addon Manager v8.1 — c00lgui edition (flicker fix)
-------------------------------------------------------
- Sin parpadeo: los cambios de seleccion y metadata solo actualizan
  la fila afectada, nunca reconstruyen toda la lista.
- Estetica retro: fondo negro, bordes rojos, texto blanco.
- Sin emojis.
- Lista de mods como filas apiladas (sin Treeview).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# ============================================================
# Dependencias opcionales
# ============================================================

try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    pyzipper = None
    HAS_PYZIPPER = False

try:
    from sourcepp import vpkpp as _vpkpp
    HAS_SOURCEPP = True
except Exception:
    _vpkpp = None
    HAS_SOURCEPP = False

# ============================================================
# Estetica
# ============================================================

C_BG       = "#000000"
C_FG       = "#ffffff"
C_FG_DIM   = "#a0a0a0"
C_RED      = "#ff0000"
C_RED_DIM  = "#7a0000"
C_RED_SEL  = "#3a0000"

F_TITLE  = ("Arial", 14, "bold")
F_SUB    = ("Arial", 9)
F_NORM   = ("Arial", 10)
F_SMALL  = ("Arial", 9)
F_BTN    = ("Arial", 10, "bold")
F_HEAD   = ("Arial", 10, "bold")
F_LOG    = ("Courier New", 9)
F_ROW    = ("Arial", 10, "bold")
F_ROW_S  = ("Arial", 9)

# ============================================================
# Constantes
# ============================================================

APP_NAME = "GMod Addon Manager"
APP_VERSION = "8.1"
CONFIG_FILE = "gmod_manager.json"
CACHE_FILE = "gmod_cache.json"
SESSION_FILE = "gmod_session.json"
LOG_FILE = "gmod_manager.log"

TEXT_EXTENSIONS = {".txt", ".json", ".lua", ".md", ".cfg", ".ini", ".xml"}
RAW_MARKERS = ("lua/", "materials/", "models/", "sound/",
               "scripts/", "particles/", "scenes/", "resource/")

KNOWN_DEPENDENCIES = {
    r"\bdrgbase\b": "DrGBase",
    r"\bvj_base\b": "VJ Base",
    r"\bvjbase\b": "VJ Base",
    r"\barc[_]?cw\b": "ArcCW",
    r"\barc9\b": "ARC9",
    r"\btfa[_]?base\b": "TFA Base",
    r"\bwiremod\b": "Wiremod",
    r"\bwire[_]?expression[2]?\b": "Wiremod",
    r"\bpac3\b": "PAC3",
    r"\bsimfphys\b": "Simfphys",
    r"\bcfc[_]?player\b": "CFC",
    r"\bnutscript\b": "NutScript",
    r"\bhelix\b": "Helix",
    r"\bsam[_]?admin\b": "SAM",
    r"\bwac[_]?aircraft\b": "WAC",
}

LUA_DEP_HINTS = {
    r"\bif\s+VJ\s+then\b": "VJ Base",
    r"\bif\s+DrGBase\s+then\b": "DrGBase",
    r"\bif\s+ArcCW\s+then\b": "ArcCW",
    r"\bif\s+simfphys\s+then\b": "Simfphys",
    r"\bif\s+CFC\s+then\b": "CFC",
}

LUA_REF_PATTERNS = [
    r'require\s*\(\s*["\']([^"\']+)["\']',
    r'include\s*\(\s*["\']([^"\']+)["\']',
]

GENERIC_REFS = {
    "shared.lua", "init.lua", "cl_init.lua", "sv_init.lua",
    "loader.lua", "sound.lua", "autorun.lua", "config.lua",
    "sh_config.lua", "cl_util.lua", "sv_util.lua", "shared/util.lua",
}

MAX_TEXT_SIZE = 2 * 1024 * 1024
MAX_ZIP_TOTAL = 8 * 1024 * 1024 * 1024
MAX_NESTED_DEPTH = 3
MAX_NESTED_IN_MEM = 300 * 1024 * 1024


# ============================================================
# Utilidades
# ============================================================

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name)).strip().rstrip(".")
    return name[:100] if name else "Unnamed_Addon"


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def folder_fingerprint(folder: Path) -> str:
    h = hashlib.sha1()
    entries = []
    try:
        for root, _, files in os.walk(folder):
            for f in files:
                p = Path(root) / f
                try:
                    entries.append((str(p.relative_to(folder)), p.stat().st_size))
                except Exception:
                    pass
    except Exception:
        return ""
    for rel, size in sorted(entries):
        h.update(f"{rel}:{size}\n".encode("utf-8"))
    return h.hexdigest()


def open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        logging.warning("No se pudo abrir la carpeta %s: %s", path, e)


def configure_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        fh = logging.FileHandler(app_dir() / LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(fh)
    except Exception:
        pass


def extractor_name() -> str:
    return "sourcepp" if HAS_SOURCEPP else "PureGMA"


# ============================================================
# Parser GMA
# ============================================================

class PureGMA:
    @staticmethod
    def _read_cstr(f) -> str:
        buf = bytearray()
        while True:
            b = f.read(1)
            if not b or b == b"\x00":
                break
            buf.extend(b)
        return buf.decode("utf-8", errors="replace")

    @classmethod
    def read_full_header(cls, stream) -> Optional[dict]:
        if stream.read(4) != b"GMAD":
            return None
        version = struct.unpack("<B", stream.read(1))[0]
        steam_id = struct.unpack("<Q", stream.read(8))[0]
        timestamp = struct.unpack("<Q", stream.read(8))[0]
        if version > 1:
            stream.read(1)
        addon_name = cls._read_cstr(stream)
        description = cls._read_cstr(stream)
        author = cls._read_cstr(stream)
        addon_version = 0
        if version > 2:
            addon_version = struct.unpack("<I", stream.read(4))[0]
        return {
            "gma_version": version,
            "steam_id": steam_id,
            "timestamp": timestamp,
            "name": addon_name,
            "description": description,
            "author": author,
            "addon_version": addon_version,
        }

    @classmethod
    def read_header_file(cls, gma_path: Path) -> Optional[dict]:
        try:
            with open(gma_path, "rb") as f:
                return cls.read_full_header(f)
        except Exception:
            return None

    @classmethod
    def _read_entries(cls, f):
        entries = []
        while True:
            chunk = f.read(4)
            if len(chunk) < 4:
                break
            idx = struct.unpack("<I", chunk)[0]
            if idx == 0:
                break
            path = cls._read_cstr(f)
            size = struct.unpack("<Q", f.read(8))[0]
            crc = struct.unpack("<I", f.read(4))[0]
            entries.append((path, size, crc))
        return entries

    @classmethod
    def read_addon_json(cls, gma_path: Path) -> Optional[dict]:
        try:
            with open(gma_path, "rb") as f:
                h = cls.read_full_header(f)
                if h is None:
                    return None
                entries = cls._read_entries(f)
                offset = f.tell()
                for path, size, _ in entries:
                    if path.lower().endswith("addon.json"):
                        f.seek(offset)
                        data = f.read(size)
                        return json.loads(data.decode("utf-8", errors="replace"))
                    offset += size
        except Exception:
            return None
        return None

    @classmethod
    def extract(cls, gma_path: Path, dest: Path) -> str:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with open(gma_path, "rb") as f:
            h = cls.read_full_header(f)
            if h is None:
                raise ValueError("No es un GMA valido")
            entries = cls._read_entries(f)
            for path, size, _ in entries:
                data = f.read(size)
                if len(data) < size:
                    raise ValueError(f"Datos incompletos: {path}")
                out = dest / path.replace("\\", "/")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
        return h.get("name", "")


class GMAExtractor:
    def extract(self, gma_path: Path, dest: Path) -> str:
        gma_path = Path(gma_path)
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        if HAS_SOURCEPP:
            try:
                pack = _vpkpp.PackedFile.open(str(gma_path))
                if pack is not None:
                    name = ""
                    try:
                        name = (pack.get_metadata("addon_name") or "").strip()
                    except Exception:
                        pass
                    try:
                        pack.extract(str(dest))
                        return name
                    finally:
                        try:
                            pack.close()
                        except Exception:
                            pass
            except Exception:
                pass
        return PureGMA.extract(gma_path, dest)


# ============================================================
# ZIP helpers
# ============================================================

_ZIP_PASSWORDS: dict[str, str] = {}


def _zip_open(path_or_bytes, password: Optional[str] = None):
    if HAS_PYZIPPER:
        zf = pyzipper.AESZipFile(path_or_bytes)
        if password:
            zf.pwd = password.encode("utf-8")
        return zf
    return zipfile.ZipFile(path_or_bytes)


def _try_open_zip(path: Path, password: Optional[str] = None):
    try:
        return zipfile.ZipFile(path)
    except RuntimeError as e:
        msg = str(e).lower()
        if "password" in msg or "encrypted" in msg:
            if HAS_PYZIPPER:
                zf = pyzipper.AESZipFile(path)
                if password:
                    zf.pwd = password.encode("utf-8")
                return zf
        raise


def _open_zip_chain(root_zip: Path, chain: list):
    if not chain:
        return _try_open_zip(root_zip, _ZIP_PASSWORDS.get(str(root_zip)))
    with _try_open_zip(root_zip, _ZIP_PASSWORDS.get(str(root_zip))) as zf:
        data = zf.read(chain[0])
    for name in chain[1:]:
        with _zip_open(io.BytesIO(data)) as inner:
            data = inner.read(name)
    return _zip_open(io.BytesIO(data))


class ZipIndex:
    @dataclass
    class Entry:
        root_zip: Path
        chain: list
        entry: str
        kind: str

    @staticmethod
    def peek_top(zip_path: Path):
        try:
            zf = _try_open_zip(zip_path, _ZIP_PASSWORDS.get(str(zip_path)))
        except RuntimeError as e:
            msg = str(e).lower()
            if "password" in msg or "encrypted" in msg:
                raise RuntimeError(
                    "ZIP cifrado. Instala pyzipper (pip install pyzipper).")
            raise
        try:
            names = [i.filename for i in zf.infolist() if not i.is_dir()]
        finally:
            zf.close()
        gmas = [n for n in names if n.lower().endswith(".gma")]
        nzips = [n for n in names if n.lower().endswith(".zip")]
        folders = []
        if not gmas and not nzips:
            folders = ZipIndex._find_raw_prefixes(names)
        return gmas, folders, nzips

    @staticmethod
    def _find_raw_prefixes(names):
        prefixes = set()
        for n in names:
            low = n.lower()
            for marker in RAW_MARKERS:
                idx = low.find("/" + marker)
                if idx > 0:
                    prefixes.add(n[:idx + 1])
            if low.endswith("addon.json") and n.count("/") <= 2:
                parent = n.rsplit("/", 1)[0] + "/" if "/" in n else ""
                prefixes.add(parent)
        return sorted(prefixes)

    @classmethod
    def build(cls, root_zip, chain=None, depth=0):
        if chain is None:
            chain = []
        if depth > MAX_NESTED_DEPTH:
            return []
        try:
            zf = _open_zip_chain(root_zip, chain)
        except Exception as e:
            logging.warning("Zip anidado %s: %s", chain, e)
            return []
        entries = []
        try:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            names = [i.filename for i in infos]
            size_map = {i.filename: i.file_size for i in infos}
            gmas = [n for n in names if n.lower().endswith(".gma")]
            for g in gmas:
                entries.append(cls.Entry(root_zip, list(chain), g, "gma"))
            if not gmas:
                for p in cls._find_raw_prefixes(names):
                    entries.append(cls.Entry(root_zip, list(chain), p, "folder"))
            if depth < MAX_NESTED_DEPTH:
                for n in names:
                    if not n.lower().endswith(".zip"):
                        continue
                    if size_map.get(n, 0) > MAX_NESTED_IN_MEM:
                        continue
                    entries.extend(cls.build(root_zip, chain + [n], depth + 1))
        finally:
            zf.close()
        return entries

    @classmethod
    def materialize(cls, entry, tmp_dir: Path):
        tmp_dir = Path(tmp_dir)
        zf = _open_zip_chain(entry.root_zip, entry.chain)
        try:
            if entry.kind == "gma":
                zf.extract(entry.entry, tmp_dir)
                return ("gma", tmp_dir / entry.entry)
            prefix = entry.entry
            for n in zf.namelist():
                if n.startswith(prefix) and not n.endswith("/"):
                    zf.extract(n, tmp_dir)
            return ("folder", tmp_dir / prefix)
        finally:
            zf.close()


# ============================================================
# Metadatos
# ============================================================

def read_gma_metadata_file(gma_path: Path) -> dict:
    h = PureGMA.read_header_file(gma_path)
    if not h:
        return {}
    aj = PureGMA.read_addon_json(gma_path)
    if aj:
        h.setdefault("addon_json", aj)
    return h


def read_gma_metadata_stream(stream) -> dict:
    try:
        h = PureGMA.read_full_header(stream)
        return h or {}
    except Exception:
        return {}


def resolve_gma_metadata_in_zip(root_zip: Path, chain: list, entry: str) -> dict:
    try:
        zf = _open_zip_chain(root_zip, chain)
        try:
            with zf.open(entry) as stream:
                return read_gma_metadata_stream(stream)
        finally:
            zf.close()
    except Exception:
        return {}


def resolve_folder_metadata_in_zip(root_zip: Path, chain: list, prefix: str) -> dict:
    meta = {}
    try:
        zf = _open_zip_chain(root_zip, chain)
        try:
            try:
                data = zf.read(prefix + "addon.json")
                meta["addon_json"] = json.loads(
                    data.decode("utf-8", errors="replace"))
            except Exception:
                pass
        finally:
            zf.close()
    except Exception:
        pass
    return meta


def resolve_folder_metadata(path: Path) -> dict:
    meta = {}
    try:
        aj = path / "addon.json"
        if aj.exists():
            with open(aj, encoding="utf-8", errors="ignore") as f:
                meta["addon_json"] = json.load(f)
    except Exception:
        pass
    return meta


# ============================================================
# Análisis
# ============================================================

class Analyzer:
    @staticmethod
    def _iter_files(d):
        for root, _, files in os.walk(d):
            for f in files:
                yield Path(root) / f

    @staticmethod
    def _read(p):
        try:
            if p.stat().st_size > MAX_TEXT_SIZE:
                return ""
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    def scan(self, folder):
        deps, refs, counts = set(), [], {}
        for p in self._iter_files(folder):
            ext = p.suffix.lower() or "[sin ext]"
            counts[ext] = counts.get(ext, 0) + 1
            if p.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            content = self._read(p)
            if not content:
                continue
            low = content.lower()
            for pat, name in KNOWN_DEPENDENCIES.items():
                if re.search(pat, low):
                    deps.add(name)
            if p.suffix.lower() == ".lua":
                for pat, name in LUA_DEP_HINTS.items():
                    if re.search(pat, content):
                        deps.add(name)
                for pat in LUA_REF_PATTERNS:
                    for m in re.findall(pat, content, re.IGNORECASE):
                        refs.append(m)
        refs = [r for r in refs
                if r.lower().replace("\\", "/").split("/")[-1] not in GENERIC_REFS]
        return {
            "file_count": sum(counts.values()),
            "deps": sorted(deps),
            "refs": sorted(set(refs)),
        }


# ============================================================
# Caché / Sesión
# ============================================================

class CacheManager:
    def __init__(self):
        self.path = app_dir() / CACHE_FILE
        self.data: dict = {"version": 1, "entries": {}}
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict) and "entries" in d:
                    self.data = d
        except Exception as e:
            logging.warning("Cache load: %s", e)

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
        except Exception as e:
            logging.warning("Cache save: %s", e)

    def get(self, key):
        return self.data["entries"].get(key)

    def put(self, key, value):
        self.data["entries"][key] = value


class SessionManager:
    def __init__(self):
        self.path = app_dir() / SESSION_FILE

    def save(self, sources):
        data = []
        for s in sources:
            item = {"kind": s.kind, "name": s.name,
                    "selected": s.selected, "origin": s.origin}
            if s.kind in ("gma", "folder") and s.path:
                item["path"] = str(s.path)
            elif s.kind in ("zip_gma", "zip_folder"):
                item["root_zip"] = str(s.root_zip) if s.root_zip else ""
                item["chain"] = list(s.chain)
                item["entry"] = s.entry
            data.append(item)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"sources": data}, f, indent=1)
        except Exception as e:
            logging.warning("Session save: %s", e)

    def load(self):
        sources = []
        try:
            if not self.path.exists():
                return sources
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("sources", []):
                kind = item.get("kind")
                src = None
                if kind == "gma":
                    p = Path(item.get("path", ""))
                    if p.exists():
                        src = Source(kind="gma", path=p,
                                     name=item.get("name", ""),
                                     origin=item.get("origin", ""))
                elif kind == "folder":
                    p = Path(item.get("path", ""))
                    if p.exists():
                        src = Source(kind="folder", path=p,
                                     name=item.get("name", ""),
                                     origin=item.get("origin", ""))
                elif kind in ("zip_gma", "zip_folder"):
                    zp = Path(item.get("root_zip", ""))
                    if zp.exists():
                        src = Source(kind=kind, root_zip=zp,
                                     chain=item.get("chain", []),
                                     entry=item.get("entry", ""),
                                     name=item.get("name", ""),
                                     origin=item.get("origin", ""))
                if src:
                    src.selected = bool(item.get("selected", True))
                    sources.append(src)
        except Exception as e:
            logging.warning("Session load: %s", e)
        return sources


# ============================================================
# Modelo
# ============================================================

@dataclass
class Source:
    kind: str
    path: Optional[Path] = None
    root_zip: Optional[Path] = None
    chain: list = field(default_factory=list)
    entry: str = ""
    name: str = ""
    origin: str = ""
    metadata: dict = field(default_factory=dict)
    selected: bool = True

    @property
    def display(self) -> str:
        tag = {"gma": "GMA", "folder": "DIR",
               "zip_gma": "ZGMA", "zip_folder": "ZDIR"}[self.kind]
        n = self.name or (self.path.name if self.path else "?")
        return f"[{tag}] {n}"

    def origin_short(self) -> str:
        if not self.origin:
            return ""
        depth = len(self.chain)
        base = self.origin
        if len(base) > 26:
            base = "..." + base[-23:]
        return f"{base} d{depth}" if depth else base

    def fingerprint(self) -> str:
        if self.kind == "gma" and self.path:
            return "gma:" + file_sha1(self.path)
        if self.kind == "folder" and self.path:
            return "dir:" + folder_fingerprint(self.path)
        if self.kind in ("zip_gma", "zip_folder") and self.root_zip:
            z = file_sha1(self.root_zip)
            chain = ":".join(self.chain)
            return f"zip:{z}:{chain}:{self.entry}"
        return ""

    def target_name(self) -> str:
        n = self.name or (self.path.stem if self.path else "addon")
        return safe_name(n)


# ============================================================
# Widgets con estetica c00lgui
# ============================================================

def make_panel(parent, title=None):
    outer = tk.Frame(parent, bg=C_RED, bd=0)
    outer.pack(fill="x", pady=(0, 8))
    inner = tk.Frame(outer, bg=C_BG)
    inner.pack(fill="x", padx=1, pady=1)
    if title:
        head = tk.Label(inner, text=title, bg=C_BG, fg=C_FG,
                        font=F_HEAD, anchor="w", padx=8, pady=4)
        head.pack(fill="x")
        sep = tk.Frame(inner, bg=C_RED, height=1)
        sep.pack(fill="x")
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
        btn.config(bg=C_RED, fg=C_FG, activebackground="#cc0000")
    return btn


def make_entry(parent, textvariable=None, **kw):
    return tk.Entry(
        parent, textvariable=textvariable,
        bg=C_BG, fg=C_FG, insertbackground=C_RED,
        relief="flat", bd=0, font=F_NORM,
        highlightbackground=C_RED, highlightcolor=C_RED,
        highlightthickness=1, **kw)


# ============================================================
# UI
# ============================================================

class GModAddonManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("520x900")
        self.root.minsize(420, 640)
        self.root.configure(bg=C_BG)

        self.sources: list[Source] = []
        self.busy = False
        self.cancel_flag = threading.Event()
        self.last_results = None
        self.filter_text = tk.StringVar()
        self.group_mode = tk.BooleanVar(value=False)

        # Refs de widgets por fila (id(source) -> dict)
        self._row_refs: dict[int, dict] = {}
        # Frames de fila en orden (para empaquetar)
        self._row_frames: list = []
        # Timer para doble clic
        self._click_timer = None
        self._pending_click_sid = None

        self.status = tk.StringVar(value="Listo.")

        self.extractor = GMAExtractor()
        self.analyzer = Analyzer()
        self.cache = CacheManager()
        self.session = SessionManager()

        self.log_q: queue.Queue[str] = queue.Queue()
        self.name_q: queue.Queue = queue.Queue()
        self._name_worker_running = True
        self._pending_row_refresh: set = set()
        self._refresh_scheduled = False

        self._build()
        self._poll_log()
        self._load_cfg()
        self._start_name_worker()
        self._load_session()
        self._auto_detect_dest()

        self._log(f"[i] Extractor: {extractor_name()}")
        self._log(f"[i] pyzipper: {'si' if HAS_PYZIPPER else 'no'}")
        self._log(f"[i] sourcepp: {'si' if HAS_SOURCEPP else 'no'}")

    def _build(self):
        # Barra de titulo
        top = tk.Frame(self.root, bg=C_BG)
        top.pack(fill="x", side="top")
        title_bar = tk.Frame(top, bg=C_RED)
        title_bar.pack(fill="x")
        title_inner = tk.Frame(title_bar, bg=C_BG)
        title_inner.pack(fill="x", padx=1, pady=1)
        tk.Label(title_inner, text=APP_NAME, bg=C_BG, fg=C_FG,
                 font=F_TITLE, pady=8).pack()
        tk.Label(title_inner, text=f"v{APP_VERSION}",
                 bg=C_BG, fg=C_FG_DIM, font=F_SUB).pack(pady=(0, 6))

        # Contenedor scroll
        outer = tk.Frame(self.root, bg=C_BG)
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, bg=C_BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        vscroll = tk.Scrollbar(outer, orient="vertical",
                                command=self.canvas.yview,
                                bg=C_BG, troughcolor=C_BG, bd=0,
                                activebackground=C_RED)
        vscroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.body = tk.Frame(self.canvas, bg=C_BG, padx=8, pady=8)
        self._cw = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._cw, width=e.width))

        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_wheel_linux)

        # === Añadir ===
        body = make_panel(self.body, "AÑADIR")
        self.path_entry = make_entry(body)
        self.path_entry.pack(fill="x", pady=(0, 6))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        make_button(row, "AÑADIR", self._add_manual).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, "ARCHIVOS", self._browse).pack(
            side="left", expand=True, fill="x", padx=2)
        make_button(row, "CARPETA", self._browse_folder).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        # === Filtro ===
        body = make_panel(self.body, "FILTRO")
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        tk.Label(row, text="Buscar:", bg=C_BG, fg=C_FG, font=F_NORM).pack(side="left")
        ent = make_entry(row, textvariable=self.filter_text)
        ent.pack(side="left", fill="x", expand=True, padx=(4, 4))
        make_button(row, "X", lambda: self.filter_text.set("")).pack(side="left")
        self.filter_text.trace_add("write", lambda *_: self._rebuild_list())

        cb = tk.Checkbutton(
            body, text="Agrupar por dependencia",
            variable=self.group_mode, command=self._rebuild_list,
            bg=C_BG, fg=C_FG, activebackground=C_BG, activeforeground=C_FG,
            selectcolor=C_BG, font=F_NORM, highlightthickness=0, bd=0)
        cb.pack(anchor="w", pady=(6, 0))

        # === Lista de mods ===
        list_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        list_panel.pack(fill="both", expand=True, pady=(0, 8))
        list_inner = tk.Frame(list_panel, bg=C_BG)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)

        list_head = tk.Label(list_inner, text="ADDONS", bg=C_BG, fg=C_FG,
                              font=F_HEAD, anchor="w", padx=8, pady=4)
        list_head.pack(fill="x")
        tk.Frame(list_inner, bg=C_RED, height=1).pack(fill="x")

        # Contenedor scroll para las filas de mods
        rows_wrap = tk.Frame(list_inner, bg=C_BG)
        rows_wrap.pack(fill="both", expand=True)

        self.rows_canvas = tk.Canvas(rows_wrap, bg=C_BG, highlightthickness=0,
                                       height=200)
        self.rows_canvas.pack(side="left", fill="both", expand=True)
        rows_sb = tk.Scrollbar(rows_wrap, orient="vertical",
                                command=self.rows_canvas.yview,
                                bg=C_BG, troughcolor=C_BG, bd=0,
                                activebackground=C_RED)
        rows_sb.pack(side="right", fill="y")
        self.rows_canvas.configure(yscrollcommand=rows_sb.set)

        self.rows_frame = tk.Frame(self.rows_canvas, bg=C_BG)
        self._rows_cw = self.rows_canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind(
            "<Configure>",
            lambda e: self.rows_canvas.configure(
                scrollregion=self.rows_canvas.bbox("all")))
        self.rows_canvas.bind(
            "<Configure>",
            lambda e: self.rows_canvas.itemconfig(self._rows_cw, width=e.width))

        # Scroll propio de la lista
        self.rows_canvas.bind("<MouseWheel>",
            lambda e: self.rows_canvas.yview_scroll(int(-e.delta/120), "units"))
        self.rows_canvas.bind("<Button-4>",
            lambda e: self.rows_canvas.yview_scroll(-1, "units"))
        self.rows_canvas.bind("<Button-5>",
            lambda e: self.rows_canvas.yview_scroll(1, "units"))

        # Botones de lista
        lb_row1 = tk.Frame(list_inner, bg=C_BG)
        lb_row1.pack(fill="x", padx=4, pady=(6, 2))
        make_button(lb_row1, "TODO", lambda: self._set_all_selected(True)
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb_row1, "NADA", lambda: self._set_all_selected(False)
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb_row1, "INVERTIR", self._invert_selection
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        lb_row2 = tk.Frame(list_inner, bg=C_BG)
        lb_row2.pack(fill="x", padx=4, pady=(0, 6))
        make_button(lb_row2, "QUITAR", self._remove_selected
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb_row2, "LIMPIAR", self._clear
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb_row2, "EXPORTAR", self._export_menu
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # === Destino ===
        body = make_panel(self.body, "DESTINO")
        self.dest_entry = make_entry(body)
        self.dest_entry.pack(fill="x", pady=(0, 6))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        make_button(row, "ELEGIR", self._browse_dest).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, "ABRIR", self._open_dest).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        # === Acciones ===
        act = tk.Frame(self.body, bg=C_BG)
        act.pack(fill="x", pady=(0, 4))
        self.btn_analyze = tk.Button(
            act, text="ANALIZAR", command=self._analyze,
            bg=C_RED, fg=C_FG, activebackground="#cc0000", activeforeground=C_FG,
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightthickness=1, cursor="hand2")
        self.btn_analyze.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.btn_extract = tk.Button(
            act, text="EXTRAER", command=self._extract,
            bg=C_BG, fg=C_FG, activebackground=C_RED, activeforeground=C_FG,
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightcolor=C_RED,
            highlightthickness=1, cursor="hand2")
        self.btn_extract.pack(side="left", expand=True, fill="x", padx=(2, 0))

        act2 = tk.Frame(self.body, bg=C_BG)
        act2.pack(fill="x", pady=(0, 8))
        make_button(act2, "RESUMEN", self._show_last_summary
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(act2, "CONFLICTOS", self._detect_conflicts
                    ).pack(side="left", expand=True, fill="x", padx=2)
        self.btn_cancel = make_button(act2, "CANCELAR", self._cancel)
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(side="left", expand=True, fill="x", padx=(2, 0))

        # === Progreso ===
        prog_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        prog_panel.pack(fill="x", pady=(0, 4))
        prog_inner = tk.Frame(prog_panel, bg=C_BG)
        prog_inner.pack(fill="x", padx=1, pady=1)
        self.progress = tk.Canvas(prog_inner, bg=C_BG, height=14,
                                    highlightthickness=0)
        self.progress.pack(fill="x", padx=4, pady=4)
        self._progress_max = 100
        self._progress_val = 0

        self.progress_label = tk.Label(self.body, text="Listo.",
                                         bg=C_BG, fg=C_FG_DIM, font=F_SMALL,
                                         anchor="w")
        self.progress_label.pack(fill="x", pady=(0, 8))

        # === Registro ===
        log_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        log_panel.pack(fill="both", expand=True, pady=(0, 0))
        log_inner = tk.Frame(log_panel, bg=C_BG)
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(log_inner, bg=C_BG)
        head.pack(fill="x")
        tk.Label(head, text="REGISTRO", bg=C_BG, fg=C_FG, font=F_HEAD,
                 anchor="w", padx=8, pady=4).pack(side="left")
        make_button(head, "ABRIR", self._open_log_file).pack(side="right", padx=(0, 4))
        make_button(head, "LIMPIAR", self._clear_log).pack(side="right", padx=(0, 4))
        make_button(head, "COPIAR", self._copy_log).pack(side="right", padx=(0, 4))
        tk.Frame(log_inner, bg=C_RED, height=1).pack(fill="x")

        log_wrap = tk.Frame(log_inner, bg=C_BG)
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(log_wrap, height=12, wrap="word",
                            font=F_LOG, bg=C_BG, fg=C_FG,
                            insertbackground=C_RED, relief="flat",
                            padx=6, pady=4, bd=0,
                            highlightbackground=C_RED,
                            highlightthickness=1)
        self.log.pack(side="left", fill="both", expand=True)
        lsb = tk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview,
                            bg=C_BG, troughcolor=C_BG, bd=0,
                            activebackground=C_RED)
        lsb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=lsb.set, state="disabled")

        # Barra de estado
        status = tk.Label(self.root, textvariable=self.status,
                           bg=C_RED, fg=C_FG, font=F_SMALL,
                           anchor="w", padx=8, pady=3)
        status.pack(side="bottom", fill="x")

    # ---------------- Scroll ----------------

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # ---------------- Log / progreso ----------------

    def _log(self, msg):
        self.log_q.put(str(msg))

    def _poll_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log.config(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
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
            self._log("[OK] Registro copiado.")
        except Exception as e:
            self._log(f"[!] No se pudo copiar: {e}")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _open_log_file(self):
        p = app_dir() / LOG_FILE
        if p.exists():
            open_folder(p.parent)
        else:
            messagebox.showinfo("Log", "Todavia no hay archivo de log.")

    def _set_progress(self, value, maximum=100, text=""):
        def upd():
            self._progress_max = max(1, maximum)
            self._progress_val = value
            self._draw_progress()
            if text:
                self.progress_label.config(text=text)
            else:
                pct = int(100 * value / max(1, maximum))
                self.progress_label.config(text=f"{value}/{maximum} ({pct}%)")
        self.root.after(0, upd)

    def _draw_progress(self):
        self.progress.delete("all")
        w = self.progress.winfo_width() or 300
        pct = max(0.0, min(1.0, self._progress_val / self._progress_max))
        self.progress.create_rectangle(0, 0, w, 14, fill=C_BG, outline=C_RED)
        if pct > 0:
            self.progress.create_rectangle(1, 1, w * pct, 13,
                                             fill=C_RED, outline="")

    def _reset_progress(self):
        def upd():
            self._progress_val = 0
            self._draw_progress()
            self.progress_label.config(text="Listo.")
        self.root.after(0, upd)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    # ---------------- Config ----------------

    def _cfg_file(self):
        return app_dir() / CONFIG_FILE

    def _load_cfg(self):
        try:
            with open(self._cfg_file(), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("dest"):
                self.dest_entry.insert(0, data["dest"])
        except Exception:
            pass

    def _save_cfg(self):
        try:
            with open(self._cfg_file(), "w", encoding="utf-8") as f:
                json.dump({"dest": self.dest_entry.get()}, f, indent=2)
        except Exception:
            pass

    def _auto_detect_dest(self):
        if self.dest_entry.get().strip():
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
            messagebox.showinfo("Destino", "Aun no hay carpeta destino.")
            return
        p = Path(d)
        if not p.exists():
            messagebox.showwarning("No existe", f"{p}")
            return
        open_folder(p)

    # ---------------- Sesión ----------------

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
            self._log(f"[i] Sesion restaurada: {len(sources)} addon(s).")

    # ---------------- Añadir ----------------

    def _browse(self):
        try:
            files = filedialog.askopenfilenames(
                title="Selecciona .gma o .zip",
                filetypes=[("Addons", "*.gma *.zip"), ("Todos", "*.*")])
        except Exception as e:
            self._log(f"[!] filedialog no disponible: {e}")
            return
        for f in files:
            self._register(Path(f))
        self._rebuild_list()

    def _browse_folder(self):
        try:
            d = filedialog.askdirectory(title="Selecciona la carpeta")
        except Exception as e:
            self._log(f"[!] filedialog no disponible: {e}")
            return
        if d:
            self._register(Path(d))
            self._rebuild_list()

    def _browse_dest(self):
        try:
            d = filedialog.askdirectory(title="Carpeta destino")
        except Exception as e:
            self._log(f"[!] filedialog no disponible: {e}")
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
            messagebox.showerror("No existe", f"No se encuentra:\n{raw}")
            return
        self._register(p)
        self.path_entry.delete(0, "end")
        self._rebuild_list()

    def _register(self, path: Path):
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
            self._log(f"[!] Formato no soportado: {path.name}")

    def _add_gma(self, path: Path, origin: str = ""):
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

    def _add_folder(self, path: Path, origin: str = "", name: str = ""):
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

    def _add_zip(self, zip_path: Path):
        try:
            gmas, folders, nested = ZipIndex.peek_top(zip_path)
        except Exception as e:
            self._log(f"[ERROR] {zip_path.name}: {e}")
            messagebox.showerror("Error al leer zip",
                                 f"{zip_path.name}\n\n{e}")
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
            self._log(f"[i] {zip_path.name}: {len(nested)} zip(s) anidado(s), "
                      f"indexando...")
            self._set_busy(True)
            threading.Thread(
                target=self._run_index_nested,
                args=(zip_path, nested), daemon=True).start()
        else:
            self._log(f"[OK] {zip_path.name}: {direct} addon(s)")

    def _run_index_nested(self, root_zip, nested_names):
        total = len(nested_names)
        added = 0
        try:
            for i, name in enumerate(nested_names, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelado.")
                    break
                self._set_progress(i - 1, total,
                                   f"Indexando {i}/{total}: {name}")
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
                                   f"Indexando {i}/{total}: {name}")
            self._log(f"[OK] Indexado anidado: {added} addon(s)")
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, self._reset_progress)
            self.root.after(0, self._rebuild_list)

    def _register_from_entry(self, root_zip: Path, e):
        if e.kind == "gma":
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_gma",
                                 name=Path(e.entry).stem, origin=root_zip.name)
        else:
            nm = e.entry.rstrip("/").split("/")[-1] or root_zip.stem
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_folder",
                                 name=nm, origin=root_zip.name)

    # ---------------- Lista de mods (filas apiladas) ----------------

    def _rebuild_list(self):
        """Reconstruye solo cuando cambia el conjunto de mods o el filtro."""
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
                key = " + ".join(deps) if deps else "Sin dependencias"
                groups.setdefault(key, []).append(s)
            for key in sorted(groups, key=lambda k: (k == "Sin dependencias", k)):
                self._add_group_header(f"{key} ({len(groups[key])})")
                for s in groups[key]:
                    self._add_row(s)

        # Ajustar altura del canvas al contenido (sincrono)
        self.rows_frame.update_idletasks()
        try:
            h = self.rows_frame.winfo_reqheight()
            self.rows_canvas.config(height=min(max(h, 80), 260))
        except Exception:
            pass

    def _add_group_header(self, text):
        h = tk.Label(self.rows_frame, text=text, bg=C_RED, fg=C_FG,
                     font=F_HEAD, anchor="w", padx=8, pady=4)
        h.pack(fill="x", pady=(6, 2))
        self._row_frames.append(h)

    def _add_row(self, s: Source):
        sid = id(s)

        # Fila
        outer = tk.Frame(self.rows_frame, bg=C_RED if s.selected else C_RED_DIM, bd=0)
        outer.pack(fill="x", pady=1)

        bg = C_RED_SEL if s.selected else C_BG
        inner = tk.Frame(outer, bg=bg, cursor="hand2")
        inner.pack(fill="x", padx=1, pady=1)

        # Indicador
        indicator = tk.Label(inner, text="X" if s.selected else " ",
                              bg=bg, fg=C_RED if s.selected else C_FG_DIM,
                              font=F_ROW, width=2, anchor="w", padx=6, pady=6)
        indicator.pack(side="left", fill="y")

        # Nombre
        name_lbl = tk.Label(inner, text=s.display, bg=bg, fg=C_FG,
                             font=F_ROW, anchor="w", padx=2, pady=6)
        name_lbl.pack(side="left", fill="x", expand=True)

        # Info (deps + archivos)
        info_text = self._info_text(s)
        info_lbl = None
        if info_text:
            info_lbl = tk.Label(inner, text=info_text, bg=bg, fg=C_FG_DIM,
                                 font=F_ROW_S, anchor="e", padx=8, pady=6)
            info_lbl.pack(side="right", fill="y")

        # Guardar refs
        refs = {
            "outer": outer,
            "inner": inner,
            "indicator": indicator,
            "name_lbl": name_lbl,
            "info_lbl": info_lbl,
        }
        self._row_refs[sid] = refs
        self._row_frames.append(outer)

        # Bindings: single click en todos los hijos, doble click via timer
        widgets = [outer, inner, indicator, name_lbl]
        if info_lbl is not None:
            widgets.append(info_lbl)

        for w in widgets:
            w.bind("<Button-1>", lambda e, src=s: self._on_row_click(src), add="+")
            w.bind("<Double-Button-1>",
                    lambda e, src=s: self._on_row_double(src), add="+")

    def _info_text(self, s: Source) -> str:
        m = s.metadata or {}
        parts = []
        deps = m.get("deps")
        if deps:
            parts.append(" | ".join(deps))
        files = m.get("file_count")
        if files:
            parts.append(f"{files}f")
        return "  ".join(parts)

    def _on_row_click(self, s: Source):
        # Cancelar cualquier timer pendiente (posible doble clic)
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
            # Si era el mismo source, lo tratamos como doble clic
            if self._pending_click_sid == id(s):
                self._pending_click_sid = None
                return

        # Programar toggle tras un pequeño delay para ver si viene doble clic
        self._pending_click_sid = id(s)
        self._click_timer = self.root.after(220, lambda: self._commit_click(s))

    def _commit_click(self, s: Source):
        self._click_timer = None
        self._pending_click_sid = None
        s.selected = not s.selected
        self._refresh_row(s)

    def _on_row_double(self, s: Source):
        # Cancelar cualquier toggle pendiente
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
            self._pending_click_sid = None
        self._on_row_double_action(s)

    def _on_row_double_action(self, s: Source):
        action = messagebox.askyesnocancel(
            "Accion",
            f"Addon: {s.name}\n\n"
            "Si = Renombrar\n"
            "No = Extraer a temporal y abrir\n"
            "Cancelar = Nada")
        if action is None:
            return
        if action:
            self._rename_source(s)
        else:
            self._open_source_temp(s)

    def _refresh_row(self, s: Source):
        """Actualiza solo la fila del source dado. Sin rebuild."""
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
            # No había info_lbl, crearlo dinámicamente
            info_lbl = tk.Label(inner, text=new_info, bg=bg, fg=C_FG_DIM,
                                 font=F_ROW_S, anchor="e", padx=8, pady=6)
            info_lbl.pack(side="right", fill="y")
            info_lbl.bind("<Button-1>",
                          lambda e, src=s: self._on_row_click(src), add="+")
            info_lbl.bind("<Double-Button-1>",
                          lambda e, src=s: self._on_row_double(src), add="+")
            refs["info_lbl"] = info_lbl

    def _rename_source(self, s: Source):
        new = simpledialog.askstring("Renombrar", "Nuevo nombre:",
                                      initialvalue=s.name)
        if not new:
            return
        s.name = new.strip()
        self._refresh_row(s)

    def _open_source_temp(self, s: Source):
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
            messagebox.showerror("Error", str(e))

    def _set_all_selected(self, val: bool):
        for s in self.sources:
            s.selected = val
            self._refresh_row(s)

    def _invert_selection(self):
        for s in self.sources:
            s.selected = not s.selected
            self._refresh_row(s)

    def _remove_selected(self):
        self.sources = [s for s in self.sources if not s.selected]
        self._rebuild_list()

    def _clear(self):
        self.sources.clear()
        self._rebuild_list()

    # ---------------- Resolución de nombres / metadata ----------------

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

    def _apply_metadata(self, source_id, meta: dict):
        """Aplica metadata sin rebuild. Solo refresca la fila afectada."""
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

        # Si estamos agrupando por dependencia y cambió la dep, hay que
        # reconstruir porque la agrupación cambia. En ese caso sí rebuild.
        if self.group_mode.get():
            self._rebuild_list()
        else:
            self._refresh_row(target)

    # ---------------- Materialización ----------------

    def _materialize(self, source: Source, tmp_dir: Path):
        if source.kind == "gma":
            return ("gma", source.path)
        if source.kind == "folder":
            return ("folder", source.path)
        if source.kind in ("zip_gma", "zip_folder"):
            entry = ZipIndex.Entry(
                root_zip=source.root_zip,
                chain=list(source.chain),
                entry=source.entry,
                kind="gma" if source.kind == "zip_gma" else "folder")
            return ZipIndex.materialize(entry, tmp_dir)
        raise ValueError(f"kind desconocido: {source.kind}")

    # ---------------- Orden por dependencias ----------------

    def _order_sources_by_deps(self, sources):
        n = len(sources)
        if n <= 1:
            return list(sources)

        def norm(s):
            t = (s.name or "").lower()
            t = re.sub(r"[\[\]\(\)\{\}]", " ", t)
            t = re.sub(r"[^a-z0-9]+", " ", t)
            return t.strip()

        name_map = {id(s): norm(s) for s in sources}
        BASE_HINTS = ("base", "core", "manager", "framework",
                      "system", "loader", "library", "shared")

        def is_base_like(s):
            return any(h in name_map[id(s)] for h in BASE_HINTS)

        def prefix_of(s):
            t = s.name or ""
            for sep in ("|", " - ", " : ", ":"):
                if sep in t:
                    return t.split(sep)[0].strip().lower()
            return ""

        edges = {id(s): set() for s in sources}
        indeg = {id(s): 0 for s in sources}

        def add_edge(u_id, v_id):
            if u_id == v_id:
                return
            if v_id not in edges[u_id]:
                edges[u_id].add(v_id)
                indeg[v_id] += 1

        for s in sources:
            deps = (s.metadata or {}).get("deps") or []
            for dep in deps:
                dep_norm = re.sub(r"[^a-z0-9]+", "", dep.lower())
                if not dep_norm:
                    continue
                for other in sources:
                    if other is s:
                        continue
                    other_norm = re.sub(r"[^a-z0-9]+", "", name_map[id(other)])
                    if dep_norm in other_norm:
                        add_edge(id(other), id(s))

        for a in sources:
            if not is_base_like(a):
                continue
            a_tokens = set(name_map[id(a)].split())
            for b in sources:
                if a is b or is_base_like(b):
                    continue
                b_tokens = set(name_map[id(b)].split())
                if a_tokens & b_tokens:
                    add_edge(id(a), id(b))

        groups = {}
        for s in sources:
            p = prefix_of(s)
            if p:
                groups.setdefault(p, []).append(s)
        for group in groups.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda x: len(x.name or ""))
            for i in range(len(ordered) - 1):
                add_edge(id(ordered[i]), id(ordered[i + 1]))

        original_index = {id(s): i for i, s in enumerate(sources)}
        ready = [s for s in sources if indeg[id(s)] == 0]
        ready.sort(key=lambda x: original_index[id(x)])

        result = []
        while ready:
            node = ready.pop(0)
            result.append(node)
            for nxt_id in edges[id(node)]:
                indeg[nxt_id] -= 1
                if indeg[nxt_id] == 0:
                    for s in sources:
                        if id(s) == nxt_id:
                            ready.append(s)
                            break
            ready.sort(key=lambda x: original_index[id(x)])

        if len(result) < n:
            seen = {id(s) for s in result}
            for s in sources:
                if id(s) not in seen:
                    result.append(s)

        return result

    # ---------------- Estado ----------------

    def _set_busy(self, busy: bool):
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

    def _cancel(self):
        if not self.busy:
            self._log("[i] No hay operacion en curso.")
            return
        self.cancel_flag.set()
        self._log("[!] Cancelacion solicitada...")

    # ---------------- Analizar ----------------

    def _analyze(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            messagebox.showinfo("Vacio", "No hay addons marcados.")
            return
        self._set_busy(True)
        threading.Thread(target=self._run_analyze,
                          args=(active,), daemon=True).start()

    def _run_analyze(self, sources):
        sources = self._order_sources_by_deps(sources)
        total = len(sources)
        results = []
        cancelled = False
        cache_hits = 0
        try:
            self._log("")
            self._log(f"=== ANALISIS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log("[i] Orden por dependencias aplicado.")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelado.")
                    cancelled = True
                    break
                self._set_progress(i - 1, total, f"Analizando {i}/{total}...")
                self._log(f"[{i}/{total}] {s.display}")

                display_name = s.name or (s.path.name if s.path else "?")
                fp = s.fingerprint()
                cached = self.cache.get(fp) if fp else None

                entry = {"name": display_name, "deps": [], "file_count": 0,
                         "refs": 0, "error": None, "cached": False}

                if cached:
                    cache_hits += 1
                    entry["deps"] = cached.get("deps", [])
                    entry["file_count"] = cached.get("file_count", 0)
                    entry["refs"] = cached.get("refs", 0)
                    entry["cached"] = True
                    s.metadata.update({"deps": entry["deps"],
                                        "file_count": entry["file_count"]})
                    self._log(f"  [CACHE] Archivos: {entry['file_count']}")
                    if entry["deps"]:
                        self._log(f"  Deps: {', '.join(entry['deps'])}")
                    else:
                        self._log("  Sin dependencias.")
                    results.append(entry)
                    # Refresh in-place
                    self.root.after(0, lambda src=s: self._refresh_row(src))
                    self._set_progress(i, total, f"Analizando {i}/{total}...")
                    continue

                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2)
                                r = self.analyzer.scan(t2)
                        else:
                            r = self.analyzer.scan(real)

                    entry["file_count"] = r["file_count"]
                    entry["deps"] = r["deps"]
                    entry["refs"] = len(r["refs"])
                    s.metadata.update({"deps": r["deps"],
                                        "file_count": r["file_count"]})

                    self._log(f"  Archivos: {r['file_count']}")
                    if r["deps"]:
                        self._log(f"  Deps: {', '.join(r['deps'])}")
                    else:
                        self._log("  Sin dependencias.")
                    if r["refs"]:
                        self._log(f"  Refs Lua: {len(r['refs'])}")
                        for ref in r["refs"][:15]:
                            self._log(f"    - {ref}")
                        if len(r["refs"]) > 15:
                            self._log(f"    ... y {len(r['refs']) - 15} mas")

                    if fp:
                        self.cache.put(fp, {"deps": r["deps"],
                                             "file_count": r["file_count"],
                                             "refs": len(r["refs"])})

                    self.root.after(0, lambda src=s: self._refresh_row(src))
                except Exception as e:
                    entry["error"] = str(e)
                    self._log(f"  [ERROR] {e}")
                    logging.error("Analyze %s: %s\n%s", s.display, e,
                                   traceback.format_exc())

                results.append(entry)
                self._set_progress(i, total, f"Analizando {i}/{total}...")

            self.cache.save()
            if cache_hits:
                self._log(f"[i] Cache: {cache_hits}/{total} hits")
            self._log("=== FIN ANALISIS ===")
            if results:
                self.last_results = (results, cancelled)
                self.root.after(0, lambda: self._show_summary(results, cancelled))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, self._reset_progress)

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
            lines.append("ANALISIS CANCELADO (parcial)")
            lines.append("")
        lines.append(f"Analizados: {total}  |  OK: {ok}  |  Errores: {failed}")
        if cached:
            lines.append(f"Cache: {cached}/{total}")
        lines.append(f"Archivos: {total_files}  |  Refs Lua: {total_refs}")
        lines.append("")

        if dep_map:
            lines.append("=== DEPENDENCIAS ===")
            for dep in sorted(dep_map, key=lambda k: -len(dep_map[k])):
                mods = dep_map[dep]
                plural = "es" if len(mods) != 1 else ""
                lines.append(f"\n> {dep}  ({len(mods)} addon{plural})")
                for m in mods:
                    lines.append(f"    {m}")
            lines.append("")
        else:
            lines.append("Sin dependencias conocidas.")
            lines.append("")

        if no_deps:
            lines.append(f"=== SIN DEPENDENCIAS ({len(no_deps)}) ===")
            for m in no_deps:
                lines.append(f"    {m}")
            lines.append("")

        errors = [r for r in results if r["error"]]
        if errors:
            lines.append(f"=== ERRORES ({len(errors)}) ===")
            for r in errors:
                lines.append(f"    {r['name']}")
                lines.append(f"      {r['error']}")
            lines.append("")
        return "\n".join(lines)

    def _show_summary(self, results, cancelled):
        text = self._format_summary(results, cancelled)
        win = tk.Toplevel(self.root)
        win.title("Resumen")
        win.geometry("560x620")
        win.minsize(400, 380)
        win.configure(bg=C_BG)
        try:
            win.transient(self.root)
        except Exception:
            pass

        head = tk.Frame(win, bg=C_RED)
        head.pack(fill="x")
        head_in = tk.Frame(head, bg=C_BG)
        head_in.pack(fill="x", padx=1, pady=1)
        tk.Label(head_in, text="RESUMEN DEL ANALISIS", bg=C_BG, fg=C_FG,
                 font=F_HEAD, pady=8).pack()
        sub = "Resultados parciales" if cancelled else f"{len(results)} addon(s)"
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
        sb = tk.Scrollbar(tf, orient="vertical", command=txt.yview,
                            bg=C_BG, troughcolor=C_BG, bd=0,
                            activebackground=C_RED)
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
                copy_btn.config(text="COPIADO")
                win.after(1500, lambda: copy_btn.config(text="COPIAR"))
            except Exception as e:
                self._log(f"[!] {e}")

        make_button(footer, "CERRAR", win.destroy).pack(
            side="right", expand=True, fill="x", padx=(3, 0))
        copy_btn = make_button(footer, "COPIAR", do_copy)
        copy_btn.pack(side="right", expand=True, fill="x", padx=(0, 3))

        win.focus_set()

    def _show_last_summary(self):
        if not self.last_results:
            messagebox.showinfo("Resumen", "Aun no has analizado nada.")
            return
        r, c = self.last_results
        self._show_summary(r, c)

    # ---------------- Conflictos ----------------

    def _detect_conflicts(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if len(active) < 2:
            messagebox.showinfo("Conflictos", "Marca al menos 2 addons.")
            return
        self._set_busy(True)
        threading.Thread(target=self._run_conflicts,
                          args=(active,), daemon=True).start()

    def _run_conflicts(self, sources):
        sources = self._order_sources_by_deps(sources)
        total = len(sources)
        files_per_source = {}
        try:
            self._log("")
            self._log(f"=== CONFLICTOS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    break
                self._set_progress(i - 1, total, f"Escaneando {i}/{total}...")
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
                self._set_progress(i, total, f"Escaneando {i}/{total}...")

            count = {}
            for name, files in files_per_source.items():
                for f in files:
                    count.setdefault(f, []).append(name)
            conflicts = {p: names for p, names in count.items() if len(names) > 1}

            self._log("")
            if not conflicts:
                self._log("[OK] Sin conflictos.")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Conflictos", "Sin conflictos entre los marcados."))
            else:
                self._log(f"[!] {len(conflicts)} archivo(s) en conflicto.")
                lines = []
                for p, names in sorted(conflicts.items())[:200]:
                    lines.append(p)
                    for n in names:
                        lines.append(f"    <- {n}")
                    lines.append("")
                preview = "\n".join(lines)
                self.root.after(0, lambda: self._show_conflicts_window(
                    preview, len(conflicts)))
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, self._reset_progress)

    def _show_conflicts_window(self, text, total):
        win = tk.Toplevel(self.root)
        win.title(f"Conflictos ({total})")
        win.geometry("560x520")
        win.configure(bg=C_BG)
        frame = tk.Frame(win, bg=C_BG, padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=f"CONFLICTOS ({total})", bg=C_BG, fg=C_FG,
                 font=F_HEAD).pack(anchor="w")
        tk.Label(frame, text="El ultimo sobrescribe a los anteriores.",
                 bg=C_BG, fg=C_FG_DIM, font=F_SMALL).pack(anchor="w", pady=(2, 8))
        tf = tk.Frame(frame, bg=C_BG)
        tf.pack(fill="both", expand=True)
        txt = tk.Text(tf, wrap="word", font=F_LOG, bg=C_BG, fg=C_FG,
                      relief="flat", highlightbackground=C_RED,
                      highlightthickness=1)
        txt.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(tf, orient="vertical", command=txt.yview,
                            bg=C_BG, troughcolor=C_BG, bd=0,
                            activebackground=C_RED)
        sb.pack(side="right", fill="y")
        txt.config(yscrollcommand=sb.set)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        make_button(frame, "CERRAR", win.destroy).pack(anchor="e", pady=(8, 0))
        win.focus_set()

    # ---------------- Exportar ----------------

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
            messagebox.showinfo("Exportar", "No hay addons.")
            return
        if fmt == "csv":
            ext, types = ".csv", [("CSV", "*.csv")]
        elif fmt == "json":
            ext, types = ".json", [("JSON", "*.json")]
        else:
            ext, types = ".txt", [("Texto", "*.txt")]
        path = filedialog.asksaveasfilename(
            title="Guardar como", defaultextension=ext,
            filetypes=types + [("Todos", "*.*")])
        if not path:
            return
        try:
            if fmt == "csv":
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Nombre", "Tipo", "Origen",
                                 "Deps", "Archivos", "Autor", "Descripcion"])
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
            self._log(f"[OK] Exportado: {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------------- Extraer ----------------

    def _extract(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if not active:
            messagebox.showinfo("Vacio", "No hay addons marcados.")
            return
        dest = self.dest_entry.get().strip()
        if not dest:
            messagebox.showerror("Falta destino",
                                 "Escribe o elige la carpeta destino.")
            return
        dest_path = Path(dest)
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo crear:\n{e}")
            return
        self._set_busy(True)
        threading.Thread(target=self._run_extract,
                          args=(dest_path, active), daemon=True).start()

    def _run_extract(self, dest_root, sources):
        sources = self._order_sources_by_deps(sources)
        total = len(sources)
        ok = fail = 0
        try:
            self._log("")
            self._log(f"=== EXTRACCION -> {dest_root} ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log("[i] Orden por dependencias:")
            for k, s in enumerate(sources, 1):
                self._log(f"    {k:2d}. {s.name}")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelado.")
                    break
                label = s.name or (s.path.name if s.path else "?")
                self._set_progress(i - 1, total,
                                   f"Extrayendo {i}/{total}: {label}")
                self._log(f"[{i}/{total}] {s.display}")
                try:
                    target = dest_root / s.target_name()
                    if target.exists():
                        self._log(f"  [!] Ya existe: {target.name}")
                    with tempfile.TemporaryDirectory() as tmp:
                        kind, real = self._materialize(s, tmp)
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                self.extractor.extract(real, t2)
                                self._copy_tree(Path(t2), target)
                        else:
                            self._copy_tree(real, target)
                    self._log(f"  [OK] -> {target}")
                    ok += 1
                except Exception as e:
                    self._log(f"  [ERROR] {e}")
                    logging.error("Extract %s: %s\n%s", s.display, e,
                                   traceback.format_exc())
                    fail += 1
                self._set_progress(i, total,
                                   f"Extrayendo {i}/{total}: {label}")
            self._log(f"=== FIN: {ok} ok, {fail} fallos ===")
        finally:
            self.root.after(0, lambda: self._set_busy(False))
            self.root.after(500, self._reset_progress)
            self.root.after(0, self._save_cfg)

    @staticmethod
    def _copy_tree(src, dst):
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        for root, _, files in os.walk(src):
            rp = Path(root)
            rel = rp.relative_to(src)
            tp = dst / rel
            tp.mkdir(parents=True, exist_ok=True)
            for f in files:
                shutil.copy2(rp / f, tp / f)

    # ---------------- Cierre ----------------

    def on_close(self):
        self.cancel_flag.set()
        self._name_worker_running = False
        try:
            self.name_q.put(None)
        except Exception:
            pass
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
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


# ============================================================
# Entrada
# ============================================================

def main():
    configure_logging()
    root = tk.Tk()
    app = GModAddonManager(root)
    app.run()


if __name__ == "__main__":
    main()
