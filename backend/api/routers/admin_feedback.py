"""관리 > 피드백 (2026-11-19) — 보미AI 👎·오류 신고 목록과 처리 표시. 관리자만 (require_admin)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import feedback

router = APIRouter(prefix="/admin", tags=["admin-feedback"], dependencies=[Depends(require_admin)])


@router.get("/feedback")
def listing(kind: str = "", status: str = "") -> dict:
    return {"counts": feedback.counts(), "items": feedback.listing(kind if kind in feedback.KINDS else "", status if status in ("open", "done") else "")}


@router.post("/feedback/{fid}/status")
def set_status(fid: int, request: Request, payload: dict = Body(...)) -> dict:
    feedback.set_status(fid, "done" if payload.get("done") else "open")
    log_action(request, "피드백 처리", f"#{fid}")
    return {"ok": True}


@router.delete("/feedback/{fid}")
def delete(fid: int, request: Request) -> dict:
    feedback.delete(fid)
    log_action(request, "피드백 삭제", f"#{fid}")
    return {"ok": True}
