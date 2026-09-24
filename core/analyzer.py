"""
core.analyzer — Lua/content scanner and dependency detection.

- Analyzer.scan(folder): walk a folder, extract dependency hints,
  Lua references, danger patterns, asset refs, global definitions,
  hook IDs, net strings, concommands and cvars.
- detect_cross_dependencies(analyses): figure out which addons depend
  on which other addons based on shared asset paths.
- detect_auto_conflicts(analyses): find framework collisions from
  Lua source (same global defined by two addons, same hook IDs, etc).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from config import (
    TEXT_EXTENSIONS,
    KNOWN_DEPENDENCIES, LUA_DEP_HINTS, LUA_REF_PATTERNS, GENERIC_REFS,
    LUA_DANGER_PATTERNS, ASSET_REF_PATTERNS, MIN_ASSET_REF_LEN,
    LUA_GLOBAL_DEF_PATTERNS, LUA_HOOK_ID_PATTERN, LUA_NETSTR_PATTERN,
    LUA_CONCMD_PATTERN, LUA_CVAR_PATTERN, LUA_EXTERNAL_USE_PATTERN,
    KNOWN_LUA_GLOBALS, EXCLUSIVE_GLOBALS, FRAMEWORK_MIN_LUA_FILES,
    MAX_TEXT_SIZE,
)


class Analyzer:
    """
    Scans an extracted addon folder and returns a dict with everything
    the rest of the app needs to know about it.
    """

    @staticmethod
    def _iter_files(d):
        for root, _, files in os.walk(d):
            for f in files:
                yield Path(root) / f

    @staticmethod
    def _read(p: Path) -> str:
        """Read a text file, handling BOM and CRLF. Rejects binary files."""
        try:
            if p.stat().st_size > MAX_TEXT_SIZE:
                return ""
            with open(p, "rb") as f:
                data = f.read()
        except Exception:
            return ""
        if not data:
            return ""
        # Strip UTF-8 BOM
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        # Reject obviously binary files (heuristic on first 4 KB)
        sample = data[:4096]
        if sample:
            printable = sum(
                1 for b in sample
                if 9 <= b <= 13 or 32 <= b <= 126 or b >= 128
            )
            if printable / len(sample) < 0.7:
                return ""
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def scan(self, folder: Path) -> dict:
        deps: set = set()
        refs: list = []
        counts: dict = {}
        dangers: list = []
        files_provided: set = set()
        asset_refs: set = set()
        global_defs: set = set()
        external_uses: set = set()
        hook_ids: set = set()
        net_strings: set = set()
        concommands: set = set()
        cvars: set = set()
        lua_file_count = 0

        for p in self._iter_files(folder):
            ext = p.suffix.lower() or "[sin ext]"
            counts[ext] = counts.get(ext, 0) + 1

            try:
                rel = str(p.relative_to(folder)).replace("\\", "/").lower()
                files_provided.add(rel)
            except Exception:
                pass

            if p.suffix.lower() not in TEXT_EXTENSIONS:
                continue

            content = self._read(p)
            if not content:
                continue
            low = content.lower()

            # ---- Known dependency name patterns ----
            for pat, name in KNOWN_DEPENDENCIES.items():
                if re.search(pat, low):
                    deps.add(name)

            # ---- Lua-specific scanning ----
            if p.suffix.lower() == ".lua":
                lua_file_count += 1

                for pat, name in LUA_DEP_HINTS.items():
                    if re.search(pat, content):
                        deps.add(name)

                for pat in LUA_REF_PATTERNS:
                    for m in re.findall(pat, content, re.IGNORECASE):
                        refs.append(m)

                try:
                    relp = str(p.relative_to(folder)).replace("\\", "/")
                except Exception:
                    relp = p.name
                for pat, label in LUA_DANGER_PATTERNS:
                    try:
                        matches = re.findall(pat, content)
                    except Exception:
                        matches = []
                    if matches:
                        dangers.append((relp, label, len(matches)))

                for pat in ASSET_REF_PATTERNS:
                    try:
                        for m in re.findall(pat, content, re.IGNORECASE):
                            r = m.lower().replace("\\", "/").lstrip("/")
                            if len(r) >= MIN_ASSET_REF_LEN:
                                asset_refs.add(r)
                    except Exception:
                        pass

                for pat in LUA_GLOBAL_DEF_PATTERNS:
                    try:
                        for m in re.findall(pat, content, re.MULTILINE):
                            name = m if isinstance(m, str) else m[0]
                            if name in KNOWN_LUA_GLOBALS:
                                global_defs.add(name)
                    except Exception:
                        pass

                try:
                    for m in re.findall(LUA_EXTERNAL_USE_PATTERN, content):
                        if m in KNOWN_LUA_GLOBALS and m not in global_defs:
                            external_uses.add(m)
                except Exception:
                    pass

                try:
                    for evt, ident in re.findall(LUA_HOOK_ID_PATTERN, content):
                        hook_ids.add(f"{evt}:{ident}")
                except Exception:
                    pass
                try:
                    for m in re.findall(LUA_NETSTR_PATTERN, content):
                        net_strings.add(m)
                except Exception:
                    pass
                try:
                    for m in re.findall(LUA_CONCMD_PATTERN, content):
                        concommands.add(m)
                except Exception:
                    pass
                try:
                    for m in re.findall(LUA_CVAR_PATTERN, content):
                        cvars.add(m)
                except Exception:
                    pass

        # ---- Filter generic Lua references ----
        refs = [r for r in refs
                if r.lower().replace("\\", "/").split("/")[-1]
                not in GENERIC_REFS]

        # ---- Filename-based dep hints ----
        try:
            fname = folder.name.lower()
        except Exception:
            fname = str(folder).lower()
        if "pill" in fname and "base" in fname:
            deps.add("Pill Base")
        if "parakeet" in fname:
            deps.add("Parakeet's Pill Base")

        # ---- Orphan asset detection ----
        files_lower = set(files_provided)
        orphan_refs: set = set()
        for ref in asset_refs:
            ref_norm = ref.lower().replace("\\", "/").lstrip("/")
            if ref_norm in files_lower:
                continue
            found = False
            for f in files_lower:
                if f.endswith("/" + ref_norm) or f == ref_norm:
                    found = True
                    break
            if not found:
                orphan_refs.add(ref_norm)

        return {
            "file_count": sum(counts.values()),
            "deps": sorted(deps),
            "refs": sorted(set(refs)),
            "dangers": dangers,
            "by_ext": counts,
            "files_provided": files_provided,
            "asset_refs": asset_refs,
            "orphan_refs": orphan_refs,
            "global_defs": sorted(global_defs),
            "external_uses": sorted(external_uses),
            "hook_ids": sorted(hook_ids),
            "net_strings": sorted(net_strings),
            "concommands": sorted(concommands),
            "cvars": sorted(cvars),
            "lua_file_count": lua_file_count,
        }


def detect_cross_dependencies(analyses: list) -> dict:
    """
    Given a list of analysis dicts (each with 'name', 'files_provided',
    'asset_refs'), return a mapping addon_name -> set(other_addon_names)
    it depends on.

    A depends on B if A references an asset path that B provides and
    A does not provide itself.
    """
    provider: dict = {}
    for a in analyses:
        name = a.get("name")
        if not name:
            continue
        for f in a.get("files_provided", set()):
            provider[f] = name

    result: dict = {}
    for a in analyses:
        name = a.get("name")
        if not name:
            continue
        own_files = a.get("files_provided", set())
        deps: set = set()
        for ref in a.get("asset_refs", set()):
            ref_norm = ref.lower().replace("\\", "/").lstrip("/")
            if len(ref_norm) < MIN_ASSET_REF_LEN:
                continue
            if ref_norm in own_files:
                continue
            owner = provider.get(ref_norm)
            if owner and owner != name:
                deps.add(owner)
                continue
            for path, owner in provider.items():
                if owner == name:
                    continue
                if path.endswith("/" + ref_norm) or path == ref_norm:
                    deps.add(owner)
                    break
        if deps:
            result[name] = deps
    return result


def detect_auto_conflicts(analyses: list) -> list:
    """
    Look for two or more addons that share a Lua global, hook ID,
    network string, concommand or cvar. Returns a list of dicts:
      {
        "kind": "Framework" | "Global" | "Hook ID" | "Net string"
                | "Concommand" | "Console variable",
        "identifier": str,
        "owners": [addon_name, ...],
        "severity": "high" | "medium" | "low",
        "note": str
      }
    """
    by_global: dict = {}
    by_hook: dict = {}
    by_netstr: dict = {}
    by_concmd: dict = {}
    by_cvar: dict = {}

    lua_count: dict = {}
    for a in analyses:
        if a.get("name"):
            lua_count[a["name"]] = a.get("lua_file_count", 0)

    for a in analyses:
        name = a.get("name")
        if not name:
            continue
        for g in a.get("global_defs", []):
            by_global.setdefault(g, []).append(name)
        for h in a.get("hook_ids", []):
            by_hook.setdefault(h, []).append(name)
        for n in a.get("net_strings", []):
            by_netstr.setdefault(n, []).append(name)
        for c in a.get("concommands", []):
            by_concmd.setdefault(c, []).append(name)
        for v in a.get("cvars", []):
            by_cvar.setdefault(v, []).append(name)

    conflicts: list = []

    # Frameworks (only count as conflict if at least 2 owners look
    # like real frameworks by Lua file count)
    for g, owners in by_global.items():
        unique = sorted(set(owners))
        if len(unique) < 2:
            continue
        fw_owners = [o for o in unique
                     if lua_count.get(o, 0) >= FRAMEWORK_MIN_LUA_FILES]
        if len(fw_owners) >= 2:
            severity = "high" if g in EXCLUSIVE_GLOBALS else "medium"
            conflicts.append({
                "kind": "Framework" if g in EXCLUSIVE_GLOBALS else "Global",
                "identifier": g,
                "owners": fw_owners,
                "severity": severity,
                "note": EXCLUSIVE_GLOBALS.get(g, ""),
            })

    for h, owners in by_hook.items():
        unique = sorted(set(owners))
        if len(unique) >= 2:
            conflicts.append({
                "kind": "Hook ID", "identifier": h,
                "owners": unique, "severity": "medium", "note": "",
            })
    for n, owners in by_netstr.items():
        unique = sorted(set(owners))
        if len(unique) >= 2:
            conflicts.append({
                "kind": "Net string", "identifier": n,
                "owners": unique, "severity": "medium", "note": "",
            })
    for c, owners in by_concmd.items():
        unique = sorted(set(owners))
        if len(unique) >= 2:
            conflicts.append({
                "kind": "Concommand", "identifier": c,
                "owners": unique, "severity": "low", "note": "",
            })
    for v, owners in by_cvar.items():
        unique = sorted(set(owners))
        if len(unique) >= 2:
            conflicts.append({
                "kind": "Console variable", "identifier": v,
                "owners": unique, "severity": "low", "note": "",
            })

    return conflicts
