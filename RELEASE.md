# Release Process

This project publishes to PyPI using GitHub Actions and Trusted Publishing.

## Prerequisites

- PyPI project has a Trusted Publisher configured for this repository and workflow:
  - Repository: `SteveEasley/pykaleidescape`
  - Workflow: `.github/workflows/publish.yml`
  - Environment: `pypi` (if used)

## Create a New Release

1. Update package version in `kaleidescape/__init__.py`:
   - Set `__version__ = "X.Y.Z"` (example: `1.1.2`).
2. Run quality checks locally:
   - `python -m pip install -e ".[dev]"`
   - `ruff check kaleidescape tests`
   - `mypy kaleidescape tests`
   - `pytest -q`
3. Optionally validate build artifacts:
   - `python -m build`
   - `twine check dist/*`
4. Commit and push the version bump (and any release notes/changelog updates) to `main`.
5. Create and publish a GitHub release:
   - Tag must be `vX.Y.Z` (example: `v1.1.2`).
   - Target branch: `main`.

## What Happens Automatically

Publishing the GitHub release triggers `.github/workflows/publish.yml`, which:

1. Checks out the repository.
2. Verifies release tag version matches `kaleidescape.__version__`:
   - `v1.1.2` tag must match `__version__ = "1.1.2"`.
3. Builds the package (`sdist` + wheel).
4. Runs `twine check` on built artifacts.
5. Publishes artifacts to PyPI via OIDC Trusted Publishing.

## Verification

- Confirm the GitHub Actions workflow succeeded.
- Confirm the new version appears on PyPI.
- Optional smoke test in a clean environment:
  - `pip install -U pykaleidescape==X.Y.Z`
