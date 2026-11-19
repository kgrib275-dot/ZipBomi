"""패스키 로그인 (2026-11-19) — /api/auth/passkey/*. 검증 로직은 pipeline/passkeys.py, 로그인 확정은 메일 로그인과 같은 _finish_login.

- register/options·verify: 메일로 로그인한 계정이 이 기기의 패스키를 등록한다.
- login/options·verify: 로그인 전 — 기기에 저장된 패스키를 골라 서명하면 로그인(메일 없이). 사용자 확인(지문·얼굴·화면 잠금) 필수.
- list·remove: 내 패스키 목록·지우기.
RP ID·출처는 운영에서는 SITE_URL, 개발에서는 요청 주소(localhost)를 쓴다.
"""
from __future__ import annotations

import hashlib
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request, Response

from api.deps import Caller, CallerDep, throttle
from api.routers.auth import _finish_login
from pipeline import accounts, passkeys

router = APIRouter(tags=["passkey"])
RP_NAME = "집보미"


def _rp(request: Request) -> tuple[str, set[str]]:
    site = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if site:
        u = urlparse(site)
        return u.hostname or "", {f"{u.scheme}://{u.netloc}"}
    host = (request.headers.get("host") or "").lower()
    return host.split(":")[0], {f"{request.url.scheme}://{host}"}


def _acc(c: Caller) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    if not a:
        raise HTTPException(401, "메일로 로그인한 계정에서만 쓸 수 있어요.")
    return a


def _fail(e: passkeys.PasskeyError) -> HTTPException:
    return HTTPException(400, str(e))


@router.post("/auth/passkey/register/options")
def reg_options(request: Request, c: Caller = CallerDep) -> dict:
    a = _acc(c)
    rp_id, _ = _rp(request)
    cid, ch = passkeys.new_challenge("reg", a["id"])
    have = [{"type": "public-key", "id": p["id"]} for p in passkeys.listing(a["id"])]
    return {"cid": cid, "publicKey": {
        "challenge": ch, "rp": {"id": rp_id, "name": RP_NAME},
        "user": {"id": passkeys.b64e(hashlib.sha256(f"zipbomi-pk-{a['id']}".encode()).digest()[:16]), "name": a["email"], "displayName": a["email"]},
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -257}],
        "excludeCredentials": have, "attestation": "none", "timeout": 120000,
        "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"}}}


@router.post("/auth/passkey/register/verify")
def reg_verify(request: Request, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    a = _acc(c)
    throttle("passkey_reg", c, per_visitor=10, per_ip=30)
    rp_id, origins = _rp(request)
    try:
        ch, acc_id = passkeys.take_challenge(str(payload.get("cid") or ""), "reg")
        if acc_id != a["id"]:
            raise passkeys.PasskeyError("처음부터 다시 해 주세요.")
        cred_id, key = passkeys.parse_registration(payload.get("credential") or {}, ch, rp_id, origins)
        if not passkeys.add(a["id"], cred_id, key, str(payload.get("label") or "")):
            raise passkeys.PasskeyError("이미 등록된 패스키예요.")
    except passkeys.PasskeyError as e:
        raise _fail(e) from e
    return {"ok": True, "passkeys": passkeys.listing(a["id"])}


@router.post("/auth/passkey/login/options")
def login_options(request: Request, c: Caller = CallerDep) -> dict:
    throttle("passkey_login", c, per_visitor=20, per_ip=120)
    rp_id, _ = _rp(request)
    cid, ch = passkeys.new_challenge("login")
    return {"cid": cid, "publicKey": {"challenge": ch, "rpId": rp_id, "timeout": 120000, "userVerification": "required", "allowCredentials": []}}


@router.post("/auth/passkey/login/verify")
def login_verify(request: Request, response: Response, payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    throttle("passkey_login_verify", c, per_visitor=10, per_ip=60)
    rp_id, origins = _rp(request)
    cred = payload.get("credential") or {}
    try:
        ch, _ = passkeys.take_challenge(str(payload.get("cid") or ""), "login")
        stored = passkeys.get(str(cred.get("id") or ""))
        if not stored:
            raise passkeys.PasskeyError("이 기기의 패스키를 서버에서 찾지 못했어요. 메일로 로그인한 뒤 다시 등록해 주세요.")
        count = passkeys.verify_assertion(cred, ch, rp_id, origins, stored)
    except passkeys.PasskeyError as e:
        raise _fail(e) from e
    con = accounts._conn()
    try:
        row = con.execute("SELECT email FROM accounts WHERE id=?", (stored["account_id"],)).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(400, "계정을 찾지 못했어요.")
    passkeys.touch(stored["cred_id"], count)
    return _finish_login(request, response, c, row[0])


@router.get("/auth/passkey/list")
def plist(c: Caller = CallerDep) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    return {"account": bool(a), "passkeys": passkeys.listing(a["id"]) if a else []}


@router.post("/auth/passkey/remove")
def remove(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    a = _acc(c)
    passkeys.remove(a["id"], str(payload.get("id") or ""))
    return {"ok": True, "passkeys": passkeys.listing(a["id"])}
