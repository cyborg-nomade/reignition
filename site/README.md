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

## Build the downloadable editions

```sh
uv run python build_editions.py
```

This creates standalone introduction and complete-book PDFs, plus reflowable
EPUB editions for the introduction, the four tomes, and the complete book. The
four canonical Prince PDFs in `../pdf-epub/` are treated as immutable inputs:
the complete PDF appends them after the newly typeset front matter without
rewriting them.

## Preview and validate

```sh
uv run mkdocs serve
uv run mkdocs build --strict
```

GitHub Pages is deployed automatically when changes to `site/` land on the
repository's `master` branch. The deployment copies all PDF and EPUB artifacts
from `../pdf-epub/` beside the generated downloads page.
