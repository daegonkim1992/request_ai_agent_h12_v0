import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, actionRequestBody, apiErrorDetails, confirmCases, confirmTarget, createRequest, fetchAnalysts, fetchHealth, fetchTargetOptions, fetchUiContract, getRequest, listRequests, runAction, saveForm, type Analyst, type RequestDetail, type RequestItem, type TargetOptions, type UiContract } from './api/client'

type DisplayError = { message: string; details: string[] }

function problem(error: unknown): DisplayError {
  if (error instanceof ApiError) return { message: error.message, details: apiErrorDetails(error) }
  return { message: error instanceof Error ? error.message : '처리 중 오류가 발생했습니다', details: [] }
}
function formatDate(value: string) { return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function titleOf(detail: RequestDetail) { return detail.request_title }
function statusLabel(status: string, contract: UiContract | null) { return contract?.workflow.statuses[status] ?? status }
function actionLabel(action: string, contract: UiContract | null) { return contract?.workflow.actions[action]?.label ?? action }

function TargetPicker({ options, onConfirm }: { options: TargetOptions; onConfirm: (body: Record<string, unknown>) => void }) {
  const [division, setDivision] = useState(''); const [lineup, setLineup] = useState(''); const [platform, setPlatform] = useState(''); const [chassis, setChassis] = useState(''); const [analysis, setAnalysis] = useState(''); const [scope, setScope] = useState(''); const [cooling, setCooling] = useState(''); const [acceptChange, setAcceptChange] = useState(false)
  const unique = (values: string[]) => [...new Set(values)]
  const lineups = unique(options.taxonomy.filter((path) => path.division === division).map((path) => path.product_lineup))
  const platforms = unique(options.taxonomy.filter((path) => path.division === division && path.product_lineup === lineup).map((path) => path.platform ?? ''))
  const chassisOptions = unique(options.taxonomy.filter((path) => path.division === division && path.product_lineup === lineup && (path.platform ?? '') === platform).map((path) => path.chassis ?? ''))
  const selected = options.taxonomy.find((path) => path.division === division && path.product_lineup === lineup && (path.platform ?? '') === platform && (path.chassis ?? '') === chassis)
  const scopeNeeded = selected?.requires_analysis_scope ?? false
  const coolingNeeded = options.analysis_types.find((item) => item.code === analysis)?.requires_cooling_method ?? false
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!selected || !analysis) return; onConfirm({ taxonomy_id: selected.id, analysis_type: analysis, ...(scopeNeeded ? { analysis_scope: scope } : {}), ...(coolingNeeded ? { cooling_method: cooling } : {}), ...(acceptChange ? { accept_change: true } : {}) }) }
  return <form className="field-grid" onSubmit={submit}>
    <label>사업부<select value={division} required onChange={(event) => { setDivision(event.target.value); setLineup(''); setPlatform(''); setChassis('') }}><option value="">선택</option>{unique(options.taxonomy.map((path) => path.division)).map((item) => <option key={item}>{item}</option>)}</select></label>
    <label>Product Line-up<select value={lineup} required disabled={!division} onChange={(event) => { setLineup(event.target.value); setPlatform(''); setChassis('') }}><option value="">선택</option>{lineups.map((item) => <option key={item}>{item}</option>)}</select></label>
    <label>Platform<select value={platform} disabled={!lineup} onChange={(event) => { setPlatform(event.target.value); setChassis('') }}><option value="">선택</option>{platforms.map((item) => <option key={item} value={item}>{item || '해당 없음'}</option>)}</select></label>
    <label>Chassis<select value={chassis} disabled={!lineup || !platforms.length} onChange={(event) => setChassis(event.target.value)}><option value="">{chassisOptions.includes('') ? '해당 없음' : '선택'}</option>{chassisOptions.filter(Boolean).map((item) => <option key={item}>{item}</option>)}</select></label>
    <label className="wide">해석유형<select value={analysis} required onChange={(event) => setAnalysis(event.target.value)}><option value="">선택</option>{options.analysis_types.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select>{analysis && <small>{options.analysis_types.find((item) => item.code === analysis)?.description}</small>}</label>
    {scopeNeeded && <label>해석 범위<select value={scope} required onChange={(event) => setScope(event.target.value)}><option value="">선택</option>{options.analysis_scope.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>}
    {coolingNeeded && <label>냉각 방식<select value={cooling} required onChange={(event) => setCooling(event.target.value)}><option value="">선택</option>{options.cooling_method.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>}
    <label className="check wide"><input type="checkbox" checked={acceptChange} onChange={(event) => setAcceptChange(event.target.checked)} /> 이미 확정한 대상의 변경 영향을 수락합니다</label><button className="primary" disabled={!selected || !analysis}>의뢰 대상 확정</button>
  </form>
}

export default function App() {
  const [items, setItems] = useState<RequestItem[]>([]); const [counts, setCounts] = useState<Record<string, number>>({})
  const [detail, setDetail] = useState<RequestDetail | null>(null); const [todoOnly, setTodoOnly] = useState(true)
  const [targetOptions, setTargetOptions] = useState<TargetOptions | null>(null)
  const [uiContract, setUiContract] = useState<UiContract | null>(null)
  const [analysts, setAnalysts] = useState<Analyst[]>([])
  const [editor, setEditor] = useState('{}'); const [activeAction, setActiveAction] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null); const [error, setError] = useState<DisplayError | null>(null)

  const open = async (id: string, clear = true) => { try { const item = await getRequest(id); setDetail(item); setEditor(JSON.stringify(item.form, null, 2)); setActiveAction(null); setError(null); if (clear) setNotice(null) } catch (cause) { setError(problem(cause)) } }
  const refresh = async (selected = detail?.id) => { try { const result = await listRequests(todoOnly); setItems(result.items); setCounts(result.status_counts); if (selected) await open(selected, false) } catch (cause) { setError(problem(cause)) } }
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        await fetchHealth()
        const [result, targets, contract] = await Promise.all([listRequests(todoOnly), fetchTargetOptions(), fetchUiContract()])
        if (!cancelled) { setItems(result.items); setCounts(result.status_counts); setTargetOptions(targets); setUiContract(contract); setError(null) }
      } catch (cause) { if (!cancelled) setError(problem(cause)) }
    }
    void load()
    return () => { cancelled = true }
  }, [todoOnly])
  const create = async () => { try { const item = await createRequest(); setNotice('새 의뢰를 만들었습니다. 의뢰 대상과 내용을 입력하세요.'); await refresh(item.id) } catch (cause) { setError(problem(cause)) } }
  const save = async () => { if (!detail) return; try { await saveForm(detail.id, JSON.parse(editor) as Record<string, unknown>, false); setNotice('의뢰서 내용을 저장했습니다.'); await refresh(detail.id) } catch (cause) { setError(problem(cause)) } }
  const act = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!detail || !activeAction) return; const data = new FormData(event.currentTarget); const inputs = uiContract?.workflow.actions[activeAction]?.inputs ?? []; try { const snapshot = inputs.some((input) => input.kind === 'form_snapshot') ? JSON.parse(editor) as Record<string, unknown> : undefined; const body = actionRequestBody(inputs, Object.fromEntries(data.entries()), snapshot); await runAction(detail.id, activeAction, body); setNotice(`${actionLabel(activeAction, uiContract)} 처리가 완료되었습니다.`); await refresh(detail.id) } catch (cause) { setError(problem(cause)) } }
  const target = async (body: Record<string, unknown>) => { if (!detail) return; try { await confirmTarget(detail.id, body); setNotice('의뢰 대상을 확정했습니다.'); await refresh(detail.id) } catch (cause) { setError(problem(cause)) } }
  const cases = async () => { if (!detail) return; try { await confirmCases(detail.id); setNotice('Case 구성을 확인했습니다.'); await refresh(detail.id) } catch (cause) { setError(problem(cause)) } }
  const loadAnalysts = async () => { try { setAnalysts((await fetchAnalysts()).items) } catch (cause) { setError(problem(cause)) } }

  return <main className="app-shell"><header className="topbar"><div><p className="eyebrow">CFD REQUEST PLATFORM</p><h1>해석의뢰</h1></div><button className="primary" onClick={() => void create()}>+ 새 의뢰</button></header><p className="auth-note">로그인 인증은 인증 프록시가 처리합니다. 현재 권한으로 가능한 기능만 표시됩니다.</p>
    {error && <div className="alert error" role="alert"><div><strong>{error.message}</strong>{error.details.length > 0 && <ul>{error.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>}</div><button onClick={() => setError(null)}>닫기</button></div>}{notice && <div className="alert success">{notice}<button onClick={() => setNotice(null)}>닫기</button></div>}
    <section className="workspace"><aside className="request-list"><div className="list-header"><h2>{todoOnly ? '내 할 일' : '전체 의뢰'}</h2><label className="switch"><input type="checkbox" checked={todoOnly} onChange={(event) => setTodoOnly(event.target.checked)} /> 내 할 일만</label></div><div className="counts">{Object.entries(counts).map(([key, value]) => <span key={key}>{statusLabel(key, uiContract)} <b>{value}</b></span>)}</div>{items.length === 0 ? <p className="empty">표시할 의뢰가 없습니다.</p> : <ul>{items.map((item) => <li key={item.id}><button className={detail?.id === item.id ? 'selected' : ''} onClick={() => void open(item.id)}><span className="status">{statusLabel(item.status, uiContract)}</span><strong>{item.request_title}</strong><small>의뢰자 {item.requester_id} · 요청일 {item.request_date}</small>{item.pending && <em>{item.pending.kind === 'cancel' ? '취소 요청 대기' : '변경 요청 대기'}</em>}</button></li>)}</ul>}</aside>
      <section className="detail-panel">{!detail ? <div className="welcome"><h2>의뢰를 선택하세요</h2><p>할 일 목록에서 의뢰를 열거나 새 의뢰를 만들어 작성할 수 있습니다.</p></div> : <><div className="detail-heading"><div><span className="status">{statusLabel(detail.status, uiContract)}</span><h2>{titleOf(detail)}</h2><p>의뢰자 {detail.requester_id} · 담당자 {detail.analyst_id ?? '미배정'} · 요청일 {detail.request_date}</p></div>{detail.pending && <div className="pending">{detail.pending.kind === 'cancel' ? '취소' : '변경'} 요청 대기<br /><small>{detail.pending.comment}</small></div>}</div><div className="actions">{detail.available_actions.map((key) => <button key={key} onClick={() => { setActiveAction(key); if ((uiContract?.workflow.actions[key]?.inputs ?? []).some((input) => input.kind === 'analyst')) void loadAnalysts() }}>{actionLabel(key, uiContract)}</button>)}{detail.can_edit_form && <button onClick={() => setActiveAction('edit')}>의뢰서 편집</button>}<button onClick={() => void cases()}>Case 확인</button></div>
        {activeAction === 'edit' && <section className="card"><h3>의뢰서 편집</h3><p>의뢰서 데이터는 JSON으로 저장됩니다. 기준 데이터에 맞는 값과 구조를 입력한 뒤 제출 조건을 확인하세요.</p><textarea className="json-editor" value={editor} onChange={(event) => setEditor(event.target.value)} spellCheck={false} /><div className="button-row"><button className="primary" onClick={() => void save()}>저장</button><button onClick={() => setActiveAction(null)}>취소</button></div></section>}
        {detail.can_edit_form && targetOptions && <details className="card"><summary>의뢰 대상 확정</summary><TargetPicker options={targetOptions} onConfirm={(body) => void target(body)} /></details>}
        {activeAction && activeAction !== 'edit' && <ActionForm action={activeAction} contract={uiContract} analysts={analysts} onSubmit={act} onCancel={() => setActiveAction(null)} />}
        <section className="history"><h3>진행 이력</h3>{detail.events.length === 0 ? <p className="empty">아직 진행 이력이 없습니다.</p> : <ol>{detail.events.map((event) => <li key={event.seq}><b>{actionLabel(event.action, uiContract)}</b><span>{statusLabel(event.from_status, uiContract)} → {statusLabel(event.to_status, uiContract)}</span><small>{event.actor_id} · {formatDate(event.at)}{event.reason_code ? ` · ${event.reason_code}` : ''}{event.comment ? ` · ${event.comment}` : ''}</small></li>)}</ol>}</section></>}</section></section></main>
}

function ActionForm({ action, contract, analysts, onSubmit, onCancel }: {
  action: string; contract: UiContract | null; analysts: Analyst[]
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>; onCancel: () => void
}) {
  const inputs = contract?.workflow.actions[action]?.inputs ?? []
  return <section className="card"><h3>{actionLabel(action, contract)}</h3><form className="field-grid" onSubmit={(event) => void onSubmit(event)}>
    {inputs.map((input) => input.kind === 'reason_code' ? <label key={input.key}>{input.label}<select name={input.request_key} required={input.required}><option value="">선택</option>{(input.choices ?? []).map((choice) => <option key={choice.code} value={choice.code}>{choice.label}</option>)}</select></label>
      : input.kind === 'textarea' ? <label key={input.key} className="wide">{input.label}<textarea name={input.request_key} required={input.required} /></label>
        : input.kind === 'analyst' ? <label key={input.key}>{input.label}<select name={input.request_key} required={input.required}><option value="">선택</option>{analysts.map((analyst) => <option key={analyst.id} value={analyst.id}>{analyst.name} · {analyst.department}</option>)}</select></label>
          : input.kind === 'boolean' ? <label key={input.key} className="check wide"><input name={input.request_key} type="checkbox" required={input.required} /> {input.label}</label>
            : <p key={input.key} className="wide hint">{input.label}는 현재 의뢰서 스냅샷으로 제출됩니다.</p>)}
    <div className="button-row wide"><button className="primary">처리</button><button type="button" onClick={onCancel}>취소</button></div>
  </form></section>
}
