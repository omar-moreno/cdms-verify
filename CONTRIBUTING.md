# Contributing to CDMS Verify

Thanks for your interest in contributing! This document explains how to set up
your environment, the conventions we follow, and how to submit changes.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Licensing](#licensing)

---

## Code of Conduct

Be respectful and constructive. We're all here to build good software for the
CDMS collaboration. Assume good faith, give actionable feedback, and keep
discussions focused on the work.

---

## Getting Started

### Prerequisites

- Python 3.9 or newer
- `git`

### Set up your environment

```bash
# Fork and clone
git clone https://github.com/YOUR-USERNAME/cdms-verify.git
cd cdms-verify

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install the package with all development extras
pip install -e ".[dev,docs]"

# Install the git hooks
pre-commit install
```

> **Note:** The internal `CDMSDataCatalog` client is only needed to run the CLI
> against a live catalog. The test suite uses a fake client, so you can develop
> and test without it installed.

---

## Development Workflow

1. **Create a branch** off `developmemt`:
   ```bash
   git checkout -b feature/short-description
   ```
2. **Make your changes** with tests and docstrings.
3. **Run the checks** locally (pre-commit runs most automatically on commit):
   ```bash
   pre-commit run --all-files
   pytest
   ```
4. **Push** and open a pull request against `development`.

---

## Code Standards

We enforce these automatically via [pre-commit](.pre-commit-config.yaml) and CI.
Running `pre-commit install` once means most checks happen on every commit.

### Formatting & linting

- **[Ruff](https://docs.astral.sh/ruff/)** handles both linting and formatting.
  There is no separate Black/isort/flake8 step.
  ```bash
  ruff check .          # lint
  ruff check --fix .    # lint + autofix
  ruff format .         # format
  ```

### Type hints

- **All public functions must have type hints** on parameters and return values.

### Docstrings

- **NumPy-style docstrings** on every public module, function, and class.
  These are rendered into the API docs by `mkdocstrings`, so keep them accurate.
- Include `Parameters`, `Returns`, and `Raises` sections where applicable.

  <details>
  <summary>Example</summary>

  ```python
  def normalize_path(path: str) -> str:
      """Normalize a path to a valid CDMS catalog path.

      Parameters
      ----------
      path : str
          The input path string.

      Returns
      -------
      str
          The normalized path, guaranteed to start with ``/CDMS``.

      Examples
      --------
      >>> normalize_path("/CUTE/Raw")
      '/CDMS/CUTE/Raw'
      """
  ```
  </details>

### Design conventions

- **Pure helpers do not call `sys.exit`.** Only `cli.py` is allowed to exit the
  process. Keep business logic testable and side-effect-free where possible.
- **Persistence is per-file.** Results are committed as each file is processed,
  for crash durability — preserve this behavior.
- **The database is the source of truth.** Do not reintroduce derived data
  (like stored summary counts) that can drift from the underlying rows.

---

## Testing

We use [pytest](https://docs.pytest.org/). All new features and bug fixes should
include tests.

```bash
# Run the full suite
pytest

# Verbose, with coverage
pytest -v --cov=cdms_verify --cov-report=term-missing

# Run a single file or test
pytest tests/test_database.py
pytest tests/test_database.py::test_save_results_ignores_duplicates
```

### Testing guidelines

- **Pure modules** (`paths`, `scanning`, `database`) test against real temporary
  directories (`tmp_path`) or in-memory data — no catalog required.
- **CLI tests** (`test_cli.py`) inject a **fake `CDMSDataCatalog`** into
  `sys.modules`; do not require the real client in tests.
- **Assert against state, not output** where possible (e.g. query the database
  via `get_summary` rather than parsing stdout).
- **Reset shared state** in fixtures to avoid test-order dependence.

---

## Documentation

Docs are built with [MkDocs](https://www.mkdocs.org/) +
[Material](https://squidfunk.github.io/mkdocs-material/) +
[mkdocstrings](https://mkdocstrings.github.io/).

```bash
# Live preview at http://127.0.0.1:8000
mkdocs serve

# Build strictly (fails on broken links / references) — matches CI
mkdocs build --strict
```

> **Always run `mkdocs build --strict` before submitting doc changes.** CI runs
> the same command and will fail on broken references.

If you add a new module, add a matching page under `docs/api/` with an
`mkdocstrings` directive:

```markdown
# `cdms_verify.your_module`

::: cdms_verify.your_module
```

...and register it in the `nav` section of `mkdocs.yml`.

---

## Commit Messages

Write clear, imperative-mood commit messages:

```
Add change-detection columns to results schema

Store size and mtime on each row so an external tool can detect
modified files without re-hashing.
```

- First line: a concise summary (≤ 72 chars), imperative mood
  ("Add", "Fix", "Remove" — not "Added" / "Fixes").
- Blank line, then a body explaining *what* and *why* if the change isn't
  trivial.

Conventional Commits (`feat:`, `fix:`, `docs:`) are welcome but not required.

---

## Pull Requests

Before opening a PR, make sure:

- [ ] `pre-commit run --all-files` passes
- [ ] `pytest` passes
- [ ] `mkdocs build --strict` passes (for doc-affecting changes)
- [ ] New/changed code has tests
- [ ] Public APIs have NumPy-style docstrings
- [ ] The PR description explains the motivation and approach

Keep PRs focused — one logical change per PR is easier to review than a large
mixed one.

