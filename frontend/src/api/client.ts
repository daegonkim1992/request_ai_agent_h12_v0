// 백엔드 API 호출의 단일 진입점. 인증 헤더는 로그인 인증 프록시가 붙인다.

export class ApiError extends Error {
  readonly status: number
  readonly fields?: Record<string, string>
  readonly issues: ApiIssue[]
  readonly impact?: Record<string, unknown>

  constructor(status: number, message: string, fields?: Record<string, string>, issues: ApiIssue[] = [], impact?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.fields = fields
    this.issues = issues
    this.impact = impact
  }
}

export type ApiIssue = { location: string; message: string }
type ErrorBody = { error?: string; fields?: unknown; issues?: unknown; impact?: unknown }

function recordOfStrings(value: unknown): Record<string, string> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const entries = Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
  return entries.length ? Object.fromEntries(entries) : undefined
}

function issueList(value: unknown): ApiIssue[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ApiIssue => Boolean(item) && typeof item === 'object' &&
    typeof (item as ApiIssue).location === 'string' && typeof (item as ApiIssue).message === 'string')
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

export function apiErrorFromResponse(status: number, fallback: string, problem: ErrorBody): ApiError {
  return new ApiError(status, problem.error ?? fallback, recordOfStrings(problem.fields), issueList(problem.issues), objectValue(problem.impact))
}

export function apiErrorDetails(error: ApiError): string[] {
  const fields = Object.entries(error.fields ?? {}).map(([location, message]) => `${location}: ${message}`)
  const issues = error.issues.map((issue) => `${issue.location}: ${issue.message}`)
  const impact = Array.isArray(error.impact?.messages)
    ? error.impact.messages.filter((message): message is string => typeof message === 'string')
    : []
  return [...fields, ...issues, ...impact]
}

export function actionRequestBody(inputs: WorkflowInput[], values: Record<string, unknown>, formSnapshot: Record<string, unknown> | undefined): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  for (const input of inputs) {
    if (input.kind === 'form_snapshot') body[input.request_key] = formSnapshot
    else if (input.kind === 'boolean') body[input.request_key] = values[input.request_key] === 'on'
    else {
      const value = values[input.request_key]
      if (typeof value === 'string' && value.trim()) body[input.request_key] = value.trim()
    }
  }
  return body
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({})) as ErrorBody
    throw apiErrorFromResponse(response.status, `${response.status} ${response.statusText}`, problem)
  }
  return response.json() as Promise<T>
}

export type Health = { status: string; workflow_statuses: number }
export type Pending = { kind: string; requested_by: string; comment: string; requested_at: string }
export type RequestItem = {
  id: string; status: string; requester_id: string; requester_department: string
  analyst_id: string | null; held_by: string | null; pending: Pending | null; created_at: string
  request_title: string; request_date: string
  available_actions: string[]; can_edit_form: boolean
}
export type EventItem = {
  seq: number; event_type: string; action: string; from_status: string; to_status: string
  actor_id: string; at: string; reason_code: string | null; comment: string | null
}
export type ResultItem = { round_no: number; summary: string; registered_by: string; registered_at: string }
export type RequestDetail = RequestItem & {
  form: Record<string, unknown>; events: EventItem[]; results: ResultItem[]
  revisions: Array<{ revision_no: number; created_by: string; created_at: string; cause_event: string }>
}
export type RequestList = { items: RequestItem[]; status_counts: Record<string, number> }
export type TargetPath = { id: string; division: string; product_lineup: string; platform: string | null; chassis: string | null; requires_analysis_scope: boolean }
export type TargetOptions = {
  release: string; taxonomy: TargetPath[]
  analysis_types: Array<{ code: string; label: string; description: string; requires_cooling_method: boolean }>
  analysis_scope: Array<{ code: string; label: string }>
  cooling_method: Array<{ code: string; label: string }>
}
export type Analyst = { id: string; name: string; department: string }
export type UiField = { path: string; label: string; kind: string; required: boolean; choices?: Array<{ code: string; label: string }>; pattern?: string }
export type UiRepeater = {
  path: string; label: string; min_items: number
  id?: { key: string; generation: 'client_uuid'; preserve_on_edit: boolean }
  count_from?: string; visible_when?: { path: string; equals: string }
}
export type WorkflowInput = { key: string; request_key: string; label: string; required: boolean; kind: 'reason_code' | 'textarea' | 'analyst' | 'form_snapshot' | 'boolean'; choices?: Array<{ code: string; label: string }> }
export type UiContract = {
  options: Record<string, { choices: Array<{ code: string; label: string }>; allow_custom: boolean; default: string | null }>
  fields: Array<{ path: string; label: string; kind: string; unit: string | null; options: string | null; required: boolean; required_for_types: string[] }>
  geometry: {
    base_product: { path: string; label: string; required: boolean; id: UiRepeater['id']; fields: UiField[] }
    comparison_products: { repeater: UiRepeater; fields: UiField[] }
  }
  reason_codes: Record<string, { label: string; choices: Array<{ code: string; label: string }> }>
  condition_groups: Array<{
    key: string; label: string; column: string | null; package_label: string | null; single: boolean
    toggle: { key: string; label: string; off_when: boolean } | null; checks: string[]
    repeaters: UiRepeater[]
    fields: Array<{ key: string; label: string; kind: string; unit: string | null; required: boolean; column: string | null }>
  }>
  condition_specials: {
    operating: { max_fans: number; rpm_modes: Array<{ code: string; label: string }>; airflow_purposes: Array<{ code: string; label: string }>; fields: UiField[]; repeaters: UiRepeater[] }
    heat_exchanger: { fields: UiField[]; catalog_endpoint: string }
    filter: { fields: UiField[]; repeaters: UiRepeater[] }
    installation: { fields: UiField[] }
    pcb: { device_bases: Array<{ code: string; label: string }>; contact_resistance_default: Record<string, unknown>; materials_default: Array<Record<string, unknown>>; refrigerant_fields: Array<Record<string, unknown>>; fields: UiField[]; repeaters: UiRepeater[] }
    measurement: { required: boolean; items: Array<{ key: string; label: string; unit?: string }> }
  }
  workflow: { statuses: Record<string, string>; actions: Record<string, { label: string; requires: string[]; inputs: WorkflowInput[] }> }
}

export const fetchHealth = () => api<Health>('/health')
export const fetchTargetOptions = () => api<TargetOptions>('/reference/target-options')
export const fetchUiContract = () => api<UiContract>('/ui-contract')
export const fetchAnalysts = () => api<{ items: Analyst[] }>('/users/analysts')
export const listRequests = (todoOnly: boolean) => api<RequestList>(`/requests${todoOnly ? '?todo=true' : ''}`)
export const getRequest = (id: string) => api<RequestDetail>(`/requests/${id}`)
export const createRequest = () => api<RequestItem>('/requests', 'POST')
export const saveForm = (id: string, form: Record<string, unknown>, confirmCase: boolean) =>
  api<RequestItem>(`/requests/${id}/form`, 'PUT', { form, confirm_case: confirmCase })
export const confirmTarget = (id: string, body: Record<string, unknown>) => api<RequestItem>(`/requests/${id}/target`, 'POST', body)
export const confirmCases = (id: string) => api<RequestItem>(`/requests/${id}/cases/confirm`, 'POST', {})
export const runAction = (id: string, action: string, body: Record<string, unknown>) =>
  api<RequestItem>(`/requests/${id}/actions/${action}`, 'POST', body)
