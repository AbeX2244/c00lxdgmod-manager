"""
main.py — Entry point. Compile THIS file with PyInstaller.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
import tkinter as tk

from config import APP_NAME, APP_VERSION, MAX_TEXT_SIZE
from core import (
    configure_logging, safe_name, copy_tree,
    GMAExtractor, Analyzer, ZipIndex, Source,
    read_gma_metadata_file,
)
from ui import GModAddonManager


def run_cli(args) -> int:
    extractor = GMAExtractor()
    analyzer = Analyzer()

    def log(msg):
        print(msg, flush=True)

    if args.version:
        print(f"{APP_NAME} v{APP_VERSION}")
        return 0

    sources = []
    for path_str in args.add or []:
        p = Path(path_str)
        if not p.exists():
            log(f"[!] Not found: {p}")
            continue
        if p.is_dir():
            sources.append(Source(kind="folder", path=p, name=p.name))
        elif p.suffix.lower() == ".gma":
            meta = read_gma_metadata_file(p)
            name = meta.get("name") or p.stem
            sources.append(Source(kind="gma", path=p, name=name, metadata=meta))
        elif p.suffix.lower() == ".zip":
            try:
                gmas, folders, nested = ZipIndex.peek_top(p)
            except Exception as e:
                log(f"[!] {p}: {e}")
                continue
            for g in gmas:
                sources.append(Source(kind="zip_gma", root_zip=p,
                                       entry=g, name=Path(g).stem,
                                       origin=p.name))
            for f in folders:
                sources.append(Source(kind="zip_folder", root_zip=p,
                                       entry=f,
                                       name=f.rstrip("/").split("/")[-1],
                                       origin=p.name))

    if not sources:
        log("[!] No addons to process.")
        return 1

    log(f"[i] {len(sources)} addon(s)")

    if args.analyze:
        ok = 0
        fail = 0
        for i, s in enumerate(sources, 1):
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    if s.kind == "gma":
                        with tempfile.TemporaryDirectory() as t2:
                            extractor.extract(s.path, t2)
                            r = analyzer.scan(t2)
                    elif s.kind in ("zip_gma", "zip_folder"):
                        entry = ZipIndex.Entry(
                            root_zip=s.root_zip, chain=list(s.chain),
                            entry=s.entry,
                            kind="gma" if s.kind == "zip_gma" else "folder")
                        kind, real = ZipIndex.materialize(entry, Path(tmp))
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                extractor.extract(real, t2)
                                r = analyzer.scan(t2)
                        else:
                            r = analyzer.scan(real)
                    else:
                        r = analyzer.scan(s.path)
                log(f"[{i}/{len(sources)}] {s.display}")
                log(f"  Files: {r['file_count']}")
                if r["deps"]:
                    log(f"  Deps: {', '.join(r['deps'])}")
                if r["dangers"]:
                    log(f"  [!] Suspicious: {len(r['dangers'])}")
                ok += 1
            except Exception as e:
                log(f"  [ERROR] {e}")
                fail += 1
        log(f"Analyzed: {ok} ok, {fail} failed")

    if args.extract_to:
        dest = Path(args.extract_to)
        dest.mkdir(parents=True, exist_ok=True)
        ok = 0
        fail = 0
        for i, s in enumerate(sources, 1):
            try:
                target = dest / safe_name(s.name)
                with tempfile.TemporaryDirectory() as tmp:
                    if s.kind == "gma":
                        with tempfile.TemporaryDirectory() as t2:
                            extractor.extract(s.path, t2)
                            copy_tree(Path(t2), target)
                    elif s.kind in ("zip_gma", "zip_folder"):
                        entry = ZipIndex.Entry(
                            root_zip=s.root_zip, chain=list(s.chain),
                            entry=s.entry,
                            kind="gma" if s.kind == "zip_gma" else "folder")
                        kind, real = ZipIndex.materialize(entry, Path(tmp))
                        if kind == "gma":
                            with tempfile.TemporaryDirectory() as t2:
                                extractor.extract(real, t2)
                                copy_tree(Path(t2), target)
                        else:
                            copy_tree(real, target)
                    else:
                        copy_tree(s.path, target)
                log(f"[{i}/{len(sources)}] {s.display} -> {target}")
                ok += 1
            except Exception as e:
                log(f"[{i}/{len(sources)}] {s.display}: [ERROR] {e}")
                fail += 1
        log(f"Extracted: {ok} ok, {fail} failed")

    return 0


def main():
    parser = argparse.ArgumentParser(prog="gmod_manager",
                                       description="GMod Addon Manager")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--add", action="append")
    parser.add_argument("--extract-to")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args()

    if args.add or args.analyze or args.extract_to or args.version or args.cli:
        sys.exit(run_cli(args))

    configure_logging()
    root = tk.Tk()
    app = GModAddonManager(root)
    app.run()


if __name__ == "__main__":
    main()
