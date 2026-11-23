import { useParams } from 'react-router-dom'
import { ScreenShell } from './ScreenShell'

/*
 * 1단계 화면 껍데기 — 라우트 · 제목 · 보기 전환 · 구역 자리.
 * 구역 이름과 순서는 각 목업(docs/v3/mockups/)을 따르고, 채우는 단계는 PLAN 6장을 따라요.
 */

export function DashboardShell() {
  return (
    <ScreenShell
      title="Dashboard"
      mockup="MissionControl.dc.html"
      aside={{ title: '에이전트', step: 3, note: '프로젝트 › worktree › 세션 목록, 답 필요가 위로 와요.' }}
      views={[
        {
          id: 'overview',
          label: 'Overview',
          sections: [
            { title: '인사 · 요약', step: 2 },
            { title: '끊긴 실행', step: 2, note: '재부팅으로 끊긴 실행을 배너로 알려요.' },
            { title: '숫자 5칸', step: 2 },
            { title: '답 필요 · 작업 중 · 끝남', step: 3 },
            { title: '열린 PR · 최근 머지', step: 4 },
            { title: '자원', step: 2 },
          ],
        },
        {
          id: 'agents',
          label: 'Agents',
          sections: [{ title: '에이전트 그래프', step: 5, note: '프로젝트별 상자 · You · 세션 · 하위 에이전트 · 학습 실행.' }],
        },
        {
          id: 'schedule',
          label: 'Schedule',
          sections: [
            { title: '24시간 띠', step: 5 },
            { title: '예약 표', step: 5, note: '켜기/끄기 · 수정 · 삭제. 사람이 시각으로 건 것만 돌아요.' },
          ],
        },
      ]}
    />
  )
}

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

export function InboxShell() {
  return (
    <ScreenShell
      title="Inbox"
      mockup="Inbox.dc.html"
      sections={[
        { title: '알림', step: 2, note: '종류 필터(전체 · 답 필요 · 실행 · 예약 · PR·머지 · 시스템), 안 읽은 것만.' },
        { title: 'Discord 웹훅', step: 2, note: '가린 주소 · 테스트 · 바꾸기 · 끊기.' },
        { title: 'Discord 로 보낼 알림', step: 2 },
        { title: '조용한 시간', step: 2 },
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
