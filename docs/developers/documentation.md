# Documentation

These docs are built with [MkDocs](https://www.mkdocs.org/) using the
[Material](https://squidfunk.github.io/mkdocs-material/) theme. The API
reference is generated automatically from source docstrings by
[MkApi](https://daizutabi.github.io/mkapi/), and versioning is handled by
[mike](https://github.com/jimporter/mike).

## Building locally

Install the docs dependencies (see [Installation](../installation.md)):

```bash
uv sync --extra docs
```

Serve the site with live reload:

```bash
uv run mkdocs serve
```

Build the static site into `site/`:

```bash
uv run mkdocs build
```

## How the site is organized

The navigation is defined in `mkdocs.yml`:

- **About** — `docs/index.md`
- **Installation** — `docs/installation.md`
- **Pipeline** — `docs/pipeline.md`
- **Developers** — this section (`docs/developers/`)
- **Reference** — auto-generated from `tetrapy.*` via the `$api/tetrapy.***`
  MkApi directive

## Writing docstrings

The API reference is generated directly from source docstrings, so **docstrings
are the API documentation**. Follow these conventions:

- Use **numpy-style** docstrings (`Parameters`, `Returns`, `Notes`, ...).
- Keep the summary line short and imperative.
- Pipeline stage docstrings in [`tetrapy.pipeline`][] double as CLI `--help`
  text — write them for end users, and describe the relevant config keys.
- Cross-reference other objects with MkApi/MkDocs link syntax, e.g.
  ``[`tetrapy.aggregate`][]``.

## Cross-referencing

To link to a module, class, or function in prose, use the bracketed reference
syntax:

```markdown
See [`tetrapy.tetracorder.TetraDecoder`][] for the expert-system decoder.
```

## Versioned deploys

Releases are published with `mike`, which keeps multiple documentation versions
available from a selector in the header:

```bash
uv run mike deploy --push --update-aliases 1.0 latest
```
