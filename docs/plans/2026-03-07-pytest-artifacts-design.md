> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Pytest Artifacts Organization Design

## Goal

Keep pytest-generated cache and temporary files out of the repository root so local test runs do not clutter the project workspace.

## Scope

- Route pytest cache output into `build/pytest/cache`
- Route the default pytest base temp directory into `build/pytest/tmp`
- Remove existing root-level `.pytest_cache` and `.pytest_tmp*` directories
- Verify a fresh pytest run only recreates artifacts under `build/pytest/`

## Approach

Use the existing repository-level `pytest.ini` as the single source of truth for local pytest behavior:

1. Add `cache_dir = build/pytest/cache`
2. Extend `addopts` with `--basetemp=build/pytest/tmp`
3. Keep generated artifacts under the already-ignored `build/` tree
4. Delete legacy pytest artifact directories from the repository root

## Rationale

- `build/` already exists in this project for generated outputs, so putting pytest artifacts there matches the current repository layout.
- Centralizing both cache and temp files in one subtree makes cleanup predictable.
- This is a small configuration-only change and avoids touching test discovery or test file locations.

## Verification

- Run a focused pytest command from the repository root
- Confirm exit status is successful
- Confirm `build/pytest/` exists after the run
- Confirm no new `.pytest_cache` or `.pytest_tmp*` directories are recreated at the repository root
