"""관리 > 노트 검토 — 초안·게시·반려 목록, 편집·저장·게시·반려·삭제, 직접 작성 (app_pages/admin/review.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.common import md_html
from api.deps import require_admin
from api.routers.admin_jobs import log_action
import json

from pipeline import db, jobs, llm, note_format, policy, profile, regions_kr

router = APIRouter(prefix="/admin/notes", tags=["admin-notes"], dependencies=[Depends(require_admin)])

_STATUSES = ("draft", "published", "rejected")


def _clean(body: dict[str, Any], require: bool = True) -> dict:
    """review.py note_form 과 같은 정리 — 제목·요약 필수, 태그 '#' 제거, 본문 비면 요약으로."""
    title = (body.get("title") or "").strip()
    summary = (body.get("summary") or "").strip()
    if require and not (title and summary):
        raise HTTPException(400, "제목과 카드 요약은 필수입니다.")
    category = body.get("category") or llm.CATEGORIES[1]
    kind = body.get("kind") or llm.KINDS[0]
    if category not in llm.CATEGORIES or kind not in llm.KINDS:
        raise HTTPException(400, "카테고리·유형 값을 확인해 주세요.")
    aud = body.get("audiences") or []
    if isinstance(aud, str):
        aud = [a.strip() for a in aud.split(",")]
    tags = body.get("tags") or ""
    if isinstance(tags, list):
        tags = ",".join(tags)
    out = {
        "title": title, "category": category, "kind": kind, "source": (body.get("source") or "").strip(),
        "url": (body.get("url") or "").strip(), "audiences": ",".join(a for a in aud if a in llm.AUDIENCES),
        "tags": ",".join(t.strip().lstrip("#") for t in tags.split(",") if t.strip()),
        "summary": summary, "body": (body.get("body") or "").strip() or f"### 요약\n{summary}",
    }
    if body.get("published"):
        out["published"] = str(body["published"])[:10]
    # 시군구·대상 유형 — 보냈을 때만 바꾼다 (예전 화면이 보내지 않아도 저장값이 지워지지 않게)
    if isinstance(body.get("regions"), list):
        out["regions"] = json.dumps([r for r in dict.fromkeys(body["regions"]) if isinstance(r, str) and r in regions_kr.NAMES][:20])
    if isinstance(body.get("audience"), list):
        out["audience"] = json.dumps(profile.audience_clean(body["audience"]))
    if body.get("format") in note_format.FORMATS:
        out["format"] = body["format"]
    if isinstance(body.get("policy_params"), list):
        out["policy_params"] = policy.clean_keys(body["policy_params"])
    return out


def _full(n: dict) -> dict:
    n = dict(n)
    n.pop("embedding", None)
    n["audiences_list"] = [a for a in (n.get("audiences") or "").split(",") if a]
    n["tags_list"] = [t for t in (n.get("tags") or "").split(",") if t]
    n["regions_list"] = profile.note_regions(n)
    n["audience_list"] = profile.note_audience(n)
    return n


@router.get("")
def list_notes(status: str = "draft") -> dict:
    if status not in _STATUSES:
        raise HTTPException(400, "status 는 draft·published·rejected 중 하나입니다")
    items = [_full(n) for n in db.notes(status)]
    return {"status": status, "notes": items, "count": len(items),
            "meta": {"categories": llm.CATEGORIES, "kinds": llm.KINDS, "audiences": llm.AUDIENCES, "types": profile.TYPES},
            "counts": {s: len(db.notes(s)) for s in _STATUSES}}


@router.get("/{note_id}")
def get_note(note_id: int) -> dict:
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    n = _full(n)
    n["body_html"] = md_html(n.get("body") or "")
    return {"note": n}


@router.post("")
def create_note(request: Request, body: dict[str, Any]) -> dict:
    """직접 작성. body.publish=true 또는 body.status='published' 면 바로 게시(+벡터화 시작) — 화면은 status 로 보낸다."""
    data = _clean(body)  # 제목·카드 요약 필수 등 /publish 가 쓰는 것과 같은 검증
    publish = bool(body.get("publish")) or body.get("status") == "published"
    note_id = db.add_note(**data, status="published" if publish else "draft")
    profile.backfill_notes()  # 시군구·대상 유형을 보내지 않았으면 본문 지명·대상 독자로 채운다
    policy.backfill_notes()
    note_format.backfill()
    log_action(request, "노트 게시" if publish else "노트 저장", data["title"])
    if publish:
        jobs.start("vectorize", trigger="게시")
    return {"id": note_id, "status": "published" if publish else "draft"}


@router.put("/{note_id}")
def save_note(note_id: int, request: Request, body: dict[str, Any]) -> dict:
    """저장 (상태 유지). body.status 로 'draft'/'rejected' 전환(반려·게시 내리기)도 가능 — 게시는 /publish."""
    if not db.note(note_id):
        raise HTTPException(404, "노트가 없습니다")
    status = body.get("status")
    if status is not None and status not in ("draft", "rejected"):
        raise HTTPException(400, "status 는 draft 또는 rejected 만 바꿀 수 있습니다 (게시는 /publish)")
    data = _clean(body, require=status is None)
    if status is None:
        db.update_note(note_id, **data)
        log_action(request, "노트 저장", data["title"])
    else:
        if data["title"]:
            db.update_note(note_id, **data)
        db.update_note(note_id, status=status)
        log_action(request, "노트 반려", data["title"] or str(note_id))
    return {"ok": True, "note": _full(db.note(note_id))}


@router.post("/{note_id}/publish")
def publish_note(note_id: int, request: Request, body: dict[str, Any] | None = None) -> dict:
    """편집 내용(있으면)을 저장하고 게시 → 벡터화 작업 시작."""
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    if body and body.get("title"):
        db.update_note(note_id, **_clean(body))
    db.publish_note(note_id)
    log_action(request, "노트 게시", (body or {}).get("title") or n["title"])
    started = jobs.start("vectorize", trigger="게시")
    return {"ok": True, "vectorize_started": started, "note": _full(db.note(note_id))}


@router.delete("/{note_id}")
def delete_note(note_id: int, request: Request) -> dict:
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    db.delete_note(note_id)
    log_action(request, "노트 삭제", n["title"])
    if n.get("article_hash"):
        db.set_article_status(n["article_hash"], "skipped")  # 원문 기사는 건너뜀으로 되돌린다
    return {"ok": True}


def _int(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(body.get(key, default))))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{key} 는 숫자여야 합니다")


@router.post("/backfill")
def backfill(request: Request, body: dict[str, Any] | None = None) -> dict:
    """지난 기사로 노트 초안 채우기 — 분류별 최소 per_category_min 편, 합계 total 편. dry_run=true 면 고를 기사만 돌려준다."""
    body = body or {}
    total = _int(body, "total", 30, 1, 100)
    per_cat = _int(body, "per_category_min", 8, 0, 50)
    min_score = _int(body, "min_score", 4, 2, 5)
    if body.get("dry_run"):
        res = jobs.draft_backfill(total, per_cat, min_score, dry_run=True)
        return {"started": False, "dry_run": True, **res}
    started = jobs.start("draft", trigger="수동(채우기)", backfill=True, total=total, per_category_min=per_cat,
                         min_score=min_score)
    if started:
        log_action(request, "노트 채우기 실행", f"{total}편 · 분류별 {per_cat}편↑ · {min_score}점↑")
    return {"started": started, "kind": "draft",
            "message": "노트 초안 채우기를 시작했습니다." if started else "이미 노트 초안 작업이 진행 중입니다."}
