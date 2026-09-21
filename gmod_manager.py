"""
GMod Addon Manager v8.4 — c00lgui edition
-----------------------------------------
- Boton de idioma (EN/ES), default ingles.
- Ventana no redimensionable.
- Enter en campo de ruta = anadir.
- Filtro con debounce (150ms) para listas grandes.
- Popups siempre encima.
- Barra de estado dinamica.
- Scrollbars rojas.
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
C_RED_HOVER = "#cc0000"

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
# i18n
# ============================================================

STRINGS = {
    "en": {
        "lang_button": "ES",
        # Panels / buttons
        "add_panel": "ADD",
        "files_btn": "FILES",
        "folder_btn": "FOLDER",
        "add_btn": "ADD",
        "filter_panel": "FILTER",
        "search_label": "Search:",
        "group_dep": "Group by dependency",
        "addons_panel": "ADDONS",
        "all_btn": "ALL",
        "none_btn": "NONE",
        "invert_btn": "INVERT",
        "remove_btn": "REMOVE",
        "clear_btn": "CLEAR",
        "export_btn": "EXPORT",
        "dest_panel": "DESTINATION",
        "choose_btn": "CHOOSE",
        "open_btn": "OPEN",
        "analyze_btn": "ANALYZE",
        "extract_btn": "EXTRACT",
        "summary_btn": "SUMMARY",
        "conflicts_btn": "CONFLICTS",
        "cancel_btn": "CANCEL",
        "log_panel": "LOG",
        "copy_btn": "COPY",
        "log_clear_btn": "CLEAR",
        "log_open_btn": "OPEN FILE",
        "close_btn": "CLOSE",
        "ready": "Ready.",
        "working": "Working...",
        "canceling": "Canceling...",
        # Messages
        "empty_title": "Empty",
        "empty_body": "No addons are marked.",
        "no_dest_title": "Missing destination",
        "no_dest_body": "Type or choose the destination folder.",
        "not_found_title": "Not found",
        "not_found_body": "Not found:\n{path}",
        "no_log_title": "Log",
        "no_log_body": "No log file yet.",
        "rename_title": "Rename",
        "rename_prompt": "New name:",
        "action_title": "Action",
        "action_body": "Addon: {name}\n\n"
                       "Yes = Rename\n"
                       "No = Extract to temp and open\n"
                       "Cancel = Nothing",
        "dest_missing_title": "Does not exist",
        "conflicts_need_title": "Conflicts",
        "conflicts_need_body": "Mark at least 2 addons.",
        "conflicts_none_title": "Conflicts",
        "conflicts_none_body": "No conflicts between marked addons.",
        "summary_empty_title": "Summary",
        "summary_empty_body": "Nothing analyzed yet.",
        "export_empty_title": "Export",
        "export_empty_body": "No addons.",
        "save_as_title": "Save as",
        "zip_error_title": "Error reading zip",
        "zip_empty_title": "No addons inside",
        "error_title": "Error",
        # Status
        "status_analyzing": "Analyzing {i}/{total}: {name}",
        "status_scanning": "Scanning {i}/{total}: {name}",
        "status_extracting": "Extracting {i}/{total}: {name}",
        "status_indexing": "Indexing {i}/{total}: {name}",
        "status_analysis_ok": "Analysis complete: {n} addon(s)",
        "status_analysis_partial": "Analysis: {ok} ok, {fail} error(s)",
        "status_analysis_cancelled": "Analysis cancelled: {n}/{total}",
        "status_extract_ok": "Extraction complete: {n} addon(s)",
        "status_extract_partial": "Extraction: {ok} ok, {fail} failed",
        "status_extract_cancelled": "Extraction cancelled: {ok} ok, {fail} failed",
        "status_index_ok": "Index complete: {n} addon(s)",
        "status_index_cancelled": "Index cancelled: {n} addon(s)",
        "status_conflicts_none": "Conflicts: none",
        "status_conflicts_found": "Conflicts: {n} file(s)",
        "status_selected_all": "Selected {n} addon(s)",
        "status_deselected_all": "Deselected {n} addon(s)",
        "status_inverted": "Selection inverted: {sel} selected",
        "status_removed": "Removed {n} addon(s)",
        "status_cleared": "List cleared ({n} removed)",
        "status_exported": "Exported: {name}",
        "status_session": "Session: {n} addon(s)",
        "status_added_zip": "{name}: {n} addon(s)",
        "status_no_op": "No operation in progress.",
        "status_cancel_requested": "Cancel requested...",
    },
    "es": {
        "lang_button": "EN",
        "add_panel": "AÑADIR",
        "files_btn": "ARCHIVOS",
        "folder_btn": "CARPETA",
        "add_btn": "AÑADIR",
        "filter_panel": "FILTRO",
        "search_label": "Buscar:",
        "group_dep": "Agrupar por dependencia",
        "addons_panel": "ADDONS",
        "all_btn": "TODO",
        "none_btn": "NADA",
        "invert_btn": "INVERTIR",
        "remove_btn": "QUITAR",
        "clear_btn": "LIMPIAR",
        "export_btn": "EXPORTAR",
        "dest_panel": "DESTINO",
        "choose_btn": "ELEGIR",
        "open_btn": "ABRIR",
        "analyze_btn": "ANALIZAR",
        "extract_btn": "EXTRAER",
        "summary_btn": "RESUMEN",
        "conflicts_btn": "CONFLICTOS",
        "cancel_btn": "CANCELAR",
        "log_panel": "REGISTRO",
        "copy_btn": "COPIAR",
        "log_clear_btn": "LIMPIAR",
        "log_open_btn": "ABRIR",
        "close_btn": "CERRAR",
        "ready": "Listo.",
        "working": "Trabajando...",
        "canceling": "Cancelando...",
        "empty_title": "Vacio",
        "empty_body": "No hay addons marcados.",
        "no_dest_title": "Falta destino",
        "no_dest_body": "Escribe o elige la carpeta destino.",
        "not_found_title": "No existe",
        "not_found_body": "No se encuentra:\n{path}",
        "no_log_title": "Log",
        "no_log_body": "Todavia no hay archivo de log.",
        "rename_title": "Renombrar",
        "rename_prompt": "Nuevo nombre:",
        "action_title": "Accion",
        "action_body": "Addon: {name}\n\n"
                       "Si = Renombrar\n"
                       "No = Extraer a temporal y abrir\n"
                       "Cancelar = Nada",
        "dest_missing_title": "No existe",
        "conflicts_need_title": "Conflictos",
        "conflicts_need_body": "Marca al menos 2 addons.",
        "conflicts_none_title": "Conflictos",
        "conflicts_none_body": "Sin conflictos entre los marcados.",
        "summary_empty_title": "Resumen",
        "summary_empty_body": "Aun no has analizado nada.",
        "export_empty_title": "Exportar",
        "export_empty_body": "No hay addons.",
        "save_as_title": "Guardar como",
        "zip_error_title": "Error al leer zip",
        "zip_empty_title": "Sin addons dentro",
        "error_title": "Error",
        "status_analyzing": "Analizando {i}/{total}: {name}",
        "status_scanning": "Escaneando {i}/{total}: {name}",
        "status_extracting": "Extrayendo {i}/{total}: {name}",
        "status_indexing": "Indexando {i}/{total}: {name}",
        "status_analysis_ok": "Analisis completo: {n} addon(s)",
        "status_analysis_partial": "Analisis: {ok} ok, {fail} errores",
        "status_analysis_cancelled": "Analisis cancelado: {n}/{total}",
        "status_extract_ok": "Extraccion completa: {n} addon(s)",
        "status_extract_partial": "Extraccion: {ok} ok, {fail} fallos",
        "status_extract_cancelled": "Extraccion cancelada: {ok} ok, {fail} fallos",
        "status_index_ok": "Indexado completo: {n} addon(s)",
        "status_index_cancelled": "Indexado cancelado: {n} addon(s)",
        "status_conflicts_none": "Conflictos: ninguno",
        "status_conflicts_found": "Conflictos: {n} archivo(s)",
        "status_selected_all": "Marcados {n} addon(s)",
        "status_deselected_all": "Desmarcados {n} addon(s)",
        "status_inverted": "Seleccion invertida: {sel} marcados",
        "status_removed": "Quitados {n} addon(s)",
        "status_cleared": "Lista limpiada ({n} eliminados)",
        "status_exported": "Exportado: {name}",
        "status_session": "Sesion: {n} addon(s)",
        "status_added_zip": "{name}: {n} addon(s)",
        "status_no_op": "No hay operacion en curso.",
        "status_cancel_requested": "Cancelacion solicitada...",
    },
}

DEFAULT_LANG = "en"

# ============================================================
# Constantes
# ============================================================

APP_NAME = "GMod Addon Manager"
APP_VERSION = "8.4"
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
FILTER_DEBOUNCE_MS = 150


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
                raise RuntimeError("ZIP encrypted. Install pyzipper.")
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


# ============================================================
# UI
# ============================================================

class GModAddonManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("520x900")
        self.root.resizable(False, False)
        self.root.configure(bg=C_BG)

        self.sources: list[Source] = []
        self.busy = False
        self.cancel_flag = threading.Event()
        self.last_results = None
        self.filter_text = tk.StringVar()
        self.group_mode = tk.BooleanVar(value=False)

        self._row_refs: dict[int, dict] = {}
        self._row_frames: list = []
        self._click_timer = None
        self._pending_click_sid = None
        self._filter_timer = None
        self._rebuilding = False

        self.status = tk.StringVar(value="Ready.")
        self.lang = DEFAULT_LANG

        self.extractor = GMAExtractor()
        self.analyzer = Analyzer()
        self.cache = CacheManager()
        self.session = SessionManager()

        self.log_q: queue.Queue[str] = queue.Queue()
        self.name_q: queue.Queue = queue.Queue()
        self._name_worker_running = True

        self._load_cfg()
        self._build()
        self._poll_log()
        self._start_name_worker()
        self._load_session()
        self._auto_detect_dest()

        self._log(f"[i] Extractor: {extractor_name()}")
        self._log(f"[i] pyzipper: {'yes' if HAS_PYZIPPER else 'no'}")
        self._log(f"[i] sourcepp: {'yes' if HAS_SOURCEPP else 'no'}")
        self._log(f"[i] language: {self.lang}")

    # --- i18n ---

    def t(self, key: str, **fmt) -> str:
        lang_dict = STRINGS.get(self.lang, STRINGS[DEFAULT_LANG])
        s = lang_dict.get(key, STRINGS[DEFAULT_LANG].get(key, key))
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

    # --- Construcción ---

    def _build(self):
        # Header
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
        self.body.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._cw, width=e.width))

        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_wheel_linux)

        # Añadir
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

        # Filtro
        body = make_panel(self.body, self.t("filter_panel"))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        tk.Label(row, text=self.t("search_label"), bg=C_BG, fg=C_FG,
                 font=F_NORM).pack(side="left")
        ent = make_entry(row, textvariable=self.filter_text)
        ent.pack(side="left", fill="x", expand=True, padx=(4, 4))
        make_button(row, "X", lambda: self.filter_text.set("")).pack(side="left")
        self.filter_text.trace_add("write", lambda *_: self._on_filter_change())

        cb = tk.Checkbutton(
            body, text=self.t("group_dep"),
            variable=self.group_mode, command=self._rebuild_list,
            bg=C_BG, fg=C_FG, activebackground=C_BG, activeforeground=C_FG,
            selectcolor=C_BG, font=F_NORM, highlightthickness=0, bd=0)
        cb.pack(anchor="w", pady=(6, 0))

        # Lista
        list_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        list_panel.pack(fill="both", expand=True, pady=(0, 8))
        list_inner = tk.Frame(list_panel, bg=C_BG)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(list_inner, text=self.t("addons_panel"), bg=C_BG, fg=C_FG,
                 font=F_HEAD, anchor="w", padx=8, pady=4).pack(fill="x")
        tk.Frame(list_inner, bg=C_RED, height=1).pack(fill="x")

        rows_wrap = tk.Frame(list_inner, bg=C_BG)
        rows_wrap.pack(fill="both", expand=True)
        self.rows_canvas = tk.Canvas(rows_wrap, bg=C_BG, highlightthickness=0,
                                       height=200)
        self.rows_canvas.pack(side="left", fill="both", expand=True)
        rows_sb = make_scrollbar(rows_wrap, "vertical", self.rows_canvas.yview)
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
        self.rows_canvas.bind("<MouseWheel>",
            lambda e: self.rows_canvas.yview_scroll(int(-e.delta/120), "units"))
        self.rows_canvas.bind("<Button-4>",
            lambda e: self.rows_canvas.yview_scroll(-1, "units"))
        self.rows_canvas.bind("<Button-5>",
            lambda e: self.rows_canvas.yview_scroll(1, "units"))

        lb_row1 = tk.Frame(list_inner, bg=C_BG)
        lb_row1.pack(fill="x", padx=4, pady=(6, 2))
        make_button(lb_row1, self.t("all_btn"),
                    lambda: self._set_all_selected(True)
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb_row1, self.t("none_btn"),
                    lambda: self._set_all_selected(False)
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb_row1, self.t("invert_btn"), self._invert_selection
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))
        lb_row2 = tk.Frame(list_inner, bg=C_BG)
        lb_row2.pack(fill="x", padx=4, pady=(0, 6))
        make_button(lb_row2, self.t("remove_btn"), self._remove_selected
                    ).pack(side="left", expand=True, fill="x", padx=(0, 2))
        make_button(lb_row2, self.t("clear_btn"), self._clear
                    ).pack(side="left", expand=True, fill="x", padx=2)
        make_button(lb_row2, self.t("export_btn"), self._export_menu
                    ).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # Destino
        body = make_panel(self.body, self.t("dest_panel"))
        self.dest_entry = make_entry(body)
        self.dest_entry.pack(fill="x", pady=(0, 6))
        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x")
        make_button(row, self.t("choose_btn"), self._browse_dest).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        make_button(row, self.t("open_btn"), self._open_dest).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        # Acciones
        act = tk.Frame(self.body, bg=C_BG)
        act.pack(fill="x", pady=(0, 4))
        self.btn_analyze = tk.Button(
            act, text=self.t("analyze_btn"), command=self._analyze,
            bg=C_RED, fg=C_FG, activebackground=C_RED_HOVER, activeforeground=C_FG,
            relief="flat", bd=0, font=F_BTN, padx=10, pady=12,
            highlightbackground=C_RED, highlightthickness=1, cursor="hand2")
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

        # Progreso
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
                                         bg=C_BG, fg=C_FG_DIM, font=F_SMALL,
                                         anchor="w")
        self.progress_label.pack(fill="x", pady=(0, 8))

        # Registro
        log_panel = tk.Frame(self.body, bg=C_RED, bd=0)
        log_panel.pack(fill="both", expand=True, pady=(0, 0))
        log_inner = tk.Frame(log_panel, bg=C_BG)
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(log_inner, bg=C_BG)
        head.pack(fill="x")
        tk.Label(head, text=self.t("log_panel"), bg=C_BG, fg=C_FG, font=F_HEAD,
                 anchor="w", padx=8, pady=4).pack(side="left")
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
                            highlightbackground=C_RED,
                            highlightthickness=1)
        self.log.pack(side="left", fill="both", expand=True)
        lsb = make_scrollbar(log_wrap, "vertical", self.log.yview)
        lsb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=lsb.set, state="disabled")

        # Status bar
        status = tk.Label(self.root, textvariable=self.status,
                           bg=C_RED, fg=C_FG, font=F_SMALL,
                           anchor="w", padx=8, pady=3)
        status.pack(side="bottom", fill="x")

    # --- Scroll ---

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # --- Log ---

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

    # --- Progreso / status ---

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

    # --- Config ---

    def _cfg_file(self):
        return app_dir() / CONFIG_FILE

    def _load_cfg(self):
        try:
            with open(self._cfg_file(), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("dest"):
                self._pending_dest = data["dest"]
            else:
                self._pending_dest = ""
            lang = data.get("lang", DEFAULT_LANG)
            if lang in STRINGS:
                self.lang = lang
            else:
                self.lang = DEFAULT_LANG
        except Exception:
            self._pending_dest = ""
            self.lang = DEFAULT_LANG

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
                json.dump({"dest": dest, "lang": self.lang}, f, indent=2)
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
            messagebox.showinfo(self.t("no_dest_title"),
                                 self.t("no_dest_body"), parent=self.root)
            return
        p = Path(d)
        if not p.exists():
            messagebox.showwarning(self.t("dest_missing_title"),
                                    f"{p}", parent=self.root)
            return
        open_folder(p)

    # --- Sesión ---

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

    # --- Añadir ---

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
        self._rebuild_list()

    def _browse_folder(self):
        try:
            d = filedialog.askdirectory(title="Select folder")
        except Exception as e:
            self._log(f"[!] filedialog unavailable: {e}")
            return
        if d:
            self._register(Path(d))
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
            self._log(f"[!] Unsupported format: {path.name}")

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
            messagebox.showerror(self.t("zip_error_title"),
                                  f"{zip_path.name}\n\n{e}",
                                  parent=self.root)
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
            threading.Thread(
                target=self._run_index_nested,
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

    def _register_from_entry(self, root_zip: Path, e):
        if e.kind == "gma":
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_gma",
                                 name=Path(e.entry).stem, origin=root_zip.name)
        else:
            nm = e.entry.rstrip("/").split("/")[-1] or root_zip.stem
            self._add_zip_source(root_zip, e.chain, e.entry, "zip_folder",
                                 name=nm, origin=root_zip.name)

    # --- Filtro con debounce ---

    def _on_filter_change(self):
        if self._filter_timer is not None:
            try:
                self.root.after_cancel(self._filter_timer)
            except Exception:
                pass
        self._filter_timer = self.root.after(
            FILTER_DEBOUNCE_MS, self._rebuild_list)

    # --- Lista ---

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

    def _commit_click(self, s: Source):
        self._click_timer = None
        self._pending_click_sid = None
        s.selected = not s.selected
        self._refresh_row(s)

    def _on_row_double(self, s: Source):
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
            self.t("action_title"),
            self.t("action_body", name=s.name),
            parent=self.root)
        if action is None:
            return
        if action:
            self._rename_source(s)
        else:
            self._open_source_temp(s)

    def _refresh_row(self, s: Source):
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

    def _rename_source(self, s: Source):
        new = simpledialog.askstring(self.t("rename_title"),
                                      self.t("rename_prompt"),
                                      initialvalue=s.name, parent=self.root)
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
            messagebox.showerror(self.t("error_title"), str(e), parent=self.root)

    def _set_all_selected(self, val: bool):
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

    # --- Metadata worker ---

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

    # --- Materialización ---

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
        raise ValueError(f"unknown kind: {source.kind}")

    # --- Orden por deps ---

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

    # --- Estado ---

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
            self._set_status(self.t("working"))

    def _cancel(self):
        if not self.busy:
            self._log("[i] No operation in progress.")
            self._set_status(self.t("status_no_op"))
            return
        self.cancel_flag.set()
        self._log("[!] Cancel requested...")
        self._set_status(self.t("status_cancel_requested"))

    # --- Analizar ---

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
        sources = self._order_sources_by_deps(sources)
        total = len(sources)
        results = []
        cancelled = False
        cache_hits = 0
        try:
            self._log("")
            self._log(f"=== ANALYSIS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log("[i] Dependency order applied.")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelled.")
                    cancelled = True
                    break
                status_text = self.t("status_analyzing",
                                      i=i, total=total, name=s.name)
                self._set_progress(i - 1, total, status_text)
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
                    self._log(f"  [CACHE] Files: {entry['file_count']}")
                    if entry["deps"]:
                        self._log(f"  Deps: {', '.join(entry['deps'])}")
                    else:
                        self._log("  No known dependencies.")
                    results.append(entry)
                    self.root.after(0, lambda src=s: self._refresh_row(src))
                    self._set_progress(i, total, status_text)
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
                    self._log(f"  Files: {r['file_count']}")
                    if r["deps"]:
                        self._log(f"  Deps: {', '.join(r['deps'])}")
                    else:
                        self._log("  No known dependencies.")
                    if r["refs"]:
                        self._log(f"  Lua refs: {len(r['refs'])}")
                        for ref in r["refs"][:15]:
                            self._log(f"    - {ref}")
                        if len(r["refs"]) > 15:
                            self._log(f"    ... and {len(r['refs']) - 15} more")
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
                self._set_progress(i, total, status_text)
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
        win.geometry("560x620")
        win.minsize(400, 380)
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
                copy_btn.config(text=self.t("copy_btn"))
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
                                 self.t("summary_empty_body"),
                                 parent=self.root)
            return
        r, c = self.last_results
        self._show_summary(r, c)

    # --- Conflictos ---

    def _detect_conflicts(self):
        if self.busy:
            return
        active = [s for s in self.sources if s.selected]
        if len(active) < 2:
            messagebox.showinfo(self.t("conflicts_need_title"),
                                 self.t("conflicts_need_body"),
                                 parent=self.root)
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
            self._log(f"=== CONFLICTS ({total}) ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    break
                status_text = self.t("status_scanning",
                                      i=i, total=total, name=s.name)
                self._set_progress(i - 1, total, status_text)
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
                self._set_progress(i, total, status_text)
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
        win.geometry("560x520")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        frame = tk.Frame(win, bg=C_BG, padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=f"{self.t('conflicts_btn')} ({total})",
                 bg=C_BG, fg=C_FG, font=F_HEAD).pack(anchor="w")
        tk.Label(frame, text="Last one overwrites previous.",
                 bg=C_BG, fg=C_FG_DIM, font=F_SMALL).pack(anchor="w", pady=(2, 8))
        tf = tk.Frame(frame, bg=C_BG)
        tf.pack(fill="both", expand=True)
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

    # --- Exportar ---

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

    # --- Extraer ---

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
        self._set_busy(True)
        threading.Thread(target=self._run_extract,
                          args=(dest_path, active), daemon=True).start()

    def _run_extract(self, dest_root, sources):
        sources = self._order_sources_by_deps(sources)
        total = len(sources)
        ok = fail = 0
        cancelled = False
        try:
            self._log("")
            self._log(f"=== EXTRACTION -> {dest_root} ===")
            self._log(f"[i] Extractor: {extractor_name()}")
            self._log("[i] Dependency order:")
            for k, s in enumerate(sources, 1):
                self._log(f"    {k:2d}. {s.name}")
            for i, s in enumerate(sources, 1):
                if self.cancel_flag.is_set():
                    self._log("[!] Cancelled.")
                    cancelled = True
                    break
                label = s.name or (s.path.name if s.path else "?")
                status_text = self.t("status_extracting",
                                      i=i, total=total, name=label)
                self._set_progress(i - 1, total, status_text)
                self._log(f"[{i}/{total}] {s.display}")
                try:
                    target = dest_root / s.target_name()
                    if target.exists():
                        self._log(f"  [!] Already exists: {target.name}")
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
                self._set_progress(i, total, status_text)
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

    # --- Cierre ---

    def on_close(self):
        self.cancel_flag.set()
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
