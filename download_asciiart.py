#!/usr/bin/env python3
"""Download ASCII art corpus from asciiart.website (Christopher Johnson collection).

Walks all categories listed on browse.php, pulls artwork via the site's own
JSON API (same endpoint the browse page calls), saves one .txt per artwork.

Usage: python3 download_asciiart.py [--out corpus] [--delay 0.4] [--max-pages 50]
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from http.cookiejar import CookieJar

BASE = "https://asciiart.website"
API = f"{BASE}/api/browseapi.php"

SECRET_RE = re.compile(r'apiSecret\s*=\s*"([^"]+)"')
CSRF_RE = re.compile(r'csrfToken\s*=\s*"([^"]+)"')


def get(opener, url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "ascii-art-corpus-downloader/1.0"})
    with opener.open(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus/chris")
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--limit-categories", type=int, default=None)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.jsonl"

    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # 1. session + tokens from a valid category page
    get(opener, f"{BASE}/browse.php")
    browse = get(opener, f"{BASE}/browse.php")
    cats = sorted(set(int(m.group(1)) for m in re.finditer(r'cat\.php\?category_id=(\d+)', browse)))
    page1 = None
    for c in cats:
        try:
            page1 = get(opener, f"{BASE}/cat.php?category_id={c}")
            break
        except Exception:
            continue
    m_sec, m_csrf = SECRET_RE.search(page1 or ""), CSRF_RE.search(page1 or "")
    if not (cats and page1 and m_sec and m_csrf):
        sys.exit("failed to bootstrap: no categories or no tokens on page")
    secret, csrf = m_sec.group(1), m_csrf.group(1)
    print(f"{len(cats)} categories; tokens ok (csrf {csrf[:8]}...)")

    if args.limit_categories:
        cats = cats[: args.limit_categories]

    # 2. walk categories, page by page
    total = 0
    manifest = open(manifest_path, "a", encoding="utf-8")
    for ci, cat in enumerate(cats):
        for page in range(1, args.max_pages + 1):
            form = urllib.parse.urlencode({
                "secret": secret, "csrf_token": csrf,
                "browse_type": "category", "browse_id": cat,
                "page": page, "sort_by": "default",
            }).encode()
            try:
                resp = json.loads(get(opener, API, form))
            except Exception as e:
                print(f"  cat {cat} page {page}: ERROR {e}", flush=True)
                break
            if resp.get("status") != "success":
                print(f"  cat {cat} page {page}: {resp.get('message')}", flush=True)
                break
            artworks = resp.get("artworks") or []
            if not artworks:
                break
            cdir = out / f"cat{cat}"
            cdir.mkdir(parents=True, exist_ok=True)
            for aw in artworks:
                art = html.unescape(aw.get("art", "")).replace("\r\n", "\n").strip("\n")
                if not art:
                    continue
                aid = aw.get("id", f"unk{total}")
                meta = {k: aw.get(k) for k in aw if k != "art"}
                (cdir / f"{aid}.txt").write_text(art + "\n", encoding="utf-8")
                meta.update({"file": str(cdir / f"{aid}.txt"), "category_id": cat})
                manifest.write(json.dumps(meta) + "\n")
                total += 1
            if len(artworks) < 12:      # likely last page
                break
            time.sleep(args.delay)
        if ci % 25 == 0:
            print(f"[{ci}/{len(cats)}] categories done, {total} artworks saved", flush=True)
        time.sleep(args.delay)
    manifest.close()
    print(f"DONE: {total} artworks -> {out}")


if __name__ == "__main__":
    main()
