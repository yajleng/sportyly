# app/services/odds.py
from __future__ import annotations

from typing import Any, Dict, Optional


def _pick_bookmaker(bookmakers: list[dict], preferred_id: Optional[int]) -> Optional[dict]:
    if not bookmakers:
        return None
    if preferred_id:
        for bm in bookmakers:
            if bm.get("id") == preferred_id:
                return bm
    # fallback: first bookmaker with bets
    for bm in bookmakers:
        if bm.get("bets"):
            return bm
    return bookmakers[0]


def _soccer_map(bm: dict) -> dict:
    """
    API-Football v3 structure:
      response: [
        {
          "bookmakers": [
            {
              "id": ...,
              "name": "...",
              "bets": [
                {"id": ..., "name": "Match Winner", "values": [{"value":"Home","odd":"1.90"}, ...]},
                {"name":"Over/Under", "values":[{"value":"Over 2.5","odd":"1.95","handicap":"2.5"}, {"value":"Under 2.5","odd":"1.85","handicap":"2.5"}]},
                {"name":"Asian Handicap", "values":[{"value":"Home -1.0","odd":"1.96","handicap":"-1.0"}, {"value":"Away +1.0","odd":"1.86","handicap":"+1.0"}]},
                ...
              ]
            }
          ]
        }
      ]
    """
    out = {
        "moneyline": None,
        "spread": None,
        "total": None,
        "half_total": None,
        "quarter_total": None,
    }

    bets = bm.get("bets") or []

    # Moneyline (3-way)
    for b in bets:
        name = (b.get("name") or "").lower()
        if name in {"match winner", "1x2", "3way result", "full time result"}:
            ml = {"home": None, "away": None, "draw": None}
            for v in b.get("values") or []:
                val = (v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                if "home" in val or val == "1":
                    ml["home"] = price
                elif "away" in val or val == "2":
                    ml["away"] = price
                elif "draw" in val or val in {"x", "draw"}:
                    ml["draw"] = price
            out["moneyline"] = ml
            break

    # Over/Under totals (full game)
    for b in bets:
        name = (b.get("name") or "").lower()
        if name in {"over/under", "goals over/under", "total"}:
            # Pick common handicap (first)
            best_line = None
            over = under = None
            for v in b.get("values") or []:
                line = v.get("handicap")
                price = _to_float(v.get("odd"))
                label = (v.get("value") or "").lower()
                # parse lines like 'Over 2.5'
                if best_line is None and line is not None:
                    best_line = _to_float(line)
                if "over" in label:
                    over = price
                elif "under" in label:
                    under = price
            if best_line is not None:
                out["total"] = {"line": best_line, "over": over, "under": under}
            break

    # Asian Handicap (treat as primary spread)
    for b in bets:
        name = (b.get("name") or "").lower()
        if name in {"asian handicap", "handicap", "spread"}:
            home = away = None
            home_line = away_line = None
            for v in b.get("values") or []:
                label = (v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                line = _to_float(v.get("handicap"))
                if label.startswith("home") or "home" in label or label.startswith("1"):
                    home = price
                    home_line = line
                elif label.startswith("away") or "away" in label or label.startswith("2"):
                    away = price
                    away_line = line
            # prefer a single symmetric line if possible
            line = home_line if home_line is not None else away_line
            out["spread"] = {
                "line": line,
                "home_price": home,
                "away_price": away,
            }
            break

    return out


def _af_map(bm: dict) -> dict:
    """
    American Football (NFL/NCAAF) structure under v1.american-football:
      response: [
        {
          "bookmakers":[
            {"name":"...", "bets":[
                {"name":"Moneyline","values":[{"value":"Home","odd":"-110"}, {"value":"Away","odd":"+100"}]},
                {"name":"Spreads","values":[{"value":"Home","odd":"-110","handicap":"-3.5"}, {"value":"Away","odd":"-110","handicap":"+3.5"}]},
                {"name":"Totals","values":[{"value":"Over","odd":"-105","handicap":"47.5"},{"value":"Under","odd":"-115","handicap":"47.5"}]}
            ] }
          ]
        }
      ]
    """
    out = {
        "moneyline": None,
        "spread": None,
        "total": None,
        "half_total": None,
        "quarter_total": None,
    }

    bets = bm.get("bets") or []

    # Moneyline
    for b in bets:
        if (b.get("name") or "").lower() in {"moneyline", "ml"}:
            ml = {"home": None, "away": None}
            for v in b.get("values") or []:
                label = (v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                if "home" in label:
                    ml["home"] = price
                elif "away" in label:
                    ml["away"] = price
            out["moneyline"] = ml
            break

    # Spreads
    for b in bets:
        if (b.get("name") or "").lower() in {"spread", "spreads", "handicap"}:
            home = away = None
            line = None
            for v in b.get("values") or []:
                label = (v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                line = line or _to_float(v.get("handicap"))
                if "home" in label:
                    home = price
                elif "away" in label:
                    away = price
            if line is not None:
                out["spread"] = {"line": line, "home_price": home, "away_price": away}
            break

    # Totals
    for b in bets:
        if (b.get("name") or "").lower() in {"total", "totals", "over/under"}:
            over = under = None
            line = None
            for v in b.get("values") or []:
                label = (v.get("value") or "").lower()
                price = _to_float(v.get("odd"))
                line = line or _to_float(v.get("handicap"))
                if "over" in label:
                    over = price
                elif "under" in label:
                    under = price
            if line is not None:
                out["total"] = {"line": line, "over": over, "under": under}
            break

    return out


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).replace("+", ""))  # keep American style numeric if present
    except Exception:
        return None


def normalize_odds(payload: Dict[str, Any], preferred_bookmaker_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Returns a unified odds dict:
      {
        "moneyline": {"home": float, "away": float, "draw": float|None},
        "spread": {"line": float, "home_price": float, "away_price": float}|None,
        "total": {"line": float, "over": float, "under": float}|None,
        "half_total": None,
        "quarter_total": None
      }
    """
    resp = payload.get("response")
    if not isinstance(resp, list) or not resp:
        return {
            "moneyline": None,
            "spread": None,
            "total": None,
            "half_total": None,
            "quarter_total": None,
        }

    node = resp[0]  # we’ll use the first fixture payload
    bookmakers = node.get("bookmakers") or []
    bm = _pick_bookmaker(bookmakers, preferred_bookmaker_id)
    if not bm:
        return {
            "moneyline": None,
            "spread": None,
            "total": None,
            "half_total": None,
            "quarter_total": None,
        }

    # Detect sport by presence of soccer keys (safe inference)
    # Soccer payloads include team/league/fixture objects elsewhere, but we rely on market names:
    names = { (bet.get("name") or "").lower() for bet in (bm.get("bets") or []) }
    if {"match winner", "over/under"} & names or "asian handicap" in names:
        return _soccer_map(bm)
    else:
        return _af_map(bm)
