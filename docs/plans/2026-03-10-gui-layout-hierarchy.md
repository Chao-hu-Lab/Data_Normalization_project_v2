# GUI Layout Hierarchy Refinement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refine the Tkinter GUI layout so the top pipeline bar is the sole workflow guide, the header becomes a clean 2x2 control deck, the left/right work surfaces open in a balanced ratio, and disabled export no longer reads as an ambiguous gray button.

**Architecture:** Build on the existing workflow-state refactor in `src/metabolomics/gui/app.py` rather than replacing it. Keep the current sections, but rebalance their hierarchy: compact the hero input strip, remove duplicated workflow messaging from the header, normalize the command buttons through shared tokens, and set the default split workspace to a stable near-50/50 ratio.

**Tech Stack:** Python, Tkinter, pytest

---

### Task 1: Lock the layout-hierarchy rules with failing tests

**Files:**
- Modify: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing tests**

- Add a test that asserts the header button tokens describe a 2x2 action deck with explicit `Reset Workflow` and `Export` labels.
- Add a test that asserts the default window configuration targets the wider workstation layout.
- Add a test that asserts export retains readable label text while disabled.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the current GUI still treats header buttons and window sizing as ad hoc layout choices.

**Step 3: Write minimal implementation**

- Add shared layout/button token helpers in `src/metabolomics/gui/app.py`.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 2: Convert the header into a uniform 2x2 control deck

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add a focused test that asserts the header no longer duplicates pipeline-order guidance and that the four control buttons retain stable explicit labels.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the header still mixes workflow explanation and command actions.

**Step 3: Write minimal implementation**

- Remove duplicated workflow-order copy from the header.
- Arrange `Auto Run`, `Stop`, `Reset Workflow`, and `Export` into a visually consistent 2x2 grid.
- Normalize button width, padding, and centered label alignment.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 3: Compact the hero section into an input strip

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add a regression test for the hero/input section token values or layout constants:
  - narrower file display target
  - preserved explicit `Browse` / `Import Preprocessing` actions

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the hero still consumes more width and emphasis than intended.

**Step 3: Write minimal implementation**

- Reduce the horizontal footprint of the file display.
- Keep file actions explicit, but treat the section as an input strip rather than a banner.
- Ensure text blocks remain left-aligned for readability.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 4: Rebalance the split workspace to a stable default ratio

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Test: `tests/unit/test_gui_step_flow.py`

**Step 1: Write the failing test**

- Add a test that captures the intended left/right workspace ratio or min-size relationship that supports a near-50/50 split.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
FAIL because the current split defaults are still inherited from older asymmetric layout assumptions.

**Step 3: Write minimal implementation**

- Adjust default PanedWindow sizing or startup sash placement so the left and right regions open with a balanced ratio.
- Keep both panels readable at the chosen minimum window size.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

### Task 5: Verify bridge/export behavior still reads correctly after the layout cleanup

**Files:**
- Modify: `tests/unit/test_bridge_launch.py` only if text or token expectations changed
- Modify: `src/metabolomics/gui/app.py` only if export label handling requires adjustment

**Step 1: Write the failing test**

- If needed, add a regression check that export remains explicitly labeled and still resolves Step 4 output correctly.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_bridge_launch.py -q`

Expected:
Either PASS already, or FAIL only if the label/state cleanup affected export wiring.

**Step 3: Write minimal implementation**

- Keep export readable when disabled without changing export resolution logic.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_bridge_launch.py -q`

Expected:
PASS

### Task 6: Run focused verification and manual smoke test

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Run focused GUI tests**

Run:
`pytest tests/unit/test_gui_step_flow.py -q`

Expected:
PASS

**Step 2: Run syntax verification**

Run:
`python -m py_compile src/metabolomics/gui/app.py`

Expected:
PASS

**Step 3: Manual smoke test**

Run:
`python Data_Normalization_program_v2.py`

Expected:
- top workflow bar remains the single process guide
- header reads as an action deck, not a second process explainer
- the four control buttons share consistent sizing
- `Reset Workflow` is visually distinct from neutral actions
- disabled `Export` is still clearly identifiable
- the left and right working areas feel balanced in windowed mode

**Step 4: Commit**

```bash
git add src/metabolomics/gui/app.py tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py docs/plans/2026-03-10-gui-layout-hierarchy-design.md docs/plans/2026-03-10-gui-layout-hierarchy.md
git commit -m "plan(gui): refine layout hierarchy and control deck"
```
