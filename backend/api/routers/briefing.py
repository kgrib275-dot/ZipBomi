"""오늘의 내 브리핑 (2026-11-20) — GET /api/me/briefing. 홈 맨 위 카드. 로그인 없이도 이 브라우저의 저장값으로 만든다. 로직은 pipeline/briefing.py."""
from __future__ import annotations

from fastapi import APIRouter

from api.deps import Caller, CallerDep
from api.routers import me as me_state
from pipeline import briefing

router = APIRouter(tags=["briefing"])


@router.get("/me/briefing")
def my_briefing(c: Caller = CallerDep) -> dict:
    return briefing.build(me_state.load_state(c.visitor))
