# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created timefilters.py: NY-timezone anchoring, killzone checks, news
#     blackout/news-day rules, midnight-open baseline, premium/discount label.
# WHY: The strategy's temporal rules (killzones, NFP/FOMC/CPI blackout,
#      news-day requirement, midnight-open premium/discount) must live in one
#      deterministic module so fvg/context/engine never re-implement them.
"""
Temporal rules for the ICT multi-timeframe FVG execution engine.

Every rule is anchored to America/New_York via zoneinfo, per the strategy
brief: killzones are NY-clock windows, the NFP/FOMC/CPI blackout is absolute
minutes around the release, and NY 00:00 is the daily premium/discount
baseline.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import config

NY = ZoneInfo(config.NY_TZ)

# A news "event" is a (datetime, name) pair. The datetime may be naive
# (assumed UTC) or tz-aware; to_ny() normalizes either.
NewsEvent = Tuple[datetime, str]


def to_ny(dt: datetime) -> datetime:
    """Convert a datetime to America/New_York time.

    Strategy rule: "Everything uses tz-aware America/New_York datetimes."
    Naive datetimes are assumed to be UTC before conversion; aware datetimes
    are converted by absolute instant.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NY)


def _parse_hhmm(text: str) -> time:
    """Parse a "HH:MM" config string into a wall-clock time."""
    hh, mm = text.split(":")
    return time(int(hh), int(mm))


def _enabled_windows(enabled: Optional[Iterable[str]]) -> list:
    """Resolve (name, start, end) windows for the enabled killzone names.

    Iterates config.KILLZONES in definition order so current_killzone() is
    deterministic; unknown names are ignored.
    """
    names = config.DEFAULT_ENABLED_KILLZONES if enabled is None else enabled
    wanted = set(names)
    windows = []
    for name, (start, end) in config.KILLZONES.items():
        if name in wanted:
            windows.append((name, _parse_hhmm(start), _parse_hhmm(end)))
    return windows


def current_killzone(dt: datetime, enabled: Optional[Iterable[str]] = None) -> Optional[str]:
    """Return the name of the enabled killzone containing dt, else None.

    Strategy rule: killzones are NY-clock windows — London 01:00-05:00,
    NY AM 07:00-11:00, NY PM 12:30-15:00 — start-inclusive, end-exclusive,
    same-day only (no window crosses midnight). `enabled` defaults to
    config.DEFAULT_ENABLED_KILLZONES (london + ny_am).
    """
    clock = to_ny(dt).time()
    for name, start, end in _enabled_windows(enabled):
        if start <= clock < end:
            return name
    return None


def in_killzone(dt: datetime, enabled: Optional[Iterable[str]] = None) -> bool:
    """True when dt falls inside any enabled killzone window (NY time).

    Implements the same rule as current_killzone(); see its docstring.
    """
    return current_killzone(dt, enabled=enabled) is not None


def _is_blocked_event(name: str) -> bool:
    """Case-insensitive substring match against config.BLOCKED_NEWS_EVENTS."""
    lowered = name.lower()
    return any(token.lower() in lowered for token in config.BLOCKED_NEWS_EVENTS)


def is_news_blackout(dt: datetime, events: Sequence[NewsEvent]) -> bool:
    """True when dt is within the hard no-trade window of a blocked release.

    Strategy rule: NEVER trade within config.NEWS_BLACKOUT_MINUTES (30)
    before or after an NFP/FOMC/CPI release. Event names match by
    case-insensitive substring ("CPI m/m", "FOMC Statement", ...). The
    window boundary itself counts as blacked out (exactly 30 minutes away
    is still inside the window).
    """
    moment = to_ny(dt)
    window = timedelta(minutes=config.NEWS_BLACKOUT_MINUTES)
    for event_dt, name in events:
        if not _is_blocked_event(name):
            continue
        if abs(moment - to_ny(event_dt)) <= window:
            return True
    return False


def has_high_impact_news_today(dt: datetime, events: Sequence[NewsEvent]) -> bool:
    """True when a high-impact news event lands on dt's NY calendar day.

    Strategy rule: intraday trades additionally require a high-impact news
    event somewhere on that day. "Day" is the America/New_York calendar day,
    not a 24h rolling window and not the UTC date.  Only events whose name
    contains one of config.HIGH_IMPACT_NEWS_KEYWORDS or config.BLOCKED_NEWS_EVENTS
    count.
    """
    day = to_ny(dt).date()
    keywords = config.HIGH_IMPACT_NEWS_KEYWORDS + config.BLOCKED_NEWS_EVENTS
    lowered = tuple(k.lower() for k in keywords)
    for event_dt, name in events:
        if to_ny(event_dt).date() != day:
            continue
        n = name.lower()
        if any(k in n for k in lowered):
            return True
    return False


def midnight_open(candles) -> Optional[float]:
    """Open price of the first candle at/after NY 00:00 of the most recent
    NY day present in `candles`; None for an empty list.

    Strategy rule: midnight open (NY 00:00) is the daily premium/discount
    baseline. Candle timestamps may be naive (assumed UTC) or aware in any
    zone; they are normalized to NY before the day is determined. "Most
    recent NY day" is the maximum NY calendar date in the list, so a list
    spanning several days yields today's baseline, not yesterday's.

    Optimized: scans backwards from the latest candle because the current
    NY day's first print is always near the end of a chronological list.
    """
    if not candles:
        return None
    latest = to_ny(candles[-1].ts).date()
    # Walk backwards to find the first candle whose NY date is earlier than
    # the latest day.  The candle immediately after it is the day's first print.
    first_of_day = candles[-1]
    for c in reversed(candles):
        if to_ny(c.ts).date() != latest:
            break
        first_of_day = c
    return first_of_day.open


def premium_discount(price: float, midnight: float) -> str:
    """Label price relative to the midnight-open baseline.

    Strategy rule: buys are favored below the midnight open ("discount"),
    sells above it ("premium"). Returns 'discount', 'premium', or 'at'
    when price equals the baseline exactly.
    """
    if price < midnight:
        return "discount"
    if price > midnight:
        return "premium"
    return "at"
