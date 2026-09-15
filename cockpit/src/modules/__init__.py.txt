"""One renderer per cockpit section; each opens as a window over the home page."""

from src.modules.brief import render_brief
from src.modules.copilot import render_copilot
from src.modules.horizon import render_horizon
from src.modules.news import render_news
from src.modules.peers import render_peers
from src.modules.scenario import render_scenario
from src.modules.strategy import render_strategy
from src.modules.treasury import render_treasury

# Maps the ``module`` query parameter to its renderer. "home" has no renderer:
# it is the page the windows open over.
RENDERERS = {
    "brief": render_brief,
    "horizon": render_horizon,
    "scenario": render_scenario,
    "treasury": render_treasury,
    "peers": render_peers,
    "strategy": render_strategy,
    "news": render_news,
    "copilot": render_copilot,
}

# Window title and the one-line description under it.
MODULE_METADATA = {
    "home": (
        "CFO overview",
        "Current state, changes and next investigations",
    ),
    "brief": (
        "Morning Brief",
        "What changed, why it matters and what to investigate next",
    ),
    "horizon": (
        "Horizon",
        "Deterministic run-rate outlook from the certified actuals",
    ),
    "scenario": (
        "What-If Engine",
        "Governed balance-sheet shock simulation",
    ),
    "copilot": (
        "CFO Copilot",
        "Conversational investigation over governed finance data",
    ),
    "treasury": (
        "Treasury",
        "Portfolio sensitivity, scenario impacts and hedge alternatives",
    ),
    "peers": (
        "Peers",
        "Directional European peer positioning and performance comparison",
    ),
    "strategy": (
        "Opportunity",
        "Strategic opportunity radar and capability-gap intelligence",
    ),
    "news": (
        "News",
        "Overnight external developments and their potential bank impact",
    ),
}

__all__ = ["RENDERERS", "MODULE_METADATA"]
