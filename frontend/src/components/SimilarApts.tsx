// 비슷한 단지 3곳 (2026-11-19) — 관심 단지 상세 아래. 같은 시군구에서 최근 6개월 3.3㎡당 거래가·전용면적이 가까운 단지 (GET /api/re/apt/similar). 규칙 계산, AI 없음.
import { Link } from "react-router-dom";
import { get } from "../api";
import { useLoad } from "./ui";

type Res = { rows: { apt: string; dong: string; area: number; pp: number; n: number }[]; base?: { area: number; pp: number }; reason?: string; note?: string };
const man = (v: number) => `${v.toLocaleString("ko-KR")}만원`;

export default function SimilarApts({ lawd, dong, apt }: { lawd: string; dong: string; apt: string }) {
  const r = useLoad(() => get<Res>(`re/apt/similar?lawd=${lawd}&dong=${encodeURIComponent(dong)}&apt=${encodeURIComponent(apt)}`), [lawd, dong, apt]);
  const d = r.data;
  if (!d || !d.rows.length) return d?.reason ? <p className="caption">{d.reason}</p> : null;
  return (
    <div className="similar">
      <h4>비슷한 단지 <small className="caption">3.3㎡당 {d.base ? man(d.base.pp) : ""} · 전용 {d.base?.area}㎡ 기준</small></h4>
      <ul>
        {d.rows.map((x) => (
          <li key={x.apt + x.dong}>
            <Link to={`/my-homes?lawd=${lawd}&dong=${encodeURIComponent(x.dong)}&apt=${encodeURIComponent(x.apt)}`}>{x.apt}</Link>
            <span className="caption"> {x.dong} · 3.3㎡당 {man(x.pp)} · 전용 {x.area}㎡ · 거래 {x.n}건</span>
          </li>
        ))}
      </ul>
      <p className="caption">{d.note}</p>
    </div>
  );
}
