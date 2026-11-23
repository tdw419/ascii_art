import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ascii_anim import NormalizedArtwork
from ascii_anim import normalize_artwork as source_normalize_artwork
from ascii_anim import shared_canvas as source_shared_canvas
from example_pipeline import (
    Candidate, ShowcaseEntry, THEMES, canonical_source, generate_showcase,
    load_showcase, match_candidates, normalize_artwork, rank_pairs, score_pair,
    shared_canvas, validate_gif, validate_showcase, write_candidate_report,
    write_contact_sheet,
)


def entry(file, title="Untitled", tags=()):
    return {"file": file, "title": title,
            "tags": [{"name": tag} for tag in tags]}


class ExamplePipelineTests(unittest.TestCase):
    def test_reexports_normalization_helpers(self):
        self.assertIs(normalize_artwork, source_normalize_artwork)
        self.assertIs(shared_canvas, source_shared_canvas)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clean_root = self.root / "corpus" / "clean"
        (self.clean_root / "art").mkdir(parents=True)
        for name in "abcdefghijkl":
            (self.clean_root / "art" / f"{name}.txt").write_text(name.upper())
        self.data = {
            "version": 1,
            "animations": [
                self.animation(f"pair_{index}", f"art/{a}.txt", f"art/{b}.txt")
                for index, (a, b) in enumerate(
                    zip("acegik", "bdfhjl"), 1)
            ],
        }

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def animation(name, source_a, source_b):
        return {"name": name, "source_a": source_a, "source_b": source_b,
                "steps": 8, "endpoint_ms": 1200, "transition_ms": 120}

    def test_load_showcase_reads_json_object(self):
        path = self.root / "showcase.json"
        path.write_text(json.dumps(self.data))
        self.assertEqual(load_showcase(path), self.data)

    def test_valid_manifest_returns_frozen_resolved_entries(self):
        entries = validate_showcase(self.data, self.clean_root)
        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0], ShowcaseEntry(
            "pair_1", "art/a.txt", "art/b.txt",
            self.clean_root / "art/a.txt", self.clean_root / "art/b.txt",
            8, 1200, 120))
        with self.assertRaises(Exception):
            entries[0].name = "changed"

    def test_requires_exact_top_level_schema_version_and_six_animations(self):
        cases = [
            ({"version": 2, "animations": self.data["animations"]}, "version"),
            ({"version": 1, "animations": self.data["animations"][:5]}, "exactly 6"),
            ({"version": 1, "animations": self.data["animations"], "extra": 1},
             "unknown"),
            ({"version": 1}, "animations"),
        ]
        for value, message in cases:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                validate_showcase(value, self.clean_root)

    def test_entry_rejects_missing_and_unknown_fields(self):
        for mutation, message in ((lambda row: row.pop("steps"), "missing.*steps"),
                                  (lambda row: row.update(extra=1), "unknown.*extra")):
            value = json.loads(json.dumps(self.data))
            mutation(value["animations"][0])
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_showcase(value, self.clean_root)

    def test_names_must_be_unique_lower_snake_identifiers(self):
        for name, message in (("Bad-Name", "name"), ("", "name")):
            value = json.loads(json.dumps(self.data))
            value["animations"][0]["name"] = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                validate_showcase(value, self.clean_root)
        value = json.loads(json.dumps(self.data))
        value["animations"][1]["name"] = value["animations"][0]["name"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_showcase(value, self.clean_root)

    def test_sources_are_distinct_safe_posix_paths_below_clean_root(self):
        for source, message in (("/tmp/a.txt", "relative"),
                                (r"art\\a.txt", "POSIX"),
                                ("art/../a.txt", r"\.\."),
                                ("other/a.txt", "art/")):
            value = json.loads(json.dumps(self.data))
            value["animations"][0]["source_a"] = source
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, message):
                validate_showcase(value, self.clean_root)
        value = json.loads(json.dumps(self.data))
        value["animations"][0]["source_b"] = "art/a.txt"
        with self.assertRaisesRegex(ValueError, "different"):
            validate_showcase(value, self.clean_root)

    def test_source_rejects_symlink_escape_and_missing_file_actionably(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        link = self.clean_root / "art/link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        value = json.loads(json.dumps(self.data))
        value["animations"][0]["source_a"] = "art/link.txt"
        with self.assertRaisesRegex(ValueError, "escapes corpus/clean"):
            validate_showcase(value, self.clean_root)
        value["animations"][0]["source_a"] = "art/missing.txt"
        with self.assertRaisesRegex(ValueError, r"art/missing\.txt.*does not exist"):
            validate_showcase(value, self.clean_root)

    def test_settings_are_positive_non_bool_integers(self):
        for field, bad in (("steps", True), ("steps", 0),
                           ("endpoint_ms", 0), ("transition_ms", 1.5)):
            value = json.loads(json.dumps(self.data))
            value["animations"][0][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaisesRegex(
                    ValueError, field):
                validate_showcase(value, self.clean_root)

    def test_gif_timings_must_be_representable_in_ten_millisecond_units(self):
        for field in ("endpoint_ms", "transition_ms"):
            for bad in (1, 15):
                value = json.loads(json.dumps(self.data))
                value["animations"][0][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaisesRegex(
                        ValueError, rf"{field}.*10"):
                    validate_showcase(value, self.clean_root)

    def test_reusing_a_source_warns_but_validation_continues(self):
        value = json.loads(json.dumps(self.data))
        value["animations"][1]["source_a"] = "art/a.txt"
        with self.assertWarnsRegex(UserWarning, "art/a.txt"):
            entries = validate_showcase(value, self.clean_root)
        self.assertEqual(len(entries), 6)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "examples"
        self.output.mkdir()
        self.sources = self.root / "sources"
        self.sources.mkdir()
        (self.sources / "a.txt").write_text("AAAA\nAAAA")
        (self.sources / "b.txt").write_text("BBBB\nBBBB")
        self.entry = ShowcaseEntry(
            "alpha_to_beta", "art/a.txt", "art/b.txt",
            self.sources / "a.txt", self.sources / "b.txt", 2, 1200, 120)

    def tearDown(self):
        self.temporary.cleanup()

    def test_generate_uses_manifest_name_timing_and_validates_gif(self):
        paths = generate_showcase([self.entry], self.output)
        self.assertEqual(paths, [self.output / "alpha_to_beta.gif"])
        validate_gif(paths[0], 4, [1200, 120, 120, 1200])

    def test_generation_deletes_only_known_legacy_names(self):
        legacy = self.output / "cat_to_dog.gif"
        unrelated = self.output / "keep_me.gif"
        legacy.write_bytes(b"legacy")
        unrelated.write_bytes(b"unrelated")
        generate_showcase([self.entry], self.output)
        self.assertFalse(legacy.exists())
        self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_committed_outputs_use_umask_permissions(self):
        paths = generate_showcase([self.entry], self.output)
        umask = os.umask(0)
        os.umask(umask)
        expected = 0o666 & ~umask
        for path in [*paths, self.output / "contact_sheet.png"]:
            self.assertEqual(path.stat().st_mode & 0o777, expected,
                             path.name)

    def test_failure_after_first_export_leaves_all_existing_outputs_untouched(self):
        from example_pipeline import export_gif as real_export_gif
        second = ShowcaseEntry(
            "beta_to_gamma", "art/a.txt", "art/b.txt",
            self.sources / "a.txt", self.sources / "b.txt", 2, 1200, 120)
        final = self.output / "alpha_to_beta.gif"
        legacy = self.output / "cat_to_dog.gif"
        final.write_bytes(b"existing final")
        legacy.write_bytes(b"existing legacy")
        calls = 0

        def fail_second(frames, path, durations):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated second export failure")
            return real_export_gif(frames, path, durations=durations)

        with mock.patch("example_pipeline.export_gif", side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, "simulated second export failure"):
                generate_showcase([self.entry, second], self.output)
        self.assertEqual(final.read_bytes(), b"existing final")
        self.assertEqual(legacy.read_bytes(), b"existing legacy")
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["alpha_to_beta.gif", "cat_to_dog.gif"])

    def test_validate_gif_reports_frame_loop_and_duration_failures(self):
        from PIL import Image
        frames = [Image.new("RGB", (2, 2), color) for color in ("red", "blue")]
        path = self.output / "bad.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=[100, 200], loop=1)
        for count, durations, message in ((3, [100, 200], "frame count"),
                                          (2, [100, 200], "loop"),
                                          (2, [100, 500], "duration")):
            with self.subTest(message=message), self.assertRaisesRegex(
                    ValueError, rf"{re.escape(str(path))}:.*{message}"):
                validate_gif(path, count, durations)


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.clean_root = Path(self.temporary.name) / "corpus" / "clean"
        (self.clean_root / "art").mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def add_art(self, name, text="X", **metadata):
        path = self.clean_root / "art" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return entry(f"corpus/clean/art/{name}", **metadata)

    def test_canonical_source_normalizes_legacy_and_windows_paths(self):
        self.add_art("animals/cat.txt")
        self.assertEqual(canonical_source(
            "corpus\\clean\\art\\animals\\cat.txt", self.clean_root),
            "art/animals/cat.txt")
        self.assertEqual(canonical_source(
            "art/animals/cat.txt", self.clean_root), "art/animals/cat.txt")

    def test_canonical_source_rejects_unsafe_paths(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("X")
        for value in (str(outside), "../outside.txt",
                      "corpus/clean/../outside.txt", "other/art.txt"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_source(value, self.clean_root)

    def test_canonical_source_rejects_symlink_escape(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("X")
        link = self.clean_root / "art" / "link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ValueError):
            canonical_source("art/link.txt", self.clean_root)

    def test_matching_is_whole_word_case_insensitive_and_ordered(self):
        entries = [self.add_art("z.txt", title="CAT portrait"),
                   self.add_art("not.txt", title="Cathedral"),
                   self.add_art("tag.txt", tags=("Cat",)),
                   self.add_art("kitten.txt", title="kitten"),
                   self.add_art("a.txt", title="cat")]
        candidates = match_candidates(entries, ["kitten", "cat"], self.clean_root)
        self.assertEqual(
            [(item.source, item.match_class, item.keyword_rank)
             for item in candidates],
            [("art/kitten.txt", 0, 0), ("art/a.txt", 0, 1),
             ("art/z.txt", 0, 1), ("art/tag.txt", 1, 1)])

    def test_matching_retains_only_best_forty(self):
        entries = [self.add_art(f"{index:02}.txt", title="cat")
                   for index in range(45)]
        candidates = match_candidates(entries, ["cat"], self.clean_root)
        self.assertEqual(len(candidates), 40)
        self.assertEqual(candidates[-1].source, "art/39.txt")

    def test_pair_score_has_hand_calculated_components_and_penalties(self):
        a = Candidate(entry("art/a.txt", title="cat"), "art/a.txt", 0, 0,
                      NormalizedArtwork("X" * 80, 80, 1, 80, 1.0, True))
        b = Candidate(entry("art/b.txt", title="dog"), "art/b.txt", 1, 2,
                      NormalizedArtwork("X" * 40, 40, 2, 40, 0.5, False))
        score = score_pair(a, b, 4)
        self.assertAlmostEqual(score.match_quality, 0.625)
        self.assertAlmostEqual(score.size_similarity, 0.5)
        self.assertAlmostEqual(score.aspect_similarity, 0.25)
        self.assertAlmostEqual(score.ink_similarity, 0.5)
        self.assertAlmostEqual(score.occupancy_similarity, 0.5)
        self.assertEqual((score.penalty_a, score.penalty_b), (35, 0))
        self.assertAlmostEqual(score.total, 57.5)

    def test_pair_ranking_breaks_raw_score_ties_by_sources(self):
        art = NormalizedArtwork("X", 1, 1, 1, 1.0, False)
        group_a = [Candidate(entry("art/b.txt"), "art/b.txt", 0, 0, art),
                   Candidate(entry("art/a.txt"), "art/a.txt", 0, 0, art)]
        group_b = [Candidate(entry("art/d.txt"), "art/d.txt", 0, 0, art),
                   Candidate(entry("art/c.txt"), "art/c.txt", 0, 0, art)]
        self.assertEqual(
            [(pair.source_a, pair.source_b)
             for pair in rank_pairs(group_a, group_b, 1)],
            [("art/a.txt", "art/c.txt"), ("art/a.txt", "art/d.txt"),
             ("art/b.txt", "art/c.txt"), ("art/b.txt", "art/d.txt")])

    def test_report_has_exact_stable_shape_order_and_rounding(self):
        entries = [self.add_art("a.txt", "XX\nX", title="Alpha cat"),
                   self.add_art("b.txt", "YY", title="Beta dog")]
        report_path = Path(self.temporary.name) / "report.json"
        report = write_candidate_report(
            entries, self.clean_root, report_path,
            {"cat_to_dog": (["cat"], ["dog"])})
        self.assertEqual(list(report), ["version", "themes"])
        theme = report["themes"][0]
        self.assertEqual(list(theme),
                         ["name", "keywords_a", "keywords_b", "pairs"])
        pair = theme["pairs"][0]
        self.assertEqual(list(pair),
                         ["rank", "total", "components", "source_a", "source_b"])
        self.assertEqual(list(pair["components"]), [
            "match_quality", "size_similarity", "aspect_similarity",
            "ink_similarity", "occupancy_similarity", "penalty_a", "penalty_b"])
        self.assertEqual(pair["source_a"], {
            "path": "art/a.txt", "title": "Alpha cat", "width": 2,
            "height": 2, "ink": 3, "occupancy": 0.75})
        self.assertEqual(json.loads(report_path.read_text()), report)
        self.assertIn('"aspect_similarity": 0.5', report_path.read_text())

    def test_empty_keyword_group_names_theme_and_keywords(self):
        entries = [self.add_art("a.txt", title="cat")]
        with self.assertRaisesRegex(ValueError, r"cat_to_dog.*dog.*puppy"):
            write_candidate_report(
                entries, self.clean_root,
                Path(self.temporary.name) / "report.json",
                {"cat_to_dog": (["cat"], ["dog", "puppy"])})

    def test_concrete_theme_order_and_keywords(self):
        self.assertEqual(list(THEMES), [
            "cat_to_dog", "sun_to_moon", "heart_to_skull", "fish_to_bird",
            "rocket_to_ufo"])
        self.assertEqual(THEMES["rocket_to_ufo"], (
            ["rocket", "spaceship", "space shuttle"],
            ["ufo", "saucer", "alien", "martian"]))


class GenerationCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The legacy script executes on import and uses cwd-relative paths.
        # Import it in an isolated complete fixture so the RED check cannot
        # touch the real corpus or examples directory.
        cls.import_fixture = tempfile.TemporaryDirectory()
        fixture = Path(cls.import_fixture.name)
        clean = fixture / "corpus" / "clean"
        (clean / "art").mkdir(parents=True)
        (fixture / "examples").mkdir()
        rows = []
        for index, title in enumerate(
                ["cat", "dog", "sun", "moon", "heart", "skull", "fish",
                 "bird", "rocket", "ufo"]):
            source = clean / "art" / f"{index}.txt"
            source.write_text(title)
            rows.append(entry(f"corpus/clean/art/{index}.txt", title=title))
        (clean / "manifest.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))
        previous = Path.cwd()
        try:
            os.chdir(fixture)
            sys.modules.pop("make_examples", None)
            cls.cli = importlib.import_module("make_examples")
        finally:
            os.chdir(previous)

    @classmethod
    def tearDownClass(cls):
        cls.import_fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def create_manifest(self):
        clean = self.root / "corpus" / "clean"
        (clean / "art").mkdir(parents=True)
        rows = []
        for index, title in enumerate(
                ["cat", "dog", "sun", "moon", "heart", "skull", "fish",
                 "bird", "rocket", "ufo", "alien", "owl"]):
            (clean / "art" / f"{index}.txt").write_text(title)
            rows.append(entry(f"corpus/clean/art/{index}.txt", title=title))
        (clean / "manifest.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))

    def create_showcase(self, missing_source=False):
        animations = []
        for index in range(6):
            animations.append({
                "name": f"showcase_{index}",
                "source_a": "art/missing.txt" if missing_source and index == 0
                            else f"art/{index * 2}.txt",
                "source_b": f"art/{index * 2 + 1}.txt",
                "steps": 1, "endpoint_ms": 100, "transition_ms": 50,
            })
        examples = self.root / "examples"
        examples.mkdir(exist_ok=True)
        (examples / "showcase.json").write_text(json.dumps({
            "version": 1, "animations": animations,
        }))

    def run_main(self, arguments):
        old_root = self.cli.PROJECT_ROOT
        self.cli.PROJECT_ROOT = self.root
        stderr = StringIO()
        try:
            with redirect_stderr(stderr):
                result = self.cli.main(arguments)
        finally:
            self.cli.PROJECT_ROOT = old_root
        return result, stderr.getvalue()

    def test_missing_corpus_and_manifest_are_actionable(self):
        result, error = self.run_main(["--report", "examples/report.json"])
        self.assertEqual(result, 2)
        self.assertIn(str(self.root / "corpus" / "clean"), error)
        self.assertIn("python3 build_clean_set.py", error)

        (self.root / "corpus" / "clean").mkdir(parents=True)
        result, error = self.run_main(["--report", "examples/report.json"])
        self.assertEqual(result, 2)
        self.assertIn(str(self.root / "corpus" / "clean" / "manifest.jsonl"), error)
        self.assertIn("python3 build_clean_set.py", error)

    def test_report_path_is_project_relative_and_creates_no_artifacts(self):
        self.create_manifest()
        result, error = self.run_main(["--report", "review/candidates.json"])
        self.assertEqual((result, error), (0, ""))
        self.assertTrue((self.root / "review" / "candidates.json").is_file())
        self.assertEqual(list(self.root.rglob("*.gif")), [])
        self.assertFalse((self.root / "examples" / "contact_sheet.png").exists())

    def test_absolute_report_path_is_rejected(self):
        self.create_manifest()
        absolute = self.root / "outside" / "candidates.json"
        result, error = self.run_main(["--report", str(absolute)])
        self.assertEqual(result, 2)
        self.assertIn("project-relative", error)
        self.assertFalse(absolute.exists())

    def test_report_path_rejects_parent_traversal(self):
        self.create_manifest()
        escape_fixture = tempfile.TemporaryDirectory(dir=self.root.parent)
        self.addCleanup(escape_fixture.cleanup)
        escape_root = Path(escape_fixture.name)
        outside = escape_root / "escaped-candidates.json"
        relative_escape = f"../{escape_root.name}/escaped-candidates.json"
        result, error = self.run_main(["--report", relative_escape])
        self.assertEqual(result, 2)
        self.assertIn("inside the project root", error)
        self.assertFalse(outside.exists())

    def test_report_path_rejects_symlinked_parent_escape(self):
        self.create_manifest()
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside, True)
        link = self.root / "review"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        result, error = self.run_main(["--report", "review/candidates.json"])
        self.assertEqual(result, 2)
        self.assertIn("inside the project root", error)
        self.assertFalse((outside / "candidates.json").exists())

    def test_report_subprocess_creates_no_showcase_artifacts(self):
        self.create_manifest()
        source_root = Path(__file__).resolve().parents[1]
        for filename in ("ascii_anim.py", "example_pipeline.py", "make_examples.py"):
            shutil.copy2(source_root / filename, self.root / filename)
        completed = subprocess.run(
            [sys.executable, "make_examples.py", "--report", "review/candidates.json"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.root / "review" / "candidates.json").is_file())
        self.assertEqual(list(self.root.rglob("*.gif")), [])
        self.assertFalse((self.root / "examples" / "contact_sheet.png").exists())

    def test_default_mode_loads_showcase_manifest_and_generates_named_gifs(self):
        self.create_manifest()
        self.create_showcase()
        result, error = self.run_main([])
        self.assertEqual((result, error), (0, ""))
        self.assertEqual(
            sorted(path.name for path in (self.root / "examples").glob("*.gif")),
            [f"showcase_{index}.gif" for index in range(6)])

    def test_default_mode_reports_missing_showcase_source_and_returns_two(self):
        self.create_manifest()
        self.create_showcase(missing_source=True)
        result, error = self.run_main([])
        self.assertEqual(result, 2)
        self.assertTrue(error.startswith("error:"))
        self.assertIn("art/missing.txt", error)
        self.assertIn("does not exist", error)

    def test_default_mode_preserves_unrelated_gif(self):
        self.create_manifest()
        self.create_showcase()
        unrelated = self.root / "examples" / "unrelated.gif"
        unrelated.write_bytes(b"not a generated showcase")
        result, error = self.run_main([])
        self.assertEqual((result, error), (0, ""))
        self.assertEqual(unrelated.read_bytes(), b"not a generated showcase")


class ContactSheetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "examples"
        self.output.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_gif(path, colors, size=(8, 6)):
        from PIL import Image
        frames = [Image.new("RGB", size, color) for color in colors]
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=100, loop=0)
        return path

    @staticmethod
    def label_metrics(names):
        from PIL import ImageFont
        boxes = [ImageFont.load_default().getbbox(name) for name in names]
        width = max(box[2] - box[0] for box in boxes)
        height = max(box[3] - box[1] for box in boxes)
        return width, height

    def test_samples_half_up_indices_in_manifest_row_order(self):
        from PIL import Image
        first = self.write_gif(
            self.output / "first.gif",
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        second = self.write_gif(
            self.output / "second.gif",
            [(0, 255, 255), (255, 0, 255), (255, 255, 0), (255, 255, 255)])
        target = self.output / "contact_sheet.png"
        write_contact_sheet([("alpha", first), ("beta", second)], target)

        label_width, label_height = self.label_metrics(["alpha", "beta"])
        label_column = label_width + 10
        row_height = max(6, label_height) + 10
        expected = [[(255, 0, 0), (0, 255, 0), (0, 255, 0),
                     (0, 0, 255), (0, 0, 255)],
                    [(0, 255, 255), (255, 0, 255), (255, 255, 0),
                     (255, 255, 0), (255, 255, 255)]]
        with Image.open(target) as sheet:
            for row, colors in enumerate(expected):
                row_top = 10 + row * (row_height + 6)
                for cell, color in enumerate(colors):
                    x = 10 + label_column + cell * (8 + 6) + 4
                    y = row_top + (row_height - 6) // 2 + 3
                    self.assertEqual(sheet.getpixel((x, y)), color,
                                     f"row {row} cell {cell}")

    def test_dimensions_follow_the_documented_formula(self):
        from PIL import Image
        names = ["a", "longer_name"]
        self.write_gif(self.output / "a.gif", [(255, 0, 0)], size=(8, 6))
        self.write_gif(self.output / "b.gif", [(0, 0, 255)], size=(12, 10))
        target = self.output / "contact_sheet.png"
        write_contact_sheet(
            [(names[0], self.output / "a.gif"),
             (names[1], self.output / "b.gif")], target)

        label_width, label_height = self.label_metrics(names)
        label_column = label_width + 10
        row_height = max(10, label_height) + 10
        expected = (label_column + 5 * 12 + 4 * 6 + 20,
                    2 * row_height + 6 + 20)
        with Image.open(target) as sheet:
            self.assertEqual(sheet.size, expected)
            for row in range(2):
                row_top = 10 + row * (row_height + 6)
                ink = any(
                    sheet.getpixel((x, y)) != (0, 0, 0)
                    for x in range(10, 10 + label_column)
                    for y in range(row_top, row_top + row_height))
                self.assertTrue(ink, f"row {row} has no label ink")

    def test_reruns_are_pixel_identical_and_leave_no_staging_files(self):
        from PIL import Image
        gif = self.write_gif(self.output / "a.gif", [(1, 2, 3), (4, 5, 6)])
        target = self.output / "contact_sheet.png"
        write_contact_sheet([("a", gif)], target)
        with Image.open(target) as sheet:
            first_size, first_pixels = sheet.size, sheet.tobytes()
        target.write_bytes(b"stale")
        write_contact_sheet([("a", gif)], target)
        with Image.open(target) as sheet:
            self.assertEqual(sheet.size, first_size)
            self.assertEqual(sheet.tobytes(), first_pixels)
        leftovers = [path.name for path in self.output.iterdir()
                     if path.name.startswith(".") or "staging" in path.name]
        self.assertEqual(leftovers, [])

    def test_missing_pillow_reports_the_target_actionably(self):
        real_import = __import__

        def import_without_pillow(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("Pillow unavailable")
            return real_import(name, *args, **kwargs)

        gif = self.write_gif(self.output / "a.gif", [(1, 2, 3)])
        target = self.output / "contact_sheet.png"
        with mock.patch("builtins.__import__",
                        side_effect=import_without_pillow):
            with self.assertRaisesRegex(
                    ValueError,
                    rf"{re.escape(str(target))}.*Pillow.*pip install pillow"):
                write_contact_sheet([("a", gif)], target)
        self.assertFalse(target.exists())

    def test_font_load_failure_reports_the_target_actionably(self):
        gif = self.write_gif(self.output / "a.gif", [(1, 2, 3)])
        target = self.output / "contact_sheet.png"
        with mock.patch("PIL.ImageFont.load_default",
                        side_effect=OSError("no fonts")):
            with self.assertRaisesRegex(
                    ValueError, rf"{re.escape(str(target))}.*font"):
                write_contact_sheet([("a", gif)], target)
        self.assertFalse(target.exists())

    def test_cli_returns_two_when_contact_sheet_fails(self):
        import make_examples

        def stub_export(frames, path, durations=None):
            from PIL import Image
            if isinstance(durations, list):
                assigned = durations
            else:
                assigned = [durations or 250] * len(frames)
            images = [Image.new("RGB", (6, 4), ((index * 60) % 256, 0, 0))
                      for index in range(len(frames))]
            images[0].save(path, save_all=True, append_images=images[1:],
                           duration=assigned, loop=0)
            return path

        clean = self.root / "corpus" / "clean"
        (clean / "art").mkdir(parents=True)
        rows = []
        for index in range(12):
            (clean / "art" / f"{index}.txt").write_text(f"art {index}")
            rows.append(entry(f"corpus/clean/art/{index}.txt",
                             title=f"piece {index}"))
        (clean / "manifest.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))
        animations = [{"name": f"showcase_{index}",
                       "source_a": f"art/{index * 2}.txt",
                       "source_b": f"art/{index * 2 + 1}.txt",
                       "steps": 1, "endpoint_ms": 100, "transition_ms": 50}
                      for index in range(6)]
        (self.output / "showcase.json").write_text(json.dumps(
            {"version": 1, "animations": animations}))
        old_root = make_examples.PROJECT_ROOT
        make_examples.PROJECT_ROOT = self.root
        try:
            with mock.patch("example_pipeline.export_gif",
                            side_effect=stub_export), \
                    mock.patch("PIL.ImageFont.load_default",
                               side_effect=OSError("no fonts")), \
                    redirect_stderr(StringIO()) as stderr:
                result = make_examples.main([])
        finally:
            make_examples.PROJECT_ROOT = old_root
        self.assertEqual(result, 2)
        self.assertIn("contact_sheet.png", stderr.getvalue())
        self.assertIn("font", stderr.getvalue())
        self.assertFalse((self.output / "contact_sheet.png").exists())
        leftovers = [path.name for path in self.output.iterdir()
                     if path.name.startswith(".") or "staging" in path.name]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
