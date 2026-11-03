"""개인정보 처리방침 내용 — 지금 켜져 있는 기능에서 실제로 처리하는 개인정보만 모아 만든다.

개인정보 보호법 제30조·시행령 제31조의 기재사항(처리 목적·항목·보유 기간, 파기, 제3자 제공, 위탁, 국외 이전,
정보주체 권리, 안전성 확보 조치, 자동 수집 장치, 보호책임자, 열람청구 부서, 구제 방법, 변경 사항)을 채우는 데 쓴다.
- 처리하는 개인정보가 하나도 없으면 active()가 False → 처리방침 페이지·링크를 아예 표시하지 않는다.
- 보호책임자·운영자 명칭처럼 코드가 알 수 없는 값은 관리 > 개인정보 처리방침에서 입력한다(missing()이 빈 값을 알려 줌).
- 버전 관리: 관리자가 '공지'하면 그때의 내용(snapshot)을 시행일·공지일과 함께 privacy_versions에 고정해 둔다.
  공개 화면은 날짜별로 골라 볼 수 있고, 기본은 지금 시행 중인 버전. 공지한 뒤 기능이 바뀌면 outdated()가 True.
- 기능을 추가·변경하면 여기의 records()/entrustments()/overseas()도 같이 고친다.
법률 검토를 대신하지 않는다 — 시행 전 담당 부서(법무·개인정보) 검토를 받는다.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

from . import db, settings_store

DEFAULTS = {
    "operator": "",          # 개인정보처리자 명칭 (사이트 운영 주체)
    "officer_name": "",      # 개인정보 보호책임자 성명 (또는 직책)
    "officer_dept": "",      # 부서
    "officer_email": "",     # 연락처 (이메일)
    "officer_phone": "",     # 연락처 (전화, 선택)
    "request_dept": "",      # 열람청구 접수·처리 부서 (비우면 보호책임자와 같음)
    "smtp_vendor": "",       # 메일 발송 위탁 업체 이름 (SMTP 사업자)
    "smtp_country": "대한민국",  # 그 업체의 처리 국가 (국외면 국외 이전으로 표시)
    "databricks_region": "미국",  # Databricks 저장 지역
    "admin_measures": "",    # 관리적 보호조치(내부관리계획·교육 등) — 실제로 하는 것만
}
REQUIRED = {"operator": "개인정보처리자(운영자) 명칭", "officer_name": "개인정보 보호책임자 성명 또는 직책",
            "officer_email": "보호책임자 연락처(이메일)"}
NOTICE_DAYS, MAJOR_NOTICE_DAYS = 7, 30  # 시행 전 공지 기간 (정보주체 권리에 중요한 변경은 30일)


def settings() -> dict:
    s = {**DEFAULTS, **(settings_store.load().get("privacy") or {})}
    # 메일 발송 업체를 비워 두면 SMTP_HOST 로 채운다 — Gmail 이면 Google LLC(미국) 국외 이전으로 표시
    if not s["smtp_vendor"].strip() and os.environ.get("SMTP_HOST", "").lower().endswith("gmail.com"):
        s["smtp_vendor"], s["smtp_country"] = "Google LLC (Gmail)", "미국"
    return s


def missing() -> list[str]:
    s = settings()
    return [label for k, label in REQUIRED.items() if not str(s.get(k, "")).strip()]


def _claude_on() -> bool:
    try:
        from . import claude_llm
        return claude_llm.provider() == "claude" and bool(claude_llm.api_key())
    except Exception:  # noqa: BLE001
        return False


def _features() -> dict:
    from . import mailer, warehouse
    cfg = settings_store.load()
    return {
        "ask": cfg["ask"]["enabled"] and (bool(os.environ.get("GEMINI_API_KEYS")) or _claude_on()),
        # 2026-11-03 — 관리 > AI 모델 설정에서 Claude 를 고르면 질문·초안이 Anthropic 으로 간다. 의미 검색(임베딩)은 Gemini 키가 있을 때만.
        "gemini": bool(os.environ.get("GEMINI_API_KEYS")),
        "claude": _claude_on(),
        "smtp": mailer.is_configured(),
        "databricks": warehouse.is_configured(),
        "kakao": bool(os.environ.get("KAKAO_JS_KEY")),
    }


def _paid() -> bool:
    """유료 월 구독을 받거나, 아직 이용 기간이 남은 구독자가 있으면 True."""
    from . import membership
    return bool(settings_store.load()["ask"].get("membership")) or membership.active_count() > 0


def records() -> list[dict]:
    """처리 업무별 (업무, 목적, 필수 항목, 선택 항목, 자동 생성 항목, 보유 기간)."""
    R = db.RETENTION_DAYS
    f = _features()
    out = [
        # 2026-10-30: 구독자 질문하기 횟수제·메일 참여 링크 — 브라우저 연결값과 질문 횟수, 메일 링크 클릭 기록이 새로 생겼다
        {"name": "뉴스레터 구독", "purpose": "주간 뉴스레터 발송, 구독 신청 확인, 관심 지역별 노트 우선 발송, 추천 보상 제공, "
                                            "질문하기 무료·충전 횟수 관리, 메일 속 퀴즈·예측 결과 제공",
         "required": "이메일", "optional": "관심 지역",
         "auto": "신청·확인·해지 일시, 추천 코드, 추천인(추천 링크로 구독한 경우), 연결된 브라우저의 쿠키 식별값(zgv), "
                 "질문 지급·사용 횟수와 충전 요청 일시, 메일 링크 클릭 기록",
         "keep": f"구독 해지 시까지 (해지 후 {R['unsubscribed']}일 이내 파기) · 확인하지 않은 신청은 {R['unconfirmed']}일 후 파기"},
        {"name": "문의 접수", "purpose": "문의 확인 및 답변", "required": "이름, 이메일, 문의 내용", "optional": "없음",
         "auto": "접수 일시", "keep": f"접수 후 {R['contacts'] // 30}개월"},
    ]
    if f["ask"] and _paid():
        out.append({"name": "월 구독 신청·이용 (질문하기)", "purpose": "월 구독 안내, 구독 코드 발급, 하루 이용 한도 관리",
                    "required": "이름, 이메일", "optional": "부서·직책",
                    "auto": "이용 기간, 구독 코드(복원할 수 없는 해시로 저장), 질문 횟수",
                    "keep": f"신청 정보는 접수 후 {R['contacts'] // 30}개월 · 이용 정보는 이용 기간 종료 후 {R['members_expired'] // 30}개월"})
    out += [
        {"name": "서비스 이용 기록 (자동 수집)", "purpose": "부정 이용·과다 호출 방지, 보안 점검, 방문 통계",
         "required": "없음", "optional": "없음", "auto": "접속 IP 주소, 접속 일시, 이용한 페이지, 남용 방지용 시도 기록, 1분 둘러보기 판정용 처음 방문 시각(IP별 — 2일 뒤 파기)",
         "keep": f"{R['access_logs']}일"},
        {"name": "참여 기록·화면 설정 (자동 수집)", "purpose": "퀴즈·투표·테스트 결과 제공, 연속 참여 기록, 다음 방문 시 화면 유지, 참여 통계, 방문 패턴 분석(시간대·이동 경로·재방문)",
         "required": "없음", "optional": "없음",
         "auto": "쿠키 식별값(zgv), 퀴즈 답·예측 투표·테스트 결과와 점수, 공유·구독 창 이용 기록, 노트 검색어·필터 등 화면 설정값, 관심 목록(관심 지역·단지·메모 — 본인 브라우저에서만 보임), "
                 "방문 분석용 화면 이동 기록(본 화면 경로와 시각만 — 주소의 검색어·토큰은 저장하지 않음)",
         "keep": f"{R['engagements'] // 30}개월 (화면 설정값은 마지막 방문 후 {R['visitor_state'] // 30}개월)"},
        # 2026-11-02 Phase 1: 내 프로필(/me) — 맞춤 노트·뉴스레터. 구독자면 구독 이메일 기준 사본(subscriber_profile)도 둔다.
        {"name": "내 프로필 (선택)", "purpose": "맞춤 노트·뉴스레터 (나에게 영향 있는 노트 고르기, 노트 '내 조건' 보기, 계산기 입력 채우기, "
                                          "구독자는 뉴스레터 맞춤 구성, 알림을 켠 구독자에게 청약 접수 3일 전·전세 만기 90일·30일 전 알림 메일)",
         "required": "없음",
         "optional": "유형(무주택·1주택 갈아타기·임차인·투자 관심), 관심 지역(시군구 3곳까지), 예산 범위, 연소득(세전), 기존 부채 연 원리금, "
                     "청약 항목(무주택 기간·부양가족 수·청약통장 가입 기간), 전세 계약 만기일(임차인만), "
                     "알림 설정(전세 만기 알림 여부, 알림 받을 청약 공고 20개까지)",
         "auto": "테스트 결과 요약(성향 유형·준비도 점수·내 집 마련 전략·공부 습관 단계), 저장 일시, "
                 "구독자인 경우 구독 이메일과의 연결, 알림 메일 발송 기록(알림 종류·대상 공고·발송 시각 — 같은 알림을 두 번 보내지 않기 위함)",
         "keep": f"마지막 방문 후 {R['visitor_state'] // 30}개월 · 구독자 사본은 구독 해지 시 즉시 파기 "
                 "· 알림 발송 기록도 구독 해지 시 즉시 파기 ('내 프로필'에서 지우기·'내 기록 지우기'로 언제든 삭제)"},
        # 2026-11-02 메일 링크 로그인·내 공간 — 계정 이메일, 로그인 링크(해시), 내 공간 저장값(관심 공고·저장한 노트·계산·메모)
        # 2026-11-03 기기별 로그인(account_sessions) — 기기 식별값 해시·User-Agent·사용 일시
        {"name": "로그인 계정·내 공간 (선택)", "purpose": "메일 링크 로그인, 여러 기기에서 같은 설정·관심 목록 보기, 내 공간(관심 단지·관심 공고·저장한 노트·저장한 계산·메모) 제공, "
                                               "보미AI에서 본인이 켠 경우 내 공간 자료를 참고한 답변",
         "required": "이메일", "optional": "관심 공고, 저장한 노트, 저장한 계산(입력값·결과 요약), 메모",
         "auto": "가입·마지막 로그인 일시, 로그인 링크·확인 코드(복원할 수 없는 해시로 저장, 30분 뒤 만료), 계정에 연결된 쿠키 식별값(zgv), "
                 "로그인한 기기 정보(기기별 식별값의 해시, 브라우저 정보(User-Agent), 처음·최근 사용 일시 — '로그인한 기기' 목록과 기기별 로그아웃용)",
         "keep": "'내 기록 지우기'로 탈퇴할 때까지 (계정의 내 공간 저장값은 오래 접속하지 않아도 지우지 않음) · 만료된 로그인 링크는 다음 발급 때 파기 "
                 "· 로그인한 기기 정보는 그 기기 로그아웃·모든 기기 로그아웃·탈퇴 때, 또는 1년 동안 쓰지 않으면 파기"},
        {"name": "참여 통계 프로필 (선택)", "purpose": "성별·연령대·지역별 참여 통계, 참여 지도(3명 미만 칸은 공개하지 않음)",
         "required": "없음", "optional": "성별, 연령대, 국가, 국내 시·도", "auto": "없음",
         "keep": f"마지막 참여 후 {R['profiles'] // 30}개월 ('바꾸기'로 수정·'내 기록 지우기'로 삭제)"},
    ]
    return out


def entrustments() -> list[dict]:
    """처리 위탁 (수탁자, 위탁 업무) — 켜져 있는 기능만."""
    s, f = settings(), _features()
    out = []
    if f["smtp"]:
        out.append({"to": s["smtp_vendor"] or "메일 발송 서버 운영사 (SMTP)", "work": "구독 확인·뉴스레터·로그인 링크·알림 메일 발송"})
    if f["ask"] and f["claude"]:
        out.append({"to": "Anthropic, PBC (Claude API)", "work": "보미AI 답변 생성, 노트 초안 작성 (질문·대화 처리 — Anthropic 정책에 따라 처리·보관)"})
    if f["ask"] and f["gemini"]:
        out.append({"to": "Google LLC (Gemini API)", "work": "보미AI 답변 생성, 노트 초안 작성, 노트 의미 검색 (질문·검색어 처리 — Google 정책에 따라 처리·보관 (무료 이용 등급은 Google이 서비스 개선·사람 검토에 이용할 수 있음 — 민감한 개인정보는 입력하지 마세요))"})
    if f["databricks"]:
        out.append({"to": "Databricks, Inc.", "work": "서비스 이용 통계 분석용 데이터 보관 (이름·이메일·IP 제외)"})
    out.append({"to": "Tailscale Inc.", "work": "공개 주소 접속 중계 (접속 IP가 지나감)"})
    return out


def overseas() -> list[dict]:
    """국외 이전 (제28조의8) — 위탁·보관으로 국외로 가는 경우. 연락처는 각 사 처리방침 문의처."""
    s, f = settings(), _features()
    out = []
    if f["ask"] and f["claude"]:
        out.append({"to": "Anthropic, PBC", "country": "미국", "items": "질문·대화 일부 (본인이 입력한 내용), 보미AI에서 '내 공간 자료 참고'를 켠 경우 내 프로필·관심 단지·관심 공고·저장한 노트·메모",
                    "when": "질문할 때마다 암호화된 네트워크로 전송", "purpose": "답변 생성 — Anthropic 정책에 따라 처리·보관",
                    "contact": "https://www.anthropic.com/legal/privacy", "refuse": "보미AI를 쓰지 않으면 이전되지 않음 (거부 시 해당 기능만 이용 불가)"})
    if f["ask"] and f["gemini"]:
        out.append({"to": "Google LLC", "country": "미국", "items": "질문·대화 일부, 의미 검색어 (본인이 입력한 내용), 보미AI에서 '내 공간 자료 참고'를 켠 경우 내 프로필·관심 단지·관심 공고·저장한 노트 제목·메모 요약",
                    "when": "질문·검색할 때마다 암호화된 네트워크로 전송", "purpose": "답변 생성·검색 — Google 정책에 따라 처리·보관 (무료 이용 등급은 Google이 서비스 개선·사람 검토에 이용할 수 있음 — 민감한 개인정보는 입력하지 마세요) · 이 사이트는 질문 원문을 저장하지 않음",
                    "contact": "https://policies.google.com/privacy", "refuse": "보미AI·의미 검색을 쓰지 않으면 이전되지 않음 (거부 시 해당 기능만 이용 불가)"})
    if f["databricks"]:
        out.append({"to": "Databricks, Inc.", "country": s["databricks_region"], "items": "참여 기록·선택 프로필 (쿠키 식별값 기준, 이름·이메일·IP 제외)",
                    "when": "작업 후 수시, 암호화된 네트워크로 전송", "purpose": "이용 통계 분석, 이 사이트의 보유 기간과 같음",
                    "contact": "https://www.databricks.com/legal/privacynotice", "refuse": "'내 기록 지우기'로 삭제 (다음 적재 때 반영)"})
    out.append({"to": "Tailscale Inc.", "country": "캐나다·미국", "items": "접속 IP 주소, 요청 정보",
                "when": "접속할 때마다 (중계 서버 경유)", "purpose": "공개 주소 접속 중계 (저장 기간은 Tailscale 정책에 따름)",
                "contact": "https://tailscale.com/privacy-policy", "refuse": "거부 시 공개 주소로 접속할 수 없음"})
    if f["smtp"] and s["smtp_country"] and s["smtp_country"] != "대한민국":
        out.append({"to": s["smtp_vendor"] or "메일 발송 업체", "country": s["smtp_country"], "items": "이메일",
                    "when": "메일 발송 시", "purpose": "메일 발송 (업체 정책에 따른 기간)", "contact": "업체 개인정보처리방침",
                    "refuse": "거부 시 구독·메일 로그인을 할 수 없음"})
    return out


def active() -> bool:
    """처리하는 개인정보가 있는지 — 없으면 처리방침 페이지·링크를 표시하지 않는다."""
    return bool(records())


# ───────────────────────── 버전 (공지일·시행일별) ─────────────────────────

_SQL = """CREATE TABLE IF NOT EXISTS privacy_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, announced_at TEXT NOT NULL, effective_date TEXT NOT NULL UNIQUE,
  summary TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, created_at TEXT NOT NULL)"""


# 제8조 안전성 확보 조치·제9조 쿠키 (2026-11-03) — 예전엔 화면 코드(Privacy.tsx)에 고정돼 지난 버전을 열어도 지금 문구가 보였다.
# 이제 공지할 때 이 내용도 함께 고정한다. 바뀌면 outdated() 가 '새 버전 공지' 를 알린다.
MEASURES = [
    "관리 화면 접근 통제 — 관리자 로그인(토큰과 OTP 2단계 인증), 30분 동안 쓰지 않으면 자동 차단, 로그인 5회 실패 시 잠금",
    "관리자 접속기록 2년 보관·위변조 방지(해시 연결)·정기 점검, 개인정보 내려받기·전체 보기 시 사유 기록, 관리 화면의 이메일 가림 표시",
    "전송 구간 암호화(HTTPS), 서버는 외부에서 직접 접속할 수 없게 내부 주소에만 열어 둠",
    "로그인 링크·확인 코드·기기 식별값·구독 코드는 복원할 수 없는 해시로, IP 대체 식별값과 쿠키는 서버 비밀값으로 서명·해시 처리",
    "접속 기록 보관과 남용 시도 제한, 오류 화면에 내부 정보 비노출",
    "데이터 백업과 무결성 검사, 보유 기간이 지난 정보 자동 파기",
]
COOKIES = [
    {"name": "zgv", "purpose": "방문자 구분 — 저장한 설정·관심 목록·참여 기록을 이 브라우저와 잇습니다. 로그인하면 계정에 연결된 이 기기의 식별값이 됩니다.",
     "keep": "1년(방문할 때마다 연장), 로그아웃하면 새 값"},
    {"name": "zgt", "purpose": "로그인 전 1분 둘러보기를 시작한 시각(서버 서명값)", "keep": "1년"},
    {"name": "zgl", "purpose": "로그인 메일을 요청한 브라우저 확인(한 번만 사용)", "keep": "30분, 로그인하면 바로 삭제"},
    {"name": "zga", "purpose": "관리자 로그인 세션(운영자만 받음)", "keep": "브라우저를 닫을 때까지, 30분 미사용·8시간이면 무효"},
]
STORAGE = ("브라우저 저장소(localStorage·sessionStorage)에는 화면 설정(밝기 테마·언어·표 보기 개수), 안내 띠 닫기, 보미AI '내 자료 참고' 선택, "
           "아직 서버로 보내지 못한 변경(zg-unsaved — 다음 방문 때 다시 보낸 뒤 지움)만 둡니다. 저장한 노트·관심 목록·메모·일정은 서버에 저장되며, "
           "이 브라우저의 쿠키 또는 로그인 계정과 연결됩니다.")
COOKIE_REFUSE = ("쿠키를 막으면 로그인과 둘러보기가 동작하지 않아 서비스를 이용하기 어렵습니다(사이트 이용에 꼭 필요한 쿠키만 씁니다). "
                 "광고·행태 추적용 쿠키는 쓰지 않습니다.")


def snapshot() -> dict:
    """지금 기능·설정으로 만든 처리방침 내용 (공지할 때 이대로 고정된다)."""
    s = settings()
    return {"settings": {k: s[k] for k in DEFAULTS}, "records": records(), "entrustments": entrustments(),
            "overseas": overseas(), "retention": dict(db.RETENTION_DAYS), "backup_days": 14,
            "measures": list(MEASURES), "cookies": [dict(c) for c in COOKIES], "storage": STORAGE, "cookie_refuse": COOKIE_REFUSE}


def _conn():
    conn = db.connect()
    conn.execute(_SQL)
    return conn


def versions() -> list[dict]:
    """공지한 버전 (시행일 최신순). status: 시행 예정 / 시행 중 / 이전."""
    today = date.today().isoformat()
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM privacy_versions ORDER BY effective_date DESC")]
    finally:
        conn.close()
    current_found = False
    for r in rows:
        r["content"] = json.loads(r["content"])
        if r["effective_date"] > today:
            r["status"] = "시행 예정"
        elif not current_found:
            r["status"], current_found = "시행 중", True
        else:
            r["status"] = "이전"
    return rows


def current() -> dict | None:
    return next((v for v in versions() if v["status"] == "시행 중"), None)


def upcoming() -> list[dict]:
    return [v for v in versions() if v["status"] == "시행 예정"]


def publish(effective_date: str, summary: str, major: bool = False) -> int:
    """지금 내용을 새 버전으로 공지한다. 시행일은 오늘 + 공지 기간(중요 변경 30일, 그 밖 7일) 이후여야 한다.
    처음 게시(이전 버전 없음)는 바로 시행할 수 있다."""
    if missing():
        raise ValueError("필수 기재사항이 비어 있습니다: " + ", ".join(missing()))
    eff = date.fromisoformat(effective_date)
    first = not versions()
    need = 0 if first else (MAJOR_NOTICE_DAYS if major else NOTICE_DAYS)
    if (eff - date.today()).days < need:
        raise ValueError(f"시행일은 공지일로부터 {need}일 뒤 이후여야 합니다" + (" (중요 변경)" if major else ""))
    conn = _conn()
    try:
        with conn:
            return conn.execute(
                "INSERT INTO privacy_versions (announced_at, effective_date, summary, content, created_at) VALUES (?,?,?,?,?)",
                (date.today().isoformat(), eff.isoformat(), summary.strip() or "개인정보 처리방침 제정" if first else summary.strip(),
                 json.dumps(snapshot(), ensure_ascii=False), datetime.now().isoformat(timespec="seconds"))).lastrowid
    finally:
        conn.close()


def withdraw(version_id: int) -> bool:
    """시행 전인 공지만 거둘 수 있다 (시행했거나 지난 버전은 기록으로 남긴다)."""
    conn = _conn()
    try:
        with conn:
            return conn.execute("DELETE FROM privacy_versions WHERE id = ? AND effective_date > ?",
                                (version_id, date.today().isoformat())).rowcount == 1
    finally:
        conn.close()


def changed_parts() -> list[str]:
    """가장 최근 공지와 지금 내용이 다른 부분 (관리 화면이 '무엇이 달라졌는지' 보여 준다, 2026-11-03)."""
    vs = versions()
    if not vs:
        return []
    old, new = vs[0]["content"] or {}, json.loads(json.dumps(snapshot(), ensure_ascii=False))
    names = {"settings": "기재사항(운영자·보호책임자 등)", "records": "처리 업무 표(수집 항목·목적·보유)", "entrustments": "처리 위탁",
             "overseas": "국외 이전", "retention": "보유 기간", "backup_days": "백업 보관 기간", "measures": "제8조 안전성 확보 조치",
             "cookies": "제9조 쿠키", "storage": "제9조 브라우저 저장소", "cookie_refuse": "제9조 쿠키 거부 시 불이익"}
    return [names.get(k, k) for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]


def outdated() -> bool:
    """지금 기능·설정이 가장 최근에 공지한 버전과 다르면 True — 새 버전을 공지해야 한다."""
    vs = versions()
    return bool(vs) and vs[0]["content"] != json.loads(json.dumps(snapshot(), ensure_ascii=False))
