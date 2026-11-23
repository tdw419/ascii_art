# ascii_art

ASCII art tooling: corpus downloading, example pipeline, and GIF morphing.

## Layout

- `example_pipeline.py` — main pipeline for generating ASCII art examples and morph animations
- `ascii_anim.py` — ASCII animation engine
- `make_examples.py` — builds showcase examples (`--report examples/candidates.json` writes a generated local review aid, intentionally not committed)
- `build_clean_set.py` — curates the clean ASCII showcase set
- `download_asciiart.py` — downloads the ASCII art corpus
- `corpus/` — downloaded ASCII art corpus (raw + curated clean set)
- `examples/` — generated showcase GIFs and `showcase.json`
- `tests/` — test suite (`pytest`)

## Docs

See `AI_GUIDE.md` for the codebase guide, and `docs/` for specs and plans.
