# app/services/odds.py
from __future__ import annotations
from typing import Any, Dict, Optional

"""
Normalize API-SPORTS odds payloads into a compact, consistent structure
we can use for moneyline, spread, totals, half totals, and quarter totals.

API-SPORTS varies a bit by sport/bookmaker:
- basketball & american-football (v1) often: bookmakers -> bets -> values
- football/soccer (v3) often: bookmakers -> markets -> outcomes
We try both shapes and fall back gracefully if a market isn't present.
"""

MarketOut = Dict[str, Optional[float]]  # {"home_price":..., "away_price":..., "line":...} or O/U
NormalizedOdds = Dict[str, Optional[Dict[str, Any]]]

def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    # accept plain ints/floats or strings like "+110", "-105", "2.5"
    try:
        if s.startswith("+") and s[1:].isdigit():
            return float(s[1:])
        if s.startswith("-") and s[1:].isdigit():
            return float(s)
        return float(s)
    except Exception:
        return None

def _first_book(payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = payload.get("response") or []
    if not resp:
        return {}
    row = resp[0]
    # try typical keys
    books = row.get("bookmakers") or row.get("odds") or []
    return books[0] if books else {}

def _iter_markets(book: Dict[str, Any]):
    # v1 style
    for m in book.get("bets", []) or []:
        yield m
    # v3 style
    for m in book.get("markets", []) or []:
        yield m

def _name_lower(m: Dict[str, Any]) -> str:
    return (m.get("name") or m.get("key") or "").lower()

def _find_market(book: Dict[str, Any], candidates: list[str]) -> Optional[Dict[str, Any]]:
    cl = [c.lower() for c in candidates]
    for m in _iter_markets(book):
        n = _name_lower(m)
        if any(c in n for c in cl):
            return m
    return None

def _iter_outcomes(m: Dict[str, Any]):
    # v1 often: values; v3 often: outcomes
    vals = m.get("values")
    if isinstance(vals, list) and vals:
        for o in vals:
            yield o
    outs = m.get("outcomes")
    if isinstance(outs, list) and outs:
        for o in outs:
            yield o

def _extract_handicap(o: Dict[str, Any]) -> Optional[float]:
    for k in ("handicap", "point", "total", "line", "value"):
        v = o.get(k)
        fv = _to_float(v)
        if fv is not None:
            return fv
    return None

def _extract_price(o: Dict[str, Any]) -> Optional[float]:
    for k in ("odd", "price", "american"):
        v = o.get(k)
        fv = _to_float(v)
        if fv is not None:
            return fv
    # some books use "decimal"; we keep as float but caller can convert if needed
    for k in ("decimal",):
        v = o.get(k)
        try:
            return float(v)
        except Exception:
            pass
    return None

def _normalize_ml(m: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    if not m:
        return None
    out: Dict[str, Optional[float]] = {"home_price": None, "away_price": None}
    for o in _iter_outcomes(m):
        name = (o.get("name") or o.get("label") or "").lower()
        p = _extract_price(o)
        if "home" in name or name in ("1", "team 1"):
            out["home_price"] = p
        elif "away" in name or name in ("2", "team 2"):
            out["away_price"] = p
        elif "draw" in name or name == "x":
            # ML for draw in soccer (three-way). Store as separate key.
            out["draw_price"] = p  # type: ignore
    if all(v is None for v in out.values()):
        return None
    return out

def _normalize_spread(m: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    if not m:
        return None
    out: Dict[str, Optional[float]] = {"home_line": None, "home_price": None, "away_line": None, "away_price": None}
    for o in _iter_outcomes(m):
        name = (o.get("name") or o.get("label") or "").lower()
        p = _extract_price(o)
        h = _extract_handicap(o)
        if "home" in name or name in ("1", "team 1"):
            out["home_line"], out["home_price"] = h, p
        elif "away" in name or name in ("2", "team 2"):
            out["away_line"], out["away_price"] = h, p
    if all(v is None for v in out.values()):
        return None
    return out

def _normalize_total(m: Dict[str, Any]) -> Optional[Dict[str, Optional[float]]]:
    if not m:
        return None
    out: Dict[str, Optional[float]] = {"total": None, "over_price": None, "under_price": None}
    for o in _iter_outcomes(m):
        name = (o.get("name") or o.get("label") or "").lower()
        p = _extract_price(o)
        h = _extract_handicap(o)
        if "over" in name:
            out["total"] = out["total"] if out["total"] is not None else h
            out["over_price"] = p
        elif "under" in name:
            out["total"] = out["total"] if out["total"] is not None else h
            out["under_price"] = p
    if all(v is None for v in out.values()):
        return None
    return out

def normalize_odds(odds_payload: Dict[str, Any]) -> NormalizedOdds:
    """
    Returns:
    {
      "moneyline": {"home_price": -120, "away_price": +105, "draw_price": +260?},
      "spread": {"home_line": -3.5, "home_price": -110, "away_line": +3.5, "away_price": -110},
      "total": {"total": 224.5, "over_price": -110, "under_price": -110},
      "half_total": {...} | None,
      "quarter_total": {...} | None
    }
    Missing markets => None.
    """
    book = _first_book(odds_payload)
    if not book:
        return {
            "moneyline": None,
            "spread": None,
            "total": None,
            "half_total": None,
            "quarter_total": None,
        }

    # Map likely market names for each target
    ml = _find_market(book, ["moneyline", "match winner", "winner"])
    sp = _find_market(book, ["spread", "handicap"])
    tot = _find_market(book, ["total", "over/under", "over under"])

    # Period markets (will exist only when book provides them)
    htot = _find_market(book, [
        "1st half total", "first half total", "half - total", "half total", "1h total"
    ])
    qtot = _find_market(book, [
        "1st quarter total", "first quarter total", "quarter total", "1q total"
    ])

    return {
        "moneyline": _normalize_ml(ml),
        "spread": _normalize_spread(sp),
        "total": _normalize_total(tot),
        "half_total": _normalize_total(htot),
        "quarter_total": _normalize_total(qtot),
    }
