// 피드백 (2026-11-19) — 보미AI 👎 와 '이상해요' 오류 신고. 처리하지 않은 것이 위로 온다. 👍는 건수만 센다(글은 저장하지 않음).
import { useState } from "react";
import { Alert, Metric, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, Row, asArray, num, str, useAct } from "./common";

export default function Feedback() {
  const [view, setView] = useState("처리 안 한 것");
  const { data, error, reload } = useLoad(() => A.get<Row>("feedback"), []);
  const act = useAct();
  const c = (data?.counts || {}) as Row;
  const all = asArray(data, "items").filter((r) => str(r.kind) !== "ask_up");
  const rows = all.filter((r) => view === "전체" || (view === "처리 안 한 것" ? str(r.status) === "open" : str(r.kind) === (view === "답변 👎" ? "ask_down" : "data")));
  const label = (k: string) => (k === "ask_down" ? "답변 👎" : "오류 신고");
  return (
    <div>
      <AdminHead title="피드백" note="보미AI 답변 👎(질문·답변 앞부분)와 화면 '이상해요' 신고가 모입니다. 이메일·계정 정보는 저장하지 않고, 180일이 지나면 자동으로 지워져요. 나쁜 답이 반복되면 관련 노트를 보강하세요." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="처리 안 한 신고" v={num(c.open)} />
        <Metric k="답변 👍" v={num(c.ask_up)} />
        <Metric k="답변 👎" v={num(c.ask_down)} />
        <Metric k="오류 신고" v={num(c.data)} />
      </div>
      <Tabs items={["처리 안 한 것", "답변 👎", "오류 신고", "전체"]} value={view} onChange={setView} />
      {!rows.length && <p className="caption">이 보기에는 피드백이 없어요.</p>}
      {rows.map((r) => {
        const id = num(r.id), done = str(r.status) === "done";
        return (
          <div key={id} className={`list-row${done ? " done" : ""}`}>
            <div className="grow">
              <div><span className={`badge${str(r.kind) === "ask_down" ? " orange" : ""}`}>{label(str(r.kind))}</span> <span className="caption">{str(r.created_at).slice(0, 16).replace("T", " ")} · {str(r.page)}</span></div>
              <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap" }}><b>{str(r.kind) === "ask_down" ? "질문: " : ""}</b>{str(r.text)}</p>
              {!!str(r.extra) && <p className="caption" style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{str(r.kind) === "ask_down" ? "답변: " : "참고: "}{str(r.extra)}</p>}
            </div>
            <div className="btn-row" style={{ alignSelf: "flex-start" }}>
              <button type="button" className={`btn sm ${done ? "ghost" : "primary"}`} onClick={async () => { if (await act(() => A.post(`feedback/${id}/status`, { done: !done }))) reload(); }}>{done ? "미처리로" : "처리 완료"}</button>
              <button type="button" className="btn sm ghost" onClick={async () => { if (window.confirm("이 피드백을 지울까요?") && await act(() => A.del(`feedback/${id}`), "지웠습니다.")) reload(); }}>지우기</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
