"""Pure theme/token layer for the DNP GUI (no Tk dependency).

Design contract (see docs/plans/2026-07-21-dnp-gui-visual-refresh-design.md):

- Every colour is a semantic token mapped to a ``(light, dark)`` pair.
- ``light`` values reproduce the *current* GUI palette exactly, so WS1's
  hex -> ``resolve`` swap is a zero-visual-diff refactor (characterization
  parity). Dark values and the visual-restraint redesign land in WS2/WS3.
- The mode is resolved once at startup (System-following); there is no
  in-app live switching. Non-Windows or registry failure falls back to light.

This module is intentionally free of ``tkinter`` imports so it can be unit
tested without a display, mirroring the pure ``workflow.py`` module.
"""

from __future__ import annotations

import sys

Mode = str  # "light" | "dark"

_VALID_MODES = ("light", "dark")

# Windows "apps" theme flag lives here; 1 == light, 0 == dark.
_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


# Semantic tokens: name -> (light, dark).
# light == current palette (parity); dark == restrained counterpart (used from WS2).
TOKENS: dict[str, tuple[str, str]] = {
    # --- structure ---
    "surface":         ("#f0f2f5", "#0f1620"),  # window background
    "surface_raised":  ("#ffffff", "#161f2b"),  # cards / panels
    "border":          ("#d1d5db", "#27313f"),
    "divider":         ("#e5e7eb", "#233040"),
    # --- text ---
    "text":            ("#1f2a37", "#e6edf3"),
    "text_muted":      ("#6b7280", "#8b97a5"),
    # --- accent (single highlight) ---
    "accent":          ("#1a73e8", "#5eb0d6"),
    "accent_hover":    ("#1557b0", "#7cc0dd"),
    # accent_fg / status_fg / control_fg are all near-white in light mode but map
    # to different dark values; nudge the light values by 1 (imperceptible) so the
    # in-place recolour swap stays unambiguous.
    "accent_fg":       ("#fffffe", "#0f1620"),
    # --- six step states (align with _set_step_status) ---
    "status_idle":     ("#9ca3af", "#6b7684"),
    "status_running":  ("#f9ab00", "#e0a83d"),
    "status_done":     ("#34a853", "#3fb970"),
    "status_skipped":  ("#6b7280", "#8b97a5"),
    "status_error":    ("#ea4335", "#e05561"),
    "status_cancelled": ("#6b7280", "#8b97a5"),
    "status_fg":       ("#fffffd", "#0f1620"),  # text on a filled status chip
    "status_idle_bg":  ("#eef2f7", "#1b2430"),  # idle chip background
    # --- action buttons ---
    "action":          ("#e8eaed", "#233040"),  # ghost button bg
    "action_fg":       ("#5f6368", "#cdd7e1"),
    "action_disabled": ("#9ca3ae", "#55606e"),  # nudged from #9ca3af (status_idle) for unambiguous swap
    # --- pipeline nav (already dark in both modes) ---
    "nav_bg":          ("#0d1b2a", "#0d1b2a"),
    "nav_fg_active":   ("#eef4fb", "#eef4fb"),
    "nav_fg_idle":     ("#9fb3c8", "#9fb3c8"),
    # --- log console (dark bg regardless of UI mode) ---
    "console_bg":      ("#1e1e1e", "#1e1e1e"),
    "console_fg":      ("#d4d4d4", "#d4d4d4"),
    "log_info":        ("#9cdcfe", "#9cdcfe"),
    "log_warning":     ("#dcdcaa", "#dcdcaa"),
    "log_error":       ("#f14c4c", "#f14c4c"),
    "log_success":     ("#4ec9b0", "#4ec9b0"),
    # --- interaction ---
    "hover":           ("#f0f0f0", "#1f2a37"),

    # --- legacy / transitional (parity in WS1; WS3 collapses these) ---
    # Four-colour step backgrounds. light == current tints exactly.
    "step1_bg":        ("#e8f0fe", "#16263a"),
    "step2_bg":        ("#e6f4ea", "#14301f"),
    "step3_bg":        ("#fef7e0", "#2e2a15"),
    "step4_bg":        ("#fce8e6", "#341a1a"),
    # Header control buttons (Auto Run / Stop / Reset) keep saturated bg in both modes.
    "control_run_bg":         ("#2563eb", "#2563eb"),
    "control_run_active":     ("#1d4ed8", "#1d4ed8"),
    "control_run_disabled_fg": ("#dbeafe", "#dbeafe"),
    "control_stop_bg":        ("#dc2626", "#dc2626"),
    "control_stop_active":    ("#b91c1c", "#b91c1c"),
    "control_stop_disabled_fg": ("#e2e8f0", "#e2e8f0"),
    "control_reset_bg":       ("#475569", "#475569"),
    "control_reset_active":   ("#334155", "#334155"),
    "control_fg":             ("#fffffc", "#fffffc"),  # white both modes; unique so recolour leaves it alone
    # Pipeline nav extras.
    "nav_arrow":       ("#4a6fa5", "#4a6fa5"),
    "nav_fg_seed":     ("#5a6a7a", "#5a6a7a"),  # transient pre-render seed colour
    # Subtle accent surfaces (Import button, hero accents).
    "accent_subtle":       ("#e8f0fe", "#16263a"),
    "accent_subtle_hover": ("#d2e3fc", "#1e3550"),
    "on_accent_muted":     ("#cce0ff", "#9fb3c8"),
    # Subtle raised surface (step card action area).
    "surface_subtle":  ("#f8fafc", "#121b26"),
}


def resolve(name: str, mode: Mode) -> str:
    """Return the colour for ``name`` under ``mode``.

    Raises ``ValueError`` for an unknown mode and ``KeyError`` for an
    unknown token, so mistakes fail loudly instead of silently theming wrong.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown theme mode: {mode!r} (expected one of {_VALID_MODES})")
    try:
        light, dark = TOKENS[name]
    except KeyError:
        raise KeyError(f"Unknown theme token: {name!r}") from None
    return light if mode == "light" else dark


def _read_apps_use_light_theme() -> int:
    """Read the Windows ``AppsUseLightTheme`` flag (1 == light, 0 == dark).

    Isolated so tests can monkeypatch it without touching the real registry.
    """
    import winreg  # Windows-only; imported lazily so the module loads anywhere.

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return int(value)


def detect_os_mode() -> Mode:
    """Resolve the startup mode by following the OS theme.

    Non-Windows platforms and any registry read failure fall back to ``light``.
    """
    if sys.platform != "win32":
        return "light"
    try:
        return "light" if _read_apps_use_light_theme() == 1 else "dark"
    except OSError:
        return "light"
