> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# GUI Workflow State Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the Tkinter GUI so that workflow navigation, step execution state, status panels, and export readiness all derive from one shared workflow-state model while aligning Step 3 with `QC Batch Scaling`.

**Architecture:** Keep the existing `DataNormalizationApp` and Tkinter layout, but introduce a single canonical workflow-state layer inside `src/metabolomics/gui/app.py`. Migrate top nav, step cards, progress, status, and export button state to render from that model, then remove duplicated UI actions that currently bypass the main workflow flow.

**Tech Stack:** Python, Tkinter, pytest

---

### Task 1: Lock the new workflow-state contract with failing tests

**Files:**
- Modify: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing tests**

- Add assertions that the GUI workflow definition exposes four ordered steps.
- Add an assertion that Step 3 is labeled `Step 3: QC Batch Scaling`.
- Add assertions that next-step enablement and export readiness are driven by shared workflow state rather than ad hoc fallback values.

**Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the current GUI still uses the legacy Step 3 label and does not expose a centralized workflow-state contract.

**Step 3: Write minimal implementation**

- Add the shared workflow-state structure and update step metadata in `app.py`.

**Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

**Step 5: Commit**

```bash
git add tests/unit/test_gui_step_flow.py src/metabolomics/gui/app.py
git commit -m "refactor(gui): centralize workflow state model"
```

### Task 2: Centralize step metadata and derived workflow state

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add a focused regression test that exercises state initialization and confirms:
  - one ordered step definition source exists
  - Step 3 uses `QC Batch Scaling`
  - workflow completion count is derived from shared state

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the state is still split across separate attributes without a single canonical model.

**Step 3: Write minimal implementation**

- Define one ordered workflow metadata structure.
- Introduce canonical workflow state for:
  - selected file
  - active step
  - completed steps
  - per-step outputs
  - export readiness
- Remove reliance on `last_output_file` for normal workflow progression where shared state already knows the previous step output.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 3: Move UI rendering to shared-state-driven helpers

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add regression coverage for:
  - completed steps updating progress
  - failed steps invalidating downstream state
  - reset clearing all workflow-derived UI state

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because multiple handlers still mutate widgets directly and inconsistently.

**Step 3: Write minimal implementation**

- Refactor lifecycle handlers to update workflow state first.
- Add focused render helpers for:
  - navigation
  - step cards/buttons
  - input lineage labels
  - status panel
  - progress bar
  - export button

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 4: Consolidate duplicated file-selection and artifact-opening flows

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add tests that verify:
  - the GUI uses one input-file selection path
  - per-step artifact actions use the canonical step output stored in workflow state
  - redundant folder-opening flow is either removed or explicitly separated from plot-opening semantics

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because file selection and artifact-opening logic are still partially duplicated.

**Step 3: Write minimal implementation**

- Merge `select_initial_file()` and `select_input_file()` into one path.
- Consolidate artifact opening helpers around canonical workflow-state artifact resolution.
- Replace icon-only artifact buttons with short, explicit labels such as `Open Excel` and `Open Plots`.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 5: Verify export and bridge behavior still works with the new state model

**Files:**
- Modify: `tests/unit/test_bridge_launch.py`
- Modify: `src/metabolomics/gui/app.py` only if needed

**Step 1: Write the failing test**

- Add or adjust a regression test that confirms export readiness and bridge launch still resolve Step 4 output from canonical workflow state.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_bridge_launch.py -q`

Expected:
Either PASS already, or FAIL only if the refactor changed where Step 4 output is read from.

**Step 3: Write minimal implementation**

- If needed, update export state lookup so Step 4 output is read from the centralized workflow state without changing bridge behavior.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_bridge_launch.py -q`

Expected:
PASS

### Task 6: Run focused regression suite for the GUI refactor

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Run focused tests**

Run:
`pytest tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py tests/unit/test_imports_without_ms_core.py -q`

Expected:
PASS

**Step 2: Run broader workflow safety checks**

Run:
`pytest tests/unit/test_qc_batch_scaling.py tests/unit/test_normalization.py -q`

Expected:
PASS

**Step 3: Manual smoke test**

Run:
`python Data_Normalization_program_v2.py`

Expected:
- top nav shows a 4-step workflow
- Step 3 reads `QC Batch Scaling`
- file selection updates the first-step lineage
- step cards expose explicit artifact actions
- reset/error/complete states remain visually consistent
- export only enables after Step 4 completes

**Step 4: Commit**

```bash
git add src/metabolomics/gui/app.py tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py docs/plans/2026-03-10-gui-workflow-state-design.md docs/plans/2026-03-10-gui-workflow-state.md
git commit -m "plan(gui): define workflow state refactor"
```
