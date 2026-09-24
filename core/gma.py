"""
core.gma — GMA parser, writer, and extractor.

- PureGMA:     pure-Python GMA reader (header + entries + extract).
- GMAWriter:   write a folder as a valid GMA v3.
- GMAExtractor: try sourcepp first, fall back to PureGMA.

sourcepp is not thread-safe, so GMAExtractor serializes calls with a
global lock. File copy stays parallel at the caller level.
All filesystem I/O uses long_path() so Windows doesn't choke on
paths longer than 260 chars.
"""

from __future__ import annotations

import json
import logging
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Optional

from core.util import ensure_dir, long_path

try:
    from sourcepp import vpkpp as _vpkpp
    HAS_SOURCEPP = True
except Exception:
    _vpkpp = None
    HAS_SOURCEPP = False


_extractor_lock = threading.Lock()


class PureGMA:
    """Pure-Python GMA parser. No external dependencies."""

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
            with open(long_path(gma_path), "rb") as f:
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
            with open(long_path(gma_path), "rb") as f:
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
        ensure_dir(dest)
        with open(long_path(gma_path), "rb") as f:
            h = cls.read_full_header(f)
            if h is None:
                raise ValueError("Not a valid GMA")
            entries = cls._read_entries(f)
            seen = set()
            for path, size, stored_crc in entries:
                p_norm = path.replace("\\", "/")
                if p_norm in seen and on_warning:
                    try:
                        on_warning(f"Duplicate entry in GMA: {p_norm}")
                    except Exception:
                        pass
                seen.add(p_norm)
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
                out = dest / p_norm
                ensure_dir(out.parent)
                with open(long_path(out), "wb") as fh:
                    fh.write(data)
        return h.get("name", "")


class GMAWriter:
    """Write a folder as a valid GMA v3 file."""

    @staticmethod
    def _write_cstr(f, s: str):
        f.write(s.encode("utf-8", errors="replace"))
        f.write(b"\x00")

    @classmethod
    def write(cls, folder: Path, out_path: Path,
              metadata: Optional[dict] = None) -> None:
        folder = Path(folder)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        meta = metadata or {}
        name = meta.get("title") or meta.get("name") or folder.name
        author = meta.get("author", "")
        description = meta.get("description", "")
        addon_json_extra = meta.get("addon_json_extra")

        files = []
        for root, _, filenames in os.walk(folder, followlinks=False):
            for fn in filenames:
                p = Path(root) / fn
                try:
                    if p.is_symlink():
                        continue
                except Exception:
                    pass
                try:
                    rel = str(p.relative_to(folder)).replace("\\", "/")
                except Exception:
                    continue
                files.append((rel, p))
        files.sort()

        addon_json = {"title": name, "type": "servercontent",
                       "tags": [], "ignore": []}
        if author:
            addon_json["author"] = author
        if description:
            addon_json["description"] = description
        if isinstance(addon_json_extra, dict):
            addon_json.update(addon_json_extra)

        with open(long_path(out_path), "wb") as f:
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
                    with open(long_path(path), "rb") as fh:
                        data = fh.read()
                except Exception:
                    continue
                crc = zlib.crc32(data) & 0xffffffff
                entries.append((rel, data))
                f.write(struct.pack("<I", idx))
                cls._write_cstr(f, rel)
                f.write(struct.pack("<Q", len(data)))
                f.write(struct.pack("<I", crc))
            f.write(struct.pack("<I", 0))
            for _, data in entries:
                f.write(data)


class GMAExtractor:
    """
    Extract a .gma to a folder.
    Tries sourcepp first, falls back to PureGMA.
    Serialized with a lock because sourcepp is not thread-safe.
    """

    def extract(self, gma_path: Path, dest: Path, on_warning=None) -> str:
        with _extractor_lock:
            gma_path = Path(gma_path)
            dest = Path(dest)
            ensure_dir(dest)

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
