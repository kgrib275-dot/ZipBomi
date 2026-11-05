// 문의함 (2026-11-03) — 사용자 문의·보미AI 사용 신청을 한곳에서. 처리하지 않은 문의가 위로 오고, '처리 완료'로 표시한다.
// 이메일은 가려 보이고, '답장 쓰기'를 누르면 사유('문의 답장')를 접속기록에 남긴 뒤 메일 앱을 연다 (ISMS-P 개인정보 표시 제한).
import { useState } from "react";
import { Alert, Metric, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, Email, Row, asArray, num, str, useAct } from "./common";

export default function Contacts() {
  const { data, error, reload } = useLoad(() => A.get<Row>("contacts"), []);
  const act = useAct();
  const all = asArray(data, "contacts");
  const [open, setOpen] = useState<number | null>(null);
  const [view, setView] = useState("처리 안 한 것");
  const rows = all.filter((r) => view === "전체" || (view === "처리 안 한 것" ? !str(r.handled_at) : !!r.urgent));
  const reply = async (r: Row) => {
    await act(() => A.post("audit/event", { kind: "reveal", target: `문의 #${str(r.id)}`, reason: "문의 답장" }));
    const subject = encodeURIComponent("[집보미] 문의하신 내용에 답변드립니다");
    window.location.href = `mailto:${str(r.email)}?subject=${subject}`;
  };
  return (
    <div>
      <AdminHead title="문의함" note="고객센터 '문의하기'와 보미AI 사용 신청이 여기에 모입니다. 새 문의가 오면 종류·미처리 건수만 알림 메일로 가고(내용은 싣지 않음), 접수 후 12개월이 지나면 자동으로 지워집니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="처리 안 한 문의" v={num(data?.open)} />
        <Metric k="기한 있는 문의(처리 전)" v={num(data?.urgent_open)} />
        <Metric k="전체" v={num(data?.count)} />
      </div>
      {Number(data?.urgent_open) > 0 && <Alert kind="warn">⚖ 개인정보 열람·정정·삭제 요청은 접수 후 <b>10일 이내</b>, 권리침해 신고는 <b>3일 안</b>(자체 목표)에 처리·답변해야 해요. 아래 '기한'을 확인하세요.</Alert>}
      <Tabs items={["처리 안 한 것", "중요 문의", "전체"]} value={view} onChange={setView} />
      {!rows.length && <p className="caption">{all.length ? "이 보기에는 문의가 없어요." : "아직 문의가 없어요."}</p>}
      <div className="contact-list">
        {rows.map((r) => {
          const id = num(r.id);
          const done = !!str(r.handled_at);
          return (
            <div key={id} className={`list-row contact${done ? " done" : ""}`}>
              <div className="grow">
                <div><b>{str(r.name) || "(이름 없음)"}</b> · <Email v={r.email} /> · <span className="caption">{str(r.created_at).slice(0, 16).replace("T", " ")}</span>
                  <span className={`badge${r.urgent ? " orange" : ""}`} style={{ marginLeft: 6 }}>{str(r.kind) || "일반 문의"}</span>
                  {done ? <span className="badge" style={{ marginLeft: 6 }}>처리 완료 {str(r.handled_at).slice(5, 16).replace("T", " ")}</span> : <span className="badge orange" style={{ marginLeft: 6 }}>미처리</span>}
                  {!done && !!str(r.due) && (() => {
                    const left = num(r.days_left);
                    return <span className={`badge ${left <= 2 ? "red" : "orange"}`} style={{ marginLeft: 6 }}>기한 {str(r.due).slice(5)} · {left < 0 ? `${-left}일 지남` : left === 0 ? "오늘까지" : `D-${left}`}</span>;
                  })()}</div>
                <p style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{open === id || str(r.message).length <= 160 ? str(r.message) : `${str(r.message).slice(0, 160)}…`}</p>
                {str(r.message).length > 160 && <button type="button" className="linkish" onClick={() => setOpen(open === id ? null : id)}>{open === id ? "접기" : "전체 보기"}</button>}
              </div>
              <div className="btn-row" style={{ alignSelf: "flex-start" }}>
                <button type="button" className="btn sm" onClick={() => reply(r)}>✉ 답장 쓰기</button>
                <button type="button" className={`btn sm ${done ? "ghost" : "primary"}`} onClick={async () => {
                  const ok = await act(() => A.post(`contacts/${id}/handled`, { done: !done }), done ? "미처리로 되돌렸습니다." : "처리 완료로 표시했습니다.");
                  if (ok) reload();
                }}>{done ? "미처리로" : "처리 완료"}</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
