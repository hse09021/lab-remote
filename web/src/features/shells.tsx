import { ScreenShell } from './ScreenShell'

/*
 * 1단계 화면 껍데기 — 라우트 · 제목 · 보기 전환 · 구역 자리.
 * 구역 이름과 순서는 각 목업(docs/v3/mockups/)을 따르고, 채우는 단계는 PLAN 6장을 따라요.
 */

export function CondaShell() {
  return (
    <ScreenShell
      title="Conda"
      mockup="Conda.dc.html"
      aside={{ title: '환경 목록', step: 7, note: 'base · labremote 는 보호돼요.' }}
      sections={[
        { title: '환경 정보', step: 7 },
        { title: '패키지 설치', step: 7, note: '바뀌는 것 미리 보기(dry-run) → 설치.' },
        { title: '패키지', step: 7 },
        { title: '환경 삭제', step: 7, note: '이름을 입력해야 지워지고, 지우기 전에 environment.yml 을 남겨요.' },
      ]}
    />
  )
}
