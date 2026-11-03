// 관리 > 회원 계정 (2026-11-02) — 메일 링크 로그인 계정 목록·저장 현황·강제 로그아웃·삭제 (backend/api/routers/admin_accounts.py).
import { useMemo, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, AdminHead, Email, Row, maskEmail, useAct, usePaged } from "./common";

type Acc = { id: number; email: string; created_at: string; last_login_at: string | null; last_seen: string | null; subscribed: boolean;
  ask_credits: number; ask_used: number;
  watch: number; apply_fav: number; alerts: number; notes: number; calcs: number; items: number; events: number; profile: boolean; memo: boolean };
type Res = { rows: Acc[]; total: number; active_7d: number; login_mails_24h: number };

export default function Accounts() {
  const [q, setQ] = useState("");
  const { data, error, reload } = useLoad(() => A.get<Res>("accounts"), []);
  const act = useAct();
  const rows = useMemo(() => (data?.rows || []).filter((r) => !q.trim() || r.email.toLowerCase().includes(q.trim().toLowerCase())), [data, q]);
  const pg = usePaged("accounts", rows as unknown as Row[], q, 20);
  const logout = async (r: Acc) => {
    if (!window.confirm(`${maskEmail(String(r.email))} 계정을 모든 기기에서 로그아웃할까요? 저장한 자료는 그대로 남습니다.`)) return;
    await act(() => A.post(`accounts/${r.id}/logout`), "모든 기기에서 로그아웃했습니다."); reload();
  };
  const grant = async (r: Acc, n: number) => {
    await act(() => A.post(`accounts/${r.id}/ask-grant`, { n }), `${maskEmail(String(r.email))} 보미AI ${n}회를 더했습니다.`); reload();
  };
  const remove = async (r: Acc) => {
    if (!window.confirm(`${maskEmail(String(r.email))} 계정과 저장 자료(관심 단지·알림·메모·참여 기록)를 모두 삭제할까요? 되돌릴 수 없습니다.`)) return;
    await act(() => A.del(`accounts/${r.id}`), "삭제했습니다."); reload();
  };
  const d = (s: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "-");
  return (
    <div>
      <AdminHead title="회원 계정" note="메일 링크로 로그인한 계정입니다. 비밀번호는 없고, 로그인 링크·쿠키 값은 화면에 내려보내지 않습니다." />
      {error && <Alert kind="err">{error}</Alert>}
      {data && (
        <div className="re-metrics" style={{ marginBottom: 12 }}>
          {[["전체 계정", data.total], ["최근 7일 로그인", data.active_7d], ["24시간 로그인 메일", data.login_mails_24h]].map(([k, v]) => (
            <div key={String(k)} className="re-card"><div className="caption">{k}</div><b style={{ fontSize: "1.4rem" }}>{Number(v).toLocaleString()}</b></div>
          ))}
        </div>
      )}
      <div className="board-bar">
        <input type="text" className="bq" placeholder="이메일 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="검색" />
        <span className="sp" />{pg.sizeSel}
      </div>
      <p className="caption">{pg.info}</p>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>이메일</th><th>가입</th><th>마지막 로그인</th><th>마지막 활동</th><th>구독</th><th>보미AI</th><th>저장 현황</th><th /></tr></thead>
          <tbody>
            {(pg.shown as unknown as Acc[]).map((r) => (
              <tr key={r.id}>
                <td><b><Email v={r.email} /></b></td>
                <td style={{ whiteSpace: "nowrap" }}>{d(r.created_at)}</td>
                <td style={{ whiteSpace: "nowrap" }}>{d(r.last_login_at)}</td>
                <td style={{ whiteSpace: "nowrap" }}>{d(r.last_seen)}</td>
                <td>{r.subscribed ? "✓" : "-"}</td>
                <td style={{ whiteSpace: "nowrap" }}>{r.ask_used}/{r.ask_credits}회{" "}
                  <button className="btn sm" onClick={() => grant(r, 5)} title="문의로 신청받으면 횟수를 늘려 주세요">+5</button>{" "}
                  <button className="btn sm ghost" onClick={() => grant(r, 30)}>+30</button></td>
                <td className="caption">{[r.profile && "프로필", r.watch && `관심 단지 ${r.watch}`, r.apply_fav && `관심 공고 ${r.apply_fav}`, r.alerts && `알림 ${r.alerts}`,
                  r.notes && `노트 ${r.notes}`, r.calcs && `계산 ${r.calcs}`, r.items && `메모·알림 ${r.items}`, r.events && `일정 ${r.events}`, r.memo && "메모"]
                  .filter(Boolean).join(" · ") || "없음"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn sm" onClick={() => logout(r)}>강제 로그아웃</button>{" "}
                  <button className="btn sm ghost" onClick={() => remove(r)}>삭제</button>
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={8} className="caption">{data ? "아직 로그인한 계정이 없습니다." : "불러오는 중…"}</td></tr>}
          </tbody>
        </table>
      </div>
      {pg.pager}
      <p className="caption">강제 로그아웃은 계정 식별값을 새로 바꿔 모든 기기의 로그인을 끊습니다(저장 자료 유지). 삭제는 사용자의 '내 기록 지우기'와 같은 범위입니다.</p>
    </div>
  );
}
