> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# GUI Layout Hierarchy Refinement Design

**Context**

The current GUI refactor improved workflow state handling, but the visual hierarchy is still inconsistent in ways the user can feel immediately on a 1920x1080 display:

- in windowed mode, the layout still feels proportionally off even though fullscreen is acceptable
- the control deck around `Auto Run`, `Stop`, `Reset Workflow`, and `Export` still reads as a mixed cluster rather than a coherent command area
- the disabled `Export` button is visually ambiguous and can be mistaken for an unrelated gray tool button
- the top workflow navigation and the `Workflow Steps` header are both trying to explain the pipeline, creating duplicated guidance

The user has confirmed the preferred direction:

- keep the very top workflow bar
- remove duplicated workflow explanation from the header area
- make the command area more coherent
- make the left/right working regions feel balanced

This design uses the `frontend-design` perspective, but applies it pragmatically to the existing Tkinter desktop UI rather than attempting a visual rewrite.

## Goals

- Keep the top pipeline bar as the single workflow-orientation surface.
- Convert the header area into a pure action deck instead of a second workflow explanation block.
- Make the four command buttons read as one intentional 2x2 control grid with equal sizing.
- Rebalance the main left/right work areas so the interface feels stable in a normal window, not only in fullscreen.
- Make the disabled export action clearly identifiable as an unavailable next-stage action rather than an unlabeled gray button.

## Non-Goals

- No migration away from Tkinter.
- No introduction of decorative or high-motion effects.
- No redesign of processor execution logic.
- No attempt to make the GUI look like a web app.

## Frontend-Design Read

### Purpose

This GUI is a laboratory workflow console. The interface should feel like a precise instrument panel, not a marketing page and not a dense legacy admin form.

### Tone

The right visual direction is:

- precise
- quiet
- operational
- clearly segmented

That means:

- restrained color usage
- sharp semantic contrast for important actions
- strong structural rhythm
- fewer duplicated headlines

### What should be memorable

The memorable quality should be:

- the user always knows where they are in the pipeline
- the action area feels deliberate and obvious
- the left and right work surfaces feel evenly balanced

## Design

### 1. One workflow guide only

Keep the top navigation bar as the only explicit workflow guide.

It already provides the right kind of orientation:

- current stage
- sequence
- progress context

Remove duplicated workflow explanation from the header block:

- keep a short local heading if needed for the action area
- remove order text such as `Order: ISTD → QC → QC Batch Scaling → Conc.`

This prevents the header from competing with the navigation bar.

### 2. Turn the header into a true control deck

The header should stop behaving like a second informational banner and become an action zone.

The command set should be arranged in a strict 2x2 grid:

- row 1: `Auto Run` | `Stop`
- row 2: `Reset Workflow` | `Export`

Rules:

- all four buttons share the same width
- all four buttons share the same height
- labels are centered
- spacing between buttons is uniform

Semantic treatment:

- `Auto Run`: primary filled action
- `Stop`: neutral interrupt action
- `Reset Workflow`: warning/destructive secondary action
- `Export`: secondary downstream action

Disabled export should still be legible as `Export`, but visually indicate that it unlocks later rather than appearing as an unnamed gray block.

### 3. Remove ambiguous button semantics

The user specifically called out the gray button to the right of `Reset Workflow`.

The design fix is not just color. The button needs all three of these:

- stable label text
- stable slot in the 2x2 grid
- clearer disabled styling

Recommended disabled export treatment:

- keep the label `Export`
- use a lighter bordered neutral style rather than a flat dark gray mass
- optionally add a short note elsewhere such as `Available after Step 4`

The key is that disabled should mean unavailable, not unreadable.

### 4. Rebalance the working surface to a stable 1:1 split

The left step area and the right info panel should feel like two equal working surfaces.

The current PanedWindow should be adjusted so the default layout visually lands close to 50/50.

Design intent:

- left: execution controls and step lineage
- right: execution feedback and status

If one side starts substantially narrower by default, the UI feels improvised. The default window should open into a balanced workspace.

### 5. Compress the hero section into an input strip

The hero section should not dominate the page.

It should become a compact input strip with:

- file name display
- `Browse`
- `Import Preprocessing`

The section should support the workflow, not compete with it. That means:

- less vertical weight
- less width consumption
- no oversized headline behavior

### 6. Alignment rules

Use centering selectively:

- center button labels
- center step number blocks
- center the 2x2 control grid

Do not center long explanatory copy, file names, or log/status content. Those remain left-aligned for readability.

## Testing

Add or update regression coverage for:

- window defaults favoring the wider workstation layout
- button token definitions for equal-sized 2x2 command grid semantics
- removal of duplicated workflow explanation from the header
- export button keeping explicit text even when disabled
- top navigation remaining the only workflow guide

Manual smoke test should confirm:

- default windowed mode feels balanced on a 1920x1080 display
- the gray-button ambiguity is gone
- the four command buttons look like one control deck
- the header no longer repeats the same process guidance shown in the top nav

## Recommendation

Implement this as a focused visual-structure cleanup on top of the current workflow-state refactor:

1. simplify header information hierarchy
2. normalize command grid sizing and semantics
3. rebalance the split workspace defaults
4. reduce hero dominance

This is the smallest change that directly addresses the user’s observations while keeping the current Tkinter architecture intact.
