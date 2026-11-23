import io
import os
import tempfile
import unittest
import warnings
from dataclasses import FrozenInstanceError
from unittest import mock

import ascii_anim
from ascii_anim import NormalizedArtwork, normalize_artwork, shared_canvas


class NormalizeArtworkTests(unittest.TestCase):
    def test_normalizes_line_endings_and_right_trims_rows(self):
        result = normalize_artwork(" X  \r\nY \r Z  ")

        self.assertEqual(result.text, " X\nY\n Z")
        self.assertEqual((result.width, result.height, result.ink), (2, 3, 3))
        self.assertEqual(result.occupancy, 0.5)

    def test_removes_short_marked_footer_after_blank_separator(self):
        result = normalize_artwork("  /\\  \n /__\\ \n\nartist@example.com\n")

        self.assertEqual(result.text, " /\\\n/__\\")
        self.assertTrue(result.footer_detected)

    def test_removes_url_and_copyright_footer(self):
        result = normalize_artwork("#\n\nhttps://example.com\n(c) Example\n")

        self.assertEqual(result.text, "#")
        self.assertTrue(result.footer_detected)

    def test_preserves_marked_footer_without_blank_separator(self):
        result = normalize_artwork("#\nartist@example.com\n")

        self.assertEqual(result.text, "#\nartist@example.com")
        self.assertFalse(result.footer_detected)

    def test_preserves_footer_with_more_than_three_nonblank_rows(self):
        result = normalize_artwork(
            "#\n\nartist@example.com\nline two\nline three\nline four\n"
        )

        self.assertEqual(
            result.text,
            "#\n\nartist@example.com\nline two\nline three\nline four",
        )
        self.assertFalse(result.footer_detected)

    def test_preserves_footer_with_a_row_longer_than_sixty_characters(self):
        long_footer = "artist@example.com " + "x" * 42

        result = normalize_artwork(f"#\n\n{long_footer}\n")

        self.assertEqual(result.text, f"#\n\n{long_footer}")
        self.assertFalse(result.footer_detected)

    def test_removes_literal_copyright_footer(self):
        result = normalize_artwork("#\n\nCopyright Example Studio\n")

        self.assertEqual(result.text, "#")
        self.assertTrue(result.footer_detected)

    def test_removes_literal_copyright_symbol_footer(self):
        result = normalize_artwork("#\n\n© Example Studio\n")

        self.assertEqual(result.text, "#")
        self.assertTrue(result.footer_detected)

    def test_preserves_unmarked_short_signature(self):
        result = normalize_artwork("#\n\nJane Doe\n")

        self.assertEqual(result.text, "#\n\nJane Doe")
        self.assertFalse(result.footer_detected)

    def test_trims_empty_outer_rows_and_columns(self):
        result = normalize_artwork("\n    \n   A  \n  BB  \n    \n")

        self.assertEqual(result.text, " A\nBB")
        self.assertEqual((result.width, result.height), (2, 2))

    def test_restores_precleaned_content_when_footer_cleanup_erases_all_ink(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = normalize_artwork("   \n\nartist@example.com\n")

        self.assertEqual(result.text, "artist@example.com")
        self.assertTrue(result.footer_detected)
        self.assertEqual(len(caught), 1)
        self.assertTrue(issubclass(caught[0].category, UserWarning))

    def test_empty_input_has_zero_metrics(self):
        result = normalize_artwork("")

        self.assertEqual(result, NormalizedArtwork("", 0, 0, 0, 0.0, False))

    def test_normalized_artwork_is_frozen(self):
        result = normalize_artwork("#")

        with self.assertRaises(FrozenInstanceError):
            result.text = "changed"


class SharedCanvasTests(unittest.TestCase):
    def test_places_odd_padding_on_bottom_and_right(self):
        artwork_a, artwork_b = shared_canvas("XX", "Y\nY\nY")

        self.assertEqual(artwork_a, "  \nXX\n  ")
        self.assertEqual(artwork_b, "Y \nY \nY ")

    def test_normalizes_each_input_exactly_once(self):
        with mock.patch(
            "ascii_anim.normalize_artwork", wraps=normalize_artwork
        ) as normalize:
            shared_canvas("A", "B")

        self.assertEqual(normalize.call_args_list, [mock.call("A"), mock.call("B")])


class DissolveFramesTests(unittest.TestCase):
    def test_returns_requested_intermediates_plus_exact_normalized_endpoints(self):
        frames = ascii_anim.dissolve_frames("  A X  ", " Y B ", steps=3)

        self.assertEqual(len(frames), 5)
        self.assertEqual(frames[0], "A X")
        self.assertEqual(frames[-1], "Y B")

    def test_all_frames_have_the_shared_canvas_dimensions(self):
        frames = ascii_anim.dissolve_frames("XX", "Y\nY\nY", steps=4)

        dimensions = [
            (len(frame.split("\n")), {len(row) for row in frame.split("\n")})
            for frame in frames
        ]
        self.assertEqual(dimensions, [(3, {2})] * 6)

    def test_is_deterministic(self):
        first = ascii_anim.dissolve_frames("AB\n C", "D \nEF", steps=3)
        second = ascii_anim.dissolve_frames("AB\n C", "D \nEF", steps=3)

        self.assertEqual(first, second)

    def test_follows_coordinate_hash_order_and_strict_thresholds(self):
        frames = ascii_anim.dissolve_frames("AB\n C", "D \nEF", steps=3)

        self.assertEqual(
            frames,
            ["AB\n C", "DB\n C", "DB\n C", "D \nEC", "D \nEF"],
        )

    def test_preserves_original_characters_without_density_punctuation(self):
        frames = ascii_anim.dissolve_frames("QZ", "uv", steps=2)

        self.assertTrue(set("".join(frames)) <= set("QZuv"))

    def test_handles_singleton_canvas(self):
        self.assertEqual(
            ascii_anim.dissolve_frames("A", "B", steps=2),
            ["A", "B", "B", "B"],
        )

    def test_rejects_invalid_steps(self):
        for steps in (True, False, 1.5, 0, -1):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                ascii_anim.dissolve_frames("A", "B", steps=steps)

    def test_uses_real_shared_canvas_and_removes_separated_attribution(self):
        source = "A\n\nartist@example.com"
        destination = "B\n\nhttps://example.com"
        with mock.patch("ascii_anim.shared_canvas", wraps=shared_canvas) as canvas:
            frames = ascii_anim.dissolve_frames(source, destination, steps=1)

        canvas.assert_called_once_with(source, destination)
        self.assertEqual((frames[0], frames[-1]), ("A", "B"))
        self.assertNotIn("example", frames[0] + frames[-1])

    def test_existing_morph_behavior_is_unchanged(self):
        self.assertEqual(ascii_anim.morph_frames("A", "B", steps=1), ["A", "+", "B"])


class GifExportTests(unittest.TestCase):
    frames = ["A", "BB", "CCC"]

    def _roundtrip_durations(self, durations=None):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "timed.gif")
            result = ascii_anim.export_gif(
                self.frames, path, scale=7, durations=durations
            )
            self.assertEqual(result, path)
            with Image.open(path) as image:
                decoded = []
                for frame_number in range(image.n_frames):
                    image.seek(frame_number)
                    decoded.append(image.info["duration"])
        return decoded

    def test_default_duration_is_250_ms_per_frame(self):
        self.assertEqual(self._roundtrip_durations(), [250, 250, 250])

    def test_scalar_duration_applies_to_every_frame(self):
        actual = self._roundtrip_durations(120)
        self.assertTrue(all(abs(value - 120) <= 10 for value in actual), actual)

    def test_duration_list_roundtrips_for_each_frame(self):
        expected = [80, 170, 310]
        actual = self._roundtrip_durations(expected)

        self.assertEqual(len(actual), len(expected))
        for decoded, requested in zip(actual, expected):
            self.assertLessEqual(abs(decoded - requested), 10)

    def test_invalid_durations_raise_before_rendering(self):
        invalid = [0, -1, 1.5, True, False, "100", (100, 200, 300),
                   [], [100], [100, 200],
                   [100, 200, 300, 400], [100, 0, 300], [100, True, 300],
                   [100, 2.5, 300], [100, "200", 300]]
        for durations in invalid:
            with self.subTest(durations=durations), mock.patch(
                "PIL.Image.new"
            ) as image_new, self.assertRaises(ValueError):
                ascii_anim.export_gif(self.frames, durations=durations)
            image_new.assert_not_called()

    def test_missing_pillow_returns_none_with_install_message(self):
        real_import = __import__

        def import_without_pillow(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("Pillow unavailable")
            return real_import(name, *args, **kwargs)

        output = io.StringIO()
        with mock.patch("builtins.__import__", side_effect=import_without_pillow), \
                mock.patch("sys.stdout", output):
            result = ascii_anim.export_gif(self.frames)

        self.assertIsNone(result)
        self.assertIn("Pillow not installed", output.getvalue())
        self.assertIn("pip install pillow", output.getvalue())


class ExistingBehaviorRegressionTests(unittest.TestCase):
    def test_load_frames_splits_percent_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "frames.txt")
            with open(path, "w") as stream:
                stream.write("one\n%\ntwo\n")

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                frames = ascii_anim.load_frames(path)

            self.assertEqual(frames, ["one", "two"])

    def test_play_once_without_clear_writes_frames_sequentially(self):
        output = io.StringIO()
        with mock.patch("ascii_anim.time.sleep") as sleep:
            ascii_anim.play(["one", "two"], fps=4, loops=1, clear=False, out=output)

        self.assertEqual(output.getvalue(), "one\ntwo\n")
        self.assertEqual(sleep.call_args_list, [mock.call(0.25), mock.call(0.25)])


if __name__ == "__main__":
    unittest.main()
