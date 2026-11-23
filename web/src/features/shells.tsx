import { useParams } from 'react-router-dom'
import { ScreenShell } from './ScreenShell'

/*
 * 1단계 화면 껍데기 — 라우트 · 제목 · 보기 전환 · 구역 자리.
 * 구역 이름과 순서는 각 목업(docs/v3/mockups/)을 따르고, 채우는 단계는 PLAN 6장을 따라요.
 */

export function AdeShell() {
  const { id } = useParams()
  return (
    <ScreenShell
      title={`ADE · ${id ?? ''}`}
      mockup="ADE.dc.html"
      aside={{ title: '세션', step: 3, note: '프로젝트 › worktree › 세션, 하위 에이전트, 전체 / 내 차례.' }}
      sections={[
        { title: '채팅', step: 3, note: '도구 사용 줄 · 할 일 · 승인 카드(diff · 이유 · 허용 / 이 세션에서 계속 허용 / 거부).' },
        { title: 'Scenario', step: 6 },
        { title: '변경', step: 3 },
        { title: '실행', step: 4 },
      ]}
    />
  )
}

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
