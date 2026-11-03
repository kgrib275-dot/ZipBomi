// 관리자·접속 — 관리자 IP 추가/삭제, 접속 기록(관리 작업·질문하기·페이지 조회·전체), 관리자 행동 기록 (app_pages/admin/access.py).
import { useEffect, useState } from "react";
import { Alert, Metric, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, DataTable, Field, Row, asArray, isObj, pick, str, useAct, usePaged, useRemembered } from "./common";

const VIEWS = ["관리 작업", "질문하기", "페이지 조회", "전체"];

export default function Access() {
  const ips = useLoad(() => A.get<unknown>("admin-ips"), []);
  const logs = useLoad(() => A.get<unknown>("access-logs?limit=2000"), []);
  const actions = useLoad(() => A.get<unknown>("actions"), []);
  const act = useAct();
  const list = asArray(ips.data, "ips", "admin_ips", "items");
  const myIp = isObj(ips.data) ? str(pick(ips.data, "my_ip", "client_ip")) : "";
  const [f, setF] = useState({ label: "", ip: "" });
  useEffect(() => { if (myIp && !f.ip) setF((x) => ({ ...x, ip: myIp })); }, [myIp]); // eslint-disable-line react-hooks/exhaustive-deps
  const [view, setView] = useRemembered("view", VIEWS[0]);
  const [q, setQ] = useRemembered<string>("q", "");
  const all = asArray(logs.data, "logs", "items");
  const needle = q.trim().toLowerCase();
  const rows = all.filter((r) => {
    const a = str(r.action);
    return (view === "전체" || (view === "관리 작업" ? !["view", "ask"].includes(a) : view === "질문하기" ? a === "ask" : a === "view"))
      && (!needle || `${str(r.ip)} ${str(r.page)} ${str(r.action)} ${str(r.detail)} ${str(r.created_at)}`.toLowerCase().includes(needle));
  });
  const pg = usePaged(`logs-${view}`, rows, needle, 50);
  const actionRows = asArray(actions.data, "actions", "items");

  return (
    <div>
      <AdminHead title="관리자·접속" note="관리 화면은 관리자 로그인(토큰·OTP)으로만 열립니다. 관리 API 요청·로그인·다운로드·전체 보기는 모두 접속기록에 남습니다 (2년 보관)." />
      <AdminAudit />
      <h3>관리자 IP</h3>
      <p className="caption">내 IP: {myIp || "로컬"} · 등록 IP 는 .env ZIPGENIE_TRUST_ADMIN_IPS=1 일 때만 토큰 없이 관리자로 인정합니다 (기본 끔 — 2026-11-03).</p>
      {ips.error && <Alert kind="err">{ips.error}</Alert>}
      {list.map((a) => (
        <div key={str(a.id)} className="list-row">
          <div className="grow"><b>{str(a.label)}</b> · <code>{str(a.ip)}</code></div>
          <button className="btn sm" onClick={async () => {
            if (!window.confirm(`${str(a.label)} (${str(a.ip)}) 를 삭제할까요?`)) return;
            await act(() => A.del(`admin-ips/${a.id}`).catch(() => A.del("admin-ips", { id: a.id })), "삭제했습니다.");
            ips.reload();
          }}>🗑 삭제</button>
        </div>
      ))}
      <div className="inline" style={{ margin: "10px 0 20px" }}>
        <Field label="이름"><input type="text" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} /></Field>
        <Field label="IP"><input type="text" value={f.ip} onChange={(e) => setF({ ...f, ip: e.target.value })} /></Field>
        <button className="btn" disabled={!(f.label.trim() && f.ip.trim())} onClick={async () => {
          await act(() => A.post("admin-ips", { label: f.label.trim(), ip: f.ip.trim() }), "추가했습니다.");
          setF({ label: "", ip: myIp }); ips.reload();
        }}>추가</button>
      </div>

      <h3>접속 기록</h3>
      <Tabs items={VIEWS} value={view} onChange={setView} />
      {logs.error && <Alert kind="err">{logs.error}</Alert>}
      {rows.length ? (
        <div>
          <div className="metrics">
            <Metric k="최근 기록" v={rows.length} />
            <Metric k="고유 IP" v={new Set(rows.map((r) => str(r.ip))).size} />
          </div>
          <div className="board-bar">
            <input type="text" className="bq" placeholder="IP·페이지·동작·내용 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="검색" />
            <span className="caption">{pg.info}</span><span className="sp" />{pg.sizeSel}
          </div>
          <DataTable rows={pg.shown} cols={rows[0] && ["created_at", "ip", "page", "action", "detail"].every((c) => c in rows[0]) ? ["created_at", "ip", "page", "action", "detail"] : undefined}
            labels={{ created_at: "시각", ip: "IP", page: "화면", action: "동작", detail: "내용" }}
            render={{ action: (v) => ACTION_KO[str(v)] || str(v) }} />
          {pg.pager}
        </div>
      ) : <p className="caption">기록이 없습니다.</p>}

      <h3 style={{ marginTop: 20 }}>관리자 행동 기록</h3>
      {actions.error && <Alert kind="err">{actions.error}</Alert>}
      <DataTable rows={actionRows as Row[]} tall empty="기록이 없습니다." labels={{ id: "번호", created_at: "시각", ip: "IP", page: "화면", action: "동작", detail: "내용" }}
        render={{ action: (v) => ACTION_KO[str(v)] || str(v) }} />
    </div>
  );
}


// 관리자 접속기록 (2026-11-03 ISMS-P 2.9.4) — GET /api/admin/audit, 위변조 검사 GET /api/admin/audit/verify (월 1회 이상 점검)
const AUDIT_KINDS: [string, string][] = [["", "전체"], ["request", "관리 요청"], ["login", "로그인"], ["login_fail", "로그인 실패"], ["login_locked", "잠김"], ["logout", "로그아웃"],
  ["download", "다운로드"], ["reveal", "전체 보기"], ["audit_check", "점검"]];
const AUDIT_KO: Record<string, string> = Object.fromEntries(AUDIT_KINDS.filter(([k]) => k));
// 접속 기록의 동작 이름 (2026-11-03 — login_try 같은 원문이 그대로 보였다)
const ACTION_KO: Record<string, string> = {
  view: "페이지 조회", ask: "질문하기", login_mail: "로그인 메일", login_try: "로그인 메일 요청", login_verify: "로그인 확인", login_revoke: "모든 기기 로그아웃",
  confirm_mail: "구독 확인 메일", ask_link_mail: "질문 연결 메일", subscribe_try: "구독 신청", subscribe_day: "구독 신청(하루)", confirm_try: "구독 확인",
  unsub_try: "구독 해지", "제한 기록": "남용 제한",
};
function AdminAudit() {
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  // 검색은 입력을 멈춘 뒤 0.5초에 — 예전엔 글자마다 요청해 그 요청이 다시 접속기록에 쌓였다 (2026-11-03)
  const [qq, setQq] = useState("");
  useEffect(() => { const t = window.setTimeout(() => setQq(q.trim()), 500); return () => window.clearTimeout(t); }, [q]);
  const list = useLoad(() => A.get<{ rows: Row[]; keep_days: number }>(`audit?limit=500&kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(qq)}`), [kind, qq]);
  const [check, setCheck] = useState<Row | null>(null);
  const act = useAct();
  const rows = list.data?.rows || [];
  const pg = usePaged(`audit-${kind}`, rows, q, 30);
  return (
    <section>
      <h3>관리자 접속기록</h3>
      <p className="caption">누가(관리자 세션)·언제·어디서(IP)·무엇을(요청·결과)·왜(다운로드·전체 보기 사유) — {list.data?.keep_days ?? 730}일 보관. 행마다 앞 행과 이은 해시로 고치거나 지우면 점검에서 드러납니다.</p>
      <div className="btn-row">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>{AUDIT_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <input placeholder="경로·IP·사유 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn sm" onClick={() => act(async () => setCheck(await A.get<Row>("audit/verify")))}>위변조 점검</button>
      </div>
      {check && <Alert kind={check.ok ? "ok" : "err"}>{check.ok ? `정상 — ${str(check.rows)}건, ${str(check.first)} ~ ${str(check.last)}` : `불일치 — ${str(check.broken_at)}번 기록(${str(check.at)})부터 사슬이 끊겼습니다. 기록이 고쳐졌거나 지워졌을 수 있습니다.`}</Alert>}
      {list.error && <Alert kind="err">{list.error}</Alert>}
      <DataTable rows={pg.shown} cols={["at", "actor", "ip", "kind", "method", "path", "status", "detail"]} render={{ kind: (v) => AUDIT_KO[str(v)] || str(v) }}
        labels={{ at: "시각", actor: "관리자", ip: "IP", kind: "종류", method: "방식", path: "경로", status: "결과", detail: "내용·사유" }} />
      {pg.pager}
    </section>
  );
}
