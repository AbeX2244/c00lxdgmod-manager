"""
core — Re-exports for backward compatibility.
ui.py and main.py can keep doing `from core import X`.
"""

from core.util import (
    app_dir, safe_name, file_sha1, folder_fingerprint, cached_zip_sha1,
    open_folder, configure_logging, extractor_name, human_size,
    is_gmod_running, copy_tree, is_app_dir_writable, is_running_from_temp,
    long_path, ensure_dir, copy_file, check_i18n_consistency,
    HAS_LOG_FILE, HAS_SOURCEPP, HAS_PYZIPPER,
)
from core.schema import load_json_schema
from core.gma import PureGMA, GMAWriter, GMAExtractor
from core.zip_index import ZipIndex
from core.analyzer import (
    Analyzer, detect_cross_dependencies, detect_auto_conflicts,
)
from core.sources import (
    Source,
    read_gma_metadata_file, read_gma_metadata_stream,
    resolve_gma_metadata_in_zip, resolve_folder_metadata_in_zip,
    resolve_folder_metadata,
    order_sources_by_deps, check_missing_deps, find_duplicates,
)
from core.managers import (
    CacheManager, SessionManager, CollectionsManager, BackupManager,
)

__all__ = [
    "app_dir", "safe_name", "file_sha1", "folder_fingerprint",
    "cached_zip_sha1",
    "open_folder", "configure_logging", "extractor_name", "human_size",
    "is_gmod_running", "copy_tree", "is_app_dir_writable",
    "is_running_from_temp",
    "long_path", "ensure_dir", "copy_file", "check_i18n_consistency",
    "HAS_LOG_FILE", "HAS_SOURCEPP", "HAS_PYZIPPER",
    "load_json_schema",
    "PureGMA", "GMAWriter", "GMAExtractor",
    "ZipIndex",
    "Analyzer", "detect_cross_dependencies", "detect_auto_conflicts",
    "Source",
    "read_gma_metadata_file", "read_gma_metadata_stream",
    "resolve_gma_metadata_in_zip", "resolve_folder_metadata_in_zip",
    "resolve_folder_metadata",
    "order_sources_by_deps", "check_missing_deps", "find_duplicates",
    "CacheManager", "SessionManager", "CollectionsManager", "BackupManager",
]
