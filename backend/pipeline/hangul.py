"""한글 초성 검색·간이 오타 허용 (2026-11-19) — 단지·노트·공고 검색에 쓴다. LLM 없음."""
from __future__ import annotations

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JAMO = set(_CHO)
# 'ㄳ' 같은 겹받침 자음은 초성이 아니라 검색어에서 제외
_SPACE = " \t\r\n·-_.,()[]"


def norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch not in _SPACE)


def chosung(s: str) -> str:
    """'대치은마' → 'ㄷㅊㅇㅁ' — 한글이 아닌 글자는 그대로 둔다."""
    out = []
    for ch in norm(s):
        o = ord(ch) - 0xAC00
        out.append(_CHO[o // 588] if 0 <= o < 11172 else ch)
    return "".join(out)


def is_initials(q: str) -> bool:
    q = norm(q)
    return len(q) >= 2 and all(ch in _JAMO for ch in q)


def match(q: str, text: str) -> int:
    """0 = 안 맞음, 3 = 앞부분 일치, 2 = 포함, 1 = 초성 포함."""
    nq, nt = norm(q), norm(text)
    if not nq:
        return 0
    if is_initials(q):
        c = chosung(text)
        return 3 if c.startswith(nq) else 1 if nq in c else 0
    return 3 if nt.startswith(nq) else 2 if nq in nt else 0


def fuzzy(q: str, text: str, cutoff: int = 82) -> bool:
    """오타 허용 — '레미안' ↔ '래미안'. 3글자 이상 검색어만."""
    nq = norm(q)
    if len(nq) < 3 or is_initials(q):
        return False
    try:
        from rapidfuzz import fuzz
    except Exception:  # noqa: BLE001
        return False
    return fuzz.partial_ratio(nq, norm(text)) >= cutoff
