import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    // Where the dev server forwards /api. Not hard-coded to the Docker service name: outside Docker
    // `backend` does not resolve. Set VITE_PROXY_TARGET in frontend/.env (or in the container's environment):
    //   - on the host, or through an SSH tunnel to the server's port 8932:  http://127.0.0.1:8932  (default)
    //   - inside docker compose, next to the backend service:               http://backend:8932
    // This only matters when VITE_API_BASE_URL is the relative `/api`; an absolute URL there makes the
    // browser call the backend directly and the proxy is not used.
    const env = loadEnv(mode, process.cwd(), '')
    const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8932'

    return {
        plugins: [vue()],
        resolve: {
            alias: {
                '@': fileURLToPath(new URL('./src', import.meta.url))
            }
        },
        server: {
            proxy: {
                '/api': {
                    target: proxyTarget,
                    changeOrigin: true,
                    rewrite: (path) => path,
                },
            },
            host: '0.0.0.0',
            port: 3000,
            // Lets this dev server be reached through a tunnel (e.g. cloudflared's
            // `tunnel --url`) for sharing with someone off this network -- Vite
            // otherwise rejects any request whose Host header isn't localhost, to
            // guard against DNS-rebinding attacks. Scoped to trycloudflare.com's
            // subdomains rather than allowing every host.
            allowedHosts: ['.trycloudflare.com'],
            fs: {
                // อนุญาตให้เข้าถึงไฟล์นอก project root
                strict: false,
                allow: ['..']
            }
        },
        build: {
            target: 'esnext'
        },
        // เพิ่ม static assets สำหรับ videos
        publicDir: 'public'
    }
})
