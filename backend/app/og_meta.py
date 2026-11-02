"""링크 공유 미리보기(제목·설명·썸네일).

카톡·슬랙 등 링크 미리보기는 자바스크립트를 실행하지 않고 첫 HTML의 <meta>만 읽는다.
React 빌드(frontend/dist/index.html)를 내보낼 때마다 render()가 페이지별 제목·설명·썸네일을 넣는다
(api/main.py 의 SPA 응답). 파일에 써 두지 않으므로 npm run build 로 dist 를 다시 만들어도 빠지지 않는다.

    python -m app.og_meta   # 썸네일(static/og.png) 다시 만들기
"""
from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OG_IMAGE = ROOT / "static" / "og.png"
INDEX = ROOT.parent / "frontend" / "dist" / "index.html"  # React 빌드 결과

# 링크 공유 미리보기(카카오톡·LinkedIn·슬랙 등)의 제목·설명. 카카오톡은 30자, 설명은 2줄 안팎만 보이므로 앞쪽에 핵심을 둔다.
TITLE = "ZipGenie 집지니 — 내 집 마련을 위한 부동산 리서치"
DESCRIPTION = ("흩어진 시세·정책·청약 정보를 매일 모아 읽고, 나에게 필요한 것만 정리해 둡니다. "
               "실수요자 체크리스트와 이번 주 꼭 알아야 할 3가지를 무료 뉴스레터로 받아 보세요.")
_START, _END = "<!-- zipgenie-og -->", "<!-- /zipgenie-og -->"

# 페이지별 공유 미리보기 — (제목, 설명, 썸네일). 썸네일 None 이면 static/og.png.
# 노트 상세(/n/…)·결과 공유(/s/…)는 app/web.py 가 따로 만든다.
PAGES: dict[str, tuple[str, str, str | None]] = {
    "/notes": ("부동산 노트 — 시세·정책·청약 정리 | ZipGenie",
               "시세·정책·청약 뉴스를 요약·실수요자 체크리스트·투자자 관점으로 정리한 노트. 지역·분류별로 찾아보세요.", None),
    "/today": ("오늘의 부동산 — 1분 퀴즈와 오늘의 용어 | ZipGenie",
               "매일 바뀌는 부동산 퀴즈와 예측, 오늘의 용어로 시장 감각을 하루 1분씩 쌓아 보세요.", None),
    "/lab": ("부동산 데이터 랩 — 숫자로 보는 시장 흐름 | ZipGenie",
             "수집한 기사·노트에서 뽑은 키워드 흐름과 지역별 움직임을 차트와 지도로 봅니다.", None),
    "/ask": ("질문하기 — 쌓인 노트로 답하는 부동산 AI | ZipGenie",
             "대출·청약·세금·시세 고민을 물어보면 ZipGenie에 쌓인 노트와 기사를 근거로 답합니다. 무료로 3번 써 보세요.", None),
    "/about": ("ZipGenie 소개 | ZipGenie",
               "내 집 마련과 부동산 결정을 위해 시세·정책·청약 자료를 찾고, 정리하고, 쌓아 두는 프라이빗 리서치입니다.", None),
    "/type": ("부동산 성향 테스트 — 나는 어떤 유형일까? | ZipGenie",
              "12문항으로 알아보는 16가지 부동산 성향. 실거주·투자, 안정·공격, 입지·상품, 데이터·현장 중 나의 스타일을 확인해 보세요.", None),
    "/terms": ("부동산 용어 퀴즈 — 몇 개나 알고 있을까? | ZipGenie",
               "LTV·DSR·청약 가점·종부세·계약갱신청구권… 집을 살 때 꼭 나오는 용어를 퀴즈로 점검해 보세요.", None),
    "/diagnosis": ("내 집 마련 준비도 자가진단 — 나는 몇 단계? | ZipGenie",
                   "자금·대출, 정보·지역, 실행·계약 12문항에 답하면 내 준비 단계와 다음 할 일을 알려 드립니다.", None),
    "/habit": ("부동산 공부 습관 진단 — 나는 얼마나 꾸준히 보고 있을까? | ZipGenie",
               "10문항으로 시세 확인·정책 확인·임장·자금 점검·기록 5개 영역을 점검하고, 내 단계와 다음에 해 볼 3가지를 알려 드립니다.", None),
    "/career": ("내 집 마련 전략 — 나에게 맞는 길은? | ZipGenie",
                "10문항으로 청약·급매·경매·갈아타기·전세 유지·분양권 중 나에게 맞는 내 집 마련 전략을 알려 드립니다.", None),
    "/deals": ("아파트 실거래가 — 지역·월별 조회 | ZipGenie",
               "국토교통부 실거래가 공개 자료로 시군구·월별 아파트 매매 거래와 평당가·㎡당 가격을 확인하세요.", None),
    "/calc": ("내 집 계산기 — 대출 한도·취득세·청약 가점 | ZipGenie",
              "LTV·DSR 대출 한도와 월 상환액, 취득세 간이 계산, 청약 가점, 전세가율·갭을 브라우저에서 바로 계산합니다.", None),
    "/now": ("현행 수치 — 대출 규제·금리·취득세·청약 | ZipGenie",
             "DSR·LTV·기준금리·주담대 금리·취득세율·청약 가점 만점을 기준일과 근거 링크와 함께 한곳에서 봅니다.", None),
    "/calendar": ("분양 일정·당첨 가점 — 청약 달력 | ZipGenie",
                  "청약홈·LH 공고의 접수·발표 일정을 달력으로 보고, 최근 당첨 가점을 내 가점과 비교합니다. 접수 3일 전 알림 메일도 받을 수 있어요.", None),
    "/letter": ("ZipGenie 뉴스레터 미리보기 | ZipGenie",
                "매주 부동산 흐름을 한 줄로 묶고 꼭 알아야 할 3가지를 정리해 보내 드립니다. 무료 구독.", None),
    "/privacy": ("개인정보 처리방침 | ZipGenie", "ZipGenie 개인정보 처리방침.", None),
}


NOINDEX = {"admin", "confirm", "unsubscribe", "refer", "me", "my-homes"}  # me: 개인 프로필 화면 · my-homes: 관심 단지 (개인)


def page_meta(path: str) -> tuple[str, str, str | None]:
    path = "/" + path.strip("/")
    return PAGES.get(path, (TITLE, DESCRIPTION, None))


def _block(site_url: str, path: str = "/") -> str:
    site = site_url.rstrip("/")
    title, desc, image = page_meta(path)
    img = f"{site}{image or '/app/static/og.png'}"
    known = path.strip("/") in {p.strip("/") for p in PAGES}
    url = site + ("/" + path.strip("/") if known else "/")
    t, d = escape(title), escape(desc)
    first = path.strip("/").split("/")[0]
    # canonical 은 페이지가 분명한 경로(홈·PAGES)에만 — 모르는 경로(404 등)에 홈을 canonical 로 주면 검색 엔진이 혼동한다
    canonical = f'<link rel="canonical" href="{escape(url)}" />' if known or not first else ""
    # 개인 화면·확인 링크는 색인하지 않는다 (robots.txt 와 같은 목록)
    robots = '<meta name="robots" content="noindex" />' if first in NOINDEX else ""
    return f"""{_START}
    <meta name="description" content="{d}" />
    {canonical}{robots}
    <meta name="theme-color" content="#120F08" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="ZipGenie" />
    <meta property="og:locale" content="ko_KR" />
    <meta property="og:title" content="{t}" />
    <meta property="og:description" content="{d}" />
    <meta property="og:url" content="{escape(url)}" />
    <meta property="og:image" content="{img}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="ZipGenie" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{t}" />
    <meta name="twitter:description" content="{d}" />
    <meta name="twitter:image" content="{img}" />
    {_END}"""


def render(html: str, path: str = "/", site_url: str | None = None) -> str:
    """React index.html 에 이 페이지의 제목·공유 메타를 넣어 돌려준다 (파일은 건드리지 않음)."""
    site_url = site_url or os.environ.get("SITE_URL", "http://localhost:5030")
    new = re.sub(re.escape(_START) + r".*?" + re.escape(_END) + r"\s*", "", html, flags=re.S)
    new = re.sub(r'\s*<meta name="(description|theme-color)"[^>]*>', "", new)  # 블록에 다시 넣는다
    new = re.sub(r"<title>.*?</title>", f"<title>{escape(page_meta(path)[0])}</title>", new, count=1, flags=re.S)
    new = new.replace('<html lang="en">', '<html lang="ko">', 1)
    return new.replace("</head>", f"{_block(site_url, path)}\n  </head>", 1)


OG_HTML = """<!doctype html><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100,900&family=Noto+Sans+KR:wght@500;700;900&display=swap');
body{margin:0;width:1200px;height:630px;overflow:hidden;font-family:'Noto Sans KR',sans-serif;color:#FBF6E9;
  background:radial-gradient(520px circle at 82% 45%,rgba(217,161,0,.55),transparent 65%),
             linear-gradient(120deg,#120F08 0%,#1C180F 55%,#3A3220 100%);}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,213,74,.06) 1px,transparent 1px),
  linear-gradient(90deg,rgba(255,213,74,.06) 1px,transparent 1px);background-size:48px 48px;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 70%);}
.net{position:absolute;right:-40px;top:0;width:640px;height:630px;opacity:.85}
.net svg{width:100%;height:100%}
.wrap{position:absolute;left:80px;top:70px;width:760px}
.by{font-family:monospace;font-size:22px;letter-spacing:3px;color:#B8AB8A}
h1{font-family:'Archivo',sans-serif;font-stretch:118%;font-weight:900;font-size:112px;line-height:1;margin:20px 0 26px;white-space:nowrap;
  background:linear-gradient(100deg,#FFD54A 5%,#FFE89A 45%,#F5B800 95%);-webkit-background-clip:text;color:transparent}
.lead{font-size:38px;font-weight:900;margin-bottom:14px}
.sub{font-size:24px;color:#E8DEC6;line-height:1.55}
.chips{position:absolute;left:80px;bottom:52px;display:flex;gap:12px}
.chips span{font-size:20px;font-weight:700;padding:8px 18px;border-radius:999px;border:1px solid rgba(255,213,74,.45);color:#FFE89A;
  background:rgba(217,161,0,.18)}
.brand{position:absolute;right:70px;bottom:60px;font-weight:900;font-size:24px;letter-spacing:1px;color:#fff}
.brand b{color:#FFD54A}
</style>
<div class="grid"></div>
<div class="net">NETWORK_SVG</div>
<div class="wrap"><div class="by">&nbsp;</div><h1>ZIP<span style="color:#FFD54A;-webkit-text-fill-color:#FFD54A">GENIE</span></h1>
<div class="lead">내 집 마련을 위한 프라이빗 리서치</div>
<div class="sub">시세·정책·청약을 매일 모아 읽고<br>나에게 필요한 것만 정리해 둡니다.</div></div>
<div class="chips"><span>시장·시세</span><span>정책·세금·대출</span><span>청약·분양·개발</span></div>
<div class="brand">집지니</div>
"""


def make_image() -> Path:
    """1200×630 썸네일을 Playwright로 렌더링한다 (Edge 채널 폴백은 report_pdf와 같은 방식)."""
    from playwright.sync_api import sync_playwright

    # set_content 페이지(about:blank)에서는 file:// 이미지가 막혀서 SVG를 그대로 넣는다(실측).
    net = (ROOT / "static" / "network.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # noqa: BLE001 - 번들 브라우저 미설치
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(OG_HTML.replace("NETWORK_SVG", net), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(OG_IMAGE))
        browser.close()
    return OG_IMAGE


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("thumbnail:", make_image())
