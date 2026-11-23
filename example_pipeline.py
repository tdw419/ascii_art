"""Deterministic candidate matching and scoring for showcase curation."""

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import warnings

from ascii_anim import (
    NormalizedArtwork, dissolve_frames, export_gif, normalize_artwork,
    shared_canvas,
)


THEMES = {
    "cat_to_dog": (["cat", "kitten"], ["dog", "puppy", "dogs"]),
    "sun_to_moon": (
        ["sun", "sunrise", "sunset"], ["moon", "crescent", "night"]),
    "heart_to_skull": (
        ["heart", "love"], ["skull", "skeleton", "grave", "death"]),
    "fish_to_bird": (
        ["fish", "fishes", "shark", "whale"],
        ["bird", "eagle", "owl", "duck"],
    ),
    "rocket_to_ufo": (
        ["rocket", "spaceship", "space shuttle"],
        ["ufo", "saucer", "alien", "martian"],
    ),
}


@dataclass(frozen=True)
class Candidate:
    entry: dict
    source: str
    match_class: int
    keyword_rank: int
    normalized: NormalizedArtwork


@dataclass(frozen=True)
class PairScore:
    source_a: str
    source_b: str
    total: float
    match_quality: float
    size_similarity: float
    aspect_similarity: float
    ink_similarity: float
    occupancy_similarity: float
    penalty_a: float
    penalty_b: float


@dataclass(frozen=True)
class ShowcaseEntry:
    name: str
    source_a: str
    source_b: str
    source_a_path: Path
    source_b_path: Path
    steps: int
    endpoint_ms: int
    transition_ms: int


_SHOWCASE_FIELDS = {
    "name", "source_a", "source_b", "steps", "endpoint_ms", "transition_ms",
}
_SHOWCASE_NAME = re.compile(r"^[a-z0-9_]+$")
_LEGACY_GIFS = {
    "cat_to_dog.gif", "sun_to_moon.gif", "heart_to_skull.gif",
    "fish_to_bird.gif", "rocket_to_ufo.gif", "chain_nature_loop.gif",
}


def load_showcase(path):
    """Load a showcase JSON manifest."""
    source = Path(path)
    try:
        data = json.loads(source.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{source}: showcase must be a JSON object")
    return data


def _showcase_source(value, clean_root, location):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: source must be a non-empty string")
    if "\\" in value:
        raise ValueError(f"{location}: source must use POSIX '/' separators")
    source = PurePosixPath(value)
    if source.is_absolute():
        raise ValueError(f"{location}: source must be relative to corpus/clean")
    if ".." in source.parts:
        raise ValueError(f"{location}: source must not contain '..'")
    if (not source.parts or source.parts[0] != "art"
            or any(part in ("", ".") for part in source.parts)):
        raise ValueError(f"{location}: source must start with art/")
    root = Path(clean_root).resolve()
    resolved = (root / Path(*source.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"{location}: {value!r} escapes corpus/clean") from error
    if not resolved.is_file():
        raise ValueError(f"{location}: {value!r} does not exist under {root}")
    return source.as_posix(), resolved


def validate_showcase(data, clean_root):
    """Validate an exact v1 showcase manifest and resolve its source files."""
    if not isinstance(data, dict):
        raise ValueError("showcase must be an object")
    required_top = {"version", "animations"}
    missing = required_top - set(data)
    unknown = set(data) - required_top
    if missing:
        raise ValueError(f"showcase missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"showcase has unknown fields: {', '.join(sorted(unknown))}")
    if data["version"] != 1 or isinstance(data["version"], bool):
        raise ValueError("showcase version must be 1")
    animations = data["animations"]
    if not isinstance(animations, list) or len(animations) != 6:
        raise ValueError("showcase animations must contain exactly 6 entries")

    entries = []
    names = set()
    source_uses = {}
    for index, row in enumerate(animations):
        location = f"animations[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{location}: entry must be an object")
        missing = _SHOWCASE_FIELDS - set(row)
        unknown = set(row) - _SHOWCASE_FIELDS
        if missing:
            raise ValueError(
                f"{location}: missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(
                f"{location}: unknown fields: {', '.join(sorted(unknown))}")
        name = row["name"]
        if not isinstance(name, str) or not _SHOWCASE_NAME.fullmatch(name):
            raise ValueError(
                f"{location}.name must match ^[a-z0-9_]+$")
        if name in names:
            raise ValueError(f"{location}.name is duplicate: {name!r}")
        names.add(name)
        source_a, path_a = _showcase_source(
            row["source_a"], clean_root, f"{location}.source_a")
        source_b, path_b = _showcase_source(
            row["source_b"], clean_root, f"{location}.source_b")
        if source_a == source_b:
            raise ValueError(f"{location}: source_a and source_b must be different")
        for field in ("steps", "endpoint_ms", "transition_ms"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{location}.{field} must be a positive integer")
        for field in ("endpoint_ms", "transition_ms"):
            if row[field] % 10 != 0:
                raise ValueError(
                    f"{location}.{field} must be a multiple of 10 "
                    "(GIF durations quantize to 10ms units)")
        for source in (source_a, source_b):
            if source in source_uses:
                warnings.warn(
                    f"showcase source reused: {source}", UserWarning, stacklevel=2)
            source_uses[source] = source_uses.get(source, 0) + 1
        entries.append(ShowcaseEntry(
            name, source_a, source_b, path_a, path_b, row["steps"],
            row["endpoint_ms"], row["transition_ms"],
        ))
    return entries


def validate_gif(path, expected_frames, expected_durations):
    """Verify an exported GIF's frame count, timing, and infinite loop."""
    target = Path(path)
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError(
            f"{target}: failed check: Pillow is required to validate GIFs") from error
    try:
        with Image.open(target) as image:
            frame_count = getattr(image, "n_frames", 1)
            if frame_count != expected_frames:
                raise ValueError(
                    f"{target}: failed check: frame count {frame_count}, "
                    f"expected {expected_frames}")
            actual_durations = []
            for index in range(frame_count):
                image.seek(index)
                actual_durations.append(image.info.get("duration"))
            if len(expected_durations) != frame_count or any(
                    actual is None or abs(actual - expected) > 10
                    for actual, expected in zip(
                        actual_durations, expected_durations)):
                raise ValueError(
                    f"{target}: failed check: duration {actual_durations}, "
                    f"expected {expected_durations} (10ms tolerance)")
            if image.info.get("loop") != 0:
                raise ValueError(
                    f"{target}: failed check: loop {image.info.get('loop')!r}, "
                    "expected 0")
    except (OSError, EOFError) as error:
        raise ValueError(f"{target}: failed check: cannot read GIF: {error}") from error


_SHEET_FRACTIONS = (0, 0.25, 0.5, 0.75, 1)
_SHEET_PADDING = 10
_SHEET_GAP = 6


def _commit_staged(staging, final):
    """Move a staging file into place with normal umask-based permissions."""
    staging.replace(final)
    umask = os.umask(0)
    os.umask(umask)
    final.chmod(0o666 & ~umask)


def write_contact_sheet(named_gif_paths, output_path):
    """Compose a labeled review sheet sampling five frames per animation.

    Each row shows the first, 25%, 50%, 75%, and last frame of one GIF in
    the given order. The sheet is saved atomically, so a failure never
    leaves a partial file behind.
    """
    target = Path(output_path)
    rows = [(name, Path(gif_path)) for name, gif_path in named_gif_paths]
    if not rows:
        raise ValueError(f"{target}: need at least one animation to review")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise ValueError(
            f"{target}: cannot write contact sheet: Pillow is required "
            "(pip install pillow)") from error
    try:
        font = ImageFont.load_default()
    except Exception as error:
        raise ValueError(
            f"{target}: cannot write contact sheet: "
            f"font load failed: {error}") from error

    sampled = []
    for name, gif_path in rows:
        try:
            with Image.open(gif_path) as image:
                frame_count = getattr(image, "n_frames", 1)
                frames = []
                for fraction in _SHEET_FRACTIONS:
                    index = int((frame_count - 1) * fraction + 0.5)
                    image.seek(index)
                    frames.append(image.convert("RGB").copy())
        except (OSError, EOFError, ValueError) as error:
            raise ValueError(
                f"{target}: cannot sample {gif_path}: {error}") from error
        sampled.append((name, frames))

    try:
        label_boxes = [font.getbbox(name) for name, _ in sampled]
    except Exception as error:
        raise ValueError(
            f"{target}: cannot write contact sheet: "
            f"font label measurement failed: {error}") from error
    label_width = max(box[2] - box[0] for box in label_boxes) + _SHEET_PADDING
    cell_width = max(
        frame.width for _, frames in sampled for frame in frames)
    row_height = max(
        max(frame.height for _, frames in sampled for frame in frames),
        max(box[3] - box[1] for box in label_boxes),
    ) + _SHEET_PADDING
    width = (label_width + len(_SHEET_FRACTIONS) * cell_width
             + (len(_SHEET_FRACTIONS) - 1) * _SHEET_GAP + 2 * _SHEET_PADDING)
    height = (len(sampled) * row_height + (len(sampled) - 1) * _SHEET_GAP
              + 2 * _SHEET_PADDING)

    sheet = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(sheet)
    for index, (name, frames) in enumerate(sampled):
        row_top = _SHEET_PADDING + index * (row_height + _SHEET_GAP)
        draw.text((_SHEET_PADDING, row_top + _SHEET_PADDING // 2),
                  name, fill="lime", font=font)
        for cell, frame in enumerate(frames):
            x = (_SHEET_PADDING + label_width
                 + cell * (cell_width + _SHEET_GAP))
            y = row_top + (row_height - frame.height) // 2
            sheet.paste(frame, (x, y))

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            delete=False, dir=target.parent,
            prefix=f".{target.stem}.", suffix=".staging.png") as handle:
        staging = Path(handle.name)
    try:
        sheet.save(staging, format="PNG")
        _commit_staged(staging, target)
    except Exception as error:
        staging.unlink(missing_ok=True)
        raise ValueError(
            f"{target}: cannot write contact sheet: {error}") from error
    return target


def generate_showcase(entries, output_dir):
    """Generate and verify all explicitly named showcase GIFs.

    Every GIF is exported to a staging file and validated before any
    output is touched, so a mid-run failure leaves existing files
    untouched. Only after all GIFs validate are legacy outputs removed,
    staged files moved into place, and the review contact sheet written.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    staged = []
    staging_paths = []
    try:
        for entry in entries:
            frames = dissolve_frames(
                entry.source_a_path.read_text(),
                entry.source_b_path.read_text(), entry.steps)
            durations = ([entry.endpoint_ms]
                         + [entry.transition_ms] * entry.steps
                         + [entry.endpoint_ms])
            final = output / f"{entry.name}.gif"
            with tempfile.NamedTemporaryFile(
                    delete=False, dir=output,
                    prefix=f".{entry.name}.", suffix=".staging.gif") as handle:
                staged_path = Path(handle.name)
            staging_paths.append(staged_path)
            try:
                result = export_gif(frames, staged_path, durations=durations)
            except Exception as error:
                raise ValueError(
                    f"{final}: GIF export failed: {error}") from error
            if result is None or not staged_path.is_file():
                raise ValueError(
                    f"{final}: GIF export failed; "
                    "install Pillow with pip install pillow")
            try:
                validate_gif(staged_path, len(frames), durations)
            except ValueError as error:
                raise ValueError(
                    f"{final}: staged GIF failed validation: "
                    f"{error}") from error
            staged.append((staged_path, final, entry.name))
    except Exception:
        for staging_path in staging_paths:
            staging_path.unlink(missing_ok=True)
        raise
    for legacy_name in _LEGACY_GIFS:
        legacy = output / legacy_name
        if legacy.is_file():
            legacy.unlink()
    generated = []
    for staged_path, final, _ in staged:
        _commit_staged(staged_path, final)
        generated.append(final)
    write_contact_sheet(
        [(name, output / f"{name}.gif") for _, _, name in staged],
        output / "contact_sheet.png")
    return generated


def canonical_source(file_value, clean_root):
    """Return a safe POSIX path relative to the clean corpus root."""
    if not isinstance(file_value, str) or not file_value:
        raise ValueError(f"invalid manifest source: {file_value!r}")
    metadata_path = file_value.replace("\\", "/")
    path = PurePosixPath(metadata_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe manifest source: {file_value!r}")

    parts = path.parts
    if parts[:2] == ("corpus", "clean"):
        parts = parts[2:]
    if not parts or parts[0] != "art" or any(part in ("", ".") for part in parts):
        raise ValueError(f"manifest source is outside corpus/clean: {file_value!r}")

    source = PurePosixPath(*parts)
    root = Path(clean_root).resolve()
    resolved = (root / Path(*source.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"manifest source escapes corpus/clean: {file_value!r}") from error
    return source.as_posix()


def _first_match(text, keywords):
    for rank, keyword in enumerate(keywords):
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            return rank
    return None


def match_candidates(entries, keywords, clean_root):
    """Find and normalize the best 40 whole-word metadata matches."""
    matches = []
    root = Path(clean_root)
    for manifest_entry in entries:
        title_rank = _first_match(str(manifest_entry.get("title", "")), keywords)
        tag_text = " ".join(
            str(tag.get("name", "")) for tag in manifest_entry.get("tags", []))
        tag_rank = _first_match(tag_text, keywords)
        if title_rank is not None:
            match_class, keyword_rank = 0, title_rank
        elif tag_rank is not None:
            match_class, keyword_rank = 1, tag_rank
        else:
            continue
        source = canonical_source(manifest_entry.get("file"), root)
        text = (root / Path(*PurePosixPath(source).parts)).read_text()
        matches.append(Candidate(
            manifest_entry, source, match_class, keyword_rank,
            normalize_artwork(text),
        ))
    matches.sort(key=lambda item: (
        item.match_class, item.keyword_rank, item.source))
    return matches[:40]


def _similarity(a, b):
    return 1 - abs(a - b) / max(a, b, 1)


def _penalty(artwork):
    return ((15 if artwork.footer_detected else 0)
            + (20 if artwork.width > 64 or artwork.height > 28 else 0))


def score_pair(a, b, max_keyword_count):
    if max_keyword_count < 1:
        raise ValueError("max_keyword_count must be at least 1")
    match_quality = max(0, min(
        1,
        1 - (a.match_class + b.match_class) / 4
        - (a.keyword_rank + b.keyword_rank) / (4 * max_keyword_count),
    ))
    width_similarity = _similarity(a.normalized.width, b.normalized.width)
    height_similarity = _similarity(a.normalized.height, b.normalized.height)
    size_similarity = (width_similarity + height_similarity) / 2
    aspect_a = (a.normalized.width / a.normalized.height
                if a.normalized.height else 0)
    aspect_b = (b.normalized.width / b.normalized.height
                if b.normalized.height else 0)
    aspect_similarity = _similarity(aspect_a, aspect_b)
    ink_similarity = _similarity(a.normalized.ink, b.normalized.ink)
    occupancy_similarity = _similarity(
        a.normalized.occupancy, b.normalized.occupancy)
    penalty_a = _penalty(a.normalized)
    penalty_b = _penalty(b.normalized)
    total = (100 * match_quality + 25 * size_similarity
             + 20 * aspect_similarity + 15 * ink_similarity
             + 10 * occupancy_similarity - penalty_a - penalty_b)
    return PairScore(
        a.source, b.source, total, match_quality, size_similarity,
        aspect_similarity, ink_similarity, occupancy_similarity,
        penalty_a, penalty_b,
    )


def rank_pairs(candidates_a, candidates_b, max_keyword_count):
    pairs = [score_pair(a, b, max_keyword_count)
             for a in candidates_a for b in candidates_b]
    pairs.sort(key=lambda pair: (-pair.total, pair.source_a, pair.source_b))
    return pairs


def _rounded(value):
    return round(value, 6)


def _source_record(candidate):
    return {
        "path": candidate.source,
        "title": candidate.entry.get("title", ""),
        "width": candidate.normalized.width,
        "height": candidate.normalized.height,
        "ink": candidate.normalized.ink,
        "occupancy": _rounded(candidate.normalized.occupancy),
    }


def write_candidate_report(entries, clean_root, output_path, themes=THEMES):
    """Rank all theme pairs, write stable JSON, and return the report object."""
    report = {"version": 1, "themes": []}
    for name, (keywords_a, keywords_b) in themes.items():
        candidates_a = match_candidates(entries, keywords_a, clean_root)
        candidates_b = match_candidates(entries, keywords_b, clean_root)
        if not candidates_a:
            raise ValueError(
                f"theme {name}: no matches for keywords {keywords_a!r}")
        if not candidates_b:
            raise ValueError(
                f"theme {name}: no matches for keywords {keywords_b!r}")
        by_source_a = {candidate.source: candidate for candidate in candidates_a}
        by_source_b = {candidate.source: candidate for candidate in candidates_b}
        scores = rank_pairs(
            candidates_a, candidates_b, max(len(keywords_a), len(keywords_b)))
        pairs = []
        for rank, score in enumerate(scores, 1):
            pairs.append({
                "rank": rank,
                "total": _rounded(score.total),
                "components": {
                    "match_quality": _rounded(score.match_quality),
                    "size_similarity": _rounded(score.size_similarity),
                    "aspect_similarity": _rounded(score.aspect_similarity),
                    "ink_similarity": _rounded(score.ink_similarity),
                    "occupancy_similarity": _rounded(score.occupancy_similarity),
                    "penalty_a": _rounded(score.penalty_a),
                    "penalty_b": _rounded(score.penalty_b),
                },
                "source_a": _source_record(by_source_a[score.source_a]),
                "source_b": _source_record(by_source_b[score.source_b]),
            })
        report["themes"].append({
            "name": name,
            "keywords_a": list(keywords_a),
            "keywords_b": list(keywords_b),
            "pairs": pairs,
        })
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


__all__ = [
    "Candidate", "NormalizedArtwork", "PairScore", "ShowcaseEntry", "THEMES",
    "canonical_source", "generate_showcase", "load_showcase", "match_candidates",
    "normalize_artwork", "rank_pairs", "score_pair", "shared_canvas",
    "validate_gif", "validate_showcase", "write_candidate_report",
    "write_contact_sheet",
]
