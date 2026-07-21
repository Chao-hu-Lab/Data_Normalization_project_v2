# DNP GUI — PySide6 View Rebuild Spec

**Date**

- 2026-07-21

**Status**

- Draft — reviewed twice (Claude: Approved w/ conditions; Codex: Blocked-for-construction, migration direction endorsed). All conditions folded in below. **Not construction-ready until the durable-landing + entry-point + worker-contract blockers are closed** (see Construction blockers).
- **Build base / asset source (Codex blocker 1):** the Qt branch is cut from **`5ea2543`** (current HEAD; already has `workflow.py`, not `theme.py`). **`3085380`** (tk branch `feature/dnp-gui-visual-refresh`) is a **visual-parity reference snapshot only**. Port only the *latest* `theme.py` + necessary design assets from it; **do NOT merge the tk implementation** into the Qt PR. The corrected spec lands at `docs/plans/2026-07-21-dnp-gui-pyside6-rebuild-design.md` on the Qt branch as its first commit.
- Supersedes the tkinter view; the tk GUI stays as reference/fallback until the Qt view reaches parity, then is retired in a later cleanup.

**Alternatives considered (and why not)**

- **Stay on the finished tk GUI, accept the resize lag.** Rejected: this repo is a *showcase*; laggy resize is the visible symptom that undercuts that goal.
- **Path A — targeted tk optimisation** (replace `tk.PanedWindow` with a static grid split, drop `grid_propagate(False)` fights). **Not empirically tried.** Assessed as unlikely to reach showcase-smooth because tk relayouts the whole tree synchronously per `<Configure>` regardless of the split widget; but honesty demands recording that the "tk can't be fixed" claim is an *assessment*, not a measurement. If cheap certainty is wanted, P0 could be preceded by a 1-hour Path-A spike — deferred by user decision in favour of B.
- **CustomTkinter** — same tk relayout engine underneath; would not fix resize.
- **Web (NiceGUI / Streamlit desktop)** — different distribution model; heavier pivot; not aligned with the user's PySide6 flagship.
- **B — PySide6 view rebuild (chosen).** Expected (not guaranteed) resize improvement via Qt's layout/threading model, flicker-free QSS theming, consistent with the user's PySide6 (XIC) flagship. The resize win is validated at P0, not assumed.

**Context**

The tkinter GUI reached a hard ceiling: **window-resize is laggy** on this UI's widget density (~100+ nested widgets), because tk relayouts the whole tree synchronously on the main thread for every `<Configure>` event, with no debounce or GPU compositing. This is fundamental to tk, not a fixable bug — and it is exactly where "showcase-grade" polish breaks down. This repo is the user's first repo and is intended as a **demonstration case**, so polish matters.

Decision (supersedes earlier O1=B1 "pure tkinter"): **rebuild the view in PySide6 (Qt for Python).** Note this is a tkinter → Qt port; PySide6 *is* Qt, not an exotic framework. Rationale: Qt's layout engine, native widgets and worker-thread model are **expected to improve** resize responsiveness, plus flicker-free live theming (QSS) and consistency with the user's PySide6 flagship (XIC).

**Correction (Codex review):** standard `QWidget` paints via a CPU-raster `QBackingStore`, **not** GPU compositing (that is the separate `QOpenGLWidget` path). So "Qt = guaranteed smooth resize" is **false**. Smoothness on *this* UI density is a **hypothesis to be proven at P0** and re-checked at near-final density in P3/P4 — not a given.

**The tk work is not wasted.** It validated the whole design, produced the spec / design principles / baseline methodology, and — critically — produced two portable, framework-agnostic assets that transfer unchanged.

**Reusable assets (transfer as-is or near-as-is)**

- `src/metabolomics/gui/workflow.py` — pure `WorkflowState` state machine. **Zero UI dependency → transfers 100%.**
- `src/metabolomics/gui/theme.py` — token table `(light, dark)` + `resolve` + `detect_os_mode`. Pure Python; **ported from `3085380`** (absent at `5ea2543`). The **token values transfer directly**; only the *consumption* changes (tk `config(bg=...)` → Qt QSS). Caveat: `detect_os_mode()` is **Windows-only** (non-Windows returns light) — the Qt adapter must do cross-platform OS-theme detection (see Theme contract).
- Shared contracts (frozen): `utils/results.py` `ProcessingResult`, processor `main()`, `file_io` session semantics.
- Design decisions locked this session: single accent, neutral cards, six-state status pills, chain-of-custody, restraint layout, System-following + Light/Dark/System toggle, progress heartbeat, persistent status bar, keyboard shortcuts, Step-3 method hint, no marketing hero, single title.
- The screenshot-baseline *methodology* — but note it is re-established fresh for Qt (`QWidget.grab()`) for **Qt-internal** regression only. tk PNGs are **not** a valid oracle for Qt output (different renderers; cross-framework pixel diff is meaningless).

---

## Goals

- G1. **Showcase-grade resize**: smooth window resizing (the entire reason for the pivot).
- G2. **Flicker-free live theming**: Light / Dark / System, switch at runtime via QSS swap (no rebuild, no flash), follow OS at startup.
- G3. **Feature parity** with the refined tk GUI (all decisions above), not a regression.
- G4. Reuse `workflow.py` and `theme.py` unchanged in logic; keep processors / schema / output / session semantics untouched.
- G5. Clean Qt architecture: worker threads via `QThread`/`QThreadPool` + signals (replacing the tk `queue` + `after` polling); controller as a thin renderer over `WorkflowState`.

## Non-goals

- N1. No change to processor science, output schema, or session directory layout.
- N2. No change to workflow semantics (order, Auto Run terminal = Step 3, Step 4 diagnostics-only, cooperative Stop).
- N3. **WS4.5 (reopen last session) stays BLOCKED** — backend-owned contract, unchanged by the framework switch.
- N4. Not a redesign — the visual/interaction design is already decided; this is a re-implementation in Qt.

## Public-surface impact

| Surface | 影響 | 說明 |
|---|---|---|
| Processor / schema / output / `file_io` | 無 | N1 |
| `WorkflowState`, `ProcessingResult`, processor `main()` | 無（凍結） | reused unchanged |
| `theme.py` token table | 無（值不變） | consumption changes only |
| GUI framework | **新增 PySide6 依賴** | requirements + packaging (see Risks) |
| Entry point `Data_Normalization_program_v2.py` | 改指向 Qt app（切換時） | tk entry kept until parity |

---

## Architecture

**Module layout.** New package `src/metabolomics/gui_qt/` alongside the tk `gui/`. tk `gui/app.py` stays runnable as fallback until Qt reaches parity.

**THREE entry points must switch (Codex blocker 2), not two:**
1. `Data_Normalization_program_v2.py:10` (root launcher)
2. `src/metabolomics/__main__.py:18` (`python -m metabolomics`)
3. **`build/MetabolomicsNormalization.spec:59`** → the PyInstaller `Analysis([... gui/app.py])`; **`.github/workflows/build.yml:21` builds from this spec**, so if it is not switched, *source runs Qt but the shipped `.exe` still runs tkinter.*

The P4 entry-point commit switches all three + README, revertibly, together. `scripts/capture_gui_baseline.py` and the `test_gui_*` tests stay bound to tk (fallback coverage) until tk is retired. `workflow.py` and `theme.py` shared (imported from `gui/`, or a neutral location — see O1).

**Threading / execution.**
- Each step runs on a `QThread` (or `QThreadPool` `QRunnable`) worker that calls `processor.main(**kwargs)`.
- Worker emits signals: `progress`, `finished(ProcessingResult)`, `failed(str)`. The GUI thread updates `WorkflowState` and the view in slots — **no `queue` + `after(100)` polling** (that whole mechanism is replaced by signals/slots).
- **Cooperative Stop** keeps the same semantics: a stop flag checked at step boundaries; the finished result is discarded if stop was requested. `WorkflowState` already models this (`should_discard_result`).
- stdout/stderr capture per step routed to the log view via a signal (replacing `StreamToLogger` + queue).

**Theming.**
- Generate a QSS stylesheet from `theme.resolve(token, mode)` for all widget classes / object names.
- Light/Dark/System: `detect_os_mode()` at startup; toggle re-generates QSS and calls `app.setStyleSheet(...)` → **instant, flicker-free, no widget rebuild** (Qt's native strength; no in-place recolour hack, no destroy/rebuild).
- **matplotlib figures stay white** (unchanged decision; figures are backend-generated, framework-independent).

**Layout.**
- `QSplitter` for the left(cards)/right(log) split — smooth, draggable, no re-snap fighting.
- Step cards as `QFrame` widgets (name + six-state pill + chain-of-custody + actions); accent only on the next step.
- `QStatusBar` or a bottom bar for progress + session path.
- Keyboard shortcuts via `QShortcut` (Enter=run next, Esc=stop) with focus handling.

---

## Worker lifecycle & concurrency contract (Codex blocker 3 — lock before P2)

Use the Qt-recommended **`QObject` worker + `moveToThread`** pattern (not a `QThread` subclass).

- **Exactly-once terminal transition.** Each run has a unique `run_id`. A run reaches exactly one terminal state — `finished(result)` XOR `failed(err)` XOR `cancelled` — applied once. Signals for a stale/superseded `run_id` are ignored.
- **Stop / finished race.** Cooperative Stop keeps tk semantics: if stop was requested before the terminal signal is applied, the finished result is **discarded** (`WorkflowState.should_discard_result`), not applied. Handle both orderings (stop-then-finish, finish-then-stop) and late signals.
- **Exceptions** in the worker → `failed` signal + cleanup; never crash the GUI thread.
- **closeEvent while a worker runs**: request stop, then `thread.quit(); thread.wait(timeout)`; do not destroy the running thread without quit/wait.
- **Ownership/teardown**: GUI thread owns the `QThread`; the worker is `moveToThread`'d in and **touches no widgets** (only emits signals). Teardown order: `quit()` → `wait()` → `worker.deleteLater()` → drop references.
- **No processor progress callback.** `processor.main` has no progress hook, so the worker emits only **log lines / `finished` / `failed`**. The progress **heartbeat is a UI-side `QTimer`** (indeterminate animation), started/stopped by the controller — not driven by the worker.

## Theme preference & state-mapping contract (Codex major — lock before P1/P2)

- **`ThemePreference = system | light | dark`**, resolving to a token **mode ∈ {light, dark}**. (Persistence: session-only by default, matching the earlier O2 "no persisted override"; the in-app toggle changes it live.)
- **Cross-platform OS detection.** `theme.detect_os_mode()` is **Windows-only** (registry) and must not be claimed cross-platform. The Qt adapter uses **`QGuiApplication.styleHints().colorScheme()`** (Qt/PySide6 ≥ 6.5) for Light/Dark on Windows **and macOS** (both are release targets). Decide in review: **System = resolve at startup only**, or **continuously follow** via `styleHints().colorSchemeChanged` (leaning: startup + honour the change signal since it is nearly free).
- **Full six-state mapping** (WorkflowState → controller → token), carried verbatim: `pending→idle`, `running→running`, `succeeded→done`, `skipped→skipped`, `failed→error`, `cancelled→cancelled`.

## Phases (reordered to front-load risk)

Order proves the two *hardest / riskiest* things first — resize (the pivot's premise) and the controller/threading — before the large but low-risk view-parity work.

- **P0 — Scaffolding + resize kill-gate**: `gui_qt/` package, share `theme.py`/`workflow.py`, add PySide6 dep, **build a real PyInstaller Qt executable** (a Qt PyInstaller spec; prove packaging works — not just `python` source), minimal `QMainWindow` at **near-final widget density** (`QSplitter` + 4 placeholder cards each ~ the real card's widget count + a log). **HARD KILL-GATE**: the user drags *the built executable* on their machine; if resize is not smooth, STOP — do not start P1+. Because smoothness depends on density, **re-run the same resize gate at P3 (real cards) and P4 (final)** — P0 passing on placeholders does not guarantee P3.
- **P1 — Theme → QSS + Light/Dark/System toggle**: a **new** `gui_qt/qss.py` generator turns `theme.resolve(token, mode)` into a stylesheet; startup OS-follow; live flicker-free switch via `setStyleSheet`. (Validates G2, the second pivot reason.)
- **P2 — Minimal FUNCTIONAL GUI (controller + threading)**: on a deliberately plain view, wire the risky part — `QThread` workers calling `processor.main`, signals for progress/finished/failed, `WorkflowState` integration, Auto Run chain, **cooperative Stop (finish-then-discard)**, log streaming, error retry. **This is the first increment that can actually run the DNP workflow end to end** — ship/validate the hard part before polishing.
- **P3 — View parity**: step cards, six-state pills, chain-of-custody, single-accent next-step, file bar, status bar + session path, single title — match the locked tk design.
- **P4 — Polish**: keyboard shortcuts (Enter/Esc + focus), Step-3 method hint, single-step no-modal, window sizing; switch the entry point (one commit; revertible).
- WS4.5 (reopen session) remains **blocked** on the backend contract.

**Kill-gate discipline**: P0 gates the whole effort; P2 (controller) gates P3/P4 — if threading/Stop/Auto-Run can't be made correct, that is the real risk, not the cards.

---

## Parity checklist — edge cases to carry (do not lose in the port)

The tk GUI accumulated domain-aware behaviour that is easy to drop when re-implementing. Each must be reproduced and verified in Qt:

- **Cooperative Stop**: request stop → current step finishes → its result is *discarded* (not applied); downstream invalidated. (`WorkflowState.should_discard_result`.)
- **Auto Run** stops after Step 3; Step 4 stays diagnostics-only (manual). Final Auto-Run modal kept.
- **Skip guidance messages**: ISTD `insufficient_good_istd`, Step-4 `single_batch`, Step-4 `paused_nonshared_qc_design` — the human-readable downstream guidance must survive.
- **Six visible states** incl. skipped & cancelled (not just idle/running/done/error).
- **Single-step completion shows no modal**; skip / error / Auto-Run-final DO show a modal/notice.
- **Error path**: failure invalidates the step + downstream; offer retry.
- **Chain-of-custody** input-source labels update as steps complete.
- **Excel/Plots buttons** enable only when a step produced artifacts; plots open the session `plots/` dir.
- **matplotlib figures stay white** regardless of UI theme.
- Native file dialogs, session-dir creation on first run.

## Controller verification plan (the real risk — test without real processors)

- Mock `processor.main(**kwargs)` to return a canned `ProcessingResult` (or raise) so the controller/threading is testable headless, mirroring the tk fake-widget tests.
- Cover: single step success; Auto-Run chain to Step 3 (and that Step 4 is not auto-scheduled); **Stop mid-run discards the finished result**; error → invalidate + retry offer; skipped result → guidance path.
- Qt-specific: worker owns no widgets; only signals cross to the GUI thread (test signal emission + slot state updates). A real-Qt startup smoke (build `QMainWindow`, toggle theme, no crash) mirrors the tk startup smoke.

## Risks & mitigations

- R1. **PySide6 dependency + packaging**: PySide6 is large; PyInstaller needs the Qt plugins/hooks. → Confirm packaging early (P0); document the `.exe` build. Consistent with XIC (already solved there).
- R2. **Qt threading correctness** (thread affinity, signals across threads): worker owns no widgets; only signals cross to the GUI thread. → Standard Qt worker pattern; test Stop/Auto-Run paths.
- R3. **QSS theming fidelity** vs the tk look: QSS differs from tk styling. → Drive QSS from the same token table; accept minor rendering differences (Qt will look better, not worse).
- R4. **Scope creep into redesign**: the design is decided. → Parity-first; no new design in this rebuild.
- R5. **Two GUIs during transition**: keep tk as fallback until parity, then switch entry point in one commit; avoid maintaining both long-term.

## Open questions (for review)

- O1. `theme.py` / `workflow.py` location: keep under `gui/` (shared import) or move to a neutral `gui_common/`? (Leaning: leave in place, import from `gui_qt`.)
- O2. Worker model: `QThread` subclass vs `QThreadPool` + `QRunnable`? (Leaning: `QThread` + worker object via `moveToThread`, standard and testable.)
- O3. Do we eventually delete the tk `gui/app.py`, or keep it as a documented fallback? (Leaning: keep until Qt ships, then remove in a later cleanup.)

## Construction blockers (Codex — close before starting)

| # | Must be done | Owner | Due | Status |
|---|---|---|---|---|
| 1 | Durable spec landed in `docs/plans/`; Qt branch cut from **`5ea2543`**, **`3085380`** as reference only, tk impl not merged | spec owner | before P0 | ✅ landed on `feature/dnp-gui-qt` (base `5ea2543`) |
| 2 | Third packaged entry point (`build/*.spec` + CI) accounted for; P0 builds & launches a real Qt **executable** as the resize gate | GUI implementer | P0 gate / P4 switch | ⬜ specified above |
| 3 | Worker lifecycle contract locked: `QObject`+`moveToThread`, `run_id` exactly-once, Stop/finished race, closeEvent, teardown | GUI implementer | before P2 | ⬜ specified above |

Direction is endorsed by both reviewers; these three gate *construction*, not the decision.

## Acceptance

- **P0 resize kill-gate passed on the built Qt executable** (not just source), re-checked at P3/P4 near-final density; the user confirms smooth resize on their own hardware (subjective but decisive; the whole premise, not an assumption).
- Light/Dark/System switch is instant and flicker-free; follows OS at startup.
- **Feature parity verified by the parity checklist above** (behaviour, not pixels). Cross-framework pixel comparison to the tk baselines is explicitly **not** used; Qt gets its own fresh `QWidget.grab()` baselines for Qt-internal regression only.
- Controller verification plan green (mock-processor tests: Stop-discard, Auto-Run, error/retry, skip).
- `workflow.py` unchanged; `theme.py` token *values* unchanged (a new `qss.py` adapter is added, not a change to `theme.py`); processor / `ProcessingResult` / `file_io` contracts and outputs unchanged.
- WS4.5 not implemented (blocked); Skip list not implemented.
- Entry-point switch is a single revertible commit; tk GUI remains launchable until then.

## Post-P4 visual direction — "A cockpit + conditional B receipt" (decided 2026-07-21; NOT yet implemented)

This section is a **deliberate redesign** decided *after* P4 passed parity/functional/resize acceptance. It is explicitly **out of scope for the parity rebuild** above (it supersedes N4 / R4 only for this later, separately-gated effort) and **must not be written back to the production branch until the P4 review is formally closed.**

**Context.** The accepted P4 UI is correct but visually generic ("boring"). A `creative-breakout` pass produced two throwaway browser prototypes (worktree `.worktrees/dnp-gui-breakout-prototype`, branch `codex/dnp-gui-breakout-prototype`): **A — Focus Stage** (current step is the stage; completed steps compress into a workflow rail; log becomes a drawer) and **B — Evidence-first Lineage** (scientific evidence/plots own the screen; workflow becomes a compact lineage bar). A fresh-context review recommended a mix, not a 2-of-1 choice.

**Decision (operator's).** Not pure A, not pure B, not a full dashboard. Build **A's action-first operational cockpit as the main shell**, with **B's evidence treatment grafted into a conditional, real-data-driven right-hand receipt** that takes over *after* a step completes or when a completed step is selected. Weighting is **not 50/50** — the operator's primary job is *driving the next step*; verifying the result is secondary. This maps cleanly to the existing pipeline: ordered 4-step dependency, Steps 1–3 support Auto Run, Step 4 is manual diagnostics-only. A-as-backbone therefore also carries the lowest Qt risk.

**Evidence receipt — v1 contract (the real constraint).** [`ProcessingResult`](../../src/metabolomics/utils/results.py) (results.py:17) today only stably exposes `output`, `metabolites`, `samples`, `plots_dir`; **Steps 1–3 expose no structured scientific metrics.** So the first receipt version MUST:

- show **real existing plot thumbnails** from the shared plots dir, filtered by `Step1_`…`Step4_` prefixes;
- show **metabolites / samples / artifact counts + the output file**;
- for **Step 4**, add a **`diagnostics-only` / "No correction applied"** warning;
- **never fabricate** CV or improvement tiles, and **never scrape** numbers from the log or the Excel workbook.

Numeric scientific tiles (CV, RLE, D-ratio, before/after deltas) are **deferred** until a formal evidence contract exposes them on `ProcessingResult`. Which steps do have genuine before/after *plots* today (for thumbnails, not fabricated numbers): **Step 1** — QC CV comparison, density overlay, ISTD tracking; **Step 2** — QC CV overview, LOESS trend before/after; **Step 3** — CV, RLE, density, D-ratio before/after; **Step 4** — comparison plots but only as a *diagnostics proxy* (must be labelled "No correction applied").

**Theme.** **Light mode stays first-class.** Distinctiveness must come from the three-column IA + step stage + evidence receipt, **not** from committing to a dark-only palette. The existing [`ThemeManager`](../../src/metabolomics/gui_qt/qss.py) (qss.py:18) already supports System / Light / Dark; no functional regression for visual identity.

**Already landed (P4-review follow-up, on `feature/dnp-gui-qt`).** The type-system half of the prototypes' intent is done independently of the A/B shell: unified UI font stack + coherent scale (display 24 / section 14 / body 12 / small 10pt, monospace reserved for the execution log) and a work-area-aware window-fit fix (commits `fix(gui-qt): unify typography…`, `fix(gui-qt): clamp window size…`). The IA restructuring (A shell + B receipt) remains unimplemented and gated as above — treat it as a **P5** effort with its own tests and controller contract.

## Lessons to capture on completion (Agent Memory)

- **Pure-tkinter has a hard resize/polish ceiling on dense desktop UIs** (synchronous full-tree relayout, no debounce/GPU). For showcase-grade desktop apps, prefer Qt (PySide6) — especially when a Qt project already exists in the stack.
- **The token layer + pure state machine paid off as portable assets**: `theme.py` and `workflow.py` transferred across a framework switch untouched. Keeping UI framework-agnostic modules (pure state, pure token table) is what made the pivot cheap.
- The tk build was not wasted: it validated the design and produced the spec/principles/baseline that the Qt rebuild executes against.
