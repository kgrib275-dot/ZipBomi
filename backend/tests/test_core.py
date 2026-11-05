"""핵심 자동 시험 — 임시 DB 로만 돌고 실서버 DB·메일·네트워크는 건드리지 않는다.

실행: backend 폴더에서  venv/Scripts/python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="zipbomi-test-")
os.environ["ZIPGENIE_DB"] = str(Path(_TMP) / "test.db")   # pipeline.db 를 가져오기 전에 정해야 한다
os.environ["ADMIN_TOKEN"] = "test-token-123"
os.environ["ADMIN_TOTP_SECRET"] = ""
os.environ["ZIPGENIE_SCHEDULER"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import admin_auth, db, reminders  # noqa: E402


class TotpTest(unittest.TestCase):
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 시험 비밀값 "12345678901234567890"

    def test_rfc6238_vector(self):
        # RFC 6238 부록: 시각 59초 → 8자리 94287082 → 6자리 287082
        self.assertEqual(admin_auth._totp(self.SECRET, 59 // 30), "287082")

    def test_accepts_neighbour_step_only(self):
        os.environ["ADMIN_TOTP_SECRET"] = self.SECRET
        try:
            now = 59.0
            self.assertEqual(admin_auth.otp_step("287082", now), 1)
            self.assertIsNone(admin_auth.otp_step("000000", now))
            self.assertIsNone(admin_auth.otp_step("28708", now))      # 자릿수 부족
            self.assertIsNone(admin_auth.otp_step("abcdef", now))     # 숫자 아님
            self.assertIsNone(admin_auth.otp_step("287082", now + 300))  # 5분 뒤엔 무효
        finally:
            os.environ["ADMIN_TOTP_SECRET"] = ""


class AdminLoginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_login_ok_and_session(self):
        sid, res = admin_auth.login("test-token-123", None, "10.0.0.1", "ua")
        self.assertEqual(res, "ok")
        self.assertTrue(admin_auth.check(sid))
        admin_auth.logout(sid, "10.0.0.1")
        self.assertFalse(admin_auth.check(sid))

    def test_wrong_token_locks_after_five(self):
        ip = "10.0.0.2"
        for _ in range(admin_auth.FAIL_LIMIT):
            self.assertEqual(admin_auth.login("틀린토큰", None, ip, "ua")[1], "bad")
        self.assertEqual(admin_auth.login("test-token-123", None, ip, "ua")[1], "locked")  # 맞는 토큰도 잠금 중엔 막힌다
        self.assertEqual(admin_auth.login("test-token-123", None, "10.0.0.3", "ua")[1], "ok")  # 다른 IP 는 영향 없음

    def test_not_configured(self):
        old = os.environ.pop("ADMIN_TOKEN")
        try:
            self.assertEqual(admin_auth.login("아무거나", None, "10.0.0.4", "ua")[1], "not_configured")
        finally:
            os.environ["ADMIN_TOKEN"] = old

    def test_audit_chain_detects_tamper(self):
        admin_auth.audit("tester", "10.0.0.5", "GET", "/api/admin/x", 200)
        admin_auth.audit("tester", "10.0.0.5", "GET", "/api/admin/y", 200)
        self.assertTrue(admin_auth.verify().get("ok"))
        c = db.connect()
        try:
            with c:
                c.execute("UPDATE admin_audit SET path='/api/admin/조작' WHERE id=(SELECT MAX(id)-1 FROM admin_audit)")
        finally:
            c.close()
        self.assertFalse(admin_auth.verify().get("ok"))


class ReminderTest(unittest.TestCase):
    def test_apply_target_prefers_start_then_end(self):
        self.assertEqual(reminders.apply_target({"receipt_start": "2026-11-10", "receipt_end": "2026-11-12"}),
                         (date(2026, 11, 10), "접수 시작"))
        self.assertEqual(reminders.apply_target({"receipt_end": "2026-11-12"}), (date(2026, 11, 12), "접수 마감"))
        self.assertEqual(reminders.apply_target({"receipt_start": "엉터리"}), (None, "접수 마감"))


class CsrfGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app, base_url="http://127.0.0.1")

    def test_post_without_header_is_428(self):
        r = self.client.post("/api/subscribe", json={})
        self.assertEqual(r.status_code, 428)

    def test_cross_site_is_428(self):
        r = self.client.post("/api/subscribe", json={}, headers={"X-Requested-With": "zipgenie", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 428)

    def test_oversize_body_is_413(self):
        r = self.client.post("/api/subscribe", content=b"x" * (70 * 1024),
                             headers={"X-Requested-With": "zipgenie", "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_pwa_files(self):
        """PWA(홈 화면 설치) 파일 — 화면을 빌드하지 않은 PC 에서는 건너뛴다."""
        from api.main import DIST
        if not (DIST / "sw.js").is_file():
            self.skipTest("frontend/dist 가 없음 (npm run build 전)")
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw.headers["cache-control"], "no-cache")  # 서비스 워커는 항상 새 버전 확인
        self.assertIn("javascript", sw.headers["content-type"])
        self.assertNotIn("/api", sw.text.split("addEventListener(\"fetch\"")[1].split("});")[0])  # API 응답은 건드리지 않는다
        mf = self.client.get("/manifest.webmanifest")
        self.assertEqual(mf.headers["content-type"].split(";")[0], "application/manifest+json")
        data = mf.json()
        self.assertEqual(data["display"], "standalone")
        for icon in data["icons"]:
            self.assertEqual(self.client.get(icon["src"]).status_code, 200, icon["src"])

    def test_security_headers_present(self):
        r = self.client.get("/api/site")
        self.assertIn("x-content-type-options", {k.lower() for k in r.headers})


if __name__ == "__main__":
    unittest.main()
