// 백엔드 API 호출의 단일 진입점. 화면 컴포넌트는 fetch 를 직접 쓰지 않는다.

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export type Health = { status: string; workflow_statuses: number }

export const fetchHealth = () => getJson<Health>('/health')
