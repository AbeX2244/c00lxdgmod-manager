"""
core.py — Parsers, analyzers, managers, utilities.
No tkinter dependencies.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import (
    CACHE_FILE, COLLECTIONS_FILE, CONFIG_FILE, LOG_FILE, SESSION_FILE,
    WHITELIST_FILE, DEFAULT_LANG,
    TEXT_EXTENSIONS, RAW_MARKERS,
    KNOWN_DEPENDENCIES, LUA_DEP_HINTS, LUA_REF_PATTERNS, GENERIC_REFS,
    LUA_DANGER_PATTERNS,
    MAX_TEXT_SIZE, MAX_NESTED_DEPTH, MAX_NESTED_IN_MEM,
    STRINGS,
)

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
# Utilities
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
        logging.warning("open_folder failed for %s: %s", path, e)


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


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def is_gmod_running() -> bool:
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq gmod.exe"],
                capture_output=True, text=True, timeout=3)
            return "gmod.exe" in out.stdout.lower()
        else:
            out = subprocess.run(
                ["pgrep", "-f", "gmod"],
                capture_output=True, text=True, timeout=3)
            return bool(out.stdout.strip())
    except Exception:
        return False


def copy_tree(src, dst):
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for root, _, files in os.walk(src):
        rp = Path(root)
        rel = rp.relative_to(src)
        tp = dst / rel
        tp.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(rp / f, tp / f)


# ============================================================
# GMA parser
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
    def extract(cls, gma_path: Path, dest: Path, on_warning=None) -> str:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with open(gma_path, "rb") as f:
            h = cls.read_full_header(f)
            if h is None:
                raise ValueError("Not a valid GMA")
            entries = cls._read_entries(f)
            for path, size, stored_crc in entries:
                data = f.read(size)
                if len(data) < size:
                    raise ValueError(f"Incomplete data: {path}")
                if stored_crc:
                    actual = zlib.crc32(data) & 0xffffffff
                    if actual != stored_crc and on_warning:
                        try:
                            on_warning(f"CRC mismatch: {path}")
                        except Exception:
                            pass
                out = dest / path.replace("\\", "/")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
        return h.get("name", "")


class GMAWriter:
    @staticmethod
    def _write_cstr(f, s: str):
        f.write(s.encode("utf-8", errors="replace"))
        f.write(b"\x00")

    @classmethod
    def write(cls, folder: Path, out_path: Path,
              metadata: Optional[dict] = None) -> None:
        folder = Path(folder)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        meta = metadata or {}
        name = meta.get("title") or meta.get("name") or folder.name
        author = meta.get("author", "")
        description = meta.get("description", "")
        addon_json_extra = meta.get("addon_json_extra")

        files = []
        for root, _, filenames in os.walk(folder):
            for fn in filenames:
                p = Path(root) / fn
                try:
                    rel = str(p.relative_to(folder)).replace("\\", "/")
                except Exception:
                    continue
                files.append((rel, p))
        files.sort()

        addon_json = {
            "title": name,
            "type": "servercontent",
            "tags": [],
            "ignore": [],
        }
        if author:
            addon_json["author"] = author
        if description:
            addon_json["description"] = description
        if isinstance(addon_json_extra, dict):
            addon_json.update(addon_json_extra)

        with open(out_path, "wb") as f:
            f.write(b"GMAD")
            f.write(struct.pack("<B", 3))
            f.write(struct.pack("<Q", 0))
            f.write(struct.pack("<Q", int(time.time())))
            f.write(b"\x00")
            cls._write_cstr(f, name)
            cls._write_cstr(f, json.dumps(addon_json))
            cls._write_cstr(f, author)
            f.write(struct.pack("<I", 1))

            entries = []
            for idx, (rel, path) in enumerate(files, 1):
                try:
                    data = path.read_bytes()
                except Exception:
                    continue
                crc = zlib.crc32(data) & 0xffffffff
                entries.append((idx, rel, len(data), crc, data))
                f.write(struct.pack("<I", idx))
                cls._write_cstr(f, rel)
                f.write(struct.pack("<Q", len(data)))
                f.write(struct.pack("<I", crc))
            f.write(struct.pack("<I", 0))

            for _, _, _, _, data in entries:
                f.write(data)


class GMAExtractor:
    def extract(self, gma_path: Path, dest: Path, on_warning=None) -> str:
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
        return PureGMA.extract(gma_path, dest, on_warning=on_warning)


# ============================================================
# ZIP
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
        except RuntimeError:
            raise RuntimeError("ZIP encrypted. Install pyzipper.")
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
            logging.warning("Nested zip %s: %s", chain, e)
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
# Metadata
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
# Analyzer
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
        dangers = []
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
                try:
                    rel = str(p.relative_to(folder)).replace("\\", "/")
                except Exception:
                    rel = p.name
                for pat, label in LUA_DANGER_PATTERNS:
                    try:
                        matches = re.findall(pat, content)
                    except Exception:
                        matches = []
                    if matches:
                        dangers.append((rel, label, len(matches)))
        refs = [r for r in refs
                if r.lower().replace("\\", "/").split("/")[-1] not in GENERIC_REFS]
        return {
            "file_count": sum(counts.values()),
            "deps": sorted(deps),
            "refs": sorted(set(refs)),
            "dangers": dangers,
            "by_ext": counts,
        }


# ============================================================
# Managers
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


class CollectionsManager:
    def __init__(self):
        self.path = app_dir() / COLLECTIONS_FILE

    def _read_all(self) -> dict:
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_all(self, data: dict):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.warning("Collections save: %s", e)

    def save_collection(self, name: str, sources: list):
        data = self._read_all()
        entries = []
        for s in sources:
            item = {"kind": s.kind, "name": s.name}
            if s.kind in ("gma", "folder") and s.path:
                item["path"] = str(s.path)
            elif s.kind in ("zip_gma", "zip_folder"):
                item["root_zip"] = str(s.root_zip) if s.root_zip else ""
                item["chain"] = list(s.chain)
                item["entry"] = s.entry
            entries.append(item)
        data[name] = entries
        self._write_all(data)

    def list_collections(self) -> list:
        return sorted(self._read_all().keys())

    def load_collection(self, name: str) -> list:
        data = self._read_all()
        sources = []
        for item in data.get(name, []):
            kind = item.get("kind")
            src = None
            if kind == "gma":
                p = Path(item.get("path", ""))
                if p.exists():
                    src = Source(kind="gma", path=p,
                                 name=item.get("name", ""))
            elif kind == "folder":
                p = Path(item.get("path", ""))
                if p.exists():
                    src = Source(kind="folder", path=p,
                                 name=item.get("name", ""))
            elif kind in ("zip_gma", "zip_folder"):
                zp = Path(item.get("root_zip", ""))
                if zp.exists():
                    src = Source(kind=kind, root_zip=zp,
                                 chain=item.get("chain", []),
                                 entry=item.get("entry", ""),
                                 name=item.get("name", ""))
            if src:
                sources.append(src)
        return sources

    def delete_collection(self, name: str):
        data = self._read_all()
        data.pop(name, None)
        self._write_all(data)


class WhitelistManager:
    def __init__(self):
        self.path = app_dir() / WHITELIST_FILE

    def load(self) -> list:
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                return [str(x) for x in data.get("ids", [])]
        except Exception:
            pass
        return []

    def save(self, ids: list):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"ids": ids}, f, indent=2)
        except Exception as e:
            logging.warning("Whitelist save: %s", e)


# ============================================================
# Source model
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
# Workshop download
# ============================================================

STEAM_API_DETAILS = (
    "https://api.steampowered.com/ISteamRemoteStorage/"
    "GetPublishedFileDetails/v1/"
)


def extract_workshop_id(url: str):
    m = re.search(r'[?&]id=(\d+)', url)
    return m.group(1) if m else None


def fetch_workshop_details(item_id: str):
    data = urllib.parse.urlencode({
        "itemcount": 1,
        "publishedfileids[0]": item_id,
    }).encode("utf-8")
    req = urllib.request.Request(STEAM_API_DETAILS, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logging.warning("Steam API error: %s", e)
        return None
    try:
        payload = json.loads(body)
        items = payload.get("response", {}).get("publishedfiledetails", [])
        return items[0] if items else None
    except Exception:
        return None


def download_workshop_gma(item_id: str, dest_dir: Path) -> Path:
    details = fetch_workshop_details(item_id)
    if not details:
        raise RuntimeError("Steam API returned no details.")
    url = details.get("file_url")
    if not url:
        raise RuntimeError("Steam did not provide a download URL for this item.")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{item_id}.gma"
    req = urllib.request.Request(url, headers={"User-Agent": "GModAddonManager/2.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(out, "wb") as f:
        shutil.copyfileobj(resp, f)
    return out


# ============================================================
# Dependency sort
# ============================================================

def order_sources_by_deps(sources: list) -> list:
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


def check_missing_deps(results, sources, dest_entry_getter) -> dict:
    """Given analysis results and current sources, return missing deps."""
    required = {}
    for r in results:
        if r.get("error"):
            continue
        for d in r.get("deps", []):
            required.setdefault(d, []).append(r["name"])
    if not required:
        return {}
    present = set()
    for s in sources:
        n = (s.name or "").lower()
        for dep in required:
            if dep.lower() in n:
                present.add(dep)
    try:
        dest = Path(dest_entry_getter().strip())
        if dest.is_dir():
            for child in dest.iterdir():
                if child.is_dir():
                    cn = child.name.lower()
                    for dep in required:
                        if dep.lower() in cn:
                            present.add(dep)
    except Exception:
        pass
    return {d: mods for d, mods in required.items() if d not in present}


def find_duplicates(sources) -> dict:
    groups = {}
    for s in sources:
        fp = s.fingerprint()
        if not fp:
            continue
        groups.setdefault(fp, []).append(s)
    return {fp: srcs for fp, srcs in groups.items() if len(srcs) > 1}
