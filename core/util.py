"""
core.util — Utility functions and global flags.
No dependencies on other core submodules.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from config import LOG_FILE, WINDOWS_RESERVED


try:
    import pyzipper  # noqa: F401
    HAS_PYZIPPER = True
except ImportError:
    pyzipper = None
    HAS_PYZIPPER = False

try:
    from sourcepp import vpkpp as _vpkpp  # noqa: F401
    HAS_SOURCEPP = True
except Exception:
    _vpkpp = None
    HAS_SOURCEPP = False

HAS_LOG_FILE = False


# ============================================================
# Path helpers
# ============================================================

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def long_path(p) -> str:
    """
    Windows-safe path string with the \\\\?\\ prefix, which bypasses the
    260-char MAX_PATH limit. Returns str, not Path, because pathlib does
    not handle the prefix well.

    On Linux/macOS returns str(p) unchanged.
    """
    if not sys.platform.startswith("win"):
        return str(p)
    s = str(p)
    if s.startswith("\\\\?\\"):
        return s
    if not os.path.isabs(s):
        return s
    if s.startswith("\\\\"):
        # UNC path \\\\server\\share\\...  →  \\\\?\\UNC\\server\\share\\...
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def ensure_dir(p) -> Path:
    """os.makedirs with long-path support. Idempotent."""
    p = Path(p)
    if p.exists():
        return p
    try:
        os.makedirs(long_path(p), exist_ok=True)
    except FileExistsError:
        pass
    return p


def copy_file(src, dst) -> None:
    """shutil.copy2 with long-path support."""
    shutil.copy2(long_path(src), long_path(dst))


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    name = name.strip().rstrip(".").rstrip(" ")
    if not name:
        return "Unnamed_Addon"
    if name.upper() in WINDOWS_RESERVED:
        name = "_" + name
    if len(name) > 100:
        name = name[:100]
    return name


def is_app_dir_writable() -> bool:
    try:
        test = app_dir() / ".write_test"
        test.write_text("x", encoding="utf-8")
        test.unlink()
        return True
    except Exception:
        return False


def is_running_from_temp() -> bool:
    try:
        p = app_dir().resolve()
        temps = []
        for env in ("TEMP", "TMP", "TMPDIR"):
            v = os.environ.get(env)
            if v:
                try:
                    temps.append(Path(v).resolve())
                except Exception:
                    pass
        try:
            temps.append(Path(tempfile.gettempdir()).resolve())
        except Exception:
            pass
        for t in temps:
            try:
                p.relative_to(t)
                return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


# ============================================================
# Hashing
# ============================================================

def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with open(long_path(path), "rb") as f:
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
                    st = p.stat()
                    entries.append((str(p.relative_to(folder)), st.st_size,
                                    int(st.st_mtime)))
                except Exception:
                    pass
    except Exception:
        return ""
    for rel, size, mtime in sorted(entries):
        h.update(f"{rel}:{size}:{mtime}\n".encode("utf-8"))
    return h.hexdigest()


_zip_sha1_cache: dict = {}


def cached_zip_sha1(zip_path: Path) -> str:
    key = str(zip_path)
    try:
        st = zip_path.stat()
        sig = (st.st_size, int(st.st_mtime))
    except Exception:
        return ""
    cached = _zip_sha1_cache.get(key)
    if cached and cached[0] == sig:
        return cached[1]
    h = file_sha1(zip_path)
    _zip_sha1_cache[key] = (sig, h)
    return h


# ============================================================
# Filesystem
# ============================================================

def open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        logging.warning("open_folder failed for %s: %s", path, e)


def copy_tree(src, dst) -> None:
    """Recursive copy with long-path support."""
    src, dst = Path(src), Path(dst)
    ensure_dir(dst)
    for root, _, files in os.walk(src):
        rp = Path(root)
        rel = rp.relative_to(src)
        tp = dst / rel
        ensure_dir(tp)
        for f in files:
            copy_file(rp / f, tp / f)


def is_gmod_running() -> bool:
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq gmod.exe"],
                                  capture_output=True, text=True, timeout=3)
            return "gmod.exe" in out.stdout.lower()
        else:
            out = subprocess.run(["pgrep", "-x", "gmod"],
                                  capture_output=True, text=True, timeout=3)
            if out.stdout.strip():
                return True
            out = subprocess.run(["pgrep", "-f", "gmod_linux"],
                                  capture_output=True, text=True, timeout=3)
            return bool(out.stdout.strip())
    except Exception:
        return False


# ============================================================
# Logging
# ============================================================

def configure_logging():
    global HAS_LOG_FILE
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        fh = logging.FileHandler(long_path(app_dir() / LOG_FILE),
                                  encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(fh)
        HAS_LOG_FILE = True
    except Exception:
        HAS_LOG_FILE = False


def check_i18n_consistency():
    """
    Log a warning for every translation key that is missing in one
    language but present in the other. Runs once at startup after
    configure_logging(). Silent if all keys match.
    """
    try:
        from config import STRINGS
    except Exception:
        return
    en_keys = set(STRINGS.get("en", {}).keys())
    es_keys = set(STRINGS.get("es", {}).keys())
    missing_es = sorted(en_keys - es_keys)
    missing_en = sorted(es_keys - en_keys)
    if not missing_es and not missing_en:
        return
    logger = logging.getLogger("i18n")
    if missing_es:
        logger.warning("i18n: %d key(s) missing in 'es': %s",
                       len(missing_es), ", ".join(missing_es))
    if missing_en:
        logger.warning("i18n: %d key(s) missing in 'en': %s",
                       len(missing_en), ", ".join(missing_en))


# ============================================================
# Misc
# ============================================================

def extractor_name() -> str:
    return "sourcepp" if HAS_SOURCEPP else "PureGMA"


def human_size(n: int) -> str:
    if n < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
