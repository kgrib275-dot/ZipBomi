"""현행 수치 (/api/now) — 대출 규제·금리·세금·청약 숫자 (pipeline/policy.py). 게시된 항목만, 기준일·근거 링크와 함께."""
from __future__ import annotations

from fastapi import APIRouter

from api.common import cached
from pipeline import policy

router = APIRouter(tags=["now"])


@router.get("/now")
def now() -> dict:
    return cached("now", _now, 300)  # 모든 방문자가 5분 나눠 쓴다 — 관리자 수정 때는 admin_policy 가 비운다


def _now() -> dict:
    params = policy.all_params()
    for p in params:
        p["notes"] = policy.notes_for(p["key"])
    groups = [{"name": g, "items": [p for p in params if p["grp"] == g]} for g in policy.GROUPS]
    return {"groups": [g for g in groups if g["items"]], "changed_days": policy.CHANGED_DAYS}
