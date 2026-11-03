"""관리자 OTP(2단계 인증) 비밀값 만들기 — ISMS-P 2.5.3 (2026-11-03).

    venv\\Scripts\\python tools\\admin_otp.py          새 비밀값과 OTP 앱 등록 주소를 보여 준다
    venv\\Scripts\\python tools\\admin_otp.py --check  .env 의 ADMIN_TOTP_SECRET 으로 지금 코드를 보여 준다 (앱과 같은지 확인)

1) 나온 비밀값을 OTP 앱(Google OTP·Microsoft Authenticator 등)에 '설정 키 입력'으로 등록한다 (계정 이름 아무거나, 시간 기준).
2) backend/.env 에 ADMIN_TOTP_SECRET=<비밀값> 을 넣고 서버를 다시 시작한다.
3) 관리 화면 로그인에서 토큰과 앱의 6자리를 함께 넣는다. 비밀값은 다른 곳에 남기거나 보내지 않는다.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from pipeline import admin_auth  # noqa: E402

if "--check" in sys.argv:
    if not admin_auth.totp_secret():
        sys.exit(".env 에 ADMIN_TOTP_SECRET 이 없습니다.")
    print("지금 OTP:", admin_auth._totp(admin_auth.totp_secret(), int(time.time() // 30)), "(앱의 숫자와 같으면 정상)")
else:
    s = admin_auth.new_totp_secret()
    print("새 OTP 비밀값 (OTP 앱에 '설정 키'로 입력):", s)
    print("등록 주소 (QR 생성기에 넣어도 됨):", f"otpauth://totp/ZIPBOMI:admin?secret={s}&issuer=ZIPBOMI")
    print("다음: backend/.env 에 ADMIN_TOTP_SECRET=" + s + " 을 넣고 서버를 다시 시작하세요.")
    if os.environ.get("ADMIN_TOTP_SECRET"):
        print("※ 이미 .env 에 ADMIN_TOTP_SECRET 이 있습니다 — 바꾸면 OTP 앱에도 다시 등록해야 합니다.")
