from django.conf import settings

from .models import WellBaseline


def percentile_rank(value: float, baseline: WellBaseline) -> float:
    pts = [
        (baseline.p5, 0.05),
        (baseline.p10, 0.10),
        (baseline.p25, 0.25),
        (baseline.p50, 0.50),
        (baseline.p75, 0.75),
        (baseline.p90, 0.90),
        (baseline.p95, 0.95),
    ]
    if value <= pts[0][0]:
        return 0.0
    if value >= pts[-1][0]:
        return 1.0
    for i in range(len(pts) - 1):
        lo_val, lo_pct = pts[i]
        hi_val, hi_pct = pts[i + 1]
        if lo_val <= value <= hi_val:
            if hi_val == lo_val:
                return lo_pct
            return lo_pct + (hi_pct - lo_pct) * (value - lo_val) / (hi_val - lo_val)
    return 0.5


def classify(percentile: float, thresholds: dict) -> str:
    from .models import Classification

    if percentile < thresholds["very_low"]:
        return Classification.VERY_LOW
    if percentile < thresholds["low"]:
        return Classification.LOW
    if percentile < thresholds["normal"]:
        return Classification.NORMAL
    if percentile < thresholds["high"]:
        return Classification.HIGH
    return Classification.VERY_HIGH


def classify_value(value: float, baseline: WellBaseline) -> tuple[str, float]:
    thresholds = getattr(
        settings,
        "SGI_THRESHOLDS",
        {"very_low": 0.10, "low": 0.25, "normal": 0.75, "high": 0.90},
    )
    pct = percentile_rank(value, baseline)
    return classify(pct, thresholds), pct
