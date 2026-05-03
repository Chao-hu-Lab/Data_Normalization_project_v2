> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Session-Based Output Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure output from step-centric folders to session-based folders so one pipeline run = one folder with all Excel + plots together.

**Architecture:** Add a `create_session_dir()` to `file_io.py` that generates a timestamped session directory. GUI creates the session once at pipeline start and passes `session_dir` to each processor. Processors write their Excel + plots into that shared session directory using step-prefixed filenames. Backward-compatible: processors called without `session_dir` fall back to current behavior.

**Tech Stack:** Python, pathlib, existing `file_io.py` utilities, tkinter GUI

---

## Target Output Structure

```
output/
└── run_20260318_1252/                          ← one session = one folder
    ├── Step1_ISTD_Results.xlsx
    ├── Step2_QC_LOWESS.xlsx
    ├── Step3_QC_Batch_Scaling.xlsx
    ├── Step4_Normalized_PQN_SampleSpecific.xlsx
    └── plots/
        ├── Step1_PCA_before_after_batch.png
        ├── Step1_PCA_before_after_sample_type.png
        ├── Step2_PCA_ISTD_vs_LOWESS_batch.png
        ├── Step2_PCA_ISTD_vs_LOWESS_sample_type.png
        ├── Step2_Trend_Fitting_*.png
        ├── Step3_PCA_by_batch.png
        ├── Step3_PCA_by_sample_type.png
        ├── Step3_Residual_Analysis.png
        ├── Step4_Boxplot.png
        ├── Step4_CV.png
        ├── Step4_RLE.png
        └── Step4_PCA.png
```

**Key design decisions:**
- `session_dir` is an **optional** `str | Path | None` parameter on all processor `main()` functions. When `None`, each processor falls back to existing behavior (backward-compatible).
- Plot filenames drop the timestamp suffix (the session folder already encodes it). They keep the `Step{N}_` prefix for natural sort order.
- Excel filenames also drop the timestamp for the same reason.
- GUI creates `session_dir` once at auto-run or first step execution and reuses it for all subsequent steps.
- Single-step re-runs in the same GUI session reuse the same `session_dir` (overwrite previous output for that step).

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/metabolomics/utils/file_io.py` | Modify | Add `create_session_dir()`, `session_output_path()`, `session_plots_dir()` |
| `src/metabolomics/processors/istd.py` | Modify | Accept `session_dir`, use session paths when provided |
| `src/metabolomics/processors/qc_lowess.py` | Modify | Accept `session_dir`, use session paths when provided |
| `src/metabolomics/processors/qc_batch_scaling.py` | Modify | Accept `session_dir`, use session paths when provided |
| `src/metabolomics/processors/normalization.py` | Modify | Accept `session_dir`, use session paths when provided; fix timestamp mismatch bug |
| `src/metabolomics/processors/batch_effect.py` | Modify | Accept `session_dir`, use session paths when provided |
| `src/metabolomics/gui/app.py` | Modify | Create session_dir at run start, pass to processors |
| `tests/unit/test_file_io.py` | Modify | Add tests for new session functions |
| `tests/unit/test_session_output.py` | Create | Integration test: full pipeline writes to single session dir |

---

### Task 1: Add Session Directory Utilities to file_io.py

**Files:**
- Modify: `src/metabolomics/utils/file_io.py`
- Modify: `tests/unit/test_file_io.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_file_io.py — append these tests

from metabolomics.utils.file_io import (
    create_session_dir,
    session_output_path,
    session_plots_dir,
)


class TestSessionDir:
    def test_create_session_dir_creates_timestamped_folder(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        assert session.exists()
        assert session.parent == tmp_path
        assert session.name.startswith("run_")

    def test_create_session_dir_creates_plots_subdir(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        assert (session / "plots").exists()

    def test_session_output_path_returns_path_in_session(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        path = session_output_path(session, step=1, prefix="ISTD_Results")
        assert path.parent == session
        assert path.name == "Step1_ISTD_Results.xlsx"

    def test_session_plots_dir_returns_plots_subdir(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        plots = session_plots_dir(session)
        assert plots == session / "plots"
        assert plots.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_file_io.py::TestSessionDir -v`
Expected: FAIL with `ImportError` (functions don't exist yet)

- [ ] **Step 3: Implement session utilities**

Add to `src/metabolomics/utils/file_io.py`:

> **Note:** `DATETIME_FORMAT_FULL` is already imported at module level in `file_io.py`.
> Only `datetime` (the class) needs adding — use a module-level import `from datetime import datetime`
> to match the file's existing style (do **not** use an inline import).

```python
def create_session_dir(output_root: Path = None, timestamp: str = None) -> Path:
    """
    Create a timestamped session directory for a pipeline run.

    Structure: output_root/run_{timestamp}/plots/
    """
    if output_root is None:
        output_root = get_output_root()
    if timestamp is None:
        timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)

    session_dir = Path(output_root) / f"run_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "plots").mkdir(exist_ok=True)
    return session_dir


def session_output_path(
    session_dir: Path, step: int, prefix: str, extension: str = ".xlsx"
) -> Path:
    """Return the output file path within a session directory."""
    return Path(session_dir) / f"Step{step}_{prefix}{extension}"


def session_plots_dir(session_dir: Path) -> Path:
    """Return the plots subdirectory within a session directory."""
    plots = Path(session_dir) / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    return plots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_file_io.py::TestSessionDir -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/metabolomics/utils/file_io.py tests/unit/test_file_io.py
git commit -m "feat(file_io): add session directory utilities for run-based output"
```

---

### Task 2: Wire Session Dir into istd.py (Step 1)

**Files:**
- Modify: `src/metabolomics/processors/istd.py`
- Modify: `tests/unit/test_istd.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_istd.py — add test to TestISTDOutput class

def test_main_writes_to_session_dir(self, sample_input_file, istd_module, tmp_path):
    """When session_dir is provided, output goes into that directory."""
    from metabolomics.utils.file_io import create_session_dir

    session = create_session_dir(output_root=tmp_path)
    result = istd_module.main(input_file=sample_input_file, session_dir=session)
    assert Path(result.output_path).is_relative_to(session)
    assert "Step1_" in os.path.basename(result.output_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_istd.py::TestISTDOutput::test_main_writes_to_session_dir -v`
Expected: FAIL with `TypeError: main() got an unexpected keyword argument 'session_dir'`

- [ ] **Step 3: Modify istd.py main() to accept session_dir**

In `istd.py`, find `def main(input_file=None):` and change to:

```python
def main(input_file=None, session_dir=None):
```

Then find the output path generation block (around lines 1829-1835):

```python
    run_timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    output_file = build_output_path("ISTD_Results", timestamp=run_timestamp)
    plots_session_dir = build_plots_dir(
        "ISTD_Correction_plots",
        timestamp=run_timestamp,
        session_prefix="ISTD_Correction"
    )
```

Replace with:

```python
    run_timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    if session_dir is not None:
        from metabolomics.utils.file_io import session_output_path, session_plots_dir
        output_file = session_output_path(session_dir, step=1, prefix="ISTD_Results")
        _plots_dir = session_plots_dir(session_dir)
    else:
        output_file = build_output_path("ISTD_Results", timestamp=run_timestamp)
        _plots_dir = build_plots_dir(
            "ISTD_Correction_plots",
            timestamp=run_timestamp,
            session_prefix="ISTD_Correction"
        )
```

> **IMPORTANT:** Use a new variable name `_plots_dir` in both branches.
> Do NOT reuse the old `plots_session_dir` variable — that name only existed
> in the old code. Using different variables per branch would break the
> `_plot_path` helper below (which must reference a single variable).

Then update all `savefig()` calls in istd.py. Create a helper that uses the unified `_plots_dir` variable:

```python
    def _plot_path(filename_without_ext):
        """Build plot file path, adding step prefix when in session mode."""
        if session_dir is not None:
            return os.path.join(str(_plots_dir), f"Step1_{filename_without_ext}.png")
        return os.path.join(str(_plots_dir), f"{filename_without_ext}_{run_timestamp}.png")
```

Then replace each `os.path.join(plots_session_dir, f"..._{timestamp}.png")` with `_plot_path("...")`.

Also update the `ProcessingResult` return to use `plots_dir=str(_plots_dir)` instead of the old variable name.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_istd.py -v`
Expected: All existing + new test PASS

- [ ] **Step 5: Commit**

```bash
git add src/metabolomics/processors/istd.py tests/unit/test_istd.py
git commit -m "feat(istd): support session_dir for run-based output"
```

---

### Task 3: Wire Session Dir into qc_lowess.py (Step 2)

**Files:**
- Modify: `src/metabolomics/processors/qc_lowess.py`
- Modify: `tests/unit/test_qc_lowess.py`

Same pattern as Task 2. Key differences:

- `def main(input_file=None, session_dir=None):`
- `session_output_path(session_dir, step=2, prefix="QC_LOWESS")`
- `_plot_path` helper uses `"Step2_"` prefix
- Plot functions `plot_pvalue_distribution`, `plot_lowess_trend_fitting`, and PCA plots need `_plot_path` or equivalent plumbing
- Note: qc_lowess.py has its own fallback `plots_dir` logic in each plot function (lines 1116-1120, 1221-1225). When `session_dir` is provided, skip those fallbacks.

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Modify qc_lowess.py main() — same pattern as Task 2**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(qc_lowess): support session_dir for run-based output"
```

---

### Task 4: Wire Session Dir into qc_batch_scaling.py (Step 3)

**Files:**
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

Same pattern. Key differences:

- `session_output_path(session_dir, step=3, prefix="QC_Batch_Scaling")`
- `_plot_path` uses `"Step3_"` prefix
- **`generate_pca_plots()` is a module-level function** (not nested in `main()`), so `session_dir` is NOT in scope. You must change its signature:

```python
# Current signature:
def generate_pca_plots(source_df, result_df, sample_columns, sample_info_df, input_file, timestamp):

# New signature — add plots_dir=None:
def generate_pca_plots(source_df, result_df, sample_columns, sample_info_df, input_file, timestamp, plots_dir=None):
```

Inside `generate_pca_plots()`, change the existing `build_plots_dir()` call to:

```python
    if plots_dir is None:
        plots_dir = build_plots_dir(...)  # existing logic
```

Update the `savefig` calls inside to conditionally drop the timestamp suffix when `plots_dir` is provided from a session context.

Update the call site in `main()` to pass `_plots_dir`:

```python
    generate_pca_plots(
        source_df, result_df, sample_columns, sample_info_df,
        input_file, run_timestamp,
        plots_dir=_plots_dir if session_dir is not None else None,
    )
```

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Modify qc_batch_scaling.py — same pattern + `generate_pca_plots()` signature change**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(qc_batch_scaling): support session_dir for run-based output"
```

---

### Task 5: Wire Session Dir into normalization.py (Step 4)

**Files:**
- Modify: `src/metabolomics/processors/normalization.py`
- Modify: `tests/unit/test_normalization.py`

Same pattern, plus **fix the timestamp mismatch bug**. This task is more complex because plot paths are constructed **inside `perform_normalization()`**, not in `main()`.

- `session_output_path(session_dir, step=4, prefix="Normalized_PQN_SampleSpecific")`
- Plot prefix: `"Step4_"` in session mode

**Architecture issue:** `perform_normalization()` (line ~2203) is a module-level function that internally calls `build_plots_dir()` and constructs all `figure_paths` with timestamps baked in. The `session_dir` from `main()` cannot reach it without a signature change.

**Required changes:**

1. Add `plots_dir=None` parameter to `perform_normalization()`:

```python
# Current:
def perform_normalization(df, method, ...):
# New:
def perform_normalization(df, method, ..., plots_dir=None):
```

2. Inside `perform_normalization()`, when `plots_dir` is provided, skip the existing `build_plots_dir()` call and use the provided directory. Change `figure_paths` dict to use `Step4_` prefix instead of `Fig{N}_`:

```python
    if plots_dir is None:
        figures_dir = build_plots_dir(...)  # existing logic
        figure_paths = {
            "boxplot": os.path.join(figures_dir, f"Fig1_Boxplot_{method_slug}_{timestamp}.png"),
            ...
        }
    else:
        figures_dir = str(plots_dir)
        figure_paths = {
            "boxplot": os.path.join(figures_dir, "Step4_Boxplot.png"),
            "cv": os.path.join(figures_dir, "Step4_CV.png"),
            "rle": os.path.join(figures_dir, "Step4_RLE.png"),
            "pca": os.path.join(figures_dir, "Step4_PCA.png"),
        }
```

3. Update call site in `main()`:

```python
    result = perform_normalization(
        df, method, ...,
        plots_dir=session_plots_dir(session_dir) if session_dir else None,
    )
```

4. **BUG FIX** for `save_normalization_results()` (line ~2334). Add an `output_path` override parameter:

```python
# Current:
def save_normalization_results(
    normalized_df, summary_report, file_path, method_name,
    preserved_data_sheet_name, sample_info_sheet_name, output_dir,
):

# New — add output_path=None:
def save_normalization_results(
    normalized_df, summary_report, file_path, method_name,
    preserved_data_sheet_name, sample_info_sheet_name, output_dir,
    output_path=None,
):
```

Inside the function, replace the timestamp/path generation block (lines 2345-2349):

```python
    # When output_path is pre-built (session mode), use it directly
    if output_path is None:
        timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
        output_filename = generate_output_filename(
            f"Normalized_{method_name}", timestamp=timestamp, extension=".xlsx"
        )
        output_path = output_dir / output_filename
```

Call site in `main()`:

```python
    if session_dir is not None:
        _save_path = session_output_path(session_dir, step=4, prefix=f"Normalized_{method_name}")
    else:
        _save_path = None  # let save_normalization_results generate its own

    save_normalization_results(
        ..., output_path=_save_path,
    )
```

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Modify normalization.py — `perform_normalization()` signature + `main()` wiring + timestamp fix**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(normalization): support session_dir; fix timestamp mismatch between plots and Excel"
```

---

### Task 6: Wire Session Dir into batch_effect.py (Optional Step 3b)

**Files:**
- Modify: `src/metabolomics/processors/batch_effect.py`
- Modify: `tests/unit/test_batch_effect.py`

Same pattern. Note: batch_effect.py calls `build_plots_dir()` twice (lines 2336 and 2350). When `session_dir` is provided, skip both and use `session_plots_dir()`.

- Step prefix: `"Step3b_"` (alternative Step 3, use `3b` to avoid filename collision with qc_batch_scaling)

> **IMPORTANT — `datetime` import difference:** `batch_effect.py` uses `import datetime` (the **module**),
> so timestamp calls are `datetime.datetime.now().strftime(...)`. Do **not** copy the
> `datetime.now()` pattern from other processors — it will raise `AttributeError`.

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Modify batch_effect.py — same pattern, mind the `datetime.datetime` module form**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(batch_effect): support session_dir for run-based output"
```

---

### Task 7: Wire GUI to Create and Pass Session Dir

**Files:**
- Modify: `src/metabolomics/gui/app.py`

This is the orchestration layer. Changes:

1. Add a `self.current_session_dir = None` instance variable
2. In `run_all_steps()`: create session dir before starting
3. In `execute_step()`: if no session dir exists yet, create one (covers single-step execution)
4. In `run_step()`: pass `session_dir=self.current_session_dir` to `script_module.main()`
5. In `reset_all_steps()`: clear `self.current_session_dir = None`
6. Update `open_step_plots()`: when session_dir exists, open the shared `plots/` folder (all steps' plots in one place)

- [ ] **Step 1: Add session_dir to `__init__`**

In `__init__`, after `self.step_outputs = {}` (line ~212), add:

```python
self.current_session_dir = None
```

- [ ] **Step 2: Create session at pipeline start**

In `execute_step()`, after `self.cancel_flag.clear()` and before `self._invalidate_step_and_downstream`, add:

```python
        # Create session dir on first step execution
        if self.current_session_dir is None:
            from metabolomics.utils.file_io import create_session_dir, get_output_root
            self.current_session_dir = create_session_dir(
                output_root=get_output_root(input_file=self.selected_file_path)
            )
            self.logger.info(f"Session directory: {self.current_session_dir}")
```

- [ ] **Step 3: Pass session_dir to processor main()**

In `run_step()`, change the processor call (line ~1844):

```python
# Before:
result = script_module.main(input_file=current_input)

# After:
result = script_module.main(
    input_file=current_input,
    session_dir=self.current_session_dir,
)
```

- [ ] **Step 4: Clear session on reset**

In `reset_all_steps()`, after `self.auto_run_mode = False` (line ~2024), add:

```python
self.current_session_dir = None
```

- [ ] **Step 5: Update open_step_plots to use shared plots dir**

In `open_step_plots()`, when `session_dir` exists, open the shared plots folder:

```python
    def open_step_plots(self, step):
        """Open step output plots folder"""
        # When session-based output is active, all plots are in one folder
        if self.current_session_dir is not None:
            plots_dir = str(Path(self.current_session_dir) / "plots")
            self._open_path_in_system(plots_dir, "Plot folder does not exist", "Cannot open folder")
            return

        # Legacy: per-step plots folder
        step_name = step['name']
        result = self._get_step_result(step_name)
        if not result:
            messagebox.showwarning("Notice", "No plots generated for this step yet")
            return
        plots_dir = self._get_plots_dir(result)
        self._open_path_in_system(plots_dir, "Plot folder does not exist", "Cannot open folder")
```

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/unit/test_bridge_launch.py`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/metabolomics/gui/app.py
git commit -m "feat(gui): create session directory and pass to processors"
```

---

### Task 8: Unit Tests for Session Output Utilities

> **Note:** True integration tests (calling all 4 processors end-to-end) require real Excel fixtures
> and are deferred. These tests verify the session utility contracts that processors depend on.

**Files:**
- Create: `tests/unit/test_session_output.py`

- [ ] **Step 1: Write unit tests for session utilities**

```python
"""Test session directory utilities and naming contracts."""
import os
from pathlib import Path

import pytest

from metabolomics.utils.file_io import create_session_dir, session_output_path, session_plots_dir


class TestSessionOutputIntegration:
    @pytest.fixture
    def session(self, tmp_path):
        return create_session_dir(output_root=tmp_path)

    def test_session_dir_structure(self, session):
        assert session.exists()
        assert (session / "plots").exists()

    def test_output_paths_all_land_in_session(self, session):
        for step, prefix in [
            (1, "ISTD_Results"),
            (2, "QC_LOWESS"),
            (3, "QC_Batch_Scaling"),
            (4, "Normalized_PQN_SampleSpecific"),
        ]:
            path = session_output_path(session, step=step, prefix=prefix)
            assert path.parent == session
            assert path.name.startswith(f"Step{step}_")
            assert path.suffix == ".xlsx"

    def test_plots_dir_is_shared(self, session):
        plots = session_plots_dir(session)
        assert plots == session / "plots"

    def test_step_prefixed_filenames_sort_naturally(self, session):
        names = sorted([
            session_output_path(session, step=s, prefix=p).name
            for s, p in [(3, "C"), (1, "A"), (4, "D"), (2, "B")]
        ])
        assert names[0].startswith("Step1_")
        assert names[1].startswith("Step2_")
        assert names[2].startswith("Step3_")
        assert names[3].startswith("Step4_")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_session_output.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_session_output.py
git commit -m "test: add session-based output integration tests"
```

---

## Execution Notes

**Order matters:** Task 1 (file_io) must be completed first. Tasks 2-6 (processors) are independent and can be parallelized. Task 7 (GUI) depends on all processors being done. Task 8 (integration test) can be done after Task 1.

**Backward compatibility:** Every processor's `main()` defaults `session_dir=None`. When called from CLI or tests without session_dir, behavior is unchanged. Only the GUI passes session_dir.

**Risk:** The trickiest parts are:
- Task 2-6: modifying plot filenames in each processor (3-6 `savefig()` calls each). The `_plot_path()` helper keeps changes localized.
- Task 4: `generate_pca_plots()` is a module-level function needing its own `plots_dir` parameter.
- Task 5: `perform_normalization()` owns its own `figures_dir` and needs a `plots_dir` parameter to accept session paths.
- Task 6: `batch_effect.py` uses `import datetime` (module form), unlike other processors.

**Edge case:** If the user selects an input file that is inside an existing `output/` tree, `get_output_root()` will resolve to that ancestor directory and the session folder will be created there. This matches existing behavior and is not a new issue.

**Out of scope:** Cleaning up old accumulated output folders (275+ ISTD sessions). That's a user decision, not code.
