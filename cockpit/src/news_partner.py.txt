import json
import re
from pathlib import Path

from src.openai_partner import generate_prompt_response

_FIXTURES_PATH = Path(__file__).parent.parent / "data" / "news_fixtures.json"

_VALID_ENGINE_PARAMS = {
    "rate_shock_bps",
    "deposit_outflow_pct",
    "stage_2_increase_pct_points",
    "stage_3_increase_pct_points",
}

_SANE_BOUNDS = {
    "rate_shock_bps": (-500, 500),
    "deposit_outflow_pct": (0.0, 50.0),
    "stage_2_increase_pct_points": (0.0, 30.0),
    "stage_3_increase_pct_points": (0.0, 15.0),
}

_SYSTEM_PROMPT = """\
You extract structured, quantitative financial signals from news articles for a bank risk cockpit. You NEVER invent numbers, entities, or dates -- every value must be explicitly present in the article text. If the article contains no quantitative signal that maps to a supported type, return {"signals": []}.

Supported signal types and their engine mapping:

rate_change -> rate_shock_bps (integer basis points). A hike is POSITIVE, a cut is NEGATIVE. "raises rates by 25bps" -> value 25. "cuts 50bps" -> value -50.
deposit_shift -> deposit_outflow_pct (float, % of deposits). Outflow/withdrawal is POSITIVE. The engine models outflow only -- if the article describes deposit inflow/growth, classify it as macro (flag only), engine_param null.
credit_migration -> stage_2_increase_pct_points or stage_3_increase_pct_points (float, percentage points). Credit deterioration is POSITIVE (more defaults/downgrades). Use stage_3 for defaults/NPLs, stage_2 for watchlist/underperforming. Credit improvement -> classify as macro, engine_param null.
macro (GDP, inflation, unemployment, or any signal with no engine lever) -> engine_param null, value null. These are informational only.

Rules:

Use only facts stated in the article. No external knowledge, no estimates.
value must be in the engine unit shown above, with the correct sign.
confidence (0-1) reflects how clearly the article states a concrete, quantified, actionable figure.
quote must be a verbatim snippet of 15 words or fewer supporting the signal.
One article may yield multiple signals or none. Return valid JSON only, no prose.\
"""


def load_articles() -> list[dict]:
    with _FIXTURES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _default_generate(prompt: str) -> str:
    return generate_prompt_response(prompt)


def _validate_signal(signal: dict) -> bool:
    engine_param = signal.get("engine_param")
    if engine_param is None:
        return True
    if engine_param not in _VALID_ENGINE_PARAMS:
        return False
    value = signal.get("value")
    if value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    lo, hi = _SANE_BOUNDS[engine_param]
    return lo <= v <= hi


def extract_signals(article: dict, generate_fn=None) -> list[dict]:
    if generate_fn is None:
        generate_fn = _default_generate

    article_text = (
        f"Headline: {article['headline']}\n"
        f"Published: {article['published']}\n"
        f"Source: {article['source']}\n\n"
        f"{article['body']}"
    )

    prompt = f"{_SYSTEM_PROMPT}\n\nArticle:\n{article_text}"
    raw = generate_fn(prompt).strip()

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0].strip()

    if not raw.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw = m.group(0)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON for article {article['id']!r}: {exc}") from exc

    signals = parsed.get("signals", [])
    return [s for s in signals if _validate_signal(s)]


def signal_to_scenario_kwargs(signal: dict) -> dict:
    engine_param = signal.get("engine_param")
    value = signal.get("value")

    if not engine_param or value is None:
        return {}

    if engine_param == "rate_shock_bps":
        return {"rate_shock_bps": int(value)}
    if engine_param == "deposit_outflow_pct":
        return {"deposit_outflow_pct": float(value)}
    if engine_param == "stage_2_increase_pct_points":
        return {"stage_2_increase_pct_points": float(value)}
    if engine_param == "stage_3_increase_pct_points":
        return {"stage_3_increase_pct_points": float(value)}

    return {}


if __name__ == "__main__":
    import sys

    articles = load_articles()
    print(f"Loaded {len(articles)} articles.")

    for article in articles:
        print(f"\nArticle: [{article['id']}] {article['headline']}")
        try:
            signals = extract_signals(article)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue

        if not signals:
            print("  (no actionable signals extracted)")
        else:
            for i, sig in enumerate(signals, 1):
                kwargs = signal_to_scenario_kwargs(sig)
                print(f"  Signal {i}: {sig.get('signal_type')} -> {kwargs}")