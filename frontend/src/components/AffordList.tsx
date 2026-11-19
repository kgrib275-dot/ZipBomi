// 내 예산으로 살 수 있는 단지 (2026-11-19) — 계산기 '살 수 있는 최고 집값'을 예산으로, 고른 시군구의 최근 3개월 실거래에서
// 단지·평형별 중위 거래가가 예산 이하인 곳을 거래 많은 순으로 (GET /api/re/affordable). 규칙 계산, AI 없음.
import { useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { RegionPicker } from "../profile";
import { useLoad } from "./ui";

type Res = { region: string; total: number; rows: { apt: string; dong: string; area: number; n: number; median: number; min: number; max: number }[]; source: string; note: string };
const man = (v: number) => { const e = Math.floor(v / 10000), r = v % 10000; return e ? `${e}억${r ? ` ${r.toLocaleString("ko-KR")}만` : ""}원` : `${r.toLocaleString("ko-KR")}만원`; };

function List({ lawd, budget }: { lawd: string; budget: number }) {
  const r = useLoad(() => get<Res>(`re/affordable?lawd=${lawd}&price=${budget}`), [lawd, budget]);
  if (r.loading && !r.data) return <p className="caption">불러오는 중…</p>;
  if (r.error) return <p className="caption">{r.error}</p>;
  const d = r.data;
  if (!d) return null;
  return (
    <>
      {!d.rows.length ? <p className="caption">{d.region}에서 최근 3개월 거래 중 예산 안에 드는 단지를 찾지 못했어요.</p> : (
        <div className="table-wrap"><table className="table afford-table">
          <thead><tr><th>단지</th><th className="num">전용㎡</th><th className="num">중위 거래가</th><th className="num">범위</th><th className="num">거래</th></tr></thead>
          <tbody>{d.rows.map((x) => (
            <tr key={x.apt + x.dong + x.area}>
              <td><Link to={`/my-homes?lawd=${lawd}&dong=${encodeURIComponent(x.dong)}&apt=${encodeURIComponent(x.apt)}`}>{x.apt}</Link> <span className="caption">{x.dong}</span></td>
              <td className="num">{x.area}</td><td className="num"><b>{man(x.median)}</b></td><td className="num caption">{man(x.min)}~{man(x.max)}</td><td className="num">{x.n}건</td>
            </tr>))}</tbody>
        </table></div>
      )}
      <p className="caption">{d.note} 총 {d.total}곳 중 거래 많은 {d.rows.length}곳. 출처: {d.source}.</p>
    </>
  );
}

export default function AffordList({ budget }: { budget: number }) {
  const [code, setCode] = useState<string[]>([]);
  if (!(budget >= 1000)) return null;
  return (
    <details className="expander afford">
      <summary>🏘 이 예산({man(budget)})으로 살 수 있는 단지 찾기</summary>
      <div className="body">
        <p className="caption" style={{ marginTop: 0 }}>시군구를 고르면 최근 3개월 실거래에서 예산 안에 드는 단지를 보여 줘요. 예산은 위 '살 수 있는 최고 집값'(취득세 포함)이에요.</p>
        <RegionPicker value={code} onChange={setCode} max={1} placeholder="시군구 이름 일부 (예: 노원, 분당)" />
        {code[0] && <List lawd={code[0]} budget={budget} />}
      </div>
    </details>
  );
}
