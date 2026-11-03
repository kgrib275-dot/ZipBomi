"""공유 미리보기·결과 카드 이미지 (1200×630) — 유형 16장, 자가진단 단계 4장, 노트 카드(요청 때 1장씩).

카카오톡·LinkedIn은 링크의 og:image를 미리보기로 쓰므로 결과마다 다른 이미지를 준다(app/web.py의 /s/… 주소).
같은 이미지를 '결과 카드 이미지 받기'로도 내려 LinkedIn 피드에 올릴 수 있게 한다.
내용(유형 이름·한 줄 설명)이 바뀌면 다시 만든다:  python -m app.og_cards
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "og"

# 자가진단 단계 (api/routers/play.py LEVELS와 같은 이름·색)
DIAG_LEVELS = [("탐색", "#B8AB8A", "내 집 마련 첫걸음 — 자기 자금과 관심 지역부터 정하세요"),
               ("준비", "#FFD54A", "시세와 대출 한도를 알아보기 시작한 단계"),
               ("실행 직전", "#F5B800", "임장·청약 자격까지 확인한, 결정만 남은 단계"),
               ("실행 가능", "#0ca30c", "자금·정보·계약 절차까지 갖춘 준비된 매수자")]

_CSS = """
*{box-sizing:border-box;margin:0}
body{width:1200px;height:630px;overflow:hidden;font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#FBF6E9;
  background:radial-gradient(900px 500px at 85% 20%,rgba(217,161,0,.55),transparent 60%),
             radial-gradient(700px 420px at 0% 100%,rgba(245,184,0,.25),transparent 60%),#120F08;}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,213,74,.06) 1px,transparent 1px),
  linear-gradient(90deg,rgba(255,213,74,.06) 1px,transparent 1px);background-size:48px 48px}
.wrap{position:absolute;left:80px;top:70px;right:80px}
.k{font:700 22px/1 'Consolas',monospace;letter-spacing:4px;color:#FFD54A}
.emo{font-size:150px;line-height:1;position:absolute;right:90px;top:120px;
  font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif}
h1{font-size:72px;font-weight:900;line-height:1.15;margin:26px 0 10px;max-width:820px}
.code{font:800 34px/1 'Consolas',monospace;letter-spacing:6px;color:#FFE89A}
.line{font-size:30px;line-height:1.5;color:#E8DEC6;margin-top:26px;max-width:860px}
.foot{position:absolute;left:80px;right:80px;bottom:56px;display:flex;justify-content:space-between;align-items:center}
.cta{font-size:24px;font-weight:700;padding:12px 26px;border-radius:999px;background:#F5B800;color:#1A1405}
.brand{font-weight:900;font-size:26px;letter-spacing:1px}.brand b{color:#FFD54A}
.score{font-size:150px;font-weight:900;line-height:1;margin-top:18px}
.lv{font-size:46px;font-weight:900;margin-top:6px}
"""


def _page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body><div class='grid'></div>{body}</body></html>"


def type_html(code: str) -> str:
    from app import ax_types
    emoji, name, line, *_ = ax_types.TYPES[code]
    return _page(f"""<div class="wrap"><div class="k">REAL ESTATE TYPE</div><h1>{escape(name)}</h1>
<div class="code">{escape(code)}</div><div class="line">{escape(line)}</div></div><div class="emo">{emoji}</div>
<div class="foot"><span class="cta">나의 부동산 성향은? 12문항 테스트 →</span><span class="brand">ZIP<b>BOMI</b></span></div>""")


def diag_html(i: int) -> str:
    name, color, line = DIAG_LEVELS[i]
    return _page(f"""<div class="wrap"><div class="k">MY HOME READINESS CHECK</div>
<div class="lv" style="color:{color};margin-top:34px">● {escape(name)} 단계</div><h1 style="margin-top:12px">나의 내 집 마련 준비도</h1>
<div class="line">{escape(line)}</div></div>
<div class="foot"><span class="cta">12문항 · 3분 자가진단 →</span><span class="brand">ZIP<b>BOMI</b></span></div>""")


def note_html(note: dict) -> str:
    """노트 공유 카드 — 제목(최대 3줄 말줄임)·분류 칩·집보미."""
    title = str(note.get("title") or "")
    cat = str(note.get("category") or "")
    kind = str(note.get("kind") or "")
    chips = "".join(f'<span class="chip">{escape(c)}</span>' for c in (cat, kind) if c)
    return _page(f"""<div class="wrap"><div class="k">ZIPBOMI NOTE</div>
<div class="chips" style="margin-top:28px;display:flex;gap:12px">{chips}</div>
<h1 class="nt" style="font-size:66px;margin-top:22px;max-width:1040px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden">{escape(title)}</h1></div>
<style>.chip{{font-size:24px;font-weight:700;padding:8px 20px;border-radius:999px;border:1px solid rgba(255,213,74,.45);color:#FFE89A;background:rgba(217,161,0,.18)}}</style>
<div class="foot"><span class="cta">요약 · 체크리스트 · 투자자 관점까지 3분 →</span><span class="brand">ZIP<b>BOMI</b></span></div>""")


def note_path(note_id: int) -> Path:
    return OUT / f"note-{int(note_id)}.png"


def note_fresh(note: dict) -> bool:
    """노트 카드 파일이 있고, 노트의 게시일·생성 시각보다 새로우면 True (그보다 오래되면 다시 만든다)."""
    p = note_path(note["id"])
    if not p.is_file():
        return False
    stamps = []
    for v in (note.get("published"), note.get("created_at")):
        try:
            stamps.append(datetime.fromisoformat(str(v)).timestamp())
        except (TypeError, ValueError):
            pass
    return p.stat().st_mtime >= max(stamps, default=0)


_pending: set[int] = set()
_failed: dict[int, float] = {}  # 실패한 노트 id → 시각. 10분 동안 다시 시도하지 않는다 (브라우저가 없을 때 매 요청마다 띄우지 않게)
_lock = threading.Lock()


def render_note(note: dict) -> Path:
    """노트 카드 1장 — make_all 과 같은 Playwright(Edge) 렌더링. 번들 브라우저가 있으면 그것을 먼저 쓴다."""
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    path = note_path(note["id"])
    tmp = path.with_suffix(".tmp.png")  # 다 그리기 전의 파일이 og:image 로 나가지 않게 임시 이름으로 쓴 뒤 바꾼다
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # noqa: BLE001 - 번들 브라우저 미설치
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(note_html(note))
        page.wait_for_timeout(150)
        page.screenshot(path=str(tmp))
        browser.close()
    tmp.replace(path)
    return path


def render_note_async(note: dict) -> None:
    """브라우저 렌더링은 느릴 수 있어 백그라운드 스레드에서 만든다. 다 될 때까지는 호출 쪽이 기본 og.png 를 쓴다."""
    nid = int(note["id"])
    with _lock:
        if nid in _pending or time.time() - _failed.get(nid, 0) < 600:
            return
        _pending.add(nid)

    def run():
        from pipeline.xlock import xlock
        try:
            # PC 전체에서 브라우저는 한 번에 하나만 (2026-11-03) — 예전엔 프로세스마다·노트마다 Chromium 을 띄워, 검색 엔진이 노트를
            # 한꺼번에 긁으면 브라우저가 수십 개 떠 PC 자원이 바닥났다. 이미 누가 그리고 있으면 이번엔 건너뛰고(og.png) 다음 요청 때 다시.
            with xlock("og_render", wait=False) as got:
                if got:
                    render_note(note)
                    _failed.pop(nid, None)
        except Exception:  # noqa: BLE001 - 실패해도 페이지는 og.png 로 계속 나간다
            _failed[nid] = time.time()
        finally:
            with _lock:
                _pending.discard(nid)

    threading.Thread(target=run, name=f"og-note-{nid}", daemon=True).start()


def type_path(code: str) -> Path:
    return OUT / f"type-{code}.png"


def diag_path(i: int) -> Path:
    return OUT / f"diag-{i}.png"


def make_all() -> list[Path]:
    """Edge(Playwright)로 렌더링한다 — 이모지·한글 글꼴이 시스템 그대로 나온다 (app/og_meta.make_image와 같은 방식)."""
    from playwright.sync_api import sync_playwright

    from app import ax_types
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(type_path(c), type_html(c)) for c in ax_types.TYPES] + [(diag_path(i), diag_html(i)) for i in range(len(DIAG_LEVELS))]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for path, html in jobs:
            page.set_content(html)
            page.wait_for_timeout(150)
            page.screenshot(path=str(path))
        browser.close()
    return [p for p, _ in jobs]


if __name__ == "__main__":
    print(len(make_all()), "장 →", OUT)
