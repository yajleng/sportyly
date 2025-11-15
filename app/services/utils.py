from __future__ import annotations

def lc_in(s: str, needles: list[str]) -> bool:
    s = s.lower()
    return any(n in s for n in needles)
