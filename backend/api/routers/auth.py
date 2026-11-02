"""메일 링크 로그인 (/api/auth/*) — 2026-11-02. 계정 구조는 pipeline/accounts.py.

- request: 주소로 로그인 링크를 보낸다. 있는 계정인지 응답으로 드러내지 않는다(항상 같은 응답, 메일은 백그라운드).
- verify: 링크 토큰을 쓰고 이 브라우저 쿠키를 계정 쿠키로 바꿔 심는다. 이 브라우저에 쌓인 값은 계정 쪽에 합친다.
- logout: 새 익명 쿠키로 바꾼다 (계정 자료는 그대로).
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Body, HTTPException, Request, Response

from api.deps import COOKIE, COOKIE_MAX_AGE, Caller, CallerDep, throttle
from api.routers import me as me_state
from api.routers.subscribe import _email, _mask, _may_mail, send_later
from pipeline import accounts, db, email_check, engage, gate, mailer

router = APIRouter(tags=["auth"])
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
# 합칠 때 목록은 두 쪽을 합치고(중복 제거), 나머지는 계정 쪽 값이 있으면 그대로 둔다
_LIST_KEYS = {"re_watch", "apply_fav", "note_bm", "calc_saves"}


def _set_cookie(request: Request, response: Response, c: Caller, raw: str) -> None:
    response.set_cookie(COOKIE, engage.sign_cookie(raw), max_age=COOKIE_MAX_AGE, samesite="lax", httponly=True,
                        secure=request.url.scheme == "https" or c.proxied, path="/")


def _merge(into_visitor: str, from_visitor: str) -> None:
    """이 브라우저(from)에 쌓인 값을 계정(into)에 합친다."""
    src = me_state.load_state(from_visitor)
    if not src:
        return
    dst = me_state.load_state(into_visitor)
    changes: dict = {}
    for k, v in src.items():
        if k in _LIST_KEYS and isinstance(v, list):
            have = dst.get(k) if isinstance(dst.get(k), list) else []
            seen = {repr(x) for x in have}
            merged = have + [x for x in v if repr(x) not in seen]
            if merged != have:
                changes[k] = merged[:100]
        elif k == "profile" and isinstance(v, dict):
            changes[k] = {**v, **(dst.get(k) or {})}  # 계정에 이미 있는 항목이 우선
        elif k not in dst:
            changes[k] = v
    if changes:
        try:
            me_state.save_state(into_visitor, changes)
        except me_state.StateTooBig:  # 합치면 한도를 넘는 경우 — 계정 쪽 값을 그대로 두고 로그인은 계속한다
            pass


NONCE_COOKIE = "zgl"  # 로그인 링크를 요청한 브라우저 표시 (HttpOnly, 30분) — 같은 브라우저면 코드 없이 확정


@router.post("/auth/request")
def request_link(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    email = _email(payload.get("email"))
    throttle("login_try", c, per_visitor=5, per_ip=30)
    bad = email_check.problem(email, typo_ok=payload.get("typo_ok") is True)
    if bad:
        raise HTTPException(status_code=400, detail=bad)
    if not mailer.is_configured():
        raise HTTPException(status_code=503, detail="지금은 로그인 메일을 보낼 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if _may_mail(email, "login_mail", "로그인 메일", gap_min=1, per_day=10, own_day=True):  # 휴대폰·PC 연달아 로그인할 수 있게
        token, code, nonce = accounts.new_link(email)
        response.set_cookie(NONCE_COOKIE, nonce, max_age=accounts.LINK_MINUTES * 60, samesite="lax", httponly=True,
                            secure=request.url.scheme == "https" or c.proxied, path="/api/auth")
        send_later(mailer.send_login_link, email, token, code)
    return {"ok": True, "message": f"{_mask(email)} 으로 로그인 링크를 보냈습니다. 30분 안에 메일의 버튼을 눌러 주세요. "
                                   "다른 기기에서 열면 메일에 적힌 6자리 확인 코드를 함께 넣어야 해요. 메일이 안 보이면 스팸함도 확인해 주세요."}


@router.post("/auth/verify")
def verify(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    t, code = payload.get("t"), payload.get("code")
    if not isinstance(t, str) or not _TOKEN_RE.match(t):
        raise HTTPException(status_code=400, detail="링크가 올바르지 않습니다.")
    if code is not None and not (isinstance(code, str) and re.fullmatch(r"\d{6}", code)):
        raise HTTPException(status_code=400, detail="확인 코드는 숫자 6자리입니다.")
    throttle("login_verify", c, per_visitor=10, per_ip=60)
    email, res = accounts.use_link(t, request.cookies.get(NONCE_COOKIE), code)
    if res == "need_code":
        raise HTTPException(status_code=401, detail={"message": "링크를 요청한 기기가 아니에요. 메일에 적힌 6자리 확인 코드를 넣어 주세요.", "need_code": True})
    if res == "bad_code":
        raise HTTPException(status_code=401, detail={"message": "확인 코드가 맞지 않습니다. 다시 확인해 주세요.", "need_code": True})
    if not email:
        raise HTTPException(status_code=400, detail="링크가 만료됐거나 이미 사용됐습니다. 다시 로그인해 주세요.")
    acc, new, revoke = accounts.login(email, c.raw)
    gate.forget(c.raw); gate.forget(acc["raw"])
    target = "c:" + acc["raw"]
    if target != c.visitor:
        _merge(target, c.visitor)
        _set_cookie(request, response, c, acc["raw"])
    response.delete_cookie(NONCE_COOKIE, path="/api/auth")
    # 같은 주소로 구독 중이면 이 계정과 잇는다 (알림 메일·질문하기 횟수가 계정을 따라오게)
    db.set_subscriber_visitor(email, target)
    # 로그인 알림 메일 — 본인이 아니면 메일의 '모든 기기에서 로그아웃'으로 끊는다
    send_later(mailer.send_login_notice, email, revoke, (request.headers.get("user-agent") or "")[:120])
    return {"ok": True, "email": _mask(email), "new": new}


@router.post("/auth/logout")
def logout(request: Request, response: Response, c: Caller = CallerDep) -> dict:
    gate.forget(c.raw)
    _set_cookie(request, response, c, uuid.uuid4().hex)
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(request: Request, response: Response, c: Caller = CallerDep) -> dict:
    """모든 기기에서 로그아웃 (내 공간 버튼) — 계정 식별값을 새로 바꾸고 이 브라우저에만 새 값을 심는다."""
    acc = accounts.by_raw(c.raw)
    if not acc:
        raise HTTPException(status_code=400, detail="로그인 상태가 아닙니다.")
    _set_cookie(request, response, c, accounts.rotate(acc))
    return {"ok": True}


@router.post("/auth/revoke")
def revoke(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """로그인 알림 메일의 '내가 아니에요 — 모든 기기에서 로그아웃'. 링크를 연 브라우저도 익명으로 둔다."""
    r = payload.get("r")
    if not isinstance(r, str) or not _TOKEN_RE.match(r):
        raise HTTPException(status_code=400, detail="링크가 올바르지 않습니다.")
    throttle("login_revoke", c, per_visitor=10, per_ip=30)
    acc = accounts.by_revoke(r)
    if not acc:
        raise HTTPException(status_code=400, detail="이미 처리됐거나 만료된 링크입니다.")
    accounts.rotate(acc)
    _set_cookie(request, response, c, uuid.uuid4().hex)
    return {"ok": True, "message": "모든 기기에서 로그아웃했습니다. 본인이 다시 로그인하면 저장한 내용은 그대로 보입니다."}
