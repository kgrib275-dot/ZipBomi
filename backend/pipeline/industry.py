"""지역 분류 — 노트를 서울·경기·부산 등 권역으로 묶는다 (규칙 기반, 노트 제목·태그·요약·본문의 지명으로).

노트 목록의 '지역' 필터와 지역별 뉴스레터(구독할 때 고른 지역의 노트를 먼저 보냄)에 쓴다.
단어를 고치면 바로 반영된다 (DB에 저장하지 않고 그때그때 판정).
이름(INDUSTRIES·industries)은 기존 호출부·DB 열과 맞추려고 그대로 두고, 뜻만 '지역'으로 쓴다.
"""
from __future__ import annotations

import re

# 지역 → 판정 지명. 여러 도시에 같은 이름이 있는 구(중구·동구·남구·서구·북구)는 헷갈려서 뺀다.
# '강서'는 서울·부산 모두 있지만 기사 대부분이 서울 강서구라 서울에 둔다. '광주'는 광주광역시로 본다.
INDUSTRIES: dict[str, list[str]] = {
    "서울": ["서울", "강남", "서초", "송파", "강동", "마포", "용산", "성동", "광진", "동작", "영등포", "양천", "목동",
           "강서구", "구로", "금천", "관악", "동대문", "성북", "강북", "도봉", "노원", "중랑", "은평", "서대문",
           "종로", "압구정", "반포", "잠실", "여의도", "성수", "한남", "마용성", "노도강", "금관구"],
    "경기": ["경기도", "경기 남부", "경기 북부", "수원", "성남", "분당", "판교", "용인", "수지", "고양", "일산", "화성", "동탄", "부천", "안양",
           "평촌", "광명", "과천", "하남", "남양주", "의정부", "파주", "운정", "김포", "시흥", "안산", "평택",
           "구리시", "의왕", "군포", "오산", "이천", "양주", "위례", "광교"],
    "인천": ["인천", "송도", "청라", "영종", "검단", "부평", "계양", "연수구", "미추홀"],
    "부산·울산·경남": ["부산", "해운대", "수영구", "동래", "센텀", "울산", "경남", "창원", "김해", "양산", "진주", "거제"],
    "대구·경북": ["대구", "수성구", "달서", "경북", "포항", "구미", "경산", "안동"],
    "대전·세종·충청": ["대전", "유성", "세종", "충청", "충남", "충북", "천안", "아산", "청주", "오송"],
    "광주·전라": ["광주광역시", "광주", "전라", "전남", "전북", "전주", "여수", "순천", "목포", "익산", "군산"],
    "강원·제주": ["강원", "춘천", "원주", "강릉", "속초", "제주", "서귀포"],
}
NAMES = list(INDUSTRIES)
_RES = {k: re.compile("|".join(re.escape(w) for w in ws), re.I) for k, ws in INDUSTRIES.items()}


_memo: dict[tuple, list[str]] = {}


def of(note: dict, min_hits: int = 2) -> list[str]:
    """노트가 속한 지역들. 제목·태그·요약에 한 번이면 바로, 본문에만 있으면 min_hits번 이상 나와야 한다 (지나가는 언급 제외).
    노트 목록 요청마다 본문 전체에 정규식을 돌리지 않게 같은 내용이면 기억해 둔 결과를 쓴다."""
    head = f"{note.get('title', '')} {note.get('tags', '')} {note.get('summary', '')}"
    body = note.get("body", "") or ""
    key = (head, hash(body), min_hits)
    hit = _memo.get(key)
    if hit is None:
        hit = [k for k, rx in _RES.items() if rx.search(head) or len(rx.findall(body)) >= min_hits]
        if len(_memo) > 5000:
            _memo.clear()
        _memo[key] = hit
    return list(hit)


def filter_notes(notes: list[dict], wanted: list[str]) -> list[dict]:
    if not wanted:
        return notes
    want = set(wanted)
    return [n for n in notes if want & set(of(n))]


def parse(raw: str | None) -> list[str]:
    """구독자 지역 문자열('서울,경기') → 알려진 지역만."""
    return [x for x in (raw or "").split(",") if x in INDUSTRIES]
