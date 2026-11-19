"""패스키(WebAuthn) 로그인 (2026-11-19) — 지문·얼굴·화면 잠금으로 로그인. 외부 패키지 없이 cryptography 와 작은 CBOR 해석기만 쓴다.

- 등록은 메일로 로그인한 계정만. 로그인은 '기기에 저장된 패스키'를 골라 서명 → 서버가 공개키로 확인.
- 서버에는 공개키·자격 증명 ID·사용 횟수·이름만 둔다 (생체 정보는 기기 밖으로 나오지 않는다). 증명서(attestation)는 받지 않는다("none").
- 확인하는 것: 한 번만 쓰는 도전값(5분), 출처(origin)·RP ID 해시, 사용자 확인(UV) 플래그, 서명(ES256·RS256), 복제 의심(횟수 되돌림).
- 계정당 10개까지. 모든 기기 로그아웃·탈퇴 때 함께 지운다. LLM 없음.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from . import db

MAX_PER_ACCOUNT = 10
CHALLENGE_SECONDS = 300
_SQL = ("CREATE TABLE IF NOT EXISTS passkey (cred_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, pubkey TEXT NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, "
        "label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, last_used_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_passkey_acc ON passkey(account_id)",
        "CREATE TABLE IF NOT EXISTS passkey_chal (cid TEXT PRIMARY KEY, challenge TEXT NOT NULL, kind TEXT NOT NULL, account_id INTEGER, expires_at REAL NOT NULL)")
_ready: list = []


class PasskeyError(Exception):
    """확인에 실패한 이유 — 화면에는 짧은 문구만 보여 준다."""


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(str(s) + "=" * (-len(str(s)) % 4))


def _conn():
    c = db.connect()
    if not _ready:
        for q in _SQL:
            c.execute(q)
        c.commit()
        _ready.append(True)
    return c


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ───────────── CBOR (필요한 만큼만: 정수·바이트·글자·배열·표·참/거짓/없음) ─────────────

def cbor(data: bytes, i: int = 0, depth: int = 0):
    """(값, 다음 위치). 길이가 정해진 값만 받는다 — WebAuthn 이 쓰는 범위."""
    if depth > 8 or i >= len(data):
        raise PasskeyError("형식이 맞지 않아요.")
    ib = data[i]
    major, info = ib >> 5, ib & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise PasskeyError("형식이 맞지 않아요.")
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    elif major == 7:
        n = info
    else:
        raise PasskeyError("지원하지 않는 형식이에요.")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(data):
            raise PasskeyError("형식이 맞지 않아요.")
        raw = data[i:i + n]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), i + n
    if major == 4:
        if n > 64:
            raise PasskeyError("형식이 맞지 않아요.")
        out = []
        for _ in range(n):
            v, i = cbor(data, i, depth + 1)
            out.append(v)
        return out, i
    if major == 5:
        if n > 64:
            raise PasskeyError("형식이 맞지 않아요.")
        d = {}
        for _ in range(n):
            k, i = cbor(data, i, depth + 1)
            v, i = cbor(data, i, depth + 1)
            d[k] = v
        return d, i
    if major == 7 and n in (20, 21, 22):
        return {20: False, 21: True, 22: None}[n], i
    raise PasskeyError("지원하지 않는 형식이에요.")


# ───────────── 도전값 ─────────────

def new_challenge(kind: str, account_id: int | None = None) -> tuple[str, str]:
    """(cid, 도전값 b64url) — 5분, 한 번만 쓸 수 있다."""
    cid, ch = secrets.token_urlsafe(16), b64e(secrets.token_bytes(32))
    c = _conn()
    try:
        c.execute("DELETE FROM passkey_chal WHERE expires_at < ?", (time.time(),))
        c.execute("INSERT INTO passkey_chal (cid, challenge, kind, account_id, expires_at) VALUES (?,?,?,?,?)", (cid, ch, kind, account_id, time.time() + CHALLENGE_SECONDS))
        c.commit()
    finally:
        c.close()
    return cid, ch


def take_challenge(cid: str, kind: str) -> tuple[str, int | None]:
    """도전값을 꺼내며 지운다 — 다시 쓸 수 없다."""
    c = _conn()
    try:
        r = c.execute("SELECT challenge, account_id, expires_at FROM passkey_chal WHERE cid=? AND kind=?", (str(cid)[:64], kind)).fetchone()
        c.execute("DELETE FROM passkey_chal WHERE cid=?", (str(cid)[:64],))
        c.commit()
    finally:
        c.close()
    if not r or r[2] < time.time():
        raise PasskeyError("시간이 지났어요. 처음부터 다시 해 주세요.")
    return r[0], r[1]


# ───────────── 확인 ─────────────

def _client_data(raw_b64: str, typ: str, challenge: str, origins: set[str]) -> bytes:
    raw = b64d(raw_b64)
    try:
        cd = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise PasskeyError("형식이 맞지 않아요.") from e
    if cd.get("type") != typ:
        raise PasskeyError("요청 종류가 맞지 않아요.")
    if not secrets.compare_digest(str(cd.get("challenge", "")), challenge):
        raise PasskeyError("확인값이 맞지 않아요. 처음부터 다시 해 주세요.")
    if cd.get("origin") not in origins:
        raise PasskeyError("이 사이트에서 만든 패스키가 아니에요.")
    if cd.get("crossOrigin") is True:
        raise PasskeyError("다른 사이트 안에서는 쓸 수 없어요.")
    return raw


def _auth_data(ad: bytes, rp_id: str, need_uv: bool = True) -> tuple[int, int]:
    if len(ad) < 37:
        raise PasskeyError("형식이 맞지 않아요.")
    if ad[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise PasskeyError("이 사이트용 패스키가 아니에요.")
    flags = ad[32]
    if not flags & 0x01:
        raise PasskeyError("기기에서 사용자 확인이 되지 않았어요.")
    if need_uv and not flags & 0x04:
        raise PasskeyError("지문·얼굴·화면 잠금 확인이 필요해요.")
    return flags, struct.unpack(">I", ad[33:37])[0]


def _public_key(cose: dict):
    """COSE 공개키 → cryptography 키. ES256(P-256)과 RS256 만."""
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == -7 and cose.get(-1) == 1:
        x, y = cose.get(-2), cose.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
            raise PasskeyError("지원하지 않는 키예요.")
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + x + y)
    if kty == 3 and alg == -257:
        n, e = cose.get(-1), cose.get(-2)
        if not (isinstance(n, bytes) and isinstance(e, bytes)) or len(n) < 256:  # 2048비트 미만 거부
            raise PasskeyError("지원하지 않는 키예요.")
        return rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
    raise PasskeyError("지원하지 않는 키예요.")


def _verify_sig(pub, sig: bytes, msg: bytes) -> None:
    try:
        if isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(sig, msg, ec.ECDSA(hashes.SHA256()))
        else:
            pub.verify(sig, msg, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise PasskeyError("서명이 맞지 않아요.") from e


def parse_registration(cred: dict, challenge: str, rp_id: str, origins: set[str]) -> tuple[str, bytes]:
    """등록 응답 → (자격 증명 ID b64url, 저장할 COSE 공개키 바이트)."""
    resp = cred.get("response") or {}
    _client_data(resp.get("clientDataJSON", ""), "webauthn.create", challenge, origins)
    att, _ = cbor(b64d(resp.get("attestationObject", "")))
    ad = att.get("authData") if isinstance(att, dict) else None
    if not isinstance(ad, bytes):
        raise PasskeyError("형식이 맞지 않아요.")
    flags, _count = _auth_data(ad, rp_id, need_uv=False)
    if not flags & 0x40 or len(ad) < 55:
        raise PasskeyError("공개키가 없어요.")
    cred_len = struct.unpack(">H", ad[53:55])[0]
    cred_id = ad[55:55 + cred_len]
    if not 16 <= cred_len <= 1023 or len(cred_id) != cred_len:
        raise PasskeyError("형식이 맞지 않아요.")
    if cred.get("id") and cred["id"] != b64e(cred_id):
        raise PasskeyError("자격 증명이 맞지 않아요.")
    key_bytes_all = ad[55 + cred_len:]
    cose, end = cbor(key_bytes_all)
    if not isinstance(cose, dict):
        raise PasskeyError("형식이 맞지 않아요.")
    _public_key(cose)  # 지원하는 키인지 미리 확인
    return b64e(cred_id), key_bytes_all[:end]


def verify_assertion(cred: dict, challenge: str, rp_id: str, origins: set[str], stored: dict) -> int:
    """로그인 응답 확인 → 새 사용 횟수. 실패하면 PasskeyError."""
    resp = cred.get("response") or {}
    cdj = _client_data(resp.get("clientDataJSON", ""), "webauthn.get", challenge, origins)
    ad = b64d(resp.get("authenticatorData", ""))
    _flags, count = _auth_data(ad, rp_id, need_uv=True)
    pub = _public_key(cbor(b64d(stored["pubkey"]))[0])
    _verify_sig(pub, b64d(resp.get("signature", "")), ad + hashlib.sha256(cdj).digest())
    old = int(stored.get("sign_count") or 0)
    if (count or old) and count <= old:
        raise PasskeyError("이 패스키가 복제됐을 수 있어 막았어요. 새로 등록해 주세요.")
    return count


# ───────────── 저장 ─────────────

def add(acc_id: int, cred_id: str, pubkey: bytes, label: str) -> bool:
    c = _conn()
    try:
        if c.execute("SELECT 1 FROM passkey WHERE cred_id=?", (cred_id,)).fetchone():
            return False
        if c.execute("SELECT COUNT(*) FROM passkey WHERE account_id=?", (acc_id,)).fetchone()[0] >= MAX_PER_ACCOUNT:
            raise PasskeyError(f"패스키는 {MAX_PER_ACCOUNT}개까지 등록할 수 있어요.")
        c.execute("INSERT INTO passkey (cred_id, account_id, pubkey, sign_count, label, created_at) VALUES (?,?,?,?,?,?)",
                  (cred_id, acc_id, b64e(pubkey), 0, (label or "내 기기").strip()[:30], _now()))
        c.commit()
        return True
    finally:
        c.close()


def get(cred_id: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute("SELECT cred_id, account_id, pubkey, sign_count, label FROM passkey WHERE cred_id=?", (str(cred_id)[:1400],)).fetchone()
        return dict(zip(("cred_id", "account_id", "pubkey", "sign_count", "label"), r)) if r else None
    finally:
        c.close()


def touch(cred_id: str, count: int) -> None:
    c = _conn()
    try:
        c.execute("UPDATE passkey SET sign_count=?, last_used_at=? WHERE cred_id=?", (count, _now(), cred_id))
        c.commit()
    finally:
        c.close()


def listing(acc_id: int) -> list[dict]:
    c = _conn()
    try:
        return [{"id": r[0], "label": r[1], "created_at": r[2], "last_used_at": r[3]}
                for r in c.execute("SELECT cred_id, label, created_at, last_used_at FROM passkey WHERE account_id=? ORDER BY created_at", (acc_id,))]
    finally:
        c.close()


def remove(acc_id: int, cred_id: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM passkey WHERE account_id=? AND cred_id=?", (acc_id, str(cred_id)[:1400]))
        c.commit()
    finally:
        c.close()


def remove_account(acc_id: int) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM passkey WHERE account_id=?", (acc_id,))
        c.commit()
    finally:
        c.close()
