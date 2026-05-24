"""Tests for lib_python_vdesktop.layouts — preset catalog & slot computation."""
from __future__ import annotations

import pytest

from lib_python_vdesktop import layouts
from lib_python_vdesktop.layouts import (
    PRESETS,
    _bounds_from_pct,
    _columns,
    _grid,
    _named_columns,
    _resolve_single,
    _rows,
    find_slot,
    lookup_slot,
    remember_layout,
)


# --- _columns / _rows --------------------------------------------------------


def test_columns_even_split():
    slots = _columns([50, 50])
    assert len(slots) == 2
    assert [s["x_pct"] for s in slots] == [0.0, 50.0]
    assert all(s["w_pct"] == 50.0 for s in slots)
    assert all(s["y_pct"] == 0.0 and s["h_pct"] == 100.0 for s in slots)


def test_columns_normalizes_to_100():
    slots = _columns([10, 20, 30, 40])
    assert sum(s["w_pct"] for s in slots) == pytest.approx(100.0)
    assert [s["w_pct"] for s in slots] == pytest.approx([10.0, 20.0, 30.0, 40.0])


def test_columns_rejects_nonstandard_total():
    with pytest.raises(ValueError, match="sum to 100"):
        _columns([1, 1, 1])


def test_columns_rejects_zero_total():
    with pytest.raises(ValueError):
        _columns([0, 0])


def test_columns_rejects_negative_split():
    with pytest.raises(ValueError, match="positive"):
        _columns([-10, 110])


def test_columns_rejects_zero_value_in_splits():
    with pytest.raises(ValueError):
        _columns([0, 50, 50])


def test_columns_accepts_exact_100():
    slots = _columns([25, 75])
    assert sum(s["w_pct"] for s in slots) == pytest.approx(100.0)


def test_columns_accepts_near_100_within_tolerance():
    # 33.33 + 33.34 + 33.33 = 100.00 — within tolerance
    slots = _columns([33.33, 33.34, 33.33])
    assert len(slots) == 3


def test_columns_rejects_empty():
    with pytest.raises(ValueError):
        _columns([])


def test_rows_even_split():
    slots = _rows([50, 50])
    assert len(slots) == 2
    assert [s["y_pct"] for s in slots] == [0.0, 50.0]
    assert all(s["h_pct"] == 50.0 for s in slots)
    assert all(s["x_pct"] == 0.0 and s["w_pct"] == 100.0 for s in slots)


def test_rows_rejects_empty():
    with pytest.raises(ValueError):
        _rows([])


def test_rows_rejects_negative_split():
    with pytest.raises(ValueError, match="positive"):
        _rows([-50, 150])


def test_rows_rejects_nonstandard_total():
    with pytest.raises(ValueError, match="sum to 100"):
        _rows([30, 30])


def test_rows_rejects_zero_value_in_splits():
    with pytest.raises(ValueError):
        _rows([0, 100])


# --- _grid -------------------------------------------------------------------


def test_grid_2x2():
    slots = _grid(2, 2)
    assert len(slots) == 4
    ids = {s["slot_id"] for s in slots}
    assert ids == {"r0c0", "r0c1", "r1c0", "r1c1"}
    assert all(s["w_pct"] == 50.0 and s["h_pct"] == 50.0 for s in slots)


def test_grid_3x2():
    slots = _grid(3, 2)
    assert len(slots) == 6
    assert all(s["w_pct"] == pytest.approx(100 / 3) for s in slots)
    assert all(s["h_pct"] == 50.0 for s in slots)


def test_grid_rejects_zero_cols():
    with pytest.raises(ValueError):
        _grid(0, 2)


def test_grid_rejects_zero_rows():
    with pytest.raises(ValueError):
        _grid(2, 0)


# --- _named_columns ----------------------------------------------------------


def test_named_columns():
    slots = _named_columns(["left", "right"], [50, 50])
    assert [s["slot_id"] for s in slots] == ["left", "right"]


# --- _bounds_from_pct --------------------------------------------------------


def test_bounds_full_screen(primary_monitor):
    pct = {"x_pct": 0, "y_pct": 0, "w_pct": 100, "h_pct": 100}
    assert _bounds_from_pct(primary_monitor, pct) == {
        "x": 0, "y": 0, "w": 1920, "h": 1080,
    }


def test_bounds_right_half(primary_monitor):
    pct = {"x_pct": 50, "y_pct": 0, "w_pct": 50, "h_pct": 100}
    assert _bounds_from_pct(primary_monitor, pct) == {
        "x": 960, "y": 0, "w": 960, "h": 1080,
    }


def test_bounds_offset_monitor(secondary_monitor):
    pct = {"x_pct": 0, "y_pct": 0, "w_pct": 100, "h_pct": 100}
    assert _bounds_from_pct(secondary_monitor, pct) == {
        "x": 1920, "y": 0, "w": 2560, "h": 1440,
    }


# --- _resolve_single ---------------------------------------------------------


def test_resolve_preset(primary_monitor):
    slots = _resolve_single(
        {"type": "preset", "name": "two-columns", "monitor": 0},
        {0: primary_monitor},
    )
    assert {s["slot_id"] for s in slots} == {"left", "right"}
    assert all(s["monitor"] == 0 for s in slots)


def test_resolve_columns_spec(primary_monitor):
    slots = _resolve_single(
        {"type": "columns", "monitor": 0, "splits": [25, 75]},
        {0: primary_monitor},
    )
    assert len(slots) == 2
    assert slots[0]["bounds"]["w"] == 480  # 25% of 1920
    assert slots[1]["bounds"]["w"] == 1440  # 75% of 1920


def test_resolve_grid_spec(primary_monitor):
    slots = _resolve_single(
        {"type": "grid", "monitor": 0, "cols": 2, "rows": 2},
        {0: primary_monitor},
    )
    assert len(slots) == 4


def test_resolve_regions_spec(primary_monitor):
    slots = _resolve_single(
        {
            "type": "regions",
            "monitor": 0,
            "regions": [
                {"id": "main", "x_pct": 0, "y_pct": 0, "w_pct": 70, "h_pct": 100},
                {"id": "side", "x_pct": 70, "y_pct": 0, "w_pct": 30, "h_pct": 100},
            ],
        },
        {0: primary_monitor},
    )
    assert [s["slot_id"] for s in slots] == ["main", "side"]


def test_resolve_unknown_preset_raises(primary_monitor):
    with pytest.raises(ValueError, match="Unknown preset"):
        _resolve_single(
            {"type": "preset", "name": "does-not-exist", "monitor": 0},
            {0: primary_monitor},
        )


def test_resolve_unknown_type_raises(primary_monitor):
    with pytest.raises(ValueError, match="Unknown layout spec type"):
        _resolve_single(
            {"type": "spiral", "monitor": 0},
            {0: primary_monitor},
        )


def test_resolve_missing_type_key_raises_helpful_error(primary_monitor):
    # Regression: the agent sent {"preset": "three-columns"} (no "type" key)
    # and got "Unknown layout spec type: ''", which was misleading.
    with pytest.raises(ValueError, match="missing the required key 'type'"):
        _resolve_single(
            {"preset": "three-columns"},
            {0: primary_monitor},
        )


def test_resolve_empty_type_raises_helpful_error(primary_monitor):
    with pytest.raises(ValueError, match="missing the required key 'type'"):
        _resolve_single(
            {"type": "", "name": "two-columns"},
            {0: primary_monitor},
        )


def test_resolve_non_dict_raises(primary_monitor):
    with pytest.raises(ValueError, match="must be a dict"):
        _resolve_single("three-columns", {0: primary_monitor})  # type: ignore[arg-type]


def test_resolve_unknown_monitor_raises(primary_monitor):
    with pytest.raises(ValueError, match="Monitor 99 unknown"):
        _resolve_single(
            {"type": "preset", "name": "two-columns", "monitor": 99},
            {0: primary_monitor},
        )


def test_resolve_single_columns_negative_split_raises(primary_monitor):
    with pytest.raises(ValueError):
        _resolve_single(
            {"type": "columns", "monitor": 0, "splits": [-10, 110]},
            {0: primary_monitor},
        )


# --- find_slot ---------------------------------------------------------------


def _slot(slot_id, monitor=0):
    return {"slot_id": slot_id, "monitor": monitor, "bounds": {"x": 0, "y": 0, "w": 10, "h": 10}}


def test_find_slot_happy():
    slots = [_slot("left"), _slot("right")]
    assert find_slot(slots, "left") == slots[0]


def test_find_slot_filters_by_monitor():
    slots = [_slot("left", 0), _slot("left", 1)]
    assert find_slot(slots, "left", monitor=1)["monitor"] == 1


def test_find_slot_missing_raises():
    with pytest.raises(KeyError):
        find_slot([_slot("right")], "left")


# --- remember_layout / lookup_slot -------------------------------------------


def test_lookup_slot_desktop_scoped():
    # Reset module-level state.
    layouts._LAST_LAYOUT.clear()
    layouts._GLOBAL_LAST = []
    a = [_slot("left")]
    b = [_slot("right")]
    remember_layout("guid-A", a)
    remember_layout("guid-B", b)
    assert lookup_slot("left", desktop_guid="guid-A") == a[0]
    assert lookup_slot("right", desktop_guid="guid-B") == b[0]
    # Cross-desktop miss falls back to global (last write wins → b).
    assert lookup_slot("right", desktop_guid="guid-A") == b[0]


def test_lookup_slot_global_fallback():
    layouts._LAST_LAYOUT.clear()
    layouts._GLOBAL_LAST = []
    slots = [_slot("main")]
    remember_layout(None, slots)
    assert lookup_slot("main") == slots[0]


def test_lookup_slot_returns_none_when_missing():
    layouts._LAST_LAYOUT.clear()
    layouts._GLOBAL_LAST = []
    assert lookup_slot("nope") is None


# --- preset catalog smoke ----------------------------------------------------


def test_every_preset_produces_valid_slots():
    """Every named preset should produce at least one slot with the required keys."""
    for name, builder in PRESETS.items():
        slots = builder()
        assert slots, f"preset {name!r} produced no slots"
        for s in slots:
            assert {"slot_id", "x_pct", "y_pct", "w_pct", "h_pct"} <= s.keys()
