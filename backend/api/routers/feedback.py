"""사용자 피드백 받기 (2026-11-19) — POST /api/feedback. 보미AI 답변 👍👎·오류 신고. 저장·보관 범위는 pipeline/feedback.py."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import Caller, CallerDep, throttle
from pipeline import feedback

router = APIRouter(tags=["feedback"])


class In(BaseModel):
    kind: str = Field(max_length=12)
    page: str = Field("", max_length=120)
    text: str = Field("", max_length=600)
    extra: str = Field("", max_length=1200)


@router.post("/feedback")
def post_feedback(body: In, c: Caller = CallerDep) -> dict:
    if body.kind not in feedback.KINDS:
        raise HTTPException(400, "종류가 올바르지 않습니다.")
    throttle("feedback", c, per_visitor=20, per_ip=60)
    if body.kind == "data" and len(body.text.strip()) < 2:
        raise HTTPException(400, "무엇이 이상한지 한두 줄로 적어 주세요.")
    feedback.add(body.kind, c.visitor, body.page, body.text.strip(), body.extra.strip())
    return {"ok": True}
