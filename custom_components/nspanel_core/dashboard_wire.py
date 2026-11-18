"""NSPanel Core — dashboard wire format (pure, host-testable).

HA state → the sanitized dash statement for one item. The object names
here MUST match the generator's layout (dashboard_design: b<slot>, l<slot>).
"""

from __future__ import annotations

from . import dashboard_design as dd


def _num(value: str) -> str | None:
    v = value.strip()
    return v if v.replace(".", "", 1).replace("-", "", 1).isdigit() else None


def item_statement(item: dd.DashItem, state) -> str | None:
    """The dash statement mirroring |state| for |item| ("" → no send)."""
    obj = f"b{item.slot}"
    st = (state.state or "").lower()
    if item.widget in ("switch", "light", "rgb_light"):
        if st in ("on", "off"):
            return f"{obj}.val={1 if st == 'on' else 0}"
        return None
    if item.widget == "climate":
        temp = state.attributes.get("current_temperature")
        if temp is not None:
            return f'{obj}.txt="{dd.clean_text(str(temp), 8)}"'
        return None
    if item.widget == "sensor":
        value = str(state.state)
        if value in ("unknown", "unavailable", "none"):
            return None
        unit = state.attributes.get("unit_of_measurement") or ""
        return f'{obj}.txt="{dd.clean_text(value + unit, 32)}"'
    return None  # scene items carry no state
