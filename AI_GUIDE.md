# ASCII Art Animation Project -- AI Agent Guide

## What This Is

A pipeline for downloading an ASCII art corpus, curating it, and animating it:
morph between any two artworks (terminal or GIF), export frames files, generate
batched example animations. Source of truth for the scrape is
asciiart.website (Christopher Johnson's ASCII Art Collection).

State: WORKING. All commands below verified 2026-11-22.

## Quick Reference

```bash
# Play a morph live in a terminal (Ctrl-C to stop)
python3 ascii_anim.py morph <artworkA.txt> <artworkB.txt> --fps 3 --loops 2

# Export a morph as GIF (verified output)
python3 ascii_anim.py morph A.txt B.txt --steps 5 --out out.gif

# Built-in demos
python3 ascii_anim.py demo --no-clear        # + -> & -> @ example, print frames
python3 ascii_anim.py spin                   # | / - \ spinner
python3 ascii_anim.py play frames.txt --fps 8

# Re-scrape the corpus (slow: ~11 min, rate-limited; corpus/ is already checked in)
python3 download_asciiart.py --out corpus/chris --delay 0.35

# Rebuild clean set (dedupe + drop flagged)
python3 build_clean_set.py

# Regenerate the 6 showcase GIFs + contact sheet from examples/showcase.json
python3 make_examples.py

# Rank compatible pairs per theme (review aid; writes JSON only, no GIFs)
python3 make_examples.py --report examples/candidates.json
```

Tests: `python3 -m unittest discover -v` (72 tests, all must pass).
Generation also self-validates every GIF (frame count, per-frame durations
within 10 ms, `loop == 0`) and exits nonzero naming the output and failed
check.

## Architecture

```
ascii_anim.py         animator: frames, playback, density morph, dissolve,
                      GIF export (line counts drift; see wc -l)
example_pipeline.py   showcase pipeline: matching, scoring, manifest
                      validation, generation, contact sheet
download_asciiart.py  corpus scraper for asciiart.website JSON API
build_clean_set.py    dedupe + content-flag filter -> corpus/clean
make_examples.py      thin CLI: showcase generation or --report
tests/                unittest suite (test_ascii_anim, test_example_pipeline)
corpus/chris/         8359 artworks + manifest.jsonl   (41 MB, raw scrape)
corpus/clean/         7460 artworks + manifest.jsonl   (HARDLINKED to chris,
                       596 category dirs, near-zero extra disk)
examples/             showcase.json (6 curated pairs) + 6 GIFs named by it
                      + contact_sheet.png review sheet
                      (+ candidates.json: local --report aid, not committed)
demo.gif, morph_bat_dragon.gif    earlier one-off outputs
```

## Corpus Layout

Raw: `corpus/chris/cat<N>/<artwork_id>.txt` -- one UTF-8 text file per artwork.
Manifest rows (JSONL) carry: `id, title, artist_name, tags[], width, height,
ascii_type, style, nudity, explicit, categories[], file` (+ `md5` in clean).

Clean: `corpus/clean/art/cat<N>_<category-slug>/<id>.txt`. 7460 entries =
8359 raw minus 171 flagged (nudity/explicit) minus 728 content dupes (md5).
Clean files are HARDLINKS into corpus/chris. Do NOT delete files from
corpus/chris without rebuilding the clean set.

Gotcha: `du` with multiple directory args attributes shared inodes to the
first argument -- per-dir sizes look wrong, the union is fine. Verify
hardlinks with `os.stat(f).st_ino` comparisons, never du.

## Finding Artwork to Animate

```python
import json, re
man = [json.loads(l) for l in open("corpus/clean/manifest.jsonl")]
# whole-word match: \bsun\b matches "Sun Logo" not "Sunglasses"
hits = [e for e in man if re.search(r"\bskull\b", e["title"], re.I)
        and e["width"] <= 60 and e["height"] <= 22]
```

Pick small pieces (width <= 60, height <= 22) for readable GIFs. Both
manifests also store per-entry dimensions, so you can filter before reading.

## Core Concepts

**Frame** = one block of text = one "screen". Animation = play frames in
sequence. Terminal playback writes the frame then `\033[H` (cursor home,
overwrite) -- never clear the screen between frames, it flickers.

**Frames file format** (for `play`/`gif` modes): text blocks separated by a
line containing only `%`.

**Density-ramp morph** (`morph_frames(text_a, text_b, steps)`):
1. Pad both artworks to a common grid (max rows/cols of the two).
2. Map every char to an ink density. RAMP = `" .,:;-~=+*x#%@"`; stroke chars
   (`/\|()<>^v~"_olT8%$WMB`) have hand-tuned densities in DENS; unknown
   non-space chars default 0.5. This stroke coverage is why real art
   dissolves smoothly instead of fizzing into noise -- keep it when
   extending.
3. Frame t blends cellwise: `d = (1-t)*dens_a + t*dens_b`, emit the RAMP char
   nearest d. Frames = [A, intermediates, B]. Kept for backward
   compatibility (`ascii_anim.py morph`); NOT used for the showcase.

**Normalization** (`normalize_artwork`): CRLF/CR -> LF, right-trim rows,
remove a detached attribution footer ONLY if it follows a blank row, has at
most 3 nonblank rows of at most 60 chars each, and at least one row matches
email/URL/`copyright`/``(c)``/``©``. Then trim empty border rows/columns.
Unmarked inline signatures (e.g. `jgs`) are deliberately preserved.
`shared_canvas(A, B)` centers both on one canvas (odd padding -> bottom/right).

**Stroke-preserving dissolve** (`dissolve_frames(text_a, text_b, steps=8)`,
used by the showcase): normalize + shared canvas, then flip cells in a
deterministic hash order (`((x*73856093)^(y*19349663))&0xffffffff`, ties by
y,x). Source-only cells vanish, destination-only cells appear in reverse
order, doubly-occupied cells switch from source char to destination char.
Only original characters appear -- no ramp punctuation. Output is
`steps + 2` frames; endpoints exactly equal the normalized canvases.

**GIF export** (`export_gif`): Pillow, `ImageFont.load_default()`, char cell
measured via `font.getbbox("+")` (never hardcode cell size),
`loop=0` (infinite). `durations=None` keeps the legacy 250 ms/frame; an int
applies to all frames; a list must match frame count. Showcase timing:
1200 ms endpoints + 120 ms intermediates, so endpoints stay readable.

## API Reference (ascii_anim.py)

| Function | Args | Returns |
|---|---|---|
| `demo_frames()` | -- | list of 5x5 text frames: `+` -> `&` -> `@` |
| `spin_frames()` | -- | list of frames: `\| / - \` spinner |
| `load_frames(path)` | frames file path | list of frame strings (`%`-separated) |
| `morph_frames(text_a, text_b, steps=3)` | two artwork texts | list of steps+2 frame strings |
| `normalize_artwork(text)` | artwork text | `NormalizedArtwork(text, width, height, ink, occupancy, footer_detected)` |
| `shared_canvas(text_a, text_b)` | two artwork texts | `(canvas_a, canvas_b)` centered strings |
| `dissolve_frames(text_a, text_b, steps=8)` | two artwork texts | list of steps+2 frame strings |
| `play(frames, fps=4, loops=None, clear=True, out=stdout)` | frames list | plays forever if loops=None |
| `export_gif(frames, path="anim.gif", scale=12, durations=None)` | frames list | output path or None if Pillow missing |

`example_pipeline.py`: `match_candidates` (best 40 whole-word title/tag
matches per keyword group), `score_pair`/`rank_pairs` (100/25/20/15/10
weighted compatibility minus footer/oversize penalties, ties by source
paths), `write_candidate_report` (`--report` JSON), `load_showcase` /
`validate_showcase` (exact v1 schema: 6 entries, unique snake names,
POSIX `art/...` sources, `steps >= 1`, timings positive multiples of 10),
`generate_showcase` (stage + validate all GIFs, then delete only the six
known legacy GIFs, commit, write the contact sheet), `write_contact_sheet`
(labeled 0/25/50/75/100% review sheet, saved atomically).

CLI: `ascii_anim.py {demo,spin,play,gif,morph} [file] [file_b]
[--fps F] [--loops N] [--steps N] [--no-clear] [--out PATH]`.
`morph` takes two artwork files. `--out` on morph/gif writes a GIF instead of
playing. `--no-clear` prints frames sequentially (deterministic, pipeable).

## download_asciiart.py -- How the Scrape Works

asciiart.website browse pages are JS-rendered; the data lives in a JSON API:
`POST https://asciiart.website/api/browseapi.php` with form fields
`secret, csrf_token, browse_type=category, browse_id=<id>, page, sort_by`.
Tokens are EMBEDDED in the category page source (`const apiSecret = "..."`,
`const csrfToken = "..."`) and are SESSION-BOUND: fetch a listing page first
(Urllib + CookieJar) and use tokens from THAT session -- cross-session or
cross-host reuse fails with "Invalid CSRF". www.chris.com 301s to
asciiart.website; use the .website host directly. Rate limit 0.35 s/request;
a page returning fewer than the page size (~12) means last page. Art text
needs `html.unescape` + `\r\n -> \n` normalization (scraper does both).

## How to Extend

**New animation mode**: add a `frames`-returning function in ascii_anim.py
(any list of equal-purpose text blocks works), then a branch in `main()`.
Reuse `play()` for terminal and `export_gif()` for files. Keep every frame
the same rows x cols, or the terminal version will scroll.

**New/changed example pair**: (1) run
`python3 make_examples.py --report examples/candidates.json` and inspect the
top-ranked pairs for the theme (score components, dimensions, titles);
(2) read the actual art files -- ranking can't see signatures or subject
clarity; (3) edit the six entries in `examples/showcase.json`
(`name`, `source_a`, `source_b`, `steps: 8`, `endpoint_ms: 1200`,
`transition_ms: 120`); (4) rerun `python3 make_examples.py`; (5) visually
inspect `examples/contact_sheet.png` -- endpoints readable and centered,
transitions stroke-preserving, no detached attribution. Generation is atomic
(a failure leaves existing outputs untouched) and deletes only the six known
legacy GIFs (`cat/dog, sun/moon, heart/skull, fish/bird, rocket/ufo,
chain_nature_loop`); unrelated files always survive.

**New corpus source**: probe reachability first
(`curl -s -o /dev/null -w "%{http_code}" <url>`), prefer JSON APIs over HTML
scraping, and write a sibling scraper that emits the same
`<dir>/manifest.jsonl` + one-.txt-per-artwork layout so build_clean_set /
make_examples can consume it. See the ascii-animation skill
(`skill_view("ascii-animation")`) for the probed source list
(asciiart.eu is JS-rendered; textfiles.com often unreachable; the
sixteencolors GitHub repo is website app code, NOT art).

## Known Issues

- 34 of 8359 raw files contain non-ASCII chars (box-drawing etc.); they
  survive into the clean set. Terminal playback is fine; GIF export renders
  them via the default font's coverage.
- `export_gif` ignores `scale` (measures the font directly); parameter kept
  for CLI compatibility.
- Re-running `download_asciiart.py` appends to the existing manifest (open
  mode "a") but rewrites the same deterministic filenames -- wipe the output
  dir first if you want an exact-count manifest.
- asciiart.website API token behavior could change; if you get
  "Invalid CSRF", re-fetch a category page in the same session before
  debugging anything else.

## Agent Boundaries

### Always (no approval needed)
- Read anything, run all four scripts, regenerate examples/, rebuild the
  clean set, add/modify project files in this directory.

### Ask First
- Re-running the full corpus scrape against asciiart.website more than once
  per day (it's a live third-party site; be polite).
- Deleting or rewriting corpus/chris (it's 41 MB of fetched ground truth).

### Never
- Remove content flags (nudity/explicit) from manifests to widen the clean
  set -- the filter exists deliberately.
- Commit corpus/ or examples/ to a shared repo without asking (large
  generated data).
