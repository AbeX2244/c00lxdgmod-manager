"""
core.managers — Persistence for cache, session, collections and backups.

- CacheManager: SHA-1 keyed analysis cache.
- SessionManager: current addon list between runs.
- CollectionsManager: named presets of addon lists.
- BackupManager: create/list/restore/delete snapshots of the destination.

All managers use schema versioning via load_json_schema. If a file was
written by a newer version, the manager marks itself non-writable and
returns defaults instead of overwriting it.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from config import (
    CACHE_FILE, COLLECTIONS_FILE, SESSION_FILE,
    CACHE_MAX_ENTRIES, RAW_FOLDER_MARKERS,
    SCHEMA_CACHE, SCHEMA_SESSION, SCHEMA_COLLECTIONS,
)
from core.schema import load_json_schema
from core.sources import Source
from core.util import (
    app_dir, copy_tree, ensure_dir, long_path, human_size,
)


# ============================================================
# Cache
# ============================================================

class CacheManager:
    def __init__(self):
        self.path = app_dir() / CACHE_FILE
        self.data: dict = {"schema": SCHEMA_CACHE, "version": 1, "entries": {}}
        self._writable = True
        self._load()

    def _load(self):
        data, ok = load_json_schema(self.path, SCHEMA_CACHE, "cache")
        self._writable = ok
        if not ok:
            return
        if "entries" in data:
            self.data = data
            self.data["schema"] = SCHEMA_CACHE

    def save(self):
        if not self._writable:
            return
        try:
            self.data["schema"] = SCHEMA_CACHE
            entries = self.data.get("entries", {})
            if len(entries) > CACHE_MAX_ENTRIES:
                items = sorted(
                    entries.items(),
                    key=lambda kv: kv[1].get("ts", 0)
                    if isinstance(kv[1], dict) else 0)
                keep = items[-CACHE_MAX_ENTRIES:]
                self.data["entries"] = dict(keep)
            with open(long_path(self.path), "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
        except Exception as e:
            logging.warning("Cache save: %s", e)

    def get(self, key: str):
        return self.data["entries"].get(key)

    def put(self, key: str, value):
        if isinstance(value, dict):
            value = dict(value)
            value["ts"] = int(time.time())
        self.data["entries"][key] = value


# ============================================================
# Session
# ============================================================

class SessionManager:
    def __init__(self):
        self.path = app_dir() / SESSION_FILE
        self._writable = True

    def save(self, sources):
        if not self._writable:
            return
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
            with open(long_path(self.path), "w", encoding="utf-8") as f:
                json.dump({"schema": SCHEMA_SESSION, "sources": data},
                          f, indent=1)
        except Exception as e:
            logging.warning("Session save: %s", e)

    def load(self):
        sources: list = []
        data, ok = load_json_schema(self.path, SCHEMA_SESSION, "session")
        self._writable = ok
        if not ok:
            return sources
        try:
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
# Collections
# ============================================================

class CollectionsManager:
    def __init__(self):
        self.path = app_dir() / COLLECTIONS_FILE
        self._writable = True

    def _read_all(self) -> dict:
        data, ok = load_json_schema(
            self.path, SCHEMA_COLLECTIONS, "collections")
        self._writable = ok
        if not ok:
            return {}
        return {k: v for k, v in data.items() if k != "schema"}

    def _write_all(self, data: dict):
        if not self._writable:
            return
        try:
            payload = dict(data)
            payload["schema"] = SCHEMA_COLLECTIONS
            with open(long_path(self.path), "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logging.warning("Collections save: %s", e)

    def save_collection(self, name: str, sources):
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

    def load_collection(self, name: str):
        data = self._read_all()
        sources: list = []
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


# ============================================================
# Backups
# ============================================================

# Extra names to skip even if they happen to have addon-ish subfolders.
_BACKUP_SKIP_NAMES = {
    ".backup", "__pycache__", "node_modules", ".git", ".svn",
    "venv", ".venv", "system volume information", "$recycle.bin",
}


class BackupManager:
    """
    Snapshots of the destination folder stored under <dest>/.backup/.

    Each backup lives in a folder named YYYY-MM-DD_HH-MM-SS and contains
    a copy of every addon-looking subfolder in the destination at the
    moment of creation.

    "Addon-looking" means the folder has an addon.json or one of the
    standard Source subfolders (lua/, materials/, models/, sound/, ...).
    Everything else is skipped. This prevents accidentally backing up
    random unrelated folders if the destination is set to something
    like Downloads or Documents.
    """

    BACKUP_DIRNAME = ".backup"

    def __init__(self, dest_getter):
        # dest_getter is a callable returning the current destination
        # path as a string (usually the value of the destination entry).
        self.dest_getter = dest_getter

    # ---------- Path helpers ----------

    def dest_path(self):
        d = (self.dest_getter() or "").strip()
        if not d:
            return None
        return Path(d)

    def backup_root(self):
        d = self.dest_path()
        if d is None:
            return None
        return d / self.BACKUP_DIRNAME

    # ---------- Addon detection ----------

    @staticmethod
    def _looks_like_addon(folder: Path) -> bool:
        """
        A folder is addon-looking if it has addon.json OR any of the
        standard Source subfolders (lua, materials, models, sound, ...).
        """
        try:
            if (folder / "addon.json").exists():
                return True
        except Exception:
            pass
        try:
            children = {p.name.lower() for p in folder.iterdir() if p.is_dir()}
        except Exception:
            return False
        return bool(children & RAW_FOLDER_MARKERS)

    @staticmethod
    def _should_skip(name: str) -> bool:
        """True if the name is a known non-addon system folder."""
        low = name.lower()
        if low.startswith("."):
            return True
        return low in _BACKUP_SKIP_NAMES

    def _iter_candidates(self):
        """
        Yield the destination subfolders that look like addons.
        Skips dot-folders, system folders, and non-addon folders.
        Returns (candidate_paths, skipped_count).
        """
        dest = self.dest_path()
        if dest is None or not dest.is_dir():
            return [], 0
        candidates: list = []
        skipped = 0
        try:
            for child in dest.iterdir():
                if not child.is_dir():
                    continue
                if self._should_skip(child.name):
                    skipped += 1
                    continue
                if not self._looks_like_addon(child):
                    skipped += 1
                    continue
                candidates.append(child)
        except Exception as e:
            logging.warning("Backup scan: %s", e)
        return candidates, skipped

    def count_candidates(self):
        """
        Return (addon_count, skipped_count) without copying anything.
        Used by the UI to show what will be backed up before confirming.
        """
        candidates, skipped = self._iter_candidates()
        return len(candidates), skipped

    # ---------- Listing ----------

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += (Path(root) / f).stat().st_size
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def list_backups(self) -> list:
        """
        Returns a list of dicts, newest first:
          { name, path, addon_count, size, size_human, created }
        """
        root = self.backup_root()
        if root is None or not root.is_dir():
            return []
        result = []
        try:
            children = [c for c in root.iterdir() if c.is_dir()]
        except Exception:
            return []
        for child in sorted(children, key=lambda p: p.name, reverse=True):
            try:
                addons = [c for c in child.iterdir() if c.is_dir()]
                addon_count = len(addons)
            except Exception:
                addon_count = 0
            size = self._dir_size(child)
            created = child.name
            try:
                dt = datetime.strptime(child.name, "%Y-%m-%d_%H-%M-%S")
                created = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            result.append({
                "name": child.name,
                "path": child,
                "addon_count": addon_count,
                "size": size,
                "size_human": human_size(size),
                "created": created,
            })
        return result

    def scan_backup_addons(self, backup_path: Path) -> list:
        backup_path = Path(backup_path)
        if not backup_path.is_dir():
            return []
        try:
            return sorted(
                c.name for c in backup_path.iterdir() if c.is_dir())
        except Exception:
            return []

    # ---------- Create ----------

    def create(self, progress_cb=None, cancel_flag=None):
        """
        Copy every addon-looking folder from the destination into a new
        backup. Returns a dict with:
          { path, copied, skipped }
        Raises RuntimeError if there is nothing to back up.
        """
        dest = self.dest_path()
        if dest is None:
            raise RuntimeError("No destination set.")
        if not dest.is_dir():
            raise RuntimeError(f"Destination does not exist: {dest}")

        candidates, skipped = self._iter_candidates()
        if not candidates:
            raise RuntimeError(
                "No addon folders found in the destination. "
                "Only folders with lua/, materials/, models/, sound/, "
                "or addon.json are backed up.")

        root = dest / self.BACKUP_DIRNAME
        ensure_dir(root)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_path = root / timestamp
        ensure_dir(backup_path)

        total = len(candidates)
        copied = 0
        for i, child in enumerate(candidates, 1):
            if cancel_flag is not None and cancel_flag.is_set():
                raise RuntimeError("Cancelled")
            if progress_cb is not None:
                progress_cb(i - 1, total, child.name)
            copy_tree(child, backup_path / child.name)
            copied += 1
            if progress_cb is not None:
                progress_cb(i, total, child.name)

        return {
            "path": backup_path,
            "copied": copied,
            "skipped": skipped,
        }

    # ---------- Restore ----------

    def restore(self, backup_path: Path, addons=None,
                progress_cb=None, cancel_flag=None) -> int:
        """
        Restore the backup (or a subset of it) into the destination.
        `addons` is a list of folder names, or None to restore everything.
        Returns the number of folders restored.
        """
        backup_path = Path(backup_path)
        if not backup_path.is_dir():
            raise RuntimeError(f"Backup not found: {backup_path}")

        dest = self.dest_path()
        if dest is None:
            raise RuntimeError("No destination set.")
        ensure_dir(dest)

        if addons is None:
            try:
                targets = [c for c in backup_path.iterdir() if c.is_dir()]
            except Exception as e:
                raise RuntimeError(f"Cannot read backup: {e}")
        else:
            wanted = set(addons)
            try:
                targets = [c for c in backup_path.iterdir()
                           if c.is_dir() and c.name in wanted]
            except Exception as e:
                raise RuntimeError(f"Cannot read backup: {e}")

        total = len(targets)
        restored = 0
        for i, child in enumerate(targets, 1):
            if cancel_flag is not None and cancel_flag.is_set():
                raise RuntimeError("Cancelled")
            if progress_cb is not None:
                progress_cb(i - 1, total, child.name)
            copy_tree(child, dest / child.name)
            restored += 1
            if progress_cb is not None:
                progress_cb(i, total, child.name)

        return restored

    # ---------- Delete ----------

    def delete(self, backup_path: Path) -> None:
        backup_path = Path(backup_path)
        if not backup_path.is_dir():
            return
        root = self.backup_root()
        if root is None:
            return
        try:
            backup_path.resolve().relative_to(root.resolve())
        except ValueError:
            raise RuntimeError("Refusing to delete outside .backup/")
        shutil.rmtree(long_path(backup_path), ignore_errors=True)

    def delete_all(self) -> int:
        """Delete every backup. Returns how many were removed."""
        root = self.backup_root()
        if root is None or not root.is_dir():
            return 0
        count = 0
        try:
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(long_path(child), ignore_errors=True)
                    count += 1
        except Exception as e:
            logging.warning("delete_all backups: %s", e)
        return count
