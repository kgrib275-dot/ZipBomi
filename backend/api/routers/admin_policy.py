"""관리 > 현행 수치 — 항목 값·기준일·근거 고치기, 게시/초안 전환, 바뀐 이력 (pipeline/policy.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import policy

router = APIRouter(prefix="/admin/policy", tags=["admin-policy"], dependencies=[Depends(require_admin)])


@router.get("")
def list_params() -> dict:
    policy.refresh_auto()
    return {"items": policy.all_params(include_draft=True), "groups": policy.GROUPS}


@router.get("/{key}/history")
def param_history(key: str) -> dict:
    return {"items": policy.history(key)}


@router.put("/{key}")
def save_param(key: str, request: Request, body: dict[str, Any]) -> dict:
    try:
        row = policy.update(key, body)
    except KeyError:
        raise HTTPException(404, "없는 항목입니다")
    except ValueError as e:
        raise HTTPException(400, str(e))
    from api.common import cached_set
    from api.routers.now import _now
    cached_set("now", _now())  # 공개 화면에 바로 반영
    log_action(request, "현행 수치 수정", f"{row['label']} → {row['value'] if row['value'] is not None else row['value_text']} ({row['status']})")
    return {"item": row}
