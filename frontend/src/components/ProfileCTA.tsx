// 테스트 결과 끝의 '내 프로필에 저장하고 맞춤 흐름 보기' — 결과는 이미 자동 기록됐으므로 저장을 마무리(flush)하고
// 유형·관심 지역이 없으면 /me, 있으면 홈의 '이번 주 나에게 영향 있는 것'으로 보낸다.
import { useNavigate } from "react-router-dom";
import { hasCore, useProfile } from "../profile";
import "../styles/profile.css";

export default function ProfileCTA({ what, onSave }: { what: string; onSave?: () => void }) {
  const { profile, flush } = useProfile();
  const nav = useNavigate();
  const go = async () => {
    onSave?.();
    await flush();
    nav(hasCore(profile) ? "/#mine" : "/me");
  };
  return (
    <div className="to-profile">
      <span>{what} 결과는 내 프로필에 기록됐어요. 유형·관심 지역까지 정하면 이번 주 노트를 나에게 맞춰 골라 드려요.</span>
      <button type="button" className="btn primary" onClick={go}>내 프로필에 저장하고 맞춤 흐름 보기 →</button>
    </div>
  );
}
