import react from '@vitejs/plugin-react'
import { createHmac } from 'node:crypto'
import { defineConfig } from 'vite'

// 개발 중에는 /api 요청을 Flask 개발 서버로 넘긴다. 실제 인증은 배포 프록시가 맡는다.
// H12_AUTH_SECRET 이 있으면 개발 프록시만 HMAC 헤더를 만들어 브라우저에는 비밀키를 노출하지 않는다.
const userId = process.env.H12_DEV_USER_ID ?? 'requester-1'
const secret = process.env.H12_DEV_PROXY_SECRET ?? process.env.H12_AUTH_SECRET
const backendUrl = process.env.H12_BACKEND_URL ?? 'http://127.0.0.1:8512'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
        configure: (proxy) => proxy.on('proxyReq', (proxyRequest) => {
          if (!secret) return
          const timestamp = String(Math.floor(Date.now() / 1000))
          const signature = createHmac('sha256', secret).update(`${userId}:${timestamp}`).digest('hex')
          proxyRequest.setHeader('X-H12-User-Id', userId)
          proxyRequest.setHeader('X-H12-Auth-Timestamp', timestamp)
          proxyRequest.setHeader('X-H12-Auth-Signature', signature)
        }),
      },
    },
  },
})
