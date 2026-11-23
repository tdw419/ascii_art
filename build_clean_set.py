#!/usr/bin/env python3
"""Build the clean working set from the raw corpus.

- Dedupe by content md5 (cross-category duplicates share one file)
- Drop entries flagged nudity/explicit in the manifest
- Hardlink survivors into corpus/clean/<category>/<id>.txt (no extra disk)
- Write corpus/clean/manifest.jsonl

Usage: python3 build_clean_set.py [--src corpus/chris] [--dst corpus/clean]
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="corpus/chris")
    ap.add_argument("--dst", default="corpus/clean")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "art").mkdir(parents=True)

    entries = [json.loads(l) for l in open(src / "manifest.jsonl")]
    print(f"loaded {len(entries)} manifest entries")

    seen_md5, kept, dropped_flagged, dropped_dupe = {}, [], 0, 0
    out_manifest = open(dst / "manifest.jsonl", "w", encoding="utf-8")
    for e in entries:
        if e.get("nudity") or e.get("explicit"):
            dropped_flagged += 1
            continue
        p = Path(e["file"])
        if not p.exists():
            continue
        md5 = hashlib.md5(p.read_bytes()).hexdigest()
        if md5 in seen_md5:
            dropped_dupe += 1
            continue
        seen_md5[md5] = e
        cat = "cat_unknown"
        for c in e.get("categories", []):
            cat = f"cat{c['id']}_{c['name'].lower().replace(' ', '-')}"
            break
        lnk = dst / "art" / cat / f"{e['id']}.txt"
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.hardlink_to(p.resolve())
        e2 = dict(e)
        e2["file"] = str(lnk)
        e2["md5"] = md5
        out_manifest.write(json.dumps(e2) + "\n")
        kept.append(e2)
    out_manifest.close()

    print(f"kept {len(kept)}  dropped flagged {dropped_flagged}  dropped dupes {dropped_dupe}")
    print(f"clean set -> {dst}/art  ({dst}/manifest.jsonl)")


if __name__ == "__main__":
    main()
