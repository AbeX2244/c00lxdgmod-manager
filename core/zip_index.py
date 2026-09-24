"""
core.zip_index — ZIP archive indexing and lazy extraction.

Handles:
  - Single zip files
  - Chains of nested zips (up to MAX_NESTED_DEPTH)
  - Optional pyzipper for AES-encrypted archives
  - Path traversal protection

The indexer only reads the central directory (namelist). Actual
extraction of a specific entry happens in materialize(), so a 5 GB
zip can be indexed in a fraction of a second.

materialize() extracts entries manually (open + read + write) instead
of relying on ZipFile.extract(), so it can go through long_path() and
avoid the Windows 260-char MAX_PATH limit.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import (
    MAX_NESTED_DEPTH, MAX_NESTED_IN_MEM, RAW_MARKERS,
)
from core.util import ensure_dir, long_path

try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    pyzipper = None
    HAS_PYZIPPER = False


_ZIP_PASSWORDS: dict = {}


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
    """Open the ZipFile corresponding to (root_zip, chain)."""
    if not chain:
        return _try_open_zip(root_zip, _ZIP_PASSWORDS.get(str(root_zip)))
    with _try_open_zip(root_zip, _ZIP_PASSWORDS.get(str(root_zip))) as zf:
        data = zf.read(chain[0])
    for name in chain[1:]:
        with _zip_open(io.BytesIO(data)) as inner:
            data = inner.read(name)
    return _zip_open(io.BytesIO(data))


def _safe_zip_target(base: Path, target: Path) -> bool:
    """Ensure `target` is inside `base` (prevents zip-slip)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
    except Exception:
        return False


def _extract_entry(zf, name: str, base: Path) -> Path:
    """
    Extract a single entry from the zip to base, using long_path.
    Returns the resulting Path.
    """
    target = base / name
    if not _safe_zip_target(base, target):
        raise RuntimeError(f"Unsafe path in zip: {name}")
    ensure_dir(target.parent)
    with zf.open(name) as src:
        data = src.read()
    with open(long_path(target), "wb") as out:
        out.write(data)
    return target


class ZipIndex:
    """
    Index any zip archive (or chain of nested zips) without extracting
    the whole thing. Only the central directory is read.
    """

    @dataclass
    class Entry:
        root_zip: Path
        chain: list
        entry: str
        kind: str   # "gma" | "folder"

    # ---------- Peek ----------

    @staticmethod
    def peek_top(zip_path: Path):
        """
        Read just the top-level zip. Returns (gmas, folders, nested_zips).
        Raises RuntimeError for encrypted archives without pyzipper.
        """
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

    # ---------- Raw prefix detection ----------

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

    # ---------- Recursive build ----------

    @classmethod
    def build(cls, root_zip, chain=None, depth=0):
        """
        Recursively index a zip and any nested zips inside it.
        Returns a list of Entry objects.
        """
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

    # ---------- Materialize ----------

    @classmethod
    def materialize(cls, entry: "ZipIndex.Entry", tmp_dir: Path):
        """
        Extract a single entry (a .gma file or a raw folder prefix)
        to tmp_dir. Returns (kind, real_path).
        Raises RuntimeError if a path would escape tmp_dir.
        """
        tmp_dir = Path(tmp_dir)
        ensure_dir(tmp_dir)
        zf = _open_zip_chain(entry.root_zip, entry.chain)
        try:
            if entry.kind == "gma":
                target = _extract_entry(zf, entry.entry, tmp_dir)
                return ("gma", target)

            prefix = entry.entry
            for n in zf.namelist():
                if n.startswith(prefix) and not n.endswith("/"):
                    _extract_entry(zf, n, tmp_dir)
            return ("folder", tmp_dir / prefix)
        finally:
            zf.close()
