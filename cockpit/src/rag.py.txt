"""
RAG status for metrics and confidence levels for predictions.

Every metric the cockpit shows carries a Red / Amber / Green reading against
an explicit threshold, and every forward-looking number carries a confidence
level with the basis it was derived from. Both are plain dicts so they survive
``st.cache_data`` and render the same way wherever they appear.
"""

import html
import math

GREEN = "GREEN"
AMBER = "AMBER"
RED = "RED"

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# Probability bands for the confidence levels.
HIGH_CONFIDENCE_FROM = 0.70
MEDIUM_CONFIDENCE_FROM = 0.45


# ------------------------------------------------------------------
# RAG
# ------------------------------------------------------------------

def rag(value, green, red, higher_is_better=True, unit="", precision=1):
    """
    Classify ``value`` against a green threshold and a red threshold.

    For a higher-is-better metric the reading is green at or above ``green``,
    red below ``red`` and amber in between; the comparisons flip when lower is
    better. The rule travels with the status so the reader can see why.
    """
    value = float(value)

    if higher_is_better:
        status = GREEN if value >= green else RED if value < red else AMBER
        rule = f"Green ≥ {green:,.{precision}f}{unit} · Red < {red:,.{precision}f}{unit}"
    else:
        status = GREEN if value <= green else RED if value > red else AMBER
        rule = f"Green ≤ {green:,.{precision}f}{unit} · Red > {red:,.{precision}f}{unit}"

    return {"status": status, "rule": rule}


def rag_from_status(status, rule):
    """A RAG reading whose status is set by a categorical rule."""
    return {"status": status, "rule": rule}


def rag_badge(reading):
    """Compact pill for a card or tile."""
    status = reading["status"]
    return (
        f'<span class="rag-badge rag-{status.lower()}" '
        f'title="{html.escape(reading["rule"], quote=True)}">'
        f'<span class="rag-dot"></span>RAG · {status.title()}</span>'
    )


def rag_line(reading):
    """Status plus its threshold, for the Why / Impact / Next readings."""
    status = reading["status"]
    return (
        f'<span class="rag-badge rag-{status.lower()}"><span class="rag-dot"></span>'
        f'{status.title()}</span>'
        f'<span class="rag-rule">{html.escape(reading["rule"])}</span>'
    )


# ------------------------------------------------------------------
# Confidence
# ------------------------------------------------------------------

def _level(probability):
    # Judged on the whole percent the badge shows, so "70%" never reads Medium.
    shown = round(probability * 100.0)
    if shown >= HIGH_CONFIDENCE_FROM * 100:
        return HIGH
    if shown >= MEDIUM_CONFIDENCE_FROM * 100:
        return MEDIUM
    return LOW


def confidence_within(sigma, tolerance, tolerance_text):
    """
    Probability that the outcome lands within ``±tolerance`` of the projection.

    ``sigma`` is the standard deviation of the projection error. The error is
    treated as normal, so the probability is ``erf(tol / (sigma * √2))``.
    """
    sigma = abs(float(sigma))
    probability = 1.0 if sigma == 0 else math.erf(tolerance / (sigma * math.sqrt(2)))
    return {
        "level": _level(probability),
        "pct": probability * 100.0,
        "basis": f"Probability the outcome lands within {tolerance_text}",
    }


def confidence_probability(probability, basis):
    """A confidence reading from an already computed probability (0–1)."""
    probability = max(0.0, min(1.0, float(probability)))
    return {"level": _level(probability), "pct": probability * 100.0, "basis": basis}


def confidence_fixed(level, basis):
    """A confidence reading set by method rather than by a probability."""
    return {"level": level, "pct": None, "basis": basis}


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def confidence_label(reading):
    pct = "" if reading["pct"] is None else f" {reading['pct']:.0f}%"
    return f"{reading['level'].title()}{pct}"


def confidence_badge(reading, with_basis=False):
    """Compact pill for a prediction; the basis sits in the tooltip or below."""
    level = reading["level"]
    basis = html.escape(reading["basis"])
    badge = (
        f'<span class="conf-badge conf-{level.lower()}" title="{basis}">'
        f'<span class="conf-bars"><i></i><i></i><i></i></span>'
        f'Confidence · {confidence_label(reading)}</span>'
    )
    if with_basis:
        badge += f'<span class="conf-basis">{basis}</span>'
    return badge
