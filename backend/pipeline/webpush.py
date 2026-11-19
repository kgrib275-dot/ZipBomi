"""웹 푸시 알림 (2026-11-19) — 로그인 계정이 '이 기기로 알림 받기'를 켠 기기에 알림을 보낸다. 외부 패키지 없이 cryptography 만 쓴다.

- VAPID(RFC 8292, ES256 JWT) + 메시지 암호화(RFC 8291, aes128gcm). 키는 data/vapid.json(웹으로 열리지 않는 폴더, git 제외)에 처음 쓸 때 만든다.
- 기기 정보(push_sub)는 계정에 묶어 저장 — endpoint·암호키는 알림을 보내는 데만 쓰고, 기기별 끄기·모든 기기 로그아웃·탈퇴 때 파기한다.
- endpoint 는 알려진 푸시 서비스 주소(https)만 받는다 — 서버가 임의 주소로 요청을 보내지 않게(SSRF 방지).
- 보내는 내용은 알림 제목·한 줄·열 주소뿐. 보낼 때 404/410 이 오면 그 기기는 지운다. LLM 없음.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import db, mailer
from .db import ROOT

log = logging.getLogger("zipgenie.webpush")

KEY_FILE = ROOT / "data" / "vapid.json"
MAX_PER_ACCOUNT = 5
ALLOWED_SUFFIX = (".googleapis.com", ".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com", ".push.microsoft.com")
_SQL = ("CREATE TABLE IF NOT EXISTS push_sub (endpoint_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, endpoint TEXT NOT NULL, "
        "p256dh TEXT NOT NULL, auth TEXT NOT NULL, ua TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, last_ok_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_push_sub_acc ON push_sub(account_id)")
_ready: list = []


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


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


# ───────────── VAPID 키 ─────────────

def _private() -> ec.EllipticCurvePrivateKey:
    try:
        raw = _b64d(json.loads(KEY_FILE.read_text("utf-8"))["private"])
        return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    except Exception:  # noqa: BLE001 - 파일이 없거나 깨졌으면 새로 만든다
        key = ec.generate_private_key(ec.SECP256R1())
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(json.dumps({"private": _b64e(key.private_numbers().private_value.to_bytes(32, "big"))}), "utf-8")
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
        return key


def _point(pub: ec.EllipticCurvePublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key() -> str:
    """브라우저 구독(applicationServerKey)에 쓰는 공개키 — 공개해도 되는 값."""
    return _b64e(_point(_private().public_key()))


def _vapid_header(endpoint: str) -> str:
    u = urlparse(endpoint)
    aud = f"{u.scheme}://{u.netloc}"
    sub = mailer.site_url() or "https://localhost"
    head = _b64e(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64e(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": sub if sub.startswith("https://") else "https://localhost"},
                              separators=(",", ":")).encode())
    key = _private()
    r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = _b64e(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{claims}.{sig}, k={public_key()}"


# ───────────── 메시지 암호화 (RFC 8291) ─────────────

def encrypt(payload: bytes, ua_public: bytes, auth: bytes, as_key: ec.EllipticCurvePrivateKey | None = None, salt: bytes | None = None) -> bytes:
    as_key = as_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_pub = _point(as_key.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    secret = as_key.exchange(ec.ECDH(), ua_key)
    prk = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_public + as_pub).derive(secret)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(prk)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(prk)
    cipher = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + cipher


# ───────────── 기기 저장 ─────────────

def valid_endpoint(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and len(endpoint) <= 600 and not u.username and any(host.endswith(s) for s in ALLOWED_SUFFIX)


def add(acc_id: int, endpoint: str, p256dh: str, auth: str, ua: str = "") -> bool:
    try:
        if len(_b64d(p256dh)) != 65 or len(_b64d(auth)) != 16:
            return False
    except Exception:  # noqa: BLE001
        return False
    if not valid_endpoint(endpoint):
        return False
    h = hashlib.sha256(endpoint.encode()).hexdigest()
    c = _conn()
    try:
        c.execute("DELETE FROM push_sub WHERE endpoint_hash=?", (h,))
        old = [r[0] for r in c.execute("SELECT endpoint_hash FROM push_sub WHERE account_id=? ORDER BY created_at DESC, rowid DESC", (acc_id,))]
        for x in old[MAX_PER_ACCOUNT - 1:]:  # 오래된 기기부터 밀어낸다
            c.execute("DELETE FROM push_sub WHERE endpoint_hash=?", (x,))
        c.execute("INSERT INTO push_sub (endpoint_hash, account_id, endpoint, p256dh, auth, ua, created_at) VALUES (?,?,?,?,?,?,?)",
                  (h, acc_id, endpoint, p256dh, auth, ua[:200], _now()))
        c.commit()
        return True
    finally:
        c.close()


def remove(acc_id: int, endpoint: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM push_sub WHERE account_id=? AND endpoint_hash=?", (acc_id, hashlib.sha256(endpoint.encode()).hexdigest()))
        c.commit()
    finally:
        c.close()


def remove_account(acc_id: int) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM push_sub WHERE account_id=?", (acc_id,))
        c.commit()
    finally:
        c.close()


def count(acc_id: int) -> int:
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM push_sub WHERE account_id=?", (acc_id,)).fetchone()[0]
    finally:
        c.close()


def has(acc_id: int, endpoint: str) -> bool:
    c = _conn()
    try:
        return bool(c.execute("SELECT 1 FROM push_sub WHERE account_id=? AND endpoint_hash=?", (acc_id, hashlib.sha256(endpoint.encode()).hexdigest())).fetchone())
    finally:
        c.close()


# ───────────── 보내기 ─────────────

def _post(endpoint: str, body: bytes, headers: dict) -> int:
    try:
        return httpx.post(endpoint, content=body, headers=headers, timeout=10, follow_redirects=False).status_code
    except Exception:  # noqa: BLE001
        log.warning("웹 푸시 전송 실패")
        return 0


def send_account(acc_id: int, title: str, body: str, url: str = "/my", tag: str = "zipbomi") -> int:
    """계정의 모든 기기에 보낸다. 성공한 기기 수를 돌려준다. 만료된 기기(404·410)는 지운다."""
    payload = json.dumps({"title": title[:80], "body": body[:160], "url": url if url.startswith("/") else "/my", "tag": tag}, ensure_ascii=False).encode()
    c = _conn()
    try:
        subs = c.execute("SELECT endpoint_hash, endpoint, p256dh, auth FROM push_sub WHERE account_id=?", (acc_id,)).fetchall()
    finally:
        c.close()
    ok = 0
    for h, endpoint, p256dh, auth in subs:
        try:
            data = encrypt(payload, _b64d(p256dh), _b64d(auth))
        except Exception:  # noqa: BLE001 - 깨진 기기 정보는 지운다
            code = 410
        else:
            code = _post(endpoint, data, {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "43200",
                                          "Urgency": "normal", "Authorization": _vapid_header(endpoint)})
        c = _conn()
        try:
            if code in (404, 410):
                c.execute("DELETE FROM push_sub WHERE endpoint_hash=?", (h,))
            elif 200 <= code < 300:
                c.execute("UPDATE push_sub SET last_ok_at=? WHERE endpoint_hash=?", (_now(), h))
                ok += 1
            c.commit()
        finally:
            c.close()
    return ok
