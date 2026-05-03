> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Pytest Artifacts Organization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move pytest-generated cache and temporary artifacts out of the repository root and into `build/pytest/`.

**Architecture:** Update `pytest.ini` so pytest writes both cache and default temporary files into `build/pytest/`, then remove legacy root-level artifact directories and verify a fresh pytest run keeps the root clean.

**Tech Stack:** pytest, `pytest.ini`, PowerShell filesystem commands

---

### Task 1: Redirect pytest artifacts into `build/pytest/`

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/pytest.ini`

**Step 1: Update pytest cache and temp settings**

Set:

```ini
cache_dir = build/pytest/cache
addopts = -v --tb=short --basetemp=build/pytest/tmp
```

**Step 2: Verify pytest still starts with the updated config**

Run:

```bash
pytest tests/unit/test_imports_without_ms_core.py -q
```

Expected: command succeeds and uses the configured artifact directories.

### Task 2: Remove legacy root-level pytest artifacts

**Files:**
- Delete runtime artifacts: `C:/Users/user/Desktop/Data_Normalization_project_v2/.pytest_cache`
- Delete runtime artifacts: `C:/Users/user/Desktop/Data_Normalization_project_v2/.pytest_tmp*`

**Step 1: Delete existing root-level pytest artifact directories**

Remove the existing `.pytest_cache` and `.pytest_tmp*` directories from the repository root.

**Step 2: Verify the root stays clean after a fresh pytest run**

Run:

```bash
Get-ChildItem -Force
```

Expected: no new `.pytest_cache` or `.pytest_tmp*` directories appear at the repository root after pytest completes.
