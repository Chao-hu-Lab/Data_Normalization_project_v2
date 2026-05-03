> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# GUI Workflow State Refactor Design

**Context**

The current Tkinter GUI in `src/metabolomics/gui/app.py` has grown around multiple parallel state channels:

- `completed_steps`
- `step_outputs`
- `current_stats`
- `last_output_file`
- per-widget direct updates spread across event handlers

That makes the interface hard to reason about and causes UX inconsistencies:

- the top navigation is still hard-coded to a 3-stage view while the actual workflow is 4 steps
- Step 3 still appears as `Batch Correction` in the GUI even though the active processor has moved to `QC Batch Scaling`
- file-selection and artifact-opening actions are duplicated
- several panels derive status independently instead of rendering from one shared workflow state

The user has confirmed that this refactor may include light structural cleanup inside `app.py`, not just copy changes.

## Goals

- Keep the current Tkinter application and layout structure.
- Introduce one shared workflow-state model inside `app.py`.
- Make navigation, step cards, progress, status, and export readiness derive from the same state.
- Rename GUI Step 3 from `Batch Correction` to `QC Batch Scaling`.
- Reduce duplicated UI actions where they represent the same user intent.
- Preserve current processor execution behavior and bridge/export behavior.

## Non-Goals

- No full MVC rewrite.
- No migration away from Tkinter.
- No broad visual redesign beyond changes required for clearer workflow semantics.
- No processor-algorithm changes.

## Design

### 1. Add a single workflow-state layer

Inside `src/metabolomics/gui/app.py`, define one canonical state structure owned by `DataNormalizationApp`.

It should represent:

- selected input file
- ordered pipeline steps and labels
- active/running step
- completed steps
- per-step result payloads and resolved artifacts
- current execution status (`idle`, `running`, `error`, `cancelled`, `completed`)
- export readiness

This state layer may remain simple and internal to `app.py`; it does not need to become a separate module yet.

The important rule is:

- widget code should render from workflow state
- event handlers should update workflow state first
- derived UI should be refreshed from a small set of render/update methods

### 2. Normalize the step definition model

Replace the current partially hard-coded workflow semantics with one ordered step definition list used by all workflow UI surfaces.

That single source should drive:

- top navigation labels
- step card titles
- next-runnable step highlighting
- progress percentage
- export eligibility checks

Step names should be:

- `Step 1: ISTD Correction`
- `Step 2: QC Correction`
- `Step 3: QC Batch Scaling`
- `Step 4: Conc. Normalization`

This aligns the GUI with the already-approved Step 3 processor design.

### 3. Consolidate render/update responsibilities

The current GUI directly mutates many widgets from multiple handlers such as:

- `update_button_states()`
- `update_input_source_labels()`
- `on_step_start()`
- `on_step_complete()`
- `on_step_error()`
- `reset_all_steps()`

Keep these lifecycle hooks, but refactor them so they update shared state and then call focused render helpers such as:

- render navigation
- render step cards
- render status panel
- render progress area
- render export button state

This reduces drift between panels after run, failure, cancellation, and reset.

### 4. Consolidate duplicate user actions

There are currently two file-selection entry points and overlapping artifact-opening helpers.

Consolidate:

- `select_initial_file()` and `select_input_file()`
- `open_step_plots()` and `open_step_folder()` after deciding whether both user intents are still necessary

Preferred user-facing artifact actions on each step card:

- `Open Excel`
- `Open Plots`

If opening the parent folder remains useful, it should be exposed intentionally, not as a second overlapping implementation path.

### 5. Improve workflow semantics without a broad restyle

The GUI does not need a visual redesign, but it does need clearer control semantics.

Apply these UX corrections:

- top nav becomes dynamic and accurately reflects the 4-step pipeline
- icon-only step artifact buttons become text-plus-icon or short text buttons
- the hero area stays focused on input acquisition only
- step cards become the primary workflow control surface
- the right panel remains secondary and observational (`Execution Log`, `Status`)

This keeps the current layout while making primary actions self-explanatory.

### 6. Preserve execution and bridge behavior

The refactor should not change:

- processor module loading flow
- threaded step execution model
- preprocessing import flow
- MetaboAnalyst export and bridge launch flow

It only changes how state is represented and rendered around those behaviors.

## Testing

Add or update unit coverage in:

- `tests/unit/test_gui_step_flow.py`
- `tests/unit/test_bridge_launch.py` only if export state wiring changes affect expectations

Required regression coverage:

- dynamic 4-step workflow definitions are consistent
- Step 3 label is `QC Batch Scaling`
- next-step enablement comes from the shared workflow state
- reset clears workflow state and disables artifacts/export correctly
- step failure invalidates downstream state consistently
- export readiness only becomes active after Step 4 completion

## Risks

- Because `app.py` currently mixes state mutation and rendering, partial refactors can create temporary inconsistency if some widgets still bypass the new state layer.
- Existing tests use lightweight dummy widgets and may need small state-shape updates once rendering is centralized.
- There are unrelated local modifications in the working tree, so source edits must stay narrowly scoped to the GUI state refactor and its direct tests.

## Recommendation

Implement the refactor incrementally inside `app.py`:

1. define the shared workflow state and step metadata
2. switch render logic to consume it
3. remove duplicated interaction paths
4. align tests with the new single-state behavior

This yields the UX benefits of a workflow cleanup without the cost of a full GUI rewrite.
