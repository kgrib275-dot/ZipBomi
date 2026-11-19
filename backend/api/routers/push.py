"""웹 푸시 알림 (2026-11-19) — 로그인 계정이 이 기기를 알림 받는 기기로 등록·해제한다. 보내기는 pipeline/reminders.py 가 맡는다.

- GET  /api/me/push        공개키와 등록 수 (이 기기가 등록돼 있는지는 ?endpoint= 로 물어본다)
- POST /api/me/push        기기 등록 {endpoint, keys:{p256dh, auth}}
- POST /api/me/push/off    기기 해제 {endpoint}
- POST /api/me/push/test   시험 알림 한 건 (30초에 한 번)
로그인 계정만. 로직은 pipeline/webpush.py.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import Caller, CallerDep
from pipeline import accounts, webpush

router = APIRouter(tags=["push"])
_last_test: dict[int, float] = {}


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class Sub(BaseModel):
    endpoint: str = Field(max_length=600)
    keys: Keys


class Off(BaseModel):
    endpoint: str = Field(max_length=600)


def _acc(c: Caller) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    if not a:
        raise HTTPException(401, "메일로 로그인한 계정에서만 쓸 수 있어요.")
    return a


@router.get("/me/push")
def status(endpoint: str = "", c: Caller = CallerDep) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    if not a:
        return {"account": False}
    return {"account": True, "key": webpush.public_key(), "count": webpush.count(a["id"]), "here": bool(endpoint) and webpush.has(a["id"], endpoint)}


@router.post("/me/push")
def subscribe(body: Sub, request: Request, c: Caller = CallerDep) -> dict:
    a = _acc(c)
    if not webpush.add(a["id"], body.endpoint, body.keys.p256dh, body.keys.auth, request.headers.get("user-agent", "")):
        raise HTTPException(400, "이 기기는 알림을 받을 수 없는 형태예요.")
    return {"ok": True, "count": webpush.count(a["id"])}


@router.post("/me/push/off")
def unsubscribe(body: Off, c: Caller = CallerDep) -> dict:
    a = _acc(c)
    webpush.remove(a["id"], body.endpoint)
    return {"ok": True, "count": webpush.count(a["id"])}


@router.post("/me/push/test")
def test(c: Caller = CallerDep) -> dict:
    a = _acc(c)
    now = time.time()
    if now - _last_test.get(a["id"], 0) < 30:
        raise HTTPException(429, "잠시 뒤에 다시 눌러 주세요.")
    _last_test[a["id"]] = now
    return {"sent": webpush.send_account(a["id"], "집보미 알림 시험", "이 기기로 알림이 잘 와요.", "/my", "zipbomi-test")}
