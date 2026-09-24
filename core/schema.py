"""
core.schema — JSON schema versioning helper.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path


def load_json_schema(path: Path, expected_schema: int, name: str):
    if not path.exists():
        return {}, True
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.warning("%s: load failed (%s), starting fresh", name, e)
        return {}, True
    if not isinstance(data, dict):
        logging.warning("%s: unexpected root type, starting fresh", name)
        return {}, True
    file_schema = data.get("schema", 1)
    try:
        file_schema = int(file_schema)
    except Exception:
        file_schema = 1
    if file_schema > expected_schema:
        logging.warning(
            "%s: file schema %d is newer than supported %d. "
            "Left untouched, running with defaults.",
            name, file_schema, expected_schema)
        return {}, False
    return data, True
