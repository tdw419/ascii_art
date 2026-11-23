# Example Animation Quality Design

## Goal

Replace the current weak, nondeterministic example selection and noisy density
crossfades with a reproducible pipeline that produces a small set of readable,
polished ASCII-art GIFs. Preserve the existing command-line interface unless a
change is necessary for the new behavior.

## Current Problems

- `make_examples.py` selects the first title or tag match, regardless of visual
  compatibility. Results depend on manifest order.
- Paired artworks often have very different dimensions, aspect ratios, visual
  weights, and subject placement.
- Attribution text and signatures become prominent visual debris.
- The density-ramp blend replaces meaningful source characters with generic
  punctuation, so intermediate frames look noisy rather than animated.
- Every frame has the same duration, leaving too little time to read endpoints.
- Verification checks only that a GIF is animated and loops forever; it does
  not check the properties responsible for visible quality.

## Chosen Approach

Use a hybrid pipeline: deterministic automatic scoring narrows each theme to
compatible candidates, while a small checked-in curation table fixes the final
showcase inputs. This makes regeneration stable without pretending that visual
quality can be selected perfectly from metadata alone.

## Components

### 1. Artwork normalization

Add focused helpers to:

- normalize newlines and remove trailing whitespace;
- trim empty outer rows and columns;
- identify and optionally remove obvious attribution-only footer rows, such as
  email addresses, URLs, copyright lines, and short signature rows separated
  from the art by blank space;
- place both artworks, centered horizontally and vertically, on one shared
  canvas.

Normalization must not mutate corpus files. It operates only on strings loaded
for animation. Conservative cleanup is preferred: uncertain rows stay intact.

The operation order is newline normalization, right-trimming every row,
footer detection/removal, then empty-border trimming. A row or column is empty
when every character is whitespace. Centering uses floor division for top and
left padding, so an odd extra cell is placed on the bottom or right.

A footer is removable only when it follows at least one blank row, occupies at
most three nonblank rows, and every such row is at most 60 characters. At least
one row must contain an email address, URL, `copyright`, `(c)`, or a copyright
symbol. Short signatures without one of those markers remain untouched.

### 2. Compatibility scoring

Build a candidate list for each keyword group, then score every possible pair
using:

- title matches ahead of tag matches;
- closeness of width, height, and aspect ratio;
- closeness of non-space character count and occupied bounding-box area;
- penalties for detected attribution text and extreme dimensions.

Scores must use explicit weights and deterministic tie-breakers. A dry-run or
selection report should show the chosen titles, files, dimensions, and score so
future agents can understand a result without opening the implementation.

For each keyword group, retain the best 40 metadata matches ordered by match
class (title before tag), keyword rank, then normalized file path. Score every
cross-group pair on normalized artworks:

`100*match_quality + 25*size_similarity + 20*aspect_similarity +
15*ink_similarity + 10*occupancy_similarity - penalties`

`match_quality` is `1 - (class_a + class_b)/4 -
(rank_a + rank_b)/(4*max_keyword_count)`, clamped to `[0,1]`, where title class
is 0, tag class is 1, keyword ranks are zero-based, and
`max_keyword_count` is the larger of the two groups' keyword-list lengths.
Each similarity is `1 - abs(a-b)/max(a,b,1)`. `size_similarity` is the mean of
separately calculated width and height similarities. Aspect similarity applies
the formula to `width/height`; ink similarity applies it to normalized
non-space counts. `occupancy` is non-space cells divided by bounding-box area.
Apply a 15-point penalty per artwork whose pre-removal normalization pass
detected a footer and a 20-point penalty per artwork wider than 64 or taller
than 28. Tie-break by source A path, then source B path.

### 3. Curated showcase manifest

Store selections in checked-in `examples/showcase.json`. It is a JSON object
with `version: 1` and an `animations` array. Each animation requires unique
`name`, `source_a`, `source_b`, `steps`, `endpoint_ms`, and `transition_ms`.
Source paths are POSIX paths relative to `corpus/clean`; names must contain only
lowercase letters, digits, and underscores. Sources within a pair must differ;
positive timing values and `steps >= 1` are required. Reusing a source across
different pairs is allowed only deliberately and produces a warning.

The automatic selector proposes candidates; the curated manifest controls the
normal regeneration path. Missing curated files must fail with an actionable
message rather than silently substituting different art.

`python3 make_examples.py` remains normal regeneration from the curated file.
`python3 make_examples.py --report examples/candidates.json` writes ranked
candidate records containing theme, rank, score components, source paths,
titles, and normalized dimensions; it does not generate GIFs. The implementation
phase will use this report plus contact-sheet review to select and check in four
pairs. Their four manifest names are the complete supported showcase output
set. The old five pair GIFs and `chain_nature_loop.gif` are retired; normal
regeneration deletes only those six explicitly known legacy outputs and never
glob-deletes unrelated files.

### 4. Stroke-preserving transition

Add `dissolve_frames(text_a, text_b, steps=8)`. Replace generic density
interpolation for showcase animations with a
deterministic ordered dissolve:

1. Keep the original source characters at the start.
2. Remove source cells in a spatially distributed, stable order.
3. Reveal destination cells in a different stable order.
4. Preserve original destination characters at the end.

Where both artworks occupy a cell, switch between original characters in the
same spatially distributed order instead of converting them through a density ramp.
A fixed coordinate hash or ordered dither pattern should distribute changes
across the canvas without random flicker. The existing density morph may remain
available for backward compatibility, but examples should use the new mode.

`steps` is the number of intermediate frames and must be an integer of at least
1, otherwise raise `ValueError`. After normalization and shared-canvas
centering, assign every cell the stable rank
`((x * 73856093) ^ (y * 19349663)) & 0xffffffff`, breaking collisions by
`(y, x)`. Sort all shared-canvas coordinates by `(hash, y, x)`. A coordinate's
rank percentile is `index/(N-1)` for `N > 1`, where `index` is its zero-based
position and `N` is the total number of canvas cells; for `N == 1`, the
percentile is 0. Its reversed percentile is `1 - percentile`. For intermediate
frame `i` in `1..steps`, progress is
`i/(steps+1)`. A source-only cell disappears when its rank percentile is less
than progress; a destination-only cell appears when its reversed rank
percentile is less than progress. A cell occupied in both switches from the
original source character to the original destination character when its rank
percentile is less than progress. The output contains `steps + 2` frames. Its
first and last frames exactly preserve the normalized, centered canvases, not
the raw untrimmed corpus strings.

### 5. Timing and rendering

Extend `export_gif` with optional `durations=None`. `None` preserves the current
250 ms duration for every frame. An integer applies that positive millisecond
duration to every frame; a list supplies one positive integer per frame and
must match frame count, otherwise raise `ValueError`. Showcase exports use
`endpoint_ms=1200` for the first and last frames and `transition_ms=120` for
each intermediate frame. Retain infinite looping. Duration tests allow GIF
quantization to the nearest 10 ms and inspect every decoded frame.

Continue using Pillow's default font and measured cell dimensions. Font changes
are outside this iteration so rendering remains portable and dependency-free.

### 6. Verification

Add automated tests for:

- trimming, conservative footer cleanup, and shared-canvas centering;
- deterministic candidate and pair ranking;
- exact preservation of first and last frames;
- equal frame dimensions throughout a transition;
- deterministic dissolve output;
- GIF animation, infinite loop metadata, and endpoint timing;
- actionable failure when curated inputs are missing.

After generation, create visual contact sheets containing representative
frames from every GIF. Inspect them for readable endpoints, stable placement,
clean transitions, and absence of obvious attribution debris. Automated checks
guard invariants; visual inspection decides showcase quality.

Write the review sheet to `examples/contact_sheet.png`, overwriting it on each
generation. Include the first, 25%, 50%, 75%, and last frame of each animation,
using nearest valid frame indices and labeling rows by animation name. The
implementation is not complete until the final sheet is visually inspected and
the chosen four pairs are recorded in `examples/showcase.json`; the final task
report records that approval.

## Data Flow

`manifest.jsonl` is searched for candidates, candidates are normalized and
scored, and a report supports curation. Normal generation reads the curated
selection, loads source text from `corpus/clean`, normalizes and aligns each
pair, creates dissolve frames, exports timed GIFs, validates them, and produces
a visual review sheet.

Corpus contents remain read-only throughout this flow.

## Error Handling

- Missing corpus or manifest: stop with the expected path and rebuild command.
- Empty keyword results: report the theme and searched keywords.
- Missing curated file: stop and instruct the operator to rerun candidate
  selection or update the curated manifest.
- Empty artwork after cleanup: retain the uncleaned normalized artwork and
  report a warning.
- Missing Pillow/font: retain the existing clear dependency/fallback behavior.
- Failed GIF validation: exit nonzero and identify the output and failed check.

## Compatibility and Scope

Keep `morph_frames`, terminal playback, and current CLI commands working.
Introduce the dissolve as a separate function or explicit mode rather than
silently changing the public density-morph behavior. Do not rescrape or modify
the corpus. Do not add broad image-processing or machine-learning dependencies.

## Success Criteria

- Exactly four regenerated showcase GIFs, named by the curated manifest, have
  readable, centered endpoints and smooth,
  stroke-preserving transitions.
- No showcase frame contains an obvious detached email, URL, or attribution
  footer.
- Regeneration is deterministic from the curated manifest.
- Tests cover selection, normalization, transition, timing, and failure paths.
- The generated contact sheet passes a final human visual review.
- `AI_GUIDE.md` accurately documents selection, regeneration, review, and the
  distinction between density morphs and showcase dissolves.
