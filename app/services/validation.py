# app/services/validation.py
from __future__ import annotations
from fastapi import HTTPException
from typing import Dict, Any, Iterable
from ..spec.apisports_map import APISPORTS_SPEC

def _missing(required: Iterable[str], params: Dict[str, Any]) -> list[str]:
    return [k for k in required if (params.get(k) is None or params.get(k) == "")]

def validate_params(league: str, op: str, **params: Any) -> None:
    """Raises 422 if the call violates the provider contract in APISPORTS_SPEC."""
    spec = APISPORTS_SPEC.get(league)
    if not spec:
        raise HTTPException(status_code=422, detail={"message": f"Unsupported league '{league}'"})
    ops = spec["ops"]
    if op not in ops:
        raise HTTPException(status_code=422, detail={"message": f"Unsupported operation '{op}' for {league}"})

    required = ops[op]["required"]
    optional = set(ops[op]["optional"])
    missing = _missing(required, params)

    if missing:
        raise HTTPException(status_code=422, detail={
            "message": f"Missing required params for {league}.{op}",
            "required": required,
            "missing": missing,
        })

    # Hard reject unknown params—helps catch typos early.
    allowed = set(required) | optional
    unknown = [k for k in params.keys() if k not in allowed]
    if unknown:
        raise HTTPException(status_code=422, detail={
            "message": f"Unknown params for {league}.{op}",
            "unknown": unknown,
            "allowed": sorted(allowed),
        })
