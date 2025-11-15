# app/services/odds.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import re

# Optional: if you later want id-based mapping or name hints, these are available.
# The module works fine without them present (we guard imports).
try:
    from ..spec.apisports_map import MAP as _MAP, NAME_FALLBACKS as _NAME_FALLBACKS, PERIOD_HINTS as _PERIOD_HINTS, PROP_FALLBACKS as _PROP_FALLBACKS
except Exception:  # pragma: no cover - run-time optional
    _MAP = {}                 # type: ignore[assignment]
    _NAME_FALLBACKS = {}      # type: ignore[assignment]
    _PERIOD_HINTS = {}        # type: ignore[assignment]
    _PROP_FALLBACKS = {}      # type: ignore[assignment]


# -------------------------------
# Public API
# -------------------------------
def normalize_odds(
    payload: Dict[str, Any],
    preferred_bookmaker_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize API-Sports odds into a compact, league-agnostic shape:

    {
      "moneyline":   {"home": float|None, "away": float|None, "draw": float|None},
      "spread":      {"line": float|None, "home_price": float|None, "away_price": float|None} | None,
      "total":       {"line": float|None, "over_price": float|None, "under_price": float|None} | None,
      "half_total":  {"line": float|None, "over_price": float|None, "under_price": float|None} | None,
      "quarter_total":{"line": float|None, "over_price": float|None, "under_price": float|None} | None,
      "props":       { <prop_key>: [ {player, line, over_price, under_price}, ... ] }
    }

    Works for:
      - Soccer (API-Football v3): usually 1X2, O/U, Asian Handicap
      - NFL/NCAAF/NBA/NCAAB (v1): Moneyline, Spreads, Totals (+ some props)

    Notes:
      • We select one bookmaker: preferred_bookmaker_id if available, else the first with bets.
      • We classify by id (if map present) and by market names as fallback.
      • American odds are returned as numeric (e.g., -110.0, 100.0).
    """
    # Default scaffold
    empty = {
        "moneyline": None,
        "spread": None,
        "total": None,
        "half_total": None,
        "quarter_total": None,
        "props": {},
    }

    resp = payload.get("response")
    if not isinstance(resp, list) or not resp:
        return empty

    node = resp[0] or {}
    books: List[dict] = node.get("bookmakers") or []

    book = _pick_bookmaker(books, preferred_bookmaker_id)
    if not book:
        return empty

    out = dict(empty)  # copy

    for bet in (book.get("bets") or []):
        alias = _detect_alias(bet) or ""  # "moneyline" | "spread" | "total" | ""
        period = _detect_period(bet)

        # Normalize core markets
        if alias == "moneyline":
            ml = _map_moneyline(bet)
            if ml is not None:
                out["moneyline"] = ml

        elif alias == "spread":
            sp = _map_spread(bet)
            if sp is not None:
                # (spreads are always game-level in our structure)
                out["spread"] = sp

        elif alias == "total":
            tot = _map_total(bet)
            if tot is not None:
                if period == "game":
                    out["total"] = tot
                elif period in ("1h", "2h"):
                    out["half_total"] = tot
                elif period.endswith("q"):
                    out["quarter_total"] = tot

        else:
            # Try props via name-based classification (if hints provided)
            _maybe_attach_prop(out, bet)

    return out


# -------------------------------
# Internals (helpers)
# -------------------------------
def _pick_bookmaker(bookmakers: List[dict], preferred_id: Optional[int]) -> Optional[dict]:
    if not bookmakers:
        return None
    if preferred_id is not None:
        for bm in bookmakers:
            try:
                if int(bm.get("id")) == int(preferred_id):
                    return bm
            except Exception:
                pass
    for bm in bookmakers:
        if bm.get("bets"):
            return bm
    return bookmakers[0] if bookmakers else None


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _contains_any(hay: str, needles: List[str]) -> bool:
    h = hay.lower()
    return any(n in h for n in needles)


def _extract_line(text: str) -> Optional[float]:
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


def _bet_name(bet: Dict[str, Any]) -> str:
    return str(bet.get("name") or "").strip()


def _detect_alias(bet: Dict[str, Any]) -> Optional[str]:
    """Try id-based classification first (if MAP present), then fall back to names."""
    bid = str(bet.get("id") or "").strip()
    name = _bet_name(bet).lower()

    # Try id-based lookup across leagues if available
    if bid and _MAP:
        for _league, conf in _MAP.items():
            if bid in (conf.get("bets") or {}):
                alias = (conf["bets"][bid] or {}).get("alias")
                if alias:
                    return alias

    # Name fallbacks
    if _NAME_FALLBACKS:
        for alias, keys in _NAME_FALLBACKS.items():
            if _contains_any(name, [k.lower() for k in keys]):
                return alias

    # Heuristic generic fallback
    if "moneyline" in name or name in {"1x2", "match odds", "match result"}:
        return "moneyline"
    if "handicap" in name or "spread" in name:
        return "spread"
    if "total" in name or "over/under" in name or "goals over/under" in name:
        return "total"
    return None


def _detect_period(bet: Dict[str, Any]) -> str:
    """Infer period from name using hints; default to 'game'."""
    name = _bet_name(bet).lower()
    if _PERIOD_HINTS:
        for p, hints in _PERIOD_HINTS.items():
            if _contains_any(name, [h.lower() for h in hints]):
                return p
    # Simple heuristics
    if "first half" in name or "1h" in name:
        return "1h"
    if "second half" in name or "2h" in name:
        return "2h"
    if "quarter" in name:
        # try to pick 1q..4q if present
        for tag in ("1q", "2q", "3q", "4q"):
            if tag in name:
                return tag
        return "1q"
    return "game"


# -------------------------------
# Mappers for specific markets
# -------------------------------
def _map_moneyline(bet: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    """
    Supports both 2-way (home/away) and 3-way (home/away/draw or 1/X/2)
    """
    values = bet.get("values") or []
    if not values:
        return None
    row = {"home": None, "away": None, "draw": None}

    for v in values:
        label = str(v.get("value") or "").lower()
        price = _to_float(v.get("odd"))
        if "home" in label or label == "1":
            row["home"] = price
        elif "away" in label or label == "2":
            row["away"] = price
        elif "draw" in label or label in {"x"}:
            row["draw"] = price

    # If nothing captured, some books put team names in value
    if row["home"] is None and row["away"] is None and row["draw"] is None:
        for v in values:
            label = str(v.get("value") or "").lower()
            price = _to_float(v.get("odd"))
            # crude fallback: first two entries become home/away
            if row["home"] is None:
                row["home"] = price
            elif row["away"] is None:
                row["away"] = price
            elif "draw" in label:
                row["draw"] = price

    return row


def _map_spread(bet: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    """
    Typical values:
      {"value":"Home -3.5","odd":"-110"} / {"value":"Away +3.5","odd":"-110"}
    Asian Handicap often appears similarly with 'Home -1.0' / 'Away +1.0'.
    """
    values = bet.get("values") or []
    if not values:
        return None

    agg = {"line": None, "home_price": None, "away_price": None}

    for v in values:
        val = str(v.get("value") or "").lower()
        odd = _to_float(v.get("odd"))
        # prefer explicit handicap if present (soccer)
        line = _to_float(v.get("handicap")) or _extract_line(val)
        if "home" in val or val == "1":
            agg["line"] = agg["line"] if agg["line"] is not None else line
            agg["home_price"] = odd
        elif "away" in val or val == "2":
            agg["line"] = agg["line"] if agg["line"] is not None else line
            agg["away_price"] = odd

    # If still no line, pick the first available numeric from any value
    if agg["line"] is None:
        for v in values:
            line = _to_float(v.get("handicap")) or _extract_line(str(v.get("value") or ""))
            if line is not None:
                agg["line"] = line
                break

    return agg


def _map_total(bet: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    """
    Values like:
      {"value":"Over 46.5","odd":"-110"} / {"value":"Under 46.5","odd":"-110"}
      or soccer style with 'handicap' carrying the line.
    """
    values = bet.get("values") or []
    if not values:
        return None

    agg = {"line": None, "over_price": None, "under_price": None}

    for v in values:
        val = str(v.get("value") or "").lower()
        odd = _to_float(v.get("odd"))
        line = _to_float(v.get("handicap")) or _extract_line(val)

        if "over" in val:
            agg["line"] = line
            agg["over_price"] = odd
        elif "under" in val:
            agg["line"] = line
            agg["under_price"] = odd

    # If line still None, take the first numeric we can find
    if agg["line"] is None:
        for v in values:
            line = _to_float(v.get("handicap")) or _extract_line(str(v.get("value") or ""))
            if line is not None:
                agg["line"] = line
                break

    return agg


def _maybe_attach_prop(out: Dict[str, Any], bet: Dict[str, Any]) -> None:
    """Attach player/team props into out['props'] using fallback name patterns."""
    if not _PROP_FALLBACKS:
        return

    name = _bet_name(bet).lower()
    values = bet.get("values") or []
    for prop_key, hints in _PROP_FALLBACKS.items():
        if _contains_any(name, [h.lower() for h in hints]):
            bucket: List[Dict[str, Any]] = out["props"].setdefault(prop_key, [])
            for v in values:
                entry = {
                    "player": v.get("player") or v.get("name"),
                    "line": _to_float(v.get("handicap")) or _extract_line(str(v.get("value") or "")),
                }
                # Assign prices based on "Over/Under" in value label when present
                label = str(v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                if "over" in label:
                    entry["over_price"] = price
                if "under" in label:
                    entry["under_price"] = price
                # If neither Over/Under appears (some books), just store raw price
                if "over_price" not in entry and "under_price" not in entry:
                    entry["price"] = price
                bucket.append(entry)
            break
