"""
core.sources — Addon source model, metadata readers, dep sorting.

- Source dataclass: represents one addon from any origin (gma, folder,
  zip_gma, zip_folder).
- Metadata readers: pull name/author/description from GMA headers or
  addon.json files.
- order_sources_by_deps: topological sort of sources so bases go first.
- check_missing_deps: find deps that aren't in the current list nor
  the destination folder.
- find_duplicates: group sources by content fingerprint.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import (
    KNOWN_DEPENDENCIES,  # noqa: F401 (kept for future use)
)
from core.gma import PureGMA
from core.zip_index import _open_zip_chain
from core.util import (
    file_sha1, folder_fingerprint, cached_zip_sha1, safe_name,
)


@dataclass
class Source:
    kind: str                          # "gma" | "folder" | "zip_gma" | "zip_folder"
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
            z = cached_zip_sha1(self.root_zip)
            chain = ":".join(self.chain)
            return f"zip:{z}:{chain}:{self.entry}"
        return ""

    def target_name(self) -> str:
        n = self.name or (self.path.stem if self.path else "addon")
        return safe_name(n)


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
        return PureGMA.read_full_header(stream) or {}
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


def order_sources_by_deps(sources: list, warn_callback=None) -> list:
    """
    Topological sort of sources so dependencies come before dependents.

    Heuristics (in order):
      1. metadata['deps'] declared dependencies
      2. Addon name contains base/core/manager/framework/etc.
      3. Shared prefix before '|', ' - ', ' : ', ':'
    Falls back to original order for nodes stuck in a cycle.

    If `warn_callback` is provided, it's called with a string message
    when a cycle is detected.
    """
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

    # 1. Declared deps
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

    # 2. Base-like names come before same-token addons
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

    # 3. Shared prefix, shortest first
    groups: dict = {}
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

    # Kahn's algorithm with stable tie-breaking
    original_index = {id(s): i for i, s in enumerate(sources)}
    ready = [s for s in sources if indeg[id(s)] == 0]
    ready.sort(key=lambda x: original_index[id(x)])

    result: list = []
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

    # Handle cycles: keep original order for the leftovers
    if len(result) < n:
        seen = {id(s) for s in result}
        leftover = [s for s in sources if id(s) not in seen]
        msg = ("Dependency cycle detected among: "
               + ", ".join(s.name or "?" for s in leftover))
        try:
            logging.warning(msg)
        except Exception:
            pass
        if warn_callback:
            try:
                warn_callback(msg)
            except Exception:
                pass
        for s in leftover:
            result.append(s)

    return result


def _norm_token(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def _name_matches(addon_name: str, dep_name: str) -> bool:
    a = _norm_token(addon_name)
    d = _norm_token(dep_name)
    if not a or not d:
        return False
    return d in a


def check_missing_deps(results, sources, dest_getter, cross_deps=None) -> dict:
    required: dict = {}
    for r in results:
        if r.get("error"):
            continue
        for d in r.get("deps", []):
            required.setdefault(d, []).append(r["name"])

    if cross_deps:
        for from_addon, to_addons in cross_deps.items():
            for dep_addon in to_addons:
                if not any(r.get("name") == dep_addon for r in results):
                    required.setdefault(dep_addon, []).append(from_addon)

    if not required:
        return {}

    present: set = set()
    for s in sources:
        n = s.name or ""
        for dep in required:
            if _name_matches(n, dep):
                present.add(dep)

    try:
        dest = Path(dest_getter().strip())
        if dest.is_dir():
            for child in dest.iterdir():
                if child.is_dir():
                    for dep in required:
                        if _name_matches(child.name, dep):
                            present.add(dep)
    except Exception:
        pass

    return {d: mods for d, mods in required.items() if d not in present}


def find_duplicates(sources) -> dict:
    groups: dict = {}
    for s in sources:
        fp = s.fingerprint()
        if not fp:
            continue
        groups.setdefault(fp, []).append(s)
    return {fp: srcs for fp, srcs in groups.items() if len(srcs) > 1}
