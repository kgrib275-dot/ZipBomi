"""테스트 — 부동산 성향 테스트·용어 퀴즈·내 집 마련 준비도 자가진단 (/api/type, /api/terms, /api/diagnosis).

Streamlit 판 app_pages/ax_type.py·terms.py·diagnosis.py 와 app/ax_types.py·glossary.py 를 옮겼다.
- 유형·진단은 규칙 기반이라 답을 받아 서버에서 채점하고 결과를 기록한다 (같은 답은 한 번만).
- 용어 퀴즈는 정답을 숨긴 문제를 내고(seed 로 같은 문제를 다시 만든다), 답은 서버에서 확인한다.
- 자가진단 답은 서버에 저장하지 않고 결과 링크(?a=코드)에만 담긴다. 집계용 기록은 영역 점수뿐이다.
"""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Body, HTTPException, Query

from api.common import cached, note_card
from api.deps import Caller, CallerDep
from api.routers import me as me_state
from app import ax_types as T
from app import glossary as G
from app import og_cards
from pipeline import db, engage

router = APIRouter(tags=["play"])

TERM_N = G.TERM_N
_SEED_RE = re.compile(r"^[0-9a-f]{8,32}$")


STATS_TTL = 30  # 결과 분포·점수 분포는 30초 캐시 (결과 화면마다 기록 전체를 세지 않게)


def _recs(cat: str, k: int = 3) -> list[dict]:
    return [note_card(n) for n in db.notes() if n["category"] == cat][:k]


# ───────────────────────── 부동산 성향 테스트 ─────────────────────────

def _distribution() -> dict[str, int]:
    return cached("play:type_dist", lambda: engage.item_counts("type_test"), STATS_TTL)


def _type_card(code: str, axes: list | None) -> dict:
    emoji, name, line, partner, cat = T.TYPES[code]
    dist = _distribution()
    total = sum(dist.values())
    pe, pn, *_ = T.TYPES[partner]
    axes_out = []
    for i, (l, r, label, l_text, r_text) in enumerate(T.AXES):
        if axes:
            lc, rc = axes[i][2], axes[i][3]
        else:
            lc, rc = (3, 0) if code[i] == l else (0, 3)
        axes_out.append([l, r, lc, rc])
    watch = T.WATCH[code[1]]  # 주의점은 둘째 축(안정·공격) 기준
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:8]
    return {
        "code": code, "emoji": emoji, "name": name, "line": line, "category": cat, "axes": axes_out,
        # 분포는 30초 캐시라 방금 낸 내 결과가 아직 없을 수 있다 — 나 자신은 적어도 1명으로 센다 ('0%가 이 유형'이 나오지 않게)
        "share_pct": max(1, round(max(1, dist.get(code, 0)) / max(total, 1) * 100)) if total else None,
        "strengths": [T.STRENGTH[ch] for ch in code], "watch": watch,
        "buddy": {"code": partner, "emoji": pe, "name": pn},
        "recommended_notes": _recs(cat),
        "distribution": {"total": total, "top": [{"code": k, "emoji": T.TYPES[k][0], "name": T.TYPES[k][1], "n": n,
                                                  "pct": round(n / total * 100)} for k, n in top if k in T.TYPES]},
        "share": {"url": f"/s/t/{code}", "title": f"나는 {name} ({code}) — 부동산 성향 테스트",
                  "text": f"부동산 성향 테스트를 해 봤더니 저는 {emoji} '{name}'({code})이었습니다. {line}. "
                          f"12문항이면 됩니다 — 여러분은 어떤 유형인가요?", "image": f"/app/static/og/type-{code}.png"},
    }


@router.get("/type")
def type_meta() -> dict:
    return {
        "axes": [{"l": l, "r": r, "label": label, "l_text": lt, "r_text": rt} for l, r, label, lt, rt in T.AXES],
        "questions": [{"q": q, "a": list(a), "b": list(b)} for q, a, b in T.QUESTIONS],
        "types": {k: {"emoji": v[0], "name": v[1], "line": v[2], "buddy": v[3], "category": v[4]} for k, v in T.TYPES.items()},
        "strength": T.STRENGTH, "watch": T.WATCH,
    }


@router.get("/type/{code}")
def type_shared(code: str) -> dict:
    """공유 링크(?t=코드)로 들어온 친구 결과 — 기록하지 않는다."""
    code = code.upper()
    if code not in T.TYPES:
        raise HTTPException(status_code=404, detail="없는 유형입니다.")
    return _type_card(code, None)


@router.post("/type/result")
def type_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    answers = payload.get("answers")
    if not isinstance(answers, list) or len(answers) != len(T.QUESTIONS):
        raise HTTPException(status_code=400, detail=f"{len(T.QUESTIONS)}문항 모두 답해 주세요.")
    for a, (_, (_, ca), (_, cb)) in zip(answers, T.QUESTIONS):
        if a not in (ca, cb):
            raise HTTPException(status_code=400, detail="보기에 없는 답입니다.")
    code, axes = T.score(answers)
    extra = {"axes": [[l, r, lc, rc] for l, r, lc, rc in axes]}
    engage.record_result("type_test", code, extra=extra, visitor=c.visitor)  # 직전과 같은 결과면 남기지 않는다
    me_state.save_state(c.visitor, {"axt_answers": answers, "axt_step": len(answers), "axt_recorded": code + "".join(answers)})
    return _type_card(code, axes)


# ───────────────────────── 부동산 용어 퀴즈 ─────────────────────────

def _questions(track: str, seed: str) -> list[dict]:
    return G.quiz_set(track, seed)  # 뉴스레터 '용어 1개 맞히기'도 같은 세트의 0번 문항을 낸다 (pipeline/mailer.py)


def _track(v) -> str:
    if v not in G.TRACKS:
        raise HTTPException(status_code=400, detail=f"트랙은 {' 또는 '.join(G.TRACKS)} 중 하나입니다.")
    return v


def _seed(v) -> str:
    if not isinstance(v, str) or not _SEED_RE.match(v):
        raise HTTPException(status_code=400, detail="문제 세트(seed)가 필요합니다.")
    return v


def _term_hist(track: str) -> dict[int, int]:
    return cached(f"play:term_hist:{track}", lambda: engage.value_hist("term_quiz", track), STATS_TTL)


def _track_stats() -> dict[str, dict]:
    out = {}
    for key in G.TRACKS:
        h = _term_hist(key)
        n = sum(h.values())
        out[key] = {"n": n, "avg": round(sum(v * c for v, c in h.items()) / n) if n else None, "terms": len(G.TERMS[key])}
    return out


@router.get("/terms")
def terms(track: str | None = None, seed: str | None = None, q: str = Query("", max_length=100)) -> dict:
    """트랙 정보·용어 사전은 늘, track 을 주면 그 트랙의 문제(정답 숨김)도 함께. seed 를 주면 같은 문제를 다시 만든다."""
    out = {
        "tracks": {k: {"emoji": e, "title": t, "desc": d} for k, (e, t, d) in G.TRACKS.items()},
        "levels": [{"min": m, "emoji": e, "name": n} for m, e, n in G.LEVELS],
        "dictionary": {k: [list(t) for t in v if not q or q.lower() in f"{t[0]} {t[1]} {t[2]}".lower()] for k, v in G.TERMS.items()},
        "stats": _track_stats(), "n": TERM_N,
    }
    if track:
        track = _track(track)
        seed = _seed(seed) if seed else secrets.token_hex(8)
        qs = _questions(track, seed)
        out["track"] = track
        out["seed"] = seed
        out["questions"] = [{"i": i, "format": i % G.FORMATS, "q": x["q"], "prompt": x["prompt"], "options": x["options"]}
                            for i, x in enumerate(qs)]
    return out


@router.post("/terms/answer")
def terms_answer(payload: dict = Body(...)) -> dict:
    track, seed, i, pick = _track(payload.get("track")), _seed(payload.get("seed")), payload.get("i"), payload.get("pick")
    qs = _questions(track, seed)
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(qs):
        raise HTTPException(status_code=400, detail="없는 문항입니다.")
    item = qs[i]
    if pick not in item["options"]:
        raise HTTPException(status_code=400, detail="보기 중에서 골라 주세요.")
    return {"correct": pick == item["answer"], "answer": item["answer"],
            "explain": {"term": item["term"], "define": item["define"], "hint": item["hint"]}}


@router.post("/terms/result")
def terms_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    track, seed, picks = _track(payload.get("track")), _seed(payload.get("seed")), payload.get("picks")
    qs = _questions(track, seed)
    if not isinstance(picks, list) or len(picks) != len(qs) or any(p not in q["options"] for p, q in zip(picks, qs)):
        raise HTTPException(status_code=400, detail=f"{len(qs)}문항 모두 답해 주세요.")
    right = sum(p == q["answer"] for p, q in zip(picks, qs))
    pct = round(right / len(qs) * 100)
    wrong = [q for p, q in zip(picks, qs) if p != q["answer"]]
    extra = {"wrong": [q["term"] for q in wrong]}
    engage.record_result("term_quiz", track, str(pct), extra, visitor=c.visitor, force=payload.get("force") is True)
    h = _term_hist(track)
    n = sum(h.values())
    better = sum(cnt for v, cnt in h.items() if v < pct) / n * 100 if n else 0
    emoji, lv = G.level(pct)
    me_state.save_state(c.visitor, {"term_track": track, "term_i": len(qs), "term_picks": picks, "term_recorded": f"{track}:{seed}"})
    return {
        "score": pct, "right": right, "n": len(qs), "level": [emoji, lv], "track_label": G.TRACKS[track][1],
        "wrong": [q["term"] for q in wrong],
        "review": [{"term": q["term"], "define": q["define"], "hint": q["hint"]} for q in wrong],
        "stats": {"n": n, "avg": round(sum(v * cnt for v, cnt in h.items()) / n) if n else None, "top_pct": max(1, round(100 - better))},
        "share": {"url": f"/s/terms?track={track}&score={pct}", "title": f"부동산 용어 퀴즈 {pct}점 ({lv}) — 너는 몇 점?",
                  "text": f"부동산 용어 퀴즈 {pct}점({lv}). 집 살 때 꼭 나오는 용어들인데, 몇 점 나오시나요?"},
    }


# ───────────────────────── 내 집 마련 준비도 자가진단 ─────────────────────────

# 영역 키는 노트 분류(llm.CATEGORIES) — 약한 영역의 추천 노트를 그 분류에서 고른다.
AREAS = {
    "정책·세금·대출": ("자금·대출", [
        "내가 동원할 수 있는 자기 자금(예금·청약통장 외 현금)을 정확히 알고 있다",
        "LTV·DSR 기준으로 내 대출 가능 한도를 계산해 봤다",
        "금리가 오를 때의 월 상환액까지 감당할 수 있는지 확인했다",
        "취득세·중개보수·이사비 등 부대비용을 예산에 넣었다",
    ]),
    "시장·시세": ("정보·지역", [
        "관심 지역 2~3곳을 정하고 시세를 꾸준히 보고 있다",
        "실거래가와 호가의 차이를 확인하는 방법을 알고 있다",
        "관심 지역의 입주 물량·교통·학군 같은 수급 요인을 정리했다",
        "최근 부동산 정책·대출 규제 변화를 따라가고 있다",
    ]),
    "청약·분양·개발": ("실행·계약", [
        "관심 단지를 직접 임장(현장 방문)해 본 적이 있다",
        "청약 자격과 내 가점(또는 추첨 가능성)을 확인했다",
        "등기부등본·건축물대장으로 권리관계를 확인하는 법을 안다",
        "계약금·중도금·잔금 일정과 대출 실행 시점을 맞춰 본 적이 있다",
    ]),
}
SCALE = ["아직 안 함", "알아보는 중", "일부 해 봄", "충분히 함"]
LEVELS = [(25, "탐색", "#B8AB8A"), (50, "준비", "#FFD54A"), (75, "실행 직전", "#F5B800"), (101, "실행 가능", "#0ca30c")]
NEXT = {
    "정책·세금·대출": ["자기 자금과 매달 저축 가능 금액부터 표로 정리하세요.",
                     "LTV·DSR로 대출 한도를 계산하고 은행 두 곳 이상에서 상담을 받아 보세요.",
                     "금리 1%p 상승 시 월 상환액을 계산해 여유 자금을 남겨 두세요.",
                     "취득세·보유세·양도세까지 포함한 보유 기간별 비용표를 만들어 두세요."],
    "시장·시세": ["관심 지역 2~3곳을 정하고 매주 실거래가를 기록하세요.",
                "같은 단지의 실거래가·호가·전세가를 한 표에 놓고 비교하세요.",
                "입주 물량·교통 개통·재건축 일정을 지역별로 정리하세요.",
                "정책 발표가 관심 지역 가격·거래량에 준 영향을 기록해 두세요."],
    "청약·분양·개발": ["관심 단지 한 곳을 정해 주말에 임장을 다녀오세요.",
                     "청약홈에서 내 가점과 특별공급 자격을 확인하세요.",
                     "등기부등본·건축물대장을 직접 떼어 근저당·위반건축물을 확인해 보세요.",
                     "계약부터 잔금까지 일정표를 만들고 대출 실행일을 맞춰 두세요."],
}
KEYS = [(cat, i) for cat, (_, qs) in AREAS.items() for i in range(len(qs))]


def level(score: float) -> tuple[str, str]:
    return next((name, color) for limit, name, color in LEVELS if score < limit)


@router.get("/diagnosis")
def diagnosis_meta() -> dict:
    return {"areas": {cat: [label, qs] for cat, (label, qs) in AREAS.items()}, "scale": SCALE,
            "levels": [[limit, name, color] for limit, name, color in LEVELS], "next": NEXT}


@router.post("/diagnosis/result")
def diagnosis_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    raw = payload.get("answers")
    if isinstance(raw, str) and re.fullmatch(f"[0-{len(SCALE) - 1}]{{{len(KEYS)}}}", raw):
        raw = [int(ch) for ch in raw]  # 공유 링크의 ?a=코드 그대로
    if not isinstance(raw, list) or len(raw) != len(KEYS):
        raise HTTPException(status_code=400, detail=f"{len(KEYS)}문항의 답(0~{len(SCALE) - 1} 또는 null)이 필요합니다.")
    answers: dict[tuple[str, int], int | None] = {}
    for key, v in zip(KEYS, raw):
        if v is None:
            answers[key] = None
        elif isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(SCALE):
            answers[key] = v
        else:
            raise HTTPException(status_code=400, detail="답은 0~3 또는 null 이어야 합니다.")
    done = sum(v is not None for v in answers.values())
    scores = {cat: sum(answers[(cat, i)] or 0 for i in range(len(qs))) / (3 * len(qs)) * 100 for cat, (_, qs) in AREAS.items()}
    total = sum(scores.values()) / len(scores)
    code = "".join(str(answers[k]) if answers[k] is not None else "0" for k in KEYS)
    name, color = level(total)
    weakest = min(scores, key=scores.get) if done else None
    next_steps = {cat: {"label": AREAS[cat][0], "score": round(scores[cat]), "level": level(scores[cat])[0],
                        "color": level(scores[cat])[1], "step": NEXT[cat][min(3, int(scores[cat] // 25))]} for cat in AREAS}
    if weakest:
        me_state.save_state(c.visitor, {"diag_weak": weakest})  # 홈 '나를 위한 추천'에 쓴다 (개인화)
    extra = {cat: round(v) for cat, v in scores.items()}
    if done == len(KEYS):
        engage.record_result("diagnosis", weakest, f"{total:.0f}", extra, visitor=c.visitor)
    report = "\n".join(
        [f"내 집 마련 준비도 자가진단 결과 — 종합 {total:.0f}점 ({name} 단계)", ""]
        + [f"[{AREAS[cat][0]}] {scores[cat]:.0f}점 ({level(scores[cat])[0]}) — 다음 단계: {NEXT[cat][min(3, int(scores[cat] // 25))]}" for cat in AREAS]
        + ["", "문항별 응답"]
        + [f"- {AREAS[cat][1][i]}: {SCALE[answers[(cat, i)]] if answers[(cat, i)] is not None else '미응답'}" for cat, i in KEYS])
    lvl = min(3, int(total // 25))  # app/web.py diag_level 과 같은 기준
    return {
        "code": code, "done": done, "scores": {cat: round(v, 1) for cat, v in scores.items()}, "total": round(total, 1),
        "level": [name, color], "weakest": weakest, "next_steps": next_steps,
        "recommended": _recs(weakest) if weakest else [], "report_txt": report,
        "share": {"url": f"/s/d?a={code}", "image": f"/app/static/og/diag-{lvl}.png", "title": f"내 집 마련 준비도: {name} 단계",
                  "text": f"내 집 마련 준비도 자가진단 결과 저는 '{name}' 단계({total:.0f}점)입니다. 12문항·3분이면 됩니다.",
                  "level_line": og_cards.DIAG_LEVELS[lvl][2]},
    }
