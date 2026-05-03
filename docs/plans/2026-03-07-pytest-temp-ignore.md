> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Pytest Temp Ignore Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ignore local pytest temporary directories so they do not appear in `git status`.

**Architecture:** Add one narrow ignore rule to the repository root `.gitignore`. Verify the rule by checking that `.pytest_tmp*` directories no longer show up as untracked files.

**Tech Stack:** git, pytest temp directory naming, `.gitignore`

---

### Task 1: Ignore pytest temporary directories

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/.gitignore`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/.gitignore`

**Step 1: Write the minimal rule**

Add:

```gitignore
.pytest_tmp*/
```

**Step 2: Verify the ignore behavior**

Run:

```bash
git status --short
```

Expected: existing `.pytest_tmp*` directories no longer appear in the untracked list.

**Step 3: Commit if requested**

```bash
git add .gitignore docs/plans/2026-03-07-pytest-temp-ignore.md
git commit -m "chore: ignore pytest temp directories"
```
