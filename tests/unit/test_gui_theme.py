"""Unit tests for the pure GUI theme/token layer (no Tk required)."""

import re

import pytest

from metabolomics.gui import theme


HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_every_token_is_a_valid_light_dark_hex_pair():
    assert theme.TOKENS, "token table must not be empty"
    for name, pair in theme.TOKENS.items():
        assert isinstance(pair, tuple) and len(pair) == 2, f"{name} must be a (light, dark) pair"
        light, dark = pair
        assert HEX_RE.match(light), f"{name} light value {light!r} is not a #rrggbb hex"
        assert HEX_RE.match(dark), f"{name} dark value {dark!r} is not a #rrggbb hex"


def test_mandated_vocabulary_is_present():
    # Reviewer gate 2: full token vocabulary incl. six states + roles.
    required = {
        "surface", "surface_raised", "border", "text", "text_muted",
        "accent", "accent_fg",
        "status_idle", "status_running", "status_done",
        "status_skipped", "status_error", "status_cancelled",
        "action", "action_disabled", "nav_bg",
        "log_info", "log_warning", "log_error", "log_success",
        "hover",
    }
    missing = required - theme.TOKENS.keys()
    assert not missing, f"missing mandated tokens: {sorted(missing)}"


def test_light_values_match_current_palette_for_parity():
    # WS1 parity: light mode must reproduce the existing GUI colours exactly.
    assert theme.resolve("surface", "light") == "#f0f2f5"
    assert theme.resolve("surface_raised", "light") == "#ffffff"
    assert theme.resolve("accent", "light") == "#1a73e8"
    assert theme.resolve("status_done", "light") == "#34a853"
    assert theme.resolve("status_running", "light") == "#f9ab00"
    assert theme.resolve("status_error", "light") == "#ea4335"


def test_resolve_picks_correct_slot_per_mode():
    assert theme.resolve("accent", "light") == "#1a73e8"
    assert theme.resolve("accent", "dark") == "#5eb0d6"


def test_resolve_unknown_token_raises_keyerror():
    with pytest.raises(KeyError):
        theme.resolve("does_not_exist", "light")


def test_resolve_unknown_mode_raises_valueerror():
    with pytest.raises(ValueError):
        theme.resolve("accent", "system")


def test_detect_os_mode_non_windows_falls_back_to_light(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "linux")
    assert theme.detect_os_mode() == "light"


def test_detect_os_mode_reads_registry_flag_on_windows(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "win32")
    monkeypatch.setattr(theme, "_read_apps_use_light_theme", lambda: 1)
    assert theme.detect_os_mode() == "light"
    monkeypatch.setattr(theme, "_read_apps_use_light_theme", lambda: 0)
    assert theme.detect_os_mode() == "dark"


def test_detect_os_mode_registry_failure_falls_back_to_light(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "win32")

    def boom():
        raise OSError("registry unavailable")

    monkeypatch.setattr(theme, "_read_apps_use_light_theme", boom)
    assert theme.detect_os_mode() == "light"
