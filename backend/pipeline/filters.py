from __future__ import annotations

import re
from functools import lru_cache

from .models import Item, KeywordRule

# 2026-10-30 키워드 보강과 함께 바꾼 매칭 규칙
# 1) 영어 단어는 단어 경계로 맞춘다 — 예전엔 단순 포함 검사라 "AX"가 tax·max·relax 에, "RAG"가 average·storage 에,
#    "ROI"가 android 에 걸려 관련 없는 기사가 대량으로 통과했다. 짧은 약어(5자 이하·대문자)는 앞뒤 모두,
#    긴 단어는 앞만 경계로 본다 (agent → agents·agentic 처럼 뒤에 붙는 꼴은 살린다).
# 2) 한글은 조사가 붙으므로 그대로 포함 검사.
# 3) 제외 규칙은 '제목'에만 적용 — 본문 발췌에 '코인'·'주가'가 한 번 스친 부동산 기사까지 버려지지 않게.
# 4) needs_ai 규칙(금리·세금·거래·건설처럼 넓은 단어)은 같은 글에 부동산 단어가 함께 있을 때만 통과 — 경제 전체 피드의
#    일반 기사가 '금리' '수주' 만으로 들어오지 않게. (필드 이름 needs_ai 는 예전 그대로, 뜻은 '부동산 단어 동반 필요')
# 2026-11-02 ZipGenie 전환: AI_ANCHORS 를 부동산 앵커로 바꿨다. 한글은 포함 검사라 '전세'는 '전세계'에 걸리므로
#    단독으로 넣지 않고 '전셋값·전세가·전세 계약'처럼 붙은 꼴만 쓴다.
_HANGUL = re.compile(r"[가-힣]")

# '부동산 단어' — needs_ai 규칙이 통과하려면 제목에 이 중 하나, 또는 needs_ai 가 아닌 포함 규칙 하나가 같은 글에 있어야 한다
# (이름은 다른 모듈이 쓸 수 있어 AI_ANCHORS 그대로 둔다)
AI_ANCHORS = ("아파트", "주택", "부동산", "집값", "전셋값", "전세가", "전세금", "전세 계약", "전세사기", "전세대출", "깡통전세",
              "역전세", "반전세", "월세", "전월세", "임대차", "청약", "분양", "재건축", "재개발", "정비사업", "매매", "실거래",
              "LTV", "DSR", "주담대", "주택담보대출", "오피스텔", "빌라", "다세대", "연립주택", "종부세", "양도세", "취득세",
              "재산세", "보유세", "공시가", "다주택", "무주택", "집주인", "세입자", "임차인", "임대인", "갭투자", "신도시", "택지",
              "미분양", "입주", "규제지역", "토지거래허가", "투기과열", "조정대상", "공공임대", "임대주택", "국토부", "국토교통부",
              "한국부동산원", "LH", "주거", "내 집", "리모델링", "모아타운", "GTX", "역세권", "견본주택", "모델하우스")


@lru_cache(maxsize=4096)
def _matcher(needle: str):
    n = needle.strip()
    if not n:
        return None
    if _HANGUL.search(n):
        low = n.lower()
        return lambda text, low=low: low in text
    esc = re.escape(n.lower())
    short = len(n) <= 5 or n.isupper()
    pat = rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if short else rf"(?<![a-z0-9]){esc}"
    rx = re.compile(pat)
    return lambda text, rx=rx: rx.search(text) is not None


def _hit(text: str, needle: str) -> bool:
    m = _matcher(needle)
    return bool(m and m(text))


def _text_of(item: Item) -> str:
    return f"{item.title} {item.excerpt}".lower()


def _rule_hits(text: str, rule: KeywordRule) -> bool:
    return any(_hit(text, n) for n in (rule.keyword, *rule.aliases))


def _has_ai(text: str) -> bool:
    return any(_hit(text, a) for a in AI_ANCHORS)


def apply_keyword_filter(items: list[Item], rules: list[KeywordRule]) -> list[Item]:
    include_rules = [r for r in rules if r.mode == "include"]
    exclude_rules = [r for r in rules if r.mode == "exclude"]

    kept = []
    for item in items:
        text = _text_of(item)
        title = item.title.lower()
        if any(_rule_hits(title, r) for r in exclude_rules):
            continue

        hits = [r for r in include_rules if _rule_hits(text, r)]
        core = [r for r in hits if not r.needs_ai]
        # 넓은 단어(needs_ai)만 걸렸으면 '제목'에 부동산 단어가 있어야 한다 — 본문 발췌에 '아파트'가 한 번 스친 금리·실적 기사까지 들어오지 않게
        matched_rules = hits if (core or _has_ai(title)) else []
        if include_rules and not matched_rules:
            continue

        item.matched_kw = [r.keyword for r in matched_rules]
        item.kw_score = sum(r.weight for r in matched_rules)
        kept.append(item)
    return kept
