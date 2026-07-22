# Codex construction brief — DNP GUI PySide6 (Qt) rebuild

You are building the **PySide6 (Qt) view rebuild** of the DNP GUI. This is a
tkinter → Qt *view* port; PySide6 *is* Qt for Python. Work on branch
**`feature/dnp-gui-qt`** (base `5ea2543`), worktree `.worktrees/dnp-gui-qt`.

**Read first, it is canonical:** `docs/plans/2026-07-21-dnp-gui-pyside6-rebuild-design.md`.
Also obey the repo `CLAUDE.md` / `AGENTS.md` (繁中回應、commit 無 AI footer、不直接 push/PR/merge、`uv` 跑測試、PowerShell shell).

## Non-negotiable boundaries

- **Build only the Qt view + its controller glue.** Do **NOT** modify: processors,
  output schema, `utils/file_io` session semantics, `utils/results.ProcessingResult`,
  or `gui/workflow.py` logic — **reuse `workflow.py` as-is** (it is at the base).
- **Parity-first, no redesign.** The visual/interaction design is locked — implement
  the "Parity checklist — edge cases to carry" in the spec. `3085380`
  (`feature/dnp-gui-visual-refresh`) is a **visual reference snapshot only**; **do
  not merge the tk implementation** into this branch.
- New code lives under **`src/metabolomics/gui_qt/`**. Add `PySide6` to requirements.
- **WS4.5 (reopen last session) stays BLOCKED** (backend-owned contract). Do not invent session semantics.

## P0 FIRST — resize kill-gate (the whole premise; do this before anything else)

1. Port the one asset: `git checkout 3085380 -- src/metabolomics/gui/theme.py`
   (and `tests/unit/test_gui_theme.py` if you want its coverage — it is pure).
2. Add PySide6; create a **Qt PyInstaller spec** and **build a real executable**
   (prove packaging, do not test resize from `python` source only).
3. Minimal `QMainWindow` at **near-final widget density**: a `QSplitter` with 4
   placeholder cards (each ~ the real card's widget count) + a log pane.
4. **STOP and hand the built `.exe` to the user to drag-resize on their machine.**
   The claim "Qt = smooth resize" is a *hypothesis* (standard `QWidget` is CPU-raster
   `QBackingStore`, not GPU). **If resize is NOT smooth → STOP the whole effort and
   report; do not start P1.** Re-run this same gate at P3 and P4 (real density).

## Then P1 → P4 (see spec for detail)

- **P1** Theme→QSS: a new `gui_qt/qss.py` turns `theme.resolve(token, mode)` into a
  stylesheet; startup OS-follow; live flicker-free `setStyleSheet` toggle
  (Light/Dark/System). Use **`QGuiApplication.styleHints().colorScheme()`** for
  cross-platform OS theme (macOS is a release target); `theme.detect_os_mode()` is
  Windows-only — do not rely on it cross-platform.
- **P2** Minimal **functional** GUI: `QObject`+`moveToThread` workers calling
  `processor.main`, signals (log / finished / failed), `WorkflowState` integration,
  Auto Run (stops after Step 3), **cooperative Stop (finish-then-discard)**, error
  retry. Obey the **Worker lifecycle & concurrency contract** in the spec
  (run_id exactly-once terminal, Stop/finished race, closeEvent, teardown; **no
  processor progress callback → heartbeat is a UI `QTimer`**). This is the first
  increment that actually runs the workflow end-to-end.
- **P3** View parity: step cards, six-state pills (idle/running/done/skipped/error/
  cancelled), chain-of-custody, single-accent next-step, file bar, status bar +
  session path, single title, Step-3 method hint.
- **P4** Polish + **switch all THREE entry points + README** in one revertible commit:
  `Data_Normalization_program_v2.py`, `src/metabolomics/__main__.py`, and
  **`build/MetabolomicsNormalization.spec`** (the CI `build.yml` builds from it — if
  not switched, source runs Qt but the shipped `.exe` still runs tkinter).

## Verification

- Controller: mock `processor.main` (canned `ProcessingResult` / raise) to test
  headless — single success, Auto-Run chain (Step 4 not auto-scheduled),
  **Stop-mid-run discards the finished result**, error→invalidate+retry, skip→guidance.
- Real-Qt startup smoke (build `QMainWindow`, toggle theme, no crash).
- Qt gets its **own fresh `QWidget.grab()` baselines** — do **NOT** pixel-compare
  against the tk PNGs (different renderers). Parity is the behaviour checklist.
- Run focused tests with `uv run pytest ...`; don't claim green without running.

## Stop-for-review points (do not blow past these)

- After **P0** kill-gate — user confirms resize before any further investment.
- After **P2** — first runnable Qt GUI; user/reviewer checks the controller/threading.
- Before **P4** entry-point switch — this changes what the shipped `.exe` launches.

Small, frequent commits; no push / PR / merge / branch-delete without the user asking.
Report in 白話: what runs, what's blocked, what needs a decision.
