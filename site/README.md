# Reignition online edition

This directory contains the complete source for the static online edition.
The 1,224 article pages under `docs/` are generated from the four canonical
HTML tomes in `../html/tomes/`; they should not be edited by hand. The editor’s
introduction at `docs/editors-introduction.md` is maintained by hand and is not
removed by the generator.

## Regenerate the Markdown

```sh
cd site
uv sync --locked
uv run python generate.py
```

The generator replaces the generated Markdown tree, copies the four covers,
and rebuilds `mkdocs.yml` with the complete navigation in source order.

## Preview and validate

```sh
uv run mkdocs serve
uv run mkdocs build --strict
```

GitHub Pages is deployed automatically when changes to `site/` land on the
repository's `master` branch.
