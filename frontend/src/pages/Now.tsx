// 현행 수치 (/now) — 대출 규제·금리·세금·청약 숫자를 기준일·근거 링크와 함께 (Phase 3).
// 값은 관리 화면에서 근거를 확인해 게시한 것과, 수집된 한국은행 자료에서 자동으로 읽은 것만 나온다.
import { Link } from "react-router-dom";
import { Alert } from "../components/ui";
import { basisOf, ParamCard, useNow } from "../policy";
import { useProfile } from "../profile";
import "./RealEstate.css";

export default function Now() {
  const { data, map } = useNow();
  const { profile } = useProfile();
  const basis = basisOf(profile);
  return (
    <div className="re-page">
      <div>
        <div className="eyebrow">현행 수치</div>
        <h2 className="sec-h">지금 적용되는 <span className="grad">규제·금리·세율</span></h2>
        <p className="sec-p">
          계산할 때 쓰는 숫자를 한곳에 모았어요. 각 숫자에 기준일과 근거 링크를 달았고, 최근 {data?.changed_days ?? 30}일 안에 바뀐 값에는 <span className="re-tag warn">변경됨</span> 표시를 붙여요.{" "}
          <Link className="re-link" to="/calc">내 집 계산기 →</Link>
        </p>
        <p className="caption" style={{ margin: "6px 0 0" }}>
          {basis.mine ? <>예시 금액은 <Link to="/me">내 프로필</Link>의 예산 상한·연소득으로 계산했어요.</>
            : <>예시 금액은 8억원 집·연소득 7,000만원 기준이에요. <Link to="/me">내 프로필</Link>에 예산·연소득을 넣으면 내 숫자로 바뀌어요.</>}
        </p>
      </div>
      {!data ? <div className="page-loading">불러오는 중…</div> : !data.groups.length ? (
        <Alert kind="info">확인을 마친 수치가 아직 없어요. 곧 채워집니다.</Alert>
      ) : data.groups.map((g) => (
        <section key={g.name} aria-label={g.name}>
          <h3 className="now-grp">{g.name}</h3>
          <div className="now-grid">{g.items.map((p) => <ParamCard key={p.key} p={p} basis={basis} map={map} />)}</div>
        </section>
      ))}
      <p className="calc-note">
        규제 비율은 지역·주택 수·소득·대출 상품에 따라 달라요. 여기 숫자는 대표값이니 실제 대출·세금은 은행·위택스·세무사에게 꼭 확인하세요.
        금리는 한국은행 공표 자료를 그대로 옮긴 값이에요.
      </p>
    </div>
  );
}
