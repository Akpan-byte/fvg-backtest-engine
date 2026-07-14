# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created central config: killzones, news rules, timeframe matrix, risk.
# WHY: Every numeric rule from the strategy brief lives here exactly once so
#      modules never hard-code their own variants.
"""
Central configuration — every constant traces to a stated strategy rule.
"""
from __future__ import annotations

NY_TZ = "America/New_York"

# --- Killzones (New York time). Indicator "ICT Everything @coldbrewrosh"
# screenshot had LONDON + NY checked; NY PM exists in the plan and stays
# available but disabled by default.
KILLZONES = {
    "london": ("01:00", "05:00"),
    "ny_am": ("07:00", "11:00"),
    "ny_pm": ("12:30", "15:00"),
}
DEFAULT_ENABLED_KILLZONES = ("london", "ny_am")

# --- News rules -----------------------------------------------------------
# NEVER trade prior to or during NFP, FOMC, or CPI.
BLOCKED_NEWS_EVENTS = ("NFP", "FOMC", "CPI")
NEWS_BLACKOUT_MINUTES = 30  # hard block window before/after the release
# Intraday entries "demand high impact news on the day" (currency pairs).
HIGH_IMPACT_NEWS_KEYWORDS = (
    "NFP",
    "FOMC",
    "CPI",
    "Interest Rate",
    "Non-Farm",
    "PMI",
    "GDP",
    "Retail Sales",
    "Unemployment",
)
REQUIRE_NEWS_DAY_FOR_INTRADAY = True

# --- Risk / reward ---------------------------------------------------------
RR = 2.0                    # fixed 1:2 target, no trailing, no partials
RISK_DIVISORS = {"passive": 20, "aggressive": 10}

# --- Timeframe matrix (context timeframe -> allowed entry timeframes) ------
# Monthly->D/H4, Weekly->H4/H1, Daily->H1/M15, H4->M15/M5, H1->M5/M1, M15->M1
TIMEFRAME_MATRIX = {
    "M": ("D", "H4"),
    "W": ("H4", "H1"),
    "D": ("H1", "M15"),
    "H4": ("M15", "M5"),
    "H1": ("M5", "M1"),
    "M15": ("M1",),
}

# Context timeframes by asset class. Currencies: M/W/D (never H4 context).
# Indices & gold: H4 may serve as context too.
CONTEXT_TFS_FOREX = ("M", "W", "D")
CONTEXT_TFS_INDEX = ("M", "W", "D", "H4")

# PD-array (reaction zone) timeframes.
PDA_TFS_INTRADAY = ("D", "H4", "H1")
PDA_TFS_SWING = ("H4", "H1")

# Entry timeframes.
ENTRY_TFS_INTRADAY = ("M15", "M5", "M1")
ENTRY_TFS_SWING = ("H4", "H1")
# Currencies: H1 and/or H4 for PDA and entry — no M15/M5/M1. End of story.
ENTRY_TFS_FOREX = ("H4", "H1")

# Order of timeframes from highest to lowest, for "consequent timeframe"
# lookups (breakaway gap -> zoom to next lower timeframe for an FVG).
TF_ORDER = ("M", "W", "D", "H4", "H1", "M15", "M5", "M1")

# Breakaway-gap strength: third candle must close within this fraction of
# its own range from the extreme (0.30 = close in top/bottom 30% of range).
BAG_CLOSE_STRENGTH = 0.30

# Timeframes on which a BAG is traded directly; above M5 the strategy zooms
# to the consequent timeframe and looks for a plain FVG instead.
BAG_DIRECT_TFS = ("M5", "M1")
