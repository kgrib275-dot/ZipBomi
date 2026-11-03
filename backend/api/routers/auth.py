"""메일 링크 로그인 (/api/auth/*) — 2026-11-02. 계정 구조는 pipeline/accounts.py.

- request: 주소로 로그인 링크·코드를 보낸다. 있는 계정인지 응답으로 드러내지 않는다(항상 같은 응답, 메일은 백그라운드).
- verify: 링크 토큰으로 확정. verify-code: 로그인 창에 메일의 6자리 코드를 바로 넣어 확정 (2026-11-03, 요청한 브라우저에서만).
  확정하면 이 기기만의 로그인 값(accounts.new_session)을 쿠키에 심는다. 익명으로 쌓은 값만 계정 쪽에 합친다(다른 계정 값은 합치지 않는다).
- logout: 이 기기만 로그아웃. logout-all·revoke: 모든 기기. sessions: 로그인한 기기 목록·하나씩 로그아웃.
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


def _mail_refused(email: str) -> HTTPException:
    """로그인 메일을 못 보낸 경우 — 예전엔 그래도 '보냈습니다'라고 답해 사용자가 오지 않는 메일을 기다렸다 (2026-11-03).
    같은 주소 간격·횟수 제한과 하루 전체 상한은 계정이 있든 없든 똑같이 걸리므로 계정 존재 여부는 드러나지 않는다."""
    return HTTPException(status_code=429, detail=f"{_mask(email)} 으로 로그인 메일을 방금 보냈거나 오늘 보낼 수 있는 수를 넘었어요. "
                                                 "받은 메일함(스팸함 포함)의 가장 최근 메일을 써 주세요. 잠시 후 다시 시도할 수 있어요.")


@router.post("/auth/request")
def request_link(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    email = _email(payload.get("email"))
    throttle("login_try", c, per_visitor=5, per_ip=30)
    bad = email_check.problem(email, typo_ok=payload.get("typo_ok") is True)
    if bad:
        raise HTTPException(status_code=400, detail=bad)
    if not mailer.is_configured():
        raise HTTPException(status_code=503, detail="지금은 로그인 메일을 보낼 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if not _may_mail(email, "login_mail", "로그인 메일", gap_min=1, per_day=10, own_day=True):  # 휴대폰·PC 연달아 로그인할 수 있게
        raise _mail_refused(email)
    token, code, nonce = accounts.new_link(email)
    response.set_cookie(NONCE_COOKIE, nonce, max_age=accounts.LINK_MINUTES * 60, samesite="lax", httponly=True,
                        secure=request.url.scheme == "https" or c.proxied, path="/api/auth")
    send_later(mailer.send_login_link, email, token, code)
    return {"ok": True, "code_entry": True,
            "message": f"{_mask(email)} 으로 로그인 메일을 보냈습니다. 메일에 적힌 6자리 코드를 아래에 넣거나, 30분 안에 메일의 버튼을 눌러 주세요. "
                       "메일이 안 보이면 스팸함도 확인해 주세요."}


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
    return _finish_login(request, response, c, email)


@router.post("/auth/verify-code")
def verify_code(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """로그인 창에서 메일의 6자리 코드로 바로 확정 — 링크를 요청한 이 브라우저(nonce 쿠키)에서만 된다."""
    code = payload.get("code")
    if not (isinstance(code, str) and re.fullmatch(r"\d{6}", code)):
        raise HTTPException(status_code=400, detail="확인 코드는 숫자 6자리입니다.")
    throttle("login_verify", c, per_visitor=10, per_ip=60)
    email, res = accounts.use_code(request.cookies.get(NONCE_COOKIE), code)
    if res == "bad_code":
        raise HTTPException(status_code=401, detail="확인 코드가 맞지 않습니다. 가장 최근 메일의 코드인지 확인해 주세요.")
    if not email:
        raise HTTPException(status_code=400, detail="코드가 만료됐거나 너무 많이 틀렸어요. 로그인 메일을 다시 받아 주세요.")
    return _finish_login(request, response, c, email)


def _finish_login(request: Request, response: Response, c: Caller, email: str) -> dict:
    was_account = accounts.by_raw(c.raw) is not None  # 이 브라우저가 이미 (다른) 계정으로 로그인돼 있었는지
    acc, new, revoke = accounts.login(email, c.raw)
    gate.forget(c.raw); gate.forget(acc["raw"])
    target = "c:" + acc["raw"]
    # 익명으로 쌓은 값만 계정에 합친다 — 예전엔 A 계정으로 로그인된 브라우저에서 B 가 로그인하면 A 의 관심 단지·프로필이 B 에 복사됐다
    if target != c.visitor and not was_account:
        _merge(target, c.visitor)
    accounts.end_session(c.sid)  # 이 기기의 예전 로그인 값은 지운다
    sid = accounts.new_session(acc["id"], (request.headers.get("user-agent") or "")[:200])
    _set_cookie(request, response, c, sid)
    response.delete_cookie(NONCE_COOKIE, path="/api/auth")
    # 같은 주소로 구독 중이면 이 계정과 잇는다 (알림 메일·질문하기 횟수가 계정을 따라오게)
    db.set_subscriber_visitor(email, target)
    # 로그인 알림 메일 — 본인이 아니면 메일의 '모든 기기에서 로그아웃'으로 끊는다
    send_later(mailer.send_login_notice, email, revoke, (request.headers.get("user-agent") or "")[:120])
    return {"ok": True, "email": _mask(email), "new": new}


@router.post("/auth/logout")
def logout(request: Request, response: Response, c: Caller = CallerDep) -> dict:
    """이 기기만 로그아웃 — 이 기기의 로그인 값을 지운다(쿠키가 새어 나갔어도 더 쓸 수 없게). 다른 기기는 그대로."""
    gate.forget(c.raw)
    accounts.end_session(c.sid)
    _set_cookie(request, response, c, uuid.uuid4().hex)
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(request: Request, response: Response, c: Caller = CallerDep) -> dict:
    """모든 기기에서 로그아웃 (내 공간 버튼) — 계정 식별값을 새로 바꾸고 이 브라우저에만 새 값을 심는다."""
    acc = accounts.by_raw(c.raw)
    if not acc:
        raise HTTPException(status_code=400, detail="로그인 상태가 아닙니다.")
    accounts.rotate(acc)  # 계정 raw 를 바꾸고 기기 로그인을 모두 지운다
    gate.forget(c.raw)
    _set_cookie(request, response, c, accounts.new_session(acc["id"], (request.headers.get("user-agent") or "")[:200]))
    return {"ok": True}


@router.get("/auth/sessions")
def my_sessions(c: Caller = CallerDep) -> dict:
    """로그인한 기기 목록 (내 공간). 예전 방식으로 로그인한 기기는 목록에 없다 — '모든 기기에서 로그아웃'으로 끊는다."""
    acc = accounts.by_raw(c.raw)
    if not acc:
        raise HTTPException(status_code=400, detail="로그인 상태가 아닙니다.")
    return {"sessions": accounts.sessions(acc["id"], c.sid), "legacy": c.sid is None}


@router.post("/auth/sessions/end")
def end_one(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """목록의 기기 하나 로그아웃."""
    acc = accounts.by_raw(c.raw)
    sid = payload.get("id")
    if not acc:
        raise HTTPException(status_code=400, detail="로그인 상태가 아닙니다.")
    if not (isinstance(sid, str) and re.fullmatch(r"[0-9a-f]{12}", sid)) or not accounts.end_session_by_id(acc["id"], sid):
        raise HTTPException(status_code=400, detail="이미 로그아웃한 기기입니다.")
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
    gate.forget(acc["raw"])
    accounts.end_session(c.sid)
    _set_cookie(request, response, c, uuid.uuid4().hex)
    return {"ok": True, "message": "모든 기기에서 로그아웃했습니다. 본인이 다시 로그인하면 저장한 내용은 그대로 보입니다."}
