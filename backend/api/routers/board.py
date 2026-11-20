"""함께 보기 링크 만들기·멈추기 (2026-11-20) — /api/me/board. 읽기 전용 공개 페이지는 app/board_page.py(/g/<토큰>), 저장·보관은 pipeline/board.py.

- GET    상태(켜짐·만료일·열람 수·무엇을 보여 주는지) — 링크 주소는 돌려주지 않는다(해시만 저장)
- POST   새 링크 {include:["apts","notices"]} — 주소는 이 응답에서만 보여 준다. 예전 링크는 멈춘다
- DELETE 멈추기
로그인 없이도 이 브라우저(방문자) 단위로 쓸 수 있다.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Request

from api.deps import Caller, CallerDep, throttle
from pipeline import board, mailer

router = APIRouter(tags=["board"])


@router.get("/me/board")
def board_status(c: Caller = CallerDep) -> dict:
    st = board.status(c.visitor)
    return {"on": bool(st), **(st or {})}


@router.post("/me/board")
def board_create(request: Request, payload: dict = Body(default={}), c: Caller = CallerDep) -> dict:
    throttle("board_create", c, per_visitor=10, per_ip=30)
    inc = payload.get("include") if isinstance(payload, dict) else None
    token = board.create(c.visitor, [x for x in (inc or []) if isinstance(x, str)])
    base = (mailer.site_url() or str(request.base_url)).rstrip("/")
    return {"on": True, "url": f"{base}/g/{token}", "include": (board.status(c.visitor) or {}).get("include", []), "expires_at": (board.status(c.visitor) or {}).get("expires_at")}


@router.delete("/me/board")
def board_stop(c: Caller = CallerDep) -> dict:
    board.stop(c.visitor)
    return {"on": False}
