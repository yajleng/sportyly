from __future__ import annotations
from typing import Dict, Any, List, Tuple
from statistics import mean

def _team_points(g: Dict[str, Any], home: bool) -> Tuple[int, int]:
    # v1 families
    sc = g.get("scores") or g.get("score") or {}
    h, a = sc.get("home"), sc.get("away")
    def pick(x): 
        if isinstance(x, dict): return x.get("total")
        return x
    hs, as_ = pick(h), pick(a)
    return (hs or 0, as_ or 0) if home else (as_ or 0, hs or 0)

def compute_efficiency(games: List[Dict[str, Any]], team_name: str) -> Dict[str, float]:
    """
    Simple rolling efficiency:
      OffEff = mean(points_for)
      DefEff = mean(points_against)
      Net    = OffEff - DefEff
    """
    pf, pa = [], []
    for g in games:
        teams = g.get("teams") or {}
        h = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
        a = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
        if not (h and a): 
            continue
        if team_name == h:
            f, ag = _team_points(g, home=True)
            pf.append(f); pa.append(ag)
        elif team_name == a:
            f, ag = _team_points(g, home=False)
            pf.append(f); pa.append(ag)
    if not pf:
        return {"off": 0.0, "def": 0.0, "net": 0.0}
    off = float(mean(pf))
    de = float(mean(pa))
    return {"off": round(off, 2), "def": round(de, 2), "net": round(off - de, 2)}
