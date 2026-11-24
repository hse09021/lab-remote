import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { scenarioQuery, useDrawScenario } from '@/api/scenarios'
import { ApiError } from '@/api/client'
import { Dialog } from '@/components'
import s from './Scenario.module.css'

/**
 * Scenario — 읽기 전용 (IDE 왼쪽 · ADE 오른쪽이 같은 컴포넌트).
 * 사람이 "그리기"를 눌렀을 때만 에이전트가 읽기만 해서 그려요. 파일이 바뀌어도 저절로
 * 다시 그리지 않고 알려만 줘요. "실행 탭에 채우기"는 명령만 채우고 실행은 직접 눌러요.
 */
export function ScenarioView({ project, onFill }: { project: string; onFill: (command: string) => void }) {
  const q = useQuery(scenarioQuery(project))
  const draw = useDrawScenario(project)
  const [asking, setAsking] = useState(false)
  const data = q.data
  const sc = data?.scenario
  const running = data?.job.state === 'running'
  const changed = data?.changed ?? []

  return (
    <div className={s.wrap}>
      <div className={s.head}>
        <span className={s.title}>Scenario · {project}</span>
        <span className={s.badge}>읽기 전용</span>
      </div>
      {q.isPending && <span className={s.muted}>불러오는 중이에요…</span>}
      {sc && (
        <span className={s.muted}>
          생성일 {new Date(sc.createdAt * 1000).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })} · Claude · 파일{' '}
          {Object.keys(sc.hashes).length}개 분석 · <span className={s.mono}>{data?.path}</span>
        </span>
      )}
      {sc?.summary && <p className={s.summary}>{sc.summary}</p>}

      {running && <div className={s.notice}>그리는 중이에요. 코드는 읽기만 해요. 끝나면 여기에 표시돼요.</div>}
      {data?.job.state === 'error' && <div className={s.warn}>그리지 못했어요: {data.job.error}</div>}
      {sc && changed.length > 0 && (
        <div className={s.warn}>
          그린 뒤에 변경된 파일이 있어요: <span className={s.mono}>{changed.slice(0, 3).join(', ')}</span>
          {changed.length > 3 ? ` 외 ${changed.length - 3}개` : ''}. 자동으로 다시 그리지는 않아요.
        </div>
      )}
      <button type="button" className={s.drawBtn} disabled={running || draw.isPending} onClick={() => setAsking(true)}>
        {sc ? 'Claude로 다시 그리기' : 'Claude로 그리기'}
      </button>
      {draw.error && <div className={s.warn}>{draw.error instanceof ApiError ? draw.error.message : String(draw.error)}</div>}

      {!sc && !running && !q.isPending && (
        <p className={s.muted}>아직 그린 적이 없어요. 데이터 준비 → 학습 → 평가 같은 순서를 코드에서 읽어 보여 줘요.</p>
      )}

      {sc && (
        <ol className={s.steps}>
          {sc.steps.map((st, i) => (
            <li key={i} className={s.step} data-changed={(st.changed ?? []).length > 0}>
              <div className={s.stepHead}>
                <span className={s.num}>{i + 1}</span>
                <span className={s.stepName}>{st.name}</span>
                {(st.changed ?? []).length > 0 && <span className={s.changedTag}>코드 변경됨</span>}
              </div>
              {st.command ? <code className={s.command}>{st.command}</code> : <span className={s.muted}>명령을 찾지 못했어요</span>}
              {st.inputs.length > 0 && (
                <div className={s.io}>
                  <span className={s.ioLabel}>입력</span>
                  <span className={s.mono}>{st.inputs.join(' · ')}</span>
                </div>
              )}
              {st.outputs.length > 0 && (
                <div className={s.io}>
                  <span className={s.ioLabel}>출력</span>
                  <span className={s.mono}>{st.outputs.join(' · ')}</span>
                </div>
              )}
              {st.env && (
                <div className={s.io}>
                  <span className={s.ioLabel}>환경</span>
                  <span>{st.env}</span>
                </div>
              )}
              {st.note && <div className={s.note}>{st.note}</div>}
              {st.command && (
                <button type="button" className={s.fill} onClick={() => onFill(st.command)}>
                  실행 탭에 채우기
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      <p className={s.footer}>
        순서만 보여 줘요. 단계를 자동으로 연달아 실행하지 않아요. "실행 탭에 채우기"는 명령만 입력하고, 실행은 직접 해야 해요.
      </p>

      <Dialog
        open={asking}
        title="Claude로 시나리오를 그릴까요?"
        confirmLabel="그리기"
        busy={draw.isPending}
        onClose={() => setAsking(false)}
        onConfirm={() => draw.mutate('', { onSuccess: () => setAsking(false) })}
      >
        <span>
          에이전트를 계획 모드로 열어 <b>읽기만</b> 해요(Read · Glob · Grep). 명령을 실행하거나 파일을 수정하지 않아요. 프로젝트 크기에 따라 몇 분 걸리고
          사용량이 조금 들어요. 결과는 <code>.labremote/scenarios/main.json</code>에 저장돼요.
        </span>
      </Dialog>
    </div>
  )
}
