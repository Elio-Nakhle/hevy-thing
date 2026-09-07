"""Weight display units.

Everything in this project - the database, the analytics, the API - is in
kilograms. ``units`` only ever changes how a number is *shown*, so conversion
belongs at the point text is produced: the insight prose here, and the
``useUnits`` composable in the frontend. A converted value must never be fed
back into a calculation.
"""

from __future__ import annotations

from typing import Literal

Units = Literal["kg", "lb"]

LB_PER_KG = 2.2046226218


def convert(value_kg: float, units: Units) -> float:
    """A kilogram value in the given display unit."""
    return value_kg * LB_PER_KG if units == "lb" else value_kg


def fmt(value_kg: float, units: Units, digits: int = 1, *, thousands: bool = False) -> str:
    """A kilogram value as display text with its unit: "82.5 kg" / "181.9 lb"."""
    value = convert(value_kg, units)
    number = f"{value:,.{digits}f}" if thousands else f"{value:.{digits}f}"
    return f"{number} {units}"
