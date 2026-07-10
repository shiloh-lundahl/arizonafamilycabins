"""
Availability calendar — fetches each cabin's Airbnb iCal (.ics) export feed,
parses the booked/blocked date ranges, and caches the result in memory.

Airbnb exposes a per-listing iCal export URL (the same "sync calendar" link you
paste into VRBO). Set these as environment variables:

    AIRBNB_ICAL_PARKWAY = https://www.airbnb.com/calendar/ical/<id>.ics?s=<secret>
    AIRBNB_ICAL_MOHAVE  = https://www.airbnb.com/calendar/ical/<id>.ics?s=<secret>

The .ics feed contains one VEVENT per reservation/block:
    DTSTART;VALUE=DATE:20260710   <- check-in day
    DTEND;VALUE=DATE:20260715     <- check-out day (exclusive; that night is free)

A "booked night" is any date d with start <= d < end. The check-out day itself
is available for a new check-in (same-day turnover).
"""

import os
import time
import requests
from datetime import date, datetime, timedelta

# slug -> env var holding that cabin's Airbnb iCal export URL
CABIN_ICAL_ENV = {
    "parkway-lodge": "AIRBNB_ICAL_PARKWAY",
    "mohave-cabin-treehouse": "AIRBNB_ICAL_MOHAVE",
}

_CACHE = {}            # slug -> {"fetched": epoch, "nights": set[str], "ranges": list}
_TTL_SECONDS = 3 * 3600  # refresh at most every 3 hours


def _parse_ical_date(value):
    """Parse an iCal DATE or DATE-TIME value into a date()."""
    value = value.strip()
    # DATE form: 20260715
    if len(value) == 8 and value.isdigit():
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    # DATE-TIME form: 20260715T110000Z
    if "T" in value:
        d = value.split("T", 1)[0]
        if len(d) == 8 and d.isdigit():
            return date(int(d[0:4]), int(d[4:6]), int(d[6:8]))
    return None


def _parse_events(ics_text):
    """Return a list of (start_date, end_date, summary) from raw iCal text."""
    events = []
    start = end = summary = None
    in_event = False
    for raw in ics_text.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            start = end = summary = None
        elif line == "END:VEVENT":
            if start and end:
                events.append((start, end, summary or "Reserved"))
            in_event = False
        elif in_event:
            if line.startswith("DTSTART"):
                start = _parse_ical_date(line.split(":", 1)[-1])
            elif line.startswith("DTEND"):
                end = _parse_ical_date(line.split(":", 1)[-1])
            elif line.startswith("SUMMARY"):
                summary = line.split(":", 1)[-1]
    return events


def _compute(ics_text):
    """Build the set of booked-night ISO strings + the raw ranges."""
    events = _parse_events(ics_text)
    nights = set()
    ranges = []
    for start, end, summary in events:
        ranges.append({"start": start.isoformat(), "end": end.isoformat(), "summary": summary})
        d = start
        while d < end:
            nights.add(d.isoformat())
            d += timedelta(days=1)
    return nights, ranges


def get_availability(slug, force=False):
    """
    Return {"available": bool, "configured": bool, "nights": [...], "ranges": [...],
            "updated": iso, "error": str|None} for a cabin slug.
    'nights' = list of ISO dates that are booked (unavailable to stay overnight).
    """
    env_key = CABIN_ICAL_ENV.get(slug)
    if not env_key:
        return {"configured": False, "error": "unknown cabin", "nights": [], "ranges": []}

    url = os.environ.get(env_key)
    if not url:
        return {"configured": False, "error": None, "nights": [], "ranges": []}

    cached = _CACHE.get(slug)
    if cached and not force and (time.time() - cached["fetched"] < _TTL_SECONDS):
        return {
            "configured": True,
            "nights": sorted(cached["nights"]),
            "ranges": cached["ranges"],
            "updated": cached["updated"],
            "error": None,
        }

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "ArizonaFamilyCabins/1.0"})
        resp.raise_for_status()
        nights, ranges = _compute(resp.text)
        updated = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        _CACHE[slug] = {"fetched": time.time(), "nights": nights, "ranges": ranges, "updated": updated}
        return {"configured": True, "nights": sorted(nights), "ranges": ranges, "updated": updated, "error": None}
    except Exception as e:
        # Serve stale cache if we have it; otherwise report the error
        if cached:
            return {
                "configured": True,
                "nights": sorted(cached["nights"]),
                "ranges": cached["ranges"],
                "updated": cached["updated"],
                "error": None,
                "stale": True,
            }
        return {"configured": True, "nights": [], "ranges": [], "error": str(e)}
