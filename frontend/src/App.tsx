import { useEffect, useState } from 'react'
import { fetchHealth, type Health } from './api/client'

// 0단계 골격: 백엔드 연결만 확인한다. 화면 구성은 6단계에서 만든다.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchHealth().then(setHealth, (e: Error) => setError(e.message))
  }, [])

  return (
    <main style={{ padding: '24px 16px', maxWidth: 960, margin: '0 auto' }}>
      <h1 style={{ fontSize: 20 }}>해석의뢰 h12_v0</h1>
      {health && (
        <p style={{ color: 'var(--ok)' }}>
          백엔드 연결됨 · 업무 상태 {health.workflow_statuses}개
        </p>
      )}
      {error && <p style={{ color: 'var(--error)' }}>백엔드 연결 실패: {error}</p>}
      {!health && !error && <p style={{ color: 'var(--text-muted)' }}>연결 확인 중…</p>}
    </main>
  )
}
