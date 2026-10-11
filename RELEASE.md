# Release Process

This project publishes to PyPI using GitHub Actions and Trusted Publishing.

## Prerequisites

- PyPI project has a Trusted Publisher configured for this repository and workflow:
  - Repository: `SteveEasley/pykaleidescape`
  - Workflow: `.github/workflows/publish.yml`
  - Environment: `pypi` (if used)

## Create a New Release

1. Update package version in `kaleidescape/_version.py`:
   - Set `__version__ = "X.Y.Z"` (example: `1.1.2`).
2. Run quality checks locally:
   - `uv run prek run --all-files`
   - `uv run pytest`
3. Optionally validate the build with `uv build`.
4. Commit and push the version bump (and any release notes/changelog updates) to `main`.
5. Create and publish a GitHub release:
   - Tag must be `vX.Y.Z` (example: `v1.1.2`).
   - Target branch: `main`.

## What Happens Automatically

Publishing the GitHub release triggers `.github/workflows/publish.yml`, which:

1. Checks out the repository.
2. Verifies release tag version matches `kaleidescape.__version__`:
   - `v1.1.2` tag must match `__version__ = "1.1.2"`.
3. Builds the package (`sdist` + wheel) with `uv build`.
4. Publishes artifacts to PyPI via OIDC Trusted Publishing, which also verifies their metadata.

## Verification

- Confirm the GitHub Actions workflow succeeded.
- Confirm the new version appears on PyPI.
- Optional smoke test in a clean environment:
  - `pip install -U pykaleidescape==X.Y.Z`
