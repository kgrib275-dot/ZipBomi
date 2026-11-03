"""관리자 접속기록 (/api/admin/audit…, 2026-11-03 ISMS-P 2.9.4 · 안전성 확보조치 기준 제8조).

- GET  /admin/audit          최근 접속기록 (종류·검색어로 거르기)
- GET  /admin/audit/verify   해시 사슬 검사 — 기록을 고치거나 지웠는지 (월 1회 이상 점검)
- POST /admin/audit/event    화면에서 일어난 개인정보 다운로드·전체 보기를 사유와 함께 남긴다
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from api.deps import _client_ip, require_admin
from pipeline import admin_auth

router = APIRouter(prefix="/admin", tags=["admin-audit"], dependencies=[Depends(require_admin)])
_KINDS = {"download": "개인정보 다운로드", "reveal": "개인정보 전체 보기"}


@router.get("/audit")
def audit_list(limit: int = 300, kind: str = "", q: str = "") -> dict:
    return {"rows": admin_auth.recent(limit, kind[:20], q[:100]), "keep_days": admin_auth.AUDIT_KEEP_DAYS}


@router.get("/audit/verify")
def audit_verify(request: Request) -> dict:
    res = admin_auth.verify()
    admin_auth.audit(getattr(request.state, "admin_actor", "-"), _client_ip(request)[0], "GET", "/api/admin/audit/verify", 200,
                     kind="audit_check", detail=f"검사 결과 {'정상' if res['ok'] else '불일치'} · {res['rows']}건")
    return res


@router.post("/audit/event")
def audit_event(request: Request, payload: dict = Body(...)) -> dict:
    kind = payload.get("kind")
    reason = str(payload.get("reason") or "").strip()
    target = str(payload.get("target") or "")[:120]
    count = payload.get("count")
    if kind not in _KINDS:
        raise HTTPException(status_code=400, detail="알 수 없는 기록 종류입니다.")
    if len(reason) < 4:
        raise HTTPException(status_code=400, detail="사유를 4자 이상 적어 주세요.")
    detail = f"{_KINDS[kind]} · 대상 {target}" + (f" · {int(count)}건" if isinstance(count, int) else "") + f" · 사유: {reason[:200]}"
    admin_auth.audit(getattr(request.state, "admin_actor", "-"), _client_ip(request)[0], "POST", "/api/admin/audit/event", 200,
                     kind=kind, detail=detail)
    return {"ok": True}
