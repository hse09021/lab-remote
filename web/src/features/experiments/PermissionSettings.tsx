import { useState } from 'react'
import { useSavePermissions } from '@/api/permissions'
import clsx from 'clsx'
import { useQueries } from '@tanstack/react-query'
import { permissionsQuery, projectsQuery } from '@/api/experiments'
import type {
  ApprovalLogEntry,
  Permission,
  PermissionAction,
  PermissionMode,
  PermissionsPayload,
} from '@/api/types'
import type { Column, SegmentedItem } from '@/components'
import {
  Button,
  CollapsedRail,
  DataTable,
  DividedCell,
  DividedRow,
  ErrorState,
  KeyValueRow,
  LoadingState,
  MetricTile,
  MetricTileRow,
  Pill,
  RadioOption,
  RadioOptionGroup,
  Resizer,
  SectionHeader,
  SegmentedControl,
  Skeleton,
  TagChip,
} from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { ProjectSidebar } from './ProjectSidebar'
import s from './PermissionSettings.module.css'
import { useIsMobile } from '@/lib/useMediaQuery'
import { MobilePermissions } from '../mobile/MobilePermissions'

const PERMISSION_ORDER: Permission[] = ['allow', 'ask', 'block']

export default function PermissionSettings() {
  const isMobile = useIsMobile()
  if (isMobile) return <MobilePermissions />

  const nav = usePaneResize({
    initial: 250,
    min: 200,
    max: 400,
    dir: 1,
    collapsible: true,
  })

  const [projects, permissions] = useQueries({
    queries: [projectsQuery(), permissionsQuery()],
  })

  return (
    <>
      {nav.closed && (
        <CollapsedRail side="left" label="사이드바 펼치기" onExpand={nav.toggle} />
      )}
      <ProjectSidebar
        style={nav.style}
        onCollapse={nav.toggle}
        data={projects.data}
        isError={projects.isError}
      />
      <Resizer handle={nav.resizerProps} label="실험 메뉴 너비 조절" />

      <main className={s.main}>
        {permissions.isError ? (
          <>
            <Header modeName={null} />
            <ErrorState
              title="권한 설정을 불러오지 못했어요"
              error={permissions.error}
              onRetry={() => void permissions.refetch()}
            />
          </>
        ) : permissions.data ? (
          <PermissionBody data={permissions.data} />
        ) : (
          <>
            <Header modeName={undefined} />
            <LoadingState label="권한 설정을 불러오는 중이에요…" />
          </>
        )}
      </main>
    </>
  )
}

/* ── 머리말 ───────────────────────────────────────────────── */

function Header({
  modeName,
  dirty,
  saving,
  onSave,
}: {
  modeName: string | null | undefined
  dirty?: boolean
  saving?: boolean
  onSave?: () => void
}) {
  return (
    <div className={s.headerRow}>
      <div className={s.titleBlock}>
        <h1 className={s.title}>권한·종료 조건</h1>
        {modeName === undefined ? (
          <Skeleton width={220} height={20} />
        ) : modeName === null ? (
          <span className={s.subtitle}>지금 단계를 확인하지 못했어요</span>
        ) : (
          <span className={s.subtitle}>
            지금은 <span className={s.modeName}>{modeName}</span> 단계예요
          </span>
        )}
      </div>
      <Button variant="primary" disabled={!modeName || !dirty || saving} onClick={onSave}>
        {saving ? '저장하는 중' : '변경 사항 저장'}
      </Button>
    </div>
  )
}

/* ── 본문 ─────────────────────────────────────────────────── */

function PermissionBody({ data }: { data: PermissionsPayload }) {
  // 저장해 둔 값이 있으면 그걸로 시작해요 (저장소에 남아 있어요)
  // 프리셋을 바꾸면 행별 수동 설정은 초기화해요 (목업과 같은 동작)
  const [mode, setMode] = useState<PermissionMode>(data.saved?.mode ?? 'full')
  const [overrides, setOverrides] = useState<Record<string, Permission>>(
    data.saved?.overrides ?? {},
  )
  const savePermissions = useSavePermissions()

  const dirty =
    mode !== (data.saved?.mode ?? 'full') ||
    JSON.stringify(overrides) !== JSON.stringify(data.saved?.overrides ?? {})

  const current = data.modes.find((m) => m.id === mode)
  const permissionOf = (a: PermissionAction) => overrides[a.key] ?? a.defaults[mode]

  const segments: SegmentedItem<Permission>[] = PERMISSION_ORDER.map((v) => ({
    value: v,
    label: data.labels[v],
    tone: v,
  }))

  const columns: Column<PermissionAction>[] = [
    {
      key: 'name',
      label: '행동',
      // 굵기는 <td>에 걸어야 해요 — 안쪽 <span>에 주면 표가 열 너비를
      // 다르게 계산해서 권한 열이 밀려요
      cellClassName: s.actionName,
      render: (a) => a.name,
    },
    {
      key: 'desc',
      label: '범위',
      cellClassName: s.actionDesc,
      render: (a) => a.desc,
    },
    {
      key: 'perm',
      label: '권한',
      // 목업은 width:300px이지만 box-sizing 리셋이 없어 내용 너비였어요.
      // 우리는 border-box라 왼쪽 패딩 12 + 테두리 1을 더해 같은 폭이 돼요.
      width: 313,
      render: (a) => (
        <SegmentedControl
          items={segments}
          value={permissionOf(a)}
          onChange={(v) => setOverrides((prev) => ({ ...prev, [a.key]: v }))}
          label={a.name}
          disabled={a.locked}
        />
      ),
    },
  ]

  const isFull = mode === 'full'

  return (
    <>
      <Header
        modeName={current?.name ?? ''}
        dirty={dirty}
        saving={savePermissions.isPending}
        onSave={() => savePermissions.mutate({ mode, overrides })}
      />

      {/* 권한 단계 */}
      <section id="mode" aria-label="권한 단계" className={clsx(s.section, s.sectionTight)}>
        <h2 className={s.h2}>권한 단계</h2>
        <RadioOptionGroup label="권한 단계" className={s.modeCards}>
          {data.modes.map((m) => (
            <RadioOption
              key={m.id}
              name={m.name}
              desc={m.desc}
              selected={m.id === mode}
              onSelect={() => {
                setMode(m.id)
                setOverrides({})
              }}
            />
          ))}
        </RadioOptionGroup>
      </section>

      {/* 행동별 권한 */}
      <section id="actions" aria-label="행동별 권한" className={s.section}>
        <SectionHeader title="행동별 권한" aside={data.actionsCaption} />
        <DataTable
          label="행동별 권한"
          columns={columns}
          rows={data.actions}
          rowKey={(a) => a.key}
          cellY={10}
          minWidth={720}
        />
      </section>

      {/* 종료 조건 */}
      <section id="stop" aria-label="종료 조건" className={s.section}>
        <SectionHeader title="종료 조건" aside={data.configPath} asideMono />
        {isFull ? (
          <div className={s.stopBody}>
            <LockNotice text={data.stopLockNotice} buttonLabel={data.stopLockButton} />
            <MetricTileRow label="종료 조건 값" size="md">
              {data.stopConditions.map((t) => (
                <MetricTile key={t.label} tile={t} />
              ))}
            </MetricTileRow>
          </div>
        ) : (
          <span className={s.stopDisabled}>{data.stopDisabledNotice}</span>
        )}
      </section>

      {/* 알림 */}
      <section id="notify" aria-label="알림" className={s.section}>
        <h2 className={s.h2}>알림</h2>
        <DividedRow label="알림 설정">
          <DividedCell gap={10}>
            <div className={s.cardHead}>
              <span className={s.cardTitle}>{data.discord.title}</span>
              <span className={s.cardCaption}>{data.discord.caption}</span>
            </div>
            <div className={s.tags}>
              {data.discord.tags.map((t) => (
                <TagChip key={t}>{t}</TagChip>
              ))}
            </div>
            <span className={s.webhook}>{data.discord.webhookMasked}</span>
            <Button size="md" compact className={s.testBtn}>
              {data.discord.testLabel}
            </Button>
          </DividedCell>

          <DividedCell gap={8}>
            <div className={s.cardHead}>
              <span className={s.cardTitle}>{data.claudePush.title}</span>
              <span className={s.cardCaption}>{data.claudePush.caption}</span>
            </div>
            {data.claudePush.rows.map((r) => (
              <KeyValueRow key={r.label} item={r} />
            ))}
          </DividedCell>
        </DividedRow>
      </section>

      {/* 승인 기록 */}
      <section id="log" aria-label="승인 기록" className={s.section}>
        <SectionHeader title="승인 기록" aside={data.logPath} asideMono />
        <DataTable
          label="승인 기록"
          columns={LOG_COLUMNS}
          rows={data.approvalLog}
          rowKey={(e) => `${e.time}-${e.action}`}
          cellY={12}
          minWidth={720}
        />
      </section>
    </>
  )
}

/* ── 조각 ─────────────────────────────────────────────────── */

function LockNotice({ text, buttonLabel }: { text: string; buttonLabel: string }) {
  return (
    <div className={s.lockNotice}>
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className={s.lockIcon}
      >
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V8a4 4 0 018 0v3" />
      </svg>
      <span className={s.lockText}>{text}</span>
      <Button size="md" compact>
        {buttonLabel}
      </Button>
    </div>
  )
}

const LOG_COLUMNS: Column<ApprovalLogEntry>[] = [
  {
    key: 'time',
    label: '시각',
    cellClassName: s.logTime,
    render: (e) => e.time,
  },
  { key: 'action', label: '행동', render: (e) => e.action },
  { key: 'request', label: '요청', render: (e) => e.request },
  {
    key: 'result',
    label: '결과',
    render: (e) =>
      e.resultPending ? (
        <Pill tone="warn" variant="status">
          {e.result}
        </Pill>
      ) : (
        e.result
      ),
  },
  { key: 'handledBy', label: '처리', render: (e) => e.handledBy },
]
