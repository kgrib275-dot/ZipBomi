// 오늘의 내 브리핑 (2026-11-20) — 홈 맨 위. 오늘 챙길 일정·접수 임박 공고·새 공고·관심 단지 새 거래·금리·가점을 규칙으로 모았다 (GET /api/me/briefing).
// 로그인 없이도 이 브라우저의 저장값으로 만든다. 저장값이 없으면 30초 시작 안내(첫 사용 안내)로 이끈다.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useMe } from "../me";
import { useProfile } from "../profile";

type Card = { kind: string; icon: string; title: string; sub: string; to: string; urgent: boolean };
type Brief = { cards: Card[]; has_profile: boolean; regions: string[]; date: string };
const WD = "일월화수목금토";

export default function MyBriefing() {
  const { me } = useMe();
  const { profile } = useProfile();
  const [d, setD] = useState<Brief | null>(null);
  useEffect(() => {
    if (!me) return;
    let alive = true;
    get<Brief>("me/briefing").then((r) => alive && setD(r)).catch(() => alive && setD(null));
    return () => { alive = false; };
  }, [me?.visitor, profile?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;
  const now = new Date();
  const head = `오늘의 내 브리핑 · ${now.getMonth() + 1}월 ${now.getDate()}일(${WD[now.getDay()]})`;
  if (!d.has_profile) {
    return (
      <section className="brief brief-empty" aria-label="오늘의 내 브리핑">
        <b>{head}</b>
        <span className="caption">내 지역과 상황을 알려 주면 오늘 챙길 일정·새 공고를 여기에 모아 드려요 (30초).</span>
        <button type="button" className="btn sm primary" onClick={() => window.dispatchEvent(new Event("zg-open-onboarding"))}>내 브리핑 만들기</button>
      </section>
    );
  }
  if (!d.cards.length) {
    return (
      <section className="brief brief-empty" aria-label="오늘의 내 브리핑">
        <b>{head}</b><span className="caption">오늘은 급하게 챙길 게 없어요 ✅ 새 공고가 올라오면 여기에 먼저 보여 드려요.</span>
        <Link className="btn sm ghost" to="/calendar">청약 일정 보기</Link>
      </section>
    );
  }
  return (
    <section className="brief" aria-label="오늘의 내 브리핑">
      <div className="brief-h"><b>{head}</b>{d.regions.length > 0 && <span className="caption"> · {d.regions.join(", ")} 기준</span>}</div>
      <div className="brief-grid">
        {d.cards.map((c, i) => (
          <Link key={i} className={`brief-card${c.urgent ? " urgent" : ""}`} to={c.to}>
            <span className="ic" aria-hidden="true">{c.icon}</span>
            <span className="tx"><b>{c.title}</b><small>{c.sub}</small></span>
            {c.urgent && <span className="re-tag warn">급해요</span>}
          </Link>
        ))}
      </div>
    </section>
  );
}
