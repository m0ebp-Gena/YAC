"""Convert supported radios' raw signal meters into compact S reports.

The curves follow Hamlib's published backend calibration points. They are
approximations for each radio family; individual radios and conditions vary.
"""

from __future__ import annotations

from collections.abc import Sequence


# Raw CAT/CI-V value -> dB relative to S9.
# Hamlib applies its measured FT-991-derived default curve to the FT-DX10.
YAESU_FTDX10_CALIBRATION: tuple[tuple[int, float], ...] = (
    (0, -54), (26, -42), (51, -30), (81, -18), (105, -9), (130, 0),
    (157, 12), (186, 25), (203, 35), (237, 50), (255, 60),
)

# Hamlib uses its IC-7300 signal curve for the IC-705. The IC-705 CI-V guide
# specifies raw 241 as S9+60 dB, so use that documented endpoint here.
ICOM_IC705_CALIBRATION: tuple[tuple[int, float], ...] = (
    (0, -54), (10, -48), (30, -36), (60, -24), (90, -12), (120, 0),
    (241, 60),
)

# Hamlib's FTX-1-specific calibration table, based on its SM CAT response.
YAESU_FTX1_CALIBRATION: tuple[tuple[int, float], ...] = (
    (0, -54), (12, -48), (27, -42), (40, -36), (55, -30), (65, -24),
    (80, -18), (95, -12), (112, -6), (130, 0), (150, 10), (172, 20),
    (190, 30), (220, 40), (240, 50), (255, 60),
)

CALIBRATIONS: dict[str, Sequence[tuple[int, float]]] = {
    "0761": YAESU_FTDX10_CALIBRATION,
    "0840": YAESU_FTX1_CALIBRATION,
    "ic-705": ICOM_IC705_CALIBRATION,
    # Both 7300 manuals specify the same S9/S9+60 raw endpoints.
    # Reuse the Icom curve as an approximation, pending hardware calibration.
    "ic-7300": ICOM_IC705_CALIBRATION,
    "ic-7300mk2": ICOM_IC705_CALIBRATION,
}


def _interpolate_db(raw: int, points: Sequence[tuple[int, float]]) -> float:
    """Interpolate the calibrated dB value, clamping to table endpoints."""
    if raw <= points[0][0]:
        return points[0][1]
    if raw >= points[-1][0]:
        return points[-1][1]
    for (raw_low, db_low), (raw_high, db_high) in zip(points, points[1:]):
        if raw <= raw_high:
            proportion = (raw - raw_low) / (raw_high - raw_low)
            return db_low + proportion * (db_high - db_low)
    return points[-1][1]


def format_s_meter(raw: int, model_id: str) -> str:
    """Return a short S-meter label, preserving raw values for unknown models.

    Below S9, report the nearest whole S unit using 6 dB per unit. Above S9,
    report dB above S9 as commonly spoken (for example, ``S9+12``).
    """
    points = CALIBRATIONS.get(model_id.casefold())
    if points is None or not 0 <= raw <= 255:
        return f"S {raw}"

    db_relative_to_s9 = _interpolate_db(raw, points)
    if db_relative_to_s9 <= 0:
        s_units = max(0, min(9, int(9 + db_relative_to_s9 / 6 + 0.5)))
        return f"S {s_units}"

    return f"S 9+{int(db_relative_to_s9 + 0.5)}"
