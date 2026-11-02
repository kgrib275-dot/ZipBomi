// 실거래가 파일 업로드 — rt.molit.go.kr(국토교통부 실거래가 공개시스템)에서 받은 CSV·XLSX 를 올려 rtms_* 표를 채운다.
// API 활용신청이 안 된 데이터셋도 파일로 채울 수 있다. 백엔드: POST admin/redata/upload, GET admin/redata/uploads (pipeline/re_upload.py).
import { useRef, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, DataTable, Row, asArray, num, str, usePaged } from "./common";

const ym = (v: unknown) => (str(v) ? `${str(v).slice(0, 4)}.${str(v).slice(4)}` : "");
const at = (v: unknown) => str(v).slice(0, 16).replace("T", " ");
const mb = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))}KB` : `${(n / 1024 / 1024).toFixed(1)}MB`);

/** multipart 업로드 — fetch 는 올리는 진행률을 못 주므로 XHR. api.ts 와 같은 머리글(위조 요청 차단·관리 토큰)을 붙인다. */
function send(file: File, dataset: string, onProgress: (p: number) => void): Promise<Row> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dataset", dataset);
    const x = new XMLHttpRequest();
    x.open("POST", "/api/admin/redata/upload");
    x.setRequestHeader("X-Requested-With", "zipgenie");
    try {
      const tok = localStorage.getItem("zipgenie-admin-token");
      if (tok) x.setRequestHeader("X-Admin-Token", tok);
    } catch { /* 사생활 보호 모드 */ }
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let data: Row = {};
      try { data = JSON.parse(x.responseText || "{}"); } catch { /* 글자 그대로 */ }
      if (x.status >= 200 && x.status < 300) resolve(data);
      else reject(new Error(str(data.detail) || `업로드 실패 (${x.status})`));
    };
    x.onerror = () => reject(new Error("서버에 연결하지 못했습니다."));
    x.send(fd);
  });
}

export default function ReUpload({ datasets, onDone }: { datasets: Row[]; onDone: () => void }) {
  const rtms = datasets.filter((r) => r.uploadable);
  const [ds, setDs] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [prog, setProg] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [res, setRes] = useState<Row | null>(null);
  const inp = useRef<HTMLInputElement>(null);
  const hist = useLoad(() => A.get<Row>("redata/uploads"), []);
  const maxMb = num(hist.data?.max_mb, 60);
  const logs = asArray(hist.data?.uploads);
  const paged = usePaged("upl", logs, "", 10);

  const go = async () => {
    if (!file) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) { setErr("CSV 또는 XLSX 파일만 올릴 수 있습니다."); return; }
    if (file.size > maxMb * 1024 * 1024) { setErr(`파일이 너무 큽니다 (최대 ${maxMb}MB). 기간·지역을 나눠 받아 주세요.`); return; }
    setBusy(true); setErr(""); setRes(null); setProg(0);
    try {
      const r = await send(file, ds, setProg);
      setRes(r);
      setFile(null);
      if (inp.current) inp.current.value = "";
      hist.reload();
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false); setProg(null);
    }
  };

  return (
    <div id="re-upload" style={{ margin: "18px 0" }}>
      <h3 style={{ margin: "0 0 6px" }}>파일 업로드 (실거래가 CSV·엑셀)</h3>
      <p className="caption" style={{ margin: "0 0 8px" }}>
        API 활용신청이 안 됐거나 오류가 나는 데이터셋은 국토교통부 실거래가 공개시스템에서 파일을 받아 올리면 같은 표에 들어갑니다.
        이미 있는 거래(같은 시군구·달·계약일·면적·층·금액)는 다시 넣지 않으니 겹쳐 올려도 괜찮습니다.
      </p>
      <ol style={{ margin: "0 0 10px 18px", lineHeight: 1.7 }}>
        <li><a href="https://rt.molit.go.kr" target="_blank" rel="noreferrer">rt.molit.go.kr</a> 접속 → 상단 <b>실거래가 자료제공</b>(조건별 자료제공)</li>
        <li>실거래 구분(아파트·연립다세대·단독다가구·오피스텔·분양입주권·상업업무용·토지)과 <b>매매/전월세</b> 선택</li>
        <li>계약일자 기간(한 번에 1년 이내 권장)·지역(시도/시군구, 전체 가능) 선택 → <b>CSV 다운</b> (엑셀 XLSX 도 됨)</li>
        <li>받은 파일을 여기에 그대로 올리기 — 앞의 안내문 줄·한글 인코딩(CP949)은 알아서 처리합니다.</li>
      </ol>
      <div className="board-bar">
        <select value={ds} onChange={(e) => setDs(e.target.value)} aria-label="데이터셋" disabled={busy}>
          <option value="">자동 감지</option>
          {rtms.map((r) => <option key={str(r.key)} value={str(r.key)}>{str(r.name)}</option>)}
        </select>
        <input ref={inp} type="file" accept=".csv,.xlsx" disabled={busy} aria-label="파일"
          onChange={(e) => { setFile(e.target.files?.[0] || null); setErr(""); }} />
        <button className="btn primary" disabled={!file || busy} onClick={go}>{busy ? "올리는 중…" : "업로드"}</button>
        {file && !busy && <span className="caption">{file.name} · {mb(file.size)}</span>}
      </div>
      {prog !== null && (
        <div style={{ margin: "8px 0", display: "flex", gap: 8, alignItems: "center" }}>
          <span className="progress" style={{ flex: 1, maxWidth: 360 }}><i style={{ width: `${Math.round(prog * 100)}%` }} /></span>
          <span className="caption">{prog < 1 ? `올리는 중 ${Math.round(prog * 100)}%` : "올림 완료 · 읽고 저장하는 중…"}</span>
        </div>
      )}
      <p className="caption" style={{ margin: "6px 0" }}>CSV(CP949·UTF-8)·XLSX, 최대 {maxMb}MB. 지원 지역 목록에 없는 시군구의 거래는 넣지 않고 '지역 불일치'로 셉니다.</p>
      {err && <Alert kind="err">{err}</Alert>}
      {res && (
        <Alert kind={num(res.inserted) ? "ok" : "info"}>
          <b>{str(res.dataset_name)}</b> {str(res.filename)} — 읽은 거래 {num(res.rows_total).toLocaleString()}건 ·
          새로 넣음 <b>{num(res.inserted).toLocaleString()}</b> · 중복 {num(res.duplicates).toLocaleString()} · 지역 불일치 {num(res.unmatched).toLocaleString()}
          {num(res.invalid) > 0 && ` · 읽지 못한 줄 ${num(res.invalid).toLocaleString()}`}
          {!!res.ymd_from && <> · 기간 {ym(res.ymd_from)}~{ym(res.ymd_to)} ({num(res.months)}개월)</>}
          {num(res.regions) > 0 && ` · 시군구 ${num(res.regions)}곳`}
          <div className="caption">판정: {str(res.detected_by)} · 인코딩 {str(res.encoding)}</div>
          {!!str(res.note) && <div className="caption">{str(res.note)}</div>}
        </Alert>
      )}
      <div className="board-bar" style={{ marginTop: 14 }}>
        <b>업로드 기록</b>
        {paged.sizeSel}
        <span className="caption">{paged.info}</span>
      </div>
      {hist.error && <Alert kind="err">{hist.error}</Alert>}
      <DataTable
        rows={paged.shown}
        empty="아직 올린 파일이 없습니다."
        cols={["uploaded_at", "dataset_name", "filename", "rows_total", "inserted", "duplicates", "unmatched", "period", "note"]}
        labels={{ uploaded_at: "올린 시각", dataset_name: "데이터셋", filename: "파일", rows_total: "읽음", inserted: "신규",
          duplicates: "중복", unmatched: "지역 밖", period: "기간", note: "메모" }}
        render={{
          uploaded_at: (v) => <span style={{ whiteSpace: "nowrap" }}>{at(v)}</span>,
          dataset_name: (v) => <span style={{ whiteSpace: "nowrap" }}>{str(v)}</span>,
          filename: (v, r) => <span title={str(v)}>{str(v).length > 36 ? str(v).slice(0, 34) + "…" : str(v)}<div className="caption">{str(r.encoding)} · {mb(num(r.size))}</div></span>,
          rows_total: (v) => num(v).toLocaleString(),
          inserted: (v) => <b>{num(v).toLocaleString()}</b>,
          duplicates: (v) => num(v).toLocaleString(),
          unmatched: (v) => num(v).toLocaleString(),
          period: (_, r) => r.ymd_from ? <span style={{ whiteSpace: "nowrap" }}>{ym(r.ymd_from)}~{ym(r.ymd_to)}</span> : "-",
          note: (v) => <span className="caption" style={{ display: "block", minWidth: 160, maxWidth: 300 }}>{str(v)}</span>,
        }}
        rowKey={(r) => str(r.id)}
      />
      {paged.pager}
    </div>
  );
}
