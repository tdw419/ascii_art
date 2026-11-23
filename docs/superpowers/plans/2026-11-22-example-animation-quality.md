# Example Animation Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce four deterministic, curated ASCII-art showcase GIFs with clean, centered endpoints, stroke-preserving dissolves, readable timing, and a review contact sheet.

**Architecture:** Keep the single authoritative text normalization/alignment implementation, generic frame generation, and GIF rendering in `ascii_anim.py`; put corpus-specific ranking, manifest validation, generation, and contact-sheet logic in a new `example_pipeline.py`; keep `make_examples.py` as a thin CLI. Store final selections in `examples/showcase.json` and cover behavior with standard-library `unittest` tests plus Pillow-backed integration tests.

**Tech Stack:** Python 3, Pillow, `unittest`, JSON/JSONL.

---

## File Map

- Modify `ascii_anim.py`: add authoritative normalization/alignment, deterministic dissolve frames, and per-frame GIF durations without changing density morph behavior.
- Create `example_pipeline.py`: metadata matching, compatibility scoring, showcase-schema validation, generation, validation, and contact-sheet creation.
- Rewrite `make_examples.py`: parse `--report`, load project paths, and call the pipeline.
- Create `tests/test_ascii_anim.py`: dissolve and GIF timing tests.
- Create `tests/test_example_pipeline.py`: cleanup, centering, scoring, schema, generation-failure, and contact-sheet tests.
- Create `tests/__init__.py`: make focused `unittest` module commands executable.
- Create `examples/showcase.json`: four visually approved source pairs and timing settings.
- Create/update `examples/*.gif` and `examples/contact_sheet.png`: reviewed generated artifacts.
- Modify `AI_GUIDE.md`: document selection, generation, outputs, review, tests, and legacy density morph behavior.

### Task 1: Add deterministic artwork normalization and alignment

**Files:**
- Modify: `ascii_anim.py`
- Create: `example_pipeline.py`
- Create: `tests/__init__.py`
- Create: `tests/test_ascii_anim.py`
- Create: `tests/test_example_pipeline.py`

- [ ] **Step 1: Write failing normalization tests**

Add `unittest` cases for CRLF normalization, row right-trimming, removal of a separated email/URL/copyright footer, preservation of an unmarked short signature, empty-border trimming, and odd-padding placement. Use compact literal inputs, including:

```python
from ascii_anim import normalize_artwork, shared_canvas

def test_removes_marked_footer_but_preserves_art(self):
    result = normalize_artwork("  /\\  \n /__\\ \n\nartist@example.com\n")
    self.assertEqual(result.text, " /\\\n/__\\")
    self.assertTrue(result.footer_detected)

def test_centers_odd_padding_on_bottom_and_right(self):
    a, b = shared_canvas("XX", "Y\nY\nY")
    self.assertEqual(a, "  \nXX\n  ")
    self.assertEqual(b, "Y \nY \nY ")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.test_example_pipeline -v`

Expected: import failure because `example_pipeline.py` does not exist.

- [ ] **Step 3: Implement normalization and shared canvases**

In `ascii_anim.py`, create immutable `NormalizedArtwork(text, width, height, ink, occupancy, footer_detected)`. `normalize_artwork(text)` converts CRLF/CR to LF, right-strips rows, records this pre-cleaned form, detects only a footer separated by a blank row with at most three nonblank rows of at most 60 characters and at least one email/URL/`copyright`/`(c)`/`©` marker, removes it, then trims all-whitespace border rows/columns. If cleanup would leave no non-space cell, issue `warnings.warn(..., UserWarning)` and restore the pre-cleaned form before border trimming. Implement `shared_canvas(text_a, text_b)` by normalizing each input once, using floor-divided top/left padding, and putting odd extra cells on bottom/right. Return `(canvas_a, canvas_b)`.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_example_pipeline.NormalizationTests -v`

Expected: all normalization tests pass.

- [ ] **Step 5: Commit**

```bash
git add ascii_anim.py example_pipeline.py tests/__init__.py tests/test_ascii_anim.py tests/test_example_pipeline.py
git commit -m "feat: normalize and align ASCII artwork"
```

### Task 2: Add the stroke-preserving dissolve

**Files:**
- Modify: `ascii_anim.py`
- Modify: `tests/test_ascii_anim.py`
- Modify: `example_pipeline.py`

- [ ] **Step 1: Write failing dissolve tests**

Test `dissolve_frames(text_a, text_b, steps)` for `steps + 2` frames, normalized shared-canvas endpoints, equal dimensions, deterministic repeated output, the exact coordinate ordering from the design, preserved original non-space characters, singleton canvases, and `ValueError` for zero, negative, float, and boolean steps.

```python
def test_dissolve_preserves_endpoint_characters(self):
    frames = dissolve_frames("A X", "Y B", steps=2)
    self.assertEqual(frames[0], "A X")
    self.assertEqual(frames[-1], "Y B")
    self.assertNotIn(".", "".join(frames))
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.test_ascii_anim.DissolveTests -v`

Expected: import failure for `dissolve_frames`.

- [ ] **Step 3: Implement the dissolve**

Add `dissolve_frames(text_a, text_b, steps=8)` to `ascii_anim.py`. Reject `bool` and non-`int` values, then reject values below 1. Call the same `shared_canvas` used by tests and showcase generation; no injectable builder or duplicate normalizer is permitted. Add an integration assertion that separated attribution is absent from both endpoint frames.

Sort every `(x, y)` by `(((x * 73856093) ^ (y * 19349663)) & 0xffffffff, y, x)`, compute `p=index/(N-1)` or zero for a singleton, and implement source-only removal, destination-only reversed reveal, and overlapping-character switch exactly as specified.

- [ ] **Step 4: Run dissolve and regression tests**

Run: `python3 -m unittest tests.test_ascii_anim -v`

Expected: dissolve tests pass and existing `morph_frames` endpoint checks remain green.

- [ ] **Step 5: Commit**

```bash
git add ascii_anim.py example_pipeline.py tests/test_ascii_anim.py
git commit -m "feat: add deterministic ASCII dissolve"
```

### Task 3: Support readable GIF timing

**Files:**
- Modify: `ascii_anim.py`
- Modify: `tests/test_ascii_anim.py`

- [ ] **Step 1: Write failing duration tests**

Use `tempfile.TemporaryDirectory` and Pillow to assert the existing default is 250 ms per decoded frame; scalar durations apply to all frames; duration lists round-trip within 10 ms; and zero, negative, wrong-length, string, and boolean values raise `ValueError`.

Also patch `builtins.__import__` to make `PIL` unavailable and assert the existing `None` return plus dependency message, and assert successful export still returns the output path. Add regression tests for `morph_frames`, `load_frames`, and `play(..., loops=1, clear=False, out=StringIO())`.

- [ ] **Step 2: Run and verify failure**

Run: `python3 -m unittest tests.test_ascii_anim.GifExportTests -v`

Expected: tests fail because `export_gif` has no `durations` argument.

- [ ] **Step 3: Implement duration validation and export**

Change the signature to `export_gif(frames, path="anim.gif", scale=12, durations=None)`. Normalize `None`, scalar integer, or list into a validated list before rendering. Pass the list to Pillow's `duration=` argument and retain `loop=0`. Preserve the `scale` compatibility parameter.

- [ ] **Step 4: Run GIF tests**

Run: `python3 -m unittest tests.test_ascii_anim.GifExportTests -v`

Expected: all GIF timing tests pass.

- [ ] **Step 5: Commit**

```bash
git add ascii_anim.py tests/test_ascii_anim.py
git commit -m "feat: support per-frame GIF timing"
```

### Task 4: Implement deterministic matching and compatibility reports

**Files:**
- Modify: `example_pipeline.py`
- Modify: `tests/test_example_pipeline.py`
- Rewrite: `make_examples.py`

- [ ] **Step 1: Write failing ranking and report tests**

Build tiny in-memory manifest fixtures and temporary artwork files. Assert whole-word matching, title-before-tag class, zero-based keyword rank, best-40 truncation, every score component and penalty, source-path tie-breaking, and stable JSON report output. Include a hand-calculated pair score assertion.

Manifest rows contain project-relative `file` values such as
`corpus/clean/art/cat1/foo.txt`. Add tests that canonicalization produces the
POSIX showcase/report path `art/cat1/foo.txt`; reject absolute paths, `..`, and
paths outside `corpus/clean`. Convert backslashes to `/` only while reading
manifest metadata, before validation. Resolve candidate files and require
`resolved_path.is_relative_to(clean_root.resolve())`; reject symlink escapes.

- [ ] **Step 2: Run and verify failure**

Run: `python3 -m unittest tests.test_example_pipeline.RankingTests -v`

Expected: missing ranking/report functions.

- [ ] **Step 3: Implement matching, scoring, and reporting**

Add `Candidate(entry, source, match_class, keyword_rank, normalized)` and
`PairScore(source_a, source_b, total, match_quality, size_similarity,
aspect_similarity, ink_similarity, occupancy_similarity, penalty_a,
penalty_b)` dataclasses. Implement `canonical_source(file_value, clean_root)`,
`match_candidates(entries, keywords, clean_root)`, `score_pair(a, b,
max_keyword_count)`, `rank_pairs(...)`, and `write_candidate_report(...)` using
the exact formula and thresholds in the design. Round only serialized numeric
values to six decimal places; sorting uses unrounded values.

Use these concrete ordered keyword groups:

```python
THEMES = {
    "cat_to_dog": (["cat", "kitten"], ["dog", "puppy", "dogs"]),
    "sun_to_moon": (["sun", "sunrise", "sunset"], ["moon", "crescent", "night"]),
    "heart_to_skull": (["heart", "love"], ["skull", "skeleton", "grave", "death"]),
    "fish_to_bird": (["fish", "fishes", "shark", "whale"], ["bird", "eagle", "owl", "duck"]),
    "rocket_to_ufo": (["rocket", "spaceship", "space shuttle"], ["ufo", "saucer", "alien", "martian"]),
}
```

The report is `{"version": 1, "themes": [...]}`. Themes follow dictionary
insertion order and contain `name`, `keywords_a`, `keywords_b`, and `pairs`.
Pairs are score order and contain `rank` (one-based), `total`, `components`
with all seven `PairScore` numeric fields other than paths, and `source_a` /
`source_b` objects with `path`, `title`, `width`, `height`, `ink`, and
`occupancy`. When either group is empty, raise `ValueError` naming the theme
and its searched keywords.

Make `make_examples.py` use `argparse`, resolve all paths from `Path(__file__).parent`, and support:

```text
python3 make_examples.py
python3 make_examples.py --report examples/candidates.json
```

The `--report` path is resolved relative to the project root and performs no GIF generation.

Before reading, explicitly check `corpus/clean` and
`corpus/clean/manifest.jsonl`. On absence, raise `FileNotFoundError` containing
the missing path and `python3 build_clean_set.py`. `main(argv=None)` catches
expected input/validation errors, prints `error: ...` to stderr, and returns 2;
the module exits with `raise SystemExit(main())`. CLI tests call `main` with
temporary roots and subprocess smoke tests assert report mode creates neither
GIFs nor a contact sheet.

- [ ] **Step 4: Run ranking tests and generate the real report**

Run: `python3 -m unittest tests.test_example_pipeline.RankingTests tests.test_example_pipeline.ReportCliTests -v`

Expected: all ranking tests pass.

Run: `python3 make_examples.py --report examples/candidates.json`

Expected: exits zero and writes ranked records with theme, rank, total/component scores, paths, titles, and normalized dimensions.

- [ ] **Step 5: Commit**

```bash
git add example_pipeline.py make_examples.py tests/test_example_pipeline.py
git commit -m "feat: rank compatible ASCII animation pairs"
```

`examples/candidates.json` is a generated local review aid and is intentionally
not committed.

### Task 5: Validate curated manifests and generate the showcase

**Files:**
- Modify: `example_pipeline.py`
- Modify: `tests/test_example_pipeline.py`
- Create: `examples/showcase.json`

- [ ] **Step 1: Write failing manifest and generation tests**

Test version, exactly four array entries, required fields, unique valid names, safe relative POSIX paths, different pair sources, `steps >= 1`, positive non-boolean integer timings, missing curated inputs, warned cross-pair reuse, resolved containment/symlink escape, and deletion of only the six named legacy GIFs. Assert unknown files in the output directory survive. Capture reuse warnings with `self.assertWarns(UserWarning)` and assert generation continues. Add CLI tests proving default invocation reads the curated manifest, missing curated sources print actionable stderr and return nonzero, report mode does not generate GIFs/contact sheets, and unrelated GIFs survive. Tests patch project paths or run against a temporary fixture tree; they never mutate the real corpus.

- [ ] **Step 2: Run and verify failure**

Run: `python3 -m unittest tests.test_example_pipeline.ManifestTests tests.test_example_pipeline.GenerationTests tests.test_example_pipeline.GenerationCliTests -v`

Expected: missing validation/generation functions.

- [ ] **Step 3: Implement schema validation and generation**

Add `load_showcase(path) -> dict`, `validate_showcase(data, clean_root) -> list[ShowcaseEntry]`, and `generate_showcase(entries, output_dir) -> list[Path]`, where frozen `ShowcaseEntry` contains the six schema fields and resolved source paths. Reject unknown/missing fields, absolute paths, `..`, non-POSIX separators, containment failures, and any animation count other than four; provide actionable errors. Generate durations as `[endpoint_ms] + [transition_ms] * steps + [endpoint_ms]`. `validate_gif(path, expected_frames, expected_durations)` opens with a context manager and raises `ValueError(f"{path}: <failed check>")` for count, loop, or any duration mismatch. The CLI catches this and returns 2. Remove only:

```python
LEGACY_OUTPUTS = {
    "cat_to_dog.gif", "sun_to_moon.gif", "heart_to_skull.gif",
    "fish_to_bird.gif", "rocket_to_ufo.gif", "chain_nature_loop.gif",
}
```

- [ ] **Step 4: Curate four pairs**

Review the top report candidates and source text. Choose four pairs with close dimensions/aspect/ink, clear subjects, no detached attribution, and attractive endpoints. Write `examples/showcase.json` with `version: 1`, unique descriptive names, `steps: 8`, `endpoint_ms: 1200`, and `transition_ms: 120` unless visual review justifies a documented exception.

- [ ] **Step 5: Run tests and initial generation**

Run: `python3 -m unittest tests.test_example_pipeline.ManifestTests tests.test_example_pipeline.GenerationTests tests.test_example_pipeline.GenerationCliTests -v`

Expected: all tests pass.

Run: `python3 make_examples.py`

Expected: exactly four manifest-named GIFs are generated and validated; only known legacy GIFs are removed.

- [ ] **Step 6: Commit**

```bash
git add example_pipeline.py make_examples.py tests/test_example_pipeline.py examples/showcase.json
# Then add only the four explicit GIF paths named in the reviewed showcase.json.
git commit -m "feat: generate curated ASCII showcase"
```

### Task 6: Create and visually review the contact sheet

**Files:**
- Modify: `example_pipeline.py`
- Modify: `tests/test_example_pipeline.py`
- Create: `examples/contact_sheet.png`
- Modify: `examples/showcase.json` if review requires pair changes

- [ ] **Step 1: Write failing contact-sheet tests**

Generate miniature fixture GIFs and assert the sheet is overwritten, contains one labeled row per animation in manifest order, samples indices `floor((n_frames - 1) * fraction + 0.5)` for fractions `(0, .25, .5, .75, 1)`, and has deterministic dimensions for fixed inputs. This defines half ties as rounding upward.

Patch Pillow import/font loading to fail and assert generation reports the
missing dependency/font operation, names the target output, and returns nonzero
through the CLI rather than leaving a partial contact sheet.

- [ ] **Step 2: Run and verify failure**

Run: `python3 -m unittest tests.test_example_pipeline.ContactSheetTests -v`

Expected: missing contact-sheet function.

- [ ] **Step 3: Implement contact-sheet generation**

Add `write_contact_sheet(named_gif_paths, output_path)`. Open every GIF with a context manager, seek to each sample, copy its RGB frame, and close the GIF before composition. Use Pillow's default font and `font.getbbox(name)` for labels. Set `padding=10`, `gap=6`, `label_width=max(label_bbox_width)+padding`, `cell_width=max(sample.width)`, and `row_height=max(sample.height, label_bbox_height)+padding`; the sheet is `label_width + 5*cell_width + 4*gap + 2*padding` wide and `len(rows)*row_height + (len(rows)-1)*gap + 2*padding` high. Draw black background, lime labels at `(padding, row_top + padding//2)`, and paste each sample at the horizontal cell origin, vertically centered in its row. Save atomically via a sibling temporary file followed by `Path.replace`. Call it after all GIFs validate in `generate_showcase`.

- [ ] **Step 4: Run tests and regenerate**

Run: `python3 -m unittest tests.test_example_pipeline.ContactSheetTests -v && python3 make_examples.py`

Expected: tests pass and `examples/contact_sheet.png` is overwritten.

- [ ] **Step 5: Inspect and iterate visually**

Open `examples/contact_sheet.png`. Confirm each endpoint is recognizable and centered, transitions retain original strokes, attribution debris is absent, and no pair jumps badly in scale or placement. If any row fails, choose the next ranked compatible pair, update `showcase.json`, regenerate, and inspect again. Record the final approval in the task handoff.

- [ ] **Step 6: Commit**

```bash
git add example_pipeline.py tests/test_example_pipeline.py examples/showcase.json examples/contact_sheet.png
# Then add only the four explicit GIF paths named in showcase.json.
git commit -m "feat: add visual review sheet for ASCII examples"
```

### Task 7: Update the agent guide and run final verification

**Files:**
- Modify: `AI_GUIDE.md`

- [ ] **Step 1: Update documentation**

Correct architecture line counts rather than freezing counts that immediately drift. Document `python3 -m unittest discover -v`, `--report`, `examples/showcase.json`, the four-output contract, known-legacy cleanup, contact-sheet review, endpoint timing, and the difference between backward-compatible density morphs and showcase dissolves. Remove the obsolete “No test suite” statement and old six-example description.

- [ ] **Step 2: Run the complete automated suite**

Run: `python3 -m unittest discover -v`

Expected: all tests pass with no errors or failures.

- [ ] **Step 3: Run command-level smoke tests**

Run:

```bash
python3 ascii_anim.py demo --no-clear
python3 make_examples.py --report examples/candidates.json
python3 make_examples.py
python3 - <<'PY'
import json, subprocess, sys
from pathlib import Path
root = Path.cwd()
entry = json.loads((root / "examples/showcase.json").read_text())["animations"][0]
a = root / "corpus/clean" / entry["source_a"]
b = root / "corpus/clean" / entry["source_b"]
subprocess.run([sys.executable, "ascii_anim.py", "morph", str(a), str(b),
                "--steps", "2", "--no-clear"], check=True,
               stdout=subprocess.DEVNULL)
PY
python3 - <<'PY'
import subprocess, sys, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as td:
    frames = Path(td) / "frames.txt"
    gif = Path(td) / "out.gif"
    frames.write_text("A\n%\nB\n")
    subprocess.run([sys.executable, "ascii_anim.py", "play", str(frames),
                    "--loops", "1", "--no-clear"], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "ascii_anim.py", "gif", str(frames),
                    "--out", str(gif)], check=True)
    assert gif.is_file()
PY
```

Expected: commands exit zero; demo/play/GIF and density morph remain functional; report and four GIFs regenerate deterministically.

- [ ] **Step 4: Validate final artifacts programmatically**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from PIL import Image
root = Path.cwd()
data = json.loads((root / "examples/showcase.json").read_text())
animations = data["animations"]
assert len(animations) == 4
for entry in animations:
    path = root / "examples" / f'{entry["name"]}.gif'
    expected = ([entry["endpoint_ms"]] +
                [entry["transition_ms"]] * entry["steps"] +
                [entry["endpoint_ms"]])
    with Image.open(path) as im:
        assert im.n_frames == entry["steps"] + 2
        assert im.info.get("loop") == 0
        actual = []
        for index in range(im.n_frames):
            im.seek(index)
            actual.append(im.info["duration"])
    assert all(abs(a - b) <= 10 for a, b in zip(actual, expected))
    print("OK", path.name)
with Image.open(root / "examples/contact_sheet.png") as sheet:
    sheet.verify()
PY
```

This compares only manifest-named outputs; unrelated GIFs are allowed to remain.

Expected: prints four `OK` lines and exits zero.

- [ ] **Step 5: Reinspect the final contact sheet**

Open `examples/contact_sheet.png` after the final clean regeneration and record visual approval in the handoff.

- [ ] **Step 6: Commit documentation**

```bash
git add AI_GUIDE.md examples/showcase.json examples/contact_sheet.png
# Then add only the four explicit GIF paths named in showcase.json.
git commit -m "docs: document curated ASCII animation workflow"
```

- [ ] **Step 7: Verify clean task scope**

Run: `git status --short -- ascii_anim.py example_pipeline.py make_examples.py tests AI_GUIDE.md examples docs/superpowers`

Expected: no uncommitted task files; unrelated pre-existing workspace changes remain untouched.
