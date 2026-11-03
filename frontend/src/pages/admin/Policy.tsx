// 관리 > 현행 수치 — /now·계산기·노트 상세에 나가는 규제·세율·금리 숫자 (backend/pipeline/policy.py).
// 초안(draft)은 공개되지 않는다. 근거 링크를 열어 값·기준일을 확인한 뒤 '게시'로 바꾼다. 자동 항목(금리)은 수집 자료에서 읽으므로 값은 못 고친다.
import { man } from "../../policy";
import { Fragment, useEffect, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, AdminHead, Field, Row, str, today, useAct } from "./common";

type Item = {
  key: string; grp: string; label: string; value: number | null; value_text: string; unit: string; scope: string; effective_on: string;
  source_name: string; source_url: string; source_kind: string; status: string; note: string; prev_value: number | null;
  changed_on: string | null; checked_on: string | null; updated_at: string; changed: boolean;
};

export default function Policy() {
  const { data, error, reload } = useLoad(() => A.get<{ items: Item[]; groups: string[] }>("policy"), []);
  const [open, setOpen] = useState<string | null>(null);
  const items = data?.items || [];
  const drafts = items.filter((i) => i.status !== "published").length;
  return (
    <div>
      <AdminHead title="현행 수치" note="계산기·/now·노트 상세에 나가는 규제·세율·금리 숫자입니다. 초안은 공개되지 않습니다. 근거 링크로 값과 기준일을 확인한 뒤 게시하세요. 값을 바꾸면 직전 값과 바뀐 날이 남아 30일 동안 '변경됨' 배지가 붙습니다." />
      {error && <Alert kind="err">{error}</Alert>}
      {drafts > 0 && <Alert kind="warn">확인 대기 {drafts}개 — 처음 넣은 값은 정책 변경 전 기준일 수 있습니다. 금융위원회·법령 원문으로 확인한 뒤 게시하세요.</Alert>}
      {(data?.groups || []).map((g) => (
        <section key={g} style={{ marginTop: 16 }}>
          <h3 style={{ margin: "0 0 8px" }}>{g}</h3>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>항목</th><th className="num">값</th><th>기준일</th><th>근거</th><th>상태</th><th /></tr></thead>
              <tbody>
                {items.filter((i) => i.grp === g).map((i) => (
                  <Fragment key={i.key}>
                    <tr>
                      <td>{i.label}<div className="caption">{i.key}{i.source_kind === "auto" ? " · 자동" : ""}</div></td>
                      <td className="num">{i.value !== null && i.unit === "만원" ? man(i.value) : <>{i.value ?? i.value_text}{i.value !== null ? i.unit : ""}</>}{i.changed && <div className="caption">이전 {i.prev_value ?? "-"}</div>}</td>
                      <td>{i.effective_on || <span className="caption">비어 있음</span>}</td>
                      <td>{i.source_url ? <a href={i.source_url} target="_blank" rel="noopener">{i.source_name || "링크"} ↗</a> : <span className="caption">없음</span>}</td>
                      <td>{i.status === "published" ? <span className="badge">게시</span> : <span className="re-tag warn">확인 대기</span>}</td>
                      <td><button type="button" className="btn sm" onClick={() => setOpen(open === i.key ? null : i.key)}>{open === i.key ? "닫기" : "고치기"}</button></td>
                    </tr>
                    {open === i.key && <tr><td colSpan={6}><Editor item={i} onSaved={() => { reload(); }} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function Editor({ item, onSaved }: { item: Item; onSaved: () => void }) {
  const act = useAct();
  const auto = item.source_kind === "auto";
  const [f, setF] = useState({ ...item, value: item.value === null ? "" : String(item.value) });
  const hist = useLoad(() => A.get<{ items: Row[] }>(`policy/${item.key}/history`), [item.key, item.updated_at]);
  useEffect(() => setF({ ...item, value: item.value === null ? "" : String(item.value) }), [item]);
  const up = (p: Partial<typeof f>) => setF((c) => ({ ...c, ...p }));
  const save = async (status?: string) => {
    const body: Record<string, unknown> = auto
      ? { label: f.label, scope: f.scope, note: f.note, source_name: f.source_name, source_url: f.source_url }
      : { label: f.label, value: f.value === "" ? null : Number(f.value), value_text: f.value_text, unit: f.unit, scope: f.scope,
          effective_on: f.effective_on, source_name: f.source_name, source_url: f.source_url, note: f.note, checked_on: today() };
    if (status) body.status = status;
    // 공개 중인 값이 바뀌면 직전 값과 새 값을 보여 주고 확인받는다 (2026-11-03 — 40 을 4 로 잘못 넣어도 바로 계산기에 나갔다)
    const live = (status ?? str(item.status)) === "published";
    const oldV = item.value === null ? "" : String(item.value), newV = f.value;
    if (live && !auto && (oldV !== newV || (f.value_text || "") !== (str(item.value_text) || ""))) {
      const show = (v: string, t: string) => (t ? t : v === "" ? "(없음)" : f.unit === "만원" ? man(Number(v)) : `${Number(v).toLocaleString("ko-KR")}${f.unit || ""}`);
      if (!window.confirm(`공개 중인 값을 바꿀까요?
${f.label}: ${show(oldV, str(item.value_text))} → ${show(newV, f.value_text || "")}
저장하면 /now·계산기·노트에 바로 반영됩니다.`)) return;
    }
    const r = await act(() => A.put(`policy/${item.key}`, body), status === "published" ? "게시했습니다" : status === "draft" ? "초안으로 내렸습니다" : "저장했습니다");
    if (r) onSaved();
  };
  return (
    <div style={{ display: "grid", gap: 8, padding: "6px 0" }}>
      {auto && <Alert kind="info">자동 항목 — 값·기준일은 '부동산 데이터' 수집 결과(한국은행)에서 읽습니다.</Alert>}
      <div className="row2">
        <Field label="항목 이름"><input value={f.label} onChange={(e) => up({ label: e.target.value })} /></Field>
        <Field label="적용 범위"><input value={f.scope} onChange={(e) => up({ scope: e.target.value })} /></Field>
        {!auto && <Field label={`값 (숫자, 단위 ${f.unit || "없음"})${f.unit === "만원" && f.value ? ` = ${man(Number(f.value))}` : ""}`}><input inputMode="decimal" value={f.value} onChange={(e) => up({ value: e.target.value.replace(/[^\d.]/g, "") })} /></Field>}
        {!auto && <Field label="값 (글로 — 숫자가 아닐 때)"><input value={f.value_text} onChange={(e) => up({ value_text: e.target.value })} /></Field>}
        {!auto && <Field label="기준일 (시행일, YYYY-MM-DD)"><input value={f.effective_on} placeholder="2026-01-01" onChange={(e) => up({ effective_on: e.target.value })} /></Field>}
        <Field label="근거 이름"><input value={f.source_name} onChange={(e) => up({ source_name: e.target.value })} /></Field>
        <Field label="근거 링크 (보도자료·법령)"><input value={f.source_url} onChange={(e) => up({ source_url: e.target.value })} /></Field>
        <Field label="설명 (선택)"><input value={f.note} onChange={(e) => up({ note: e.target.value })} /></Field>
      </div>
      <div className="btn-row">
        <button type="button" className="btn sm" onClick={() => save()}>저장</button>
        {item.status !== "published" ? <button type="button" className="btn sm primary" onClick={() => save("published")}>확인했음 — 게시</button>
          : <button type="button" className="btn sm ghost" onClick={() => save("draft")}>초안으로 내리기</button>}
        <span className="caption">마지막 확인 {item.checked_on || "-"} · 수정 {item.updated_at.slice(0, 16).replace("T", " ")}</span>
      </div>
      {!!hist.data?.items.length && (
        <div className="caption">바뀐 이력: {hist.data.items.map((h) => `${str(h.at).slice(0, 10)} ${str(h.value ?? h.value_text)} (${str(h.by)})`).join(" · ")}</div>
      )}
    </div>
  );
}
