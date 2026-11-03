"""링크 공유 미리보기(제목·설명·썸네일).

카톡·슬랙 등 링크 미리보기는 자바스크립트를 실행하지 않고 첫 HTML의 <meta>만 읽는다.
React 빌드(frontend/dist/index.html)를 내보낼 때마다 render()가 페이지별 제목·설명·썸네일을 넣는다
(api/main.py 의 SPA 응답). 파일에 써 두지 않으므로 npm run build 로 dist 를 다시 만들어도 빠지지 않는다.

    python -m app.og_meta   # 썸네일(static/og.png)과 화면별 썸네일(static/og/page-*.png) 다시 만들기
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
TITLE = "집보미 — 집에 관한 모든 것, 시세·청약·대출·세금까지"
DESCRIPTION = ("아파트 실거래가·청약 일정·대출 한도·세금·정책 변화를 한곳에서. 흩어진 집 이야기를 매일 모아 숫자와 함께 정리하고, "
               "연소득만 넣으면 살 수 있는 집값도 바로 계산해 드립니다. 무료.")
_START, _END = "<!-- zipgenie-og -->", "<!-- /zipgenie-og -->"

# 페이지별 공유 미리보기 — (제목, 설명, 썸네일). 썸네일 None 이면 static/og.png.
# 노트 상세(/n/…)·결과 공유(/s/…)는 app/web.py 가 따로 만든다.
PAGES: dict[str, tuple[str, str, str | None]] = {
    "/notes": ("부동산 노트 — 시세·정책·청약 정리 | 집보미",
               "시세·정책·청약 뉴스를 요약·실수요자 체크리스트·투자자 관점으로 정리한 노트. 지역·분류별로 찾아보세요.", "/app/static/og/page-notes.png"),
    "/today": ("오늘의 부동산 — 1분 퀴즈와 오늘의 용어 | 집보미",
               "매일 바뀌는 부동산 퀴즈와 예측, 오늘의 용어로 시장 감각을 하루 1분씩 쌓아 보세요.", None),
    "/lab": ("부동산 데이터 랩 — 숫자로 보는 시장 흐름 | 집보미",
             "수집한 기사·노트에서 뽑은 키워드 흐름과 지역별 움직임을 차트와 지도로 봅니다.", "/app/static/og/page-lab.png"),
    "/ask": ("보미AI — 쌓인 노트로 답하는 부동산 질문 | 집보미",
             "대출·청약·세금·시세 고민을 물어보면 집보미에 쌓인 노트와 기사를 근거로 답합니다. 메일로 로그인하면 처음 1번 무료예요.", "/app/static/og/page-ask.png"),
    "/about": ("집보미 소개 | 집보미",
               "집에 관한 모든 것 — 시세·청약·대출·세금·정책 자료를 매일 모아 숫자와 함께 정리합니다.", None),
    "/type": ("부동산 성향 테스트 — 나는 어떤 유형일까? | 집보미",
              "12문항으로 알아보는 16가지 부동산 성향. 실거주·투자, 안정·공격, 입지·상품, 데이터·현장 중 나의 스타일을 확인해 보세요.", None),
    "/terms": ("부동산 용어 퀴즈 — 몇 개나 알고 있을까? | 집보미",
               "LTV·DSR·청약 가점·종부세·계약갱신청구권… 집을 살 때 꼭 나오는 용어를 퀴즈로 점검해 보세요.", None),
    "/diagnosis": ("내 집 마련 준비도 자가진단 — 나는 몇 단계? | 집보미",
                   "자금·대출, 정보·지역, 실행·계약 12문항에 답하면 내 준비 단계와 다음 할 일을 알려 드립니다.", None),
    "/habit": ("부동산 공부 습관 진단 — 나는 얼마나 꾸준히 보고 있을까? | 집보미",
               "10문항으로 시세 확인·정책 확인·임장·자금 점검·기록 5개 영역을 점검하고, 내 단계와 다음에 해 볼 3가지를 알려 드립니다.", None),
    "/career": ("내 집 마련 전략 — 나에게 맞는 길은? | 집보미",
                "10문항으로 청약·급매·경매·갈아타기·전세 유지·분양권 중 나에게 맞는 내 집 마련 전략을 알려 드립니다.", None),
    "/deals": ("아파트 실거래가 — 지역·월별 조회 | 집보미",
               "국토교통부 실거래가 공개 자료로 시군구·월별 아파트 매매 거래와 평당가·㎡당 가격을 확인하세요.", "/app/static/og/page-deals.png"),
    "/calc": ("내 집 계산기 — 대출 한도·취득세·청약 가점 | 집보미",
              "LTV·DSR 대출 한도와 월 상환액, 취득세 간이 계산, 청약 가점, 전세가율·갭을 브라우저에서 바로 계산합니다.", "/app/static/og/page-calc.png"),
    "/now": ("현행 수치 — 대출 규제·금리·취득세·청약 | 집보미",
             "DSR·LTV·기준금리·주담대 금리·취득세율·청약 가점 만점을 기준일과 근거 링크와 함께 한곳에서 봅니다.", "/app/static/og/page-now.png"),
    "/calendar": ("분양 일정·당첨 가점 — 청약 달력 | 집보미",
                  "청약홈·LH 공고의 접수·발표 일정을 달력으로 보고, 최근 당첨 가점을 내 가점과 비교합니다. 접수 3일 전 알림 메일도 받을 수 있어요.", "/app/static/og/page-calendar.png"),
    "/letter": ("집보미 뉴스레터 미리보기 | 집보미",
                "매주 부동산 흐름을 한 줄로 묶고 꼭 알아야 할 3가지를 정리해 보내 드립니다. 무료 구독.", None),
    "/map": ("부동산 지도 — 지역별 시세와 청약 위치 | 집보미",
             "시군구별 거래량·중위 가격과 분양 단지 위치를 지도에서 한눈에 봅니다.", "/app/static/og/page-map.png"),
    "/privacy": ("개인정보 처리방침 | 집보미", "집보미 개인정보 처리방침.", None),
}


NOINDEX = {"admin", "confirm", "unsubscribe", "refer", "me", "my-homes", "my", "login"}  # me: 개인 프로필 화면 · my-homes: 관심 단지 (개인)


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
    <meta property="og:site_name" content="집보미" />
    <meta property="og:locale" content="ko_KR" />
    <meta property="og:title" content="{t}" />
    <meta property="og:description" content="{d}" />
    <meta property="og:url" content="{escape(url)}" />
    <meta property="og:image" content="{img}" />
    <meta property="og:image:secure_url" content="{img}" />
    <meta property="og:image:type" content="image/png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="{t}" />
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
.logo{display:flex;align-items:center;gap:26px;margin-top:6px}
.logo .house{width:118px;height:126px;flex:none}
.logo h1{margin:0;font-size:104px}
h1 .w{color:#FBF6E9;-webkit-text-fill-color:#FBF6E9}
.tag{font-size:26px;font-weight:700;color:#FFD54A;margin:10px 0 30px 144px}
body::after{content:'';position:absolute;left:0;right:0;bottom:0;height:12px;background:linear-gradient(90deg,#F5B800,#FFD54A)}
.brand b{color:#FFD54A}
</style>
<div class="grid"></div>
<div class="net">NETWORK_SVG</div>
<div class="wrap"><div class="logo"><svg class="house" viewBox="0 0 28 30"><path d="M3 15.2 14 5.5l11 9.7" fill="none" stroke="#F5B800" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M6.5 14.2V26a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V14.2L14 7.8z" fill="#F5B800"/><circle cx="14" cy="17.6" r="2.3" fill="#120F08"/><path d="M12.9 18.8h2.2l.7 5h-3.6z" fill="#120F08"/><circle cx="23.5" cy="6.5" r="1.4" fill="#FFD54A"/></svg><h1><span class="w">ZIP</span>BOMI</h1></div><div class="tag">집보미 · 집을 봐 주는 비서</div>
<div class="lead">LEAD</div>
<div class="sub">SUB</div></div>
<div class="chips">CHIPS</div>
<div class="brand">집보미</div>
"""


# 홈 썸네일과 화면별 썸네일 문구 — (큰 문구, 작은 문구, 칩)
HOME_CARD = ("집에 관한 모든 것", "실거래가·청약 일정·대출 한도·세금·정책을<br>한곳에서 숫자와 함께 확인하세요.",
             ["실거래가", "청약 달력", "대출·세금 계산기", "현행 수치"])
PAGE_CARDS: dict[str, tuple[str, str, list[str]]] = {
    "notes": ("부동산 노트", "시세·정책·청약 소식을<br>실수요자 기준으로 정리했어요.", ["시장·시세", "정책·세금·대출", "청약·분양·개발"]),
    "deals": ("아파트 실거래가", "시군구·월별 거래와 3.3㎡당 가격,<br>단지별 추이를 확인하세요.", ["국토교통부 공개 자료", "매매·전월세", "단지 검색"]),
    "calc": ("내 집 계산기", "대출 한도·월 상환액·취득세·청약 가점을<br>바로 계산합니다.", ["LTV·DSR", "취득세", "청약 가점", "전세가율"]),
    "now": ("지금 적용되는 숫자", "기준금리·주담대 금리·LTV·DSR·취득세율을<br>기준일과 출처까지 한곳에.", ["금리", "대출 규제", "세율", "시장 심리"]),
    "calendar": ("분양 일정 달력", "청약 접수·발표 일정을 달력으로 보고<br>접수 3일 전 알림을 받으세요.", ["청약홈", "LH", "당첨 가점 비교"]),
    "ask": ("부동산 질문하기", "대출·청약·세금 고민을 물어보면<br>쌓인 노트와 기사를 근거로 답해요.", ["근거 링크", "노트·기사 검색"]),
    "lab": ("부동산 데이터 랩", "키워드 흐름과 지역별 움직임을<br>차트와 지도로 봅니다.", ["키워드 흐름", "지역 지도"]),
    "map": ("부동산 지도", "지역별 거래량·중위 가격과<br>분양 단지 위치를 한눈에.", ["시군구 시세", "청약 위치"]),
}


def _card_html(net: str, card: tuple[str, str, list[str]]) -> str:
    lead, sub, chips = card
    return (OG_HTML.replace("NETWORK_SVG", net).replace("LEAD", lead).replace("SUB", sub)
            .replace("CHIPS", "".join(f"<span>{c}</span>" for c in chips)))


def make_page_images() -> list[Path]:
    """화면별 썸네일 static/og/page-<이름>.png — 공유 미리보기에서 어느 화면인지 보이게."""
    from playwright.sync_api import sync_playwright

    net = (ROOT / "static" / "network.svg").read_text(encoding="utf-8")
    out = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # noqa: BLE001 - 번들 브라우저 미설치
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for name, card in PAGE_CARDS.items():
            page.set_content(_card_html(net, card), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            path = ROOT / "static" / "og" / f"page-{name}.png"
            page.screenshot(path=str(path))
            out.append(path)
        browser.close()
    return out


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
        page.set_content(_card_html(net, HOME_CARD), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(OG_IMAGE))
        browser.close()
    return OG_IMAGE


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("thumbnail:", make_image())
    for path in make_page_images():
        print("page:", path)
