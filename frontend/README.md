# FamilyFin PWA workspace

This Next.js workspace owns the Hebrew-first browser shell and the same-origin API client. It currently contains sign-in/session UX and route shells for the nine existing Streamlit sections. Feature modules will connect these routes to their matching `/api/v1` contracts in later work.

## Local development

Use Node `22.14.0` (see the repository `.nvmrc`) and npm:

```sh
npm ci
npm run dev
```

The browser expects the Python API at the same origin under `/api/v1`. For local development, configure a same-origin proxy in front of Next and FastAPI; no cross-origin API URL or credentialed CORS mode is built into the client. Production commands are `npm run build` and `npm run start`.

## Privacy behavior

- Session and feature requests use same-origin cookies, `cache: "no-store"`, and `credentials: "same-origin"`.
- No household response, session token, upload, preview, or form draft is written to browser persistence.
- The service worker bypasses `/api/`, all non-GET requests, and navigation HTML. It caches only Next static assets, local icons, the manifest, and the generic offline page.
- API 401, 503, and fetch failures are broadcast to the shared session/connectivity state. Any 401 clears in-memory auth and CSRF state; an unavailable API hides protected content even if `navigator.onLine` remains true. The app revalidates on visible-tab resume, browser reconnect, or the reconnect button.
- Every financial section remains unavailable offline and contains no demo financial records.

The shared patterns in `src/components/ui/` provide loading, empty, error/retry, field validation, form actions, and a semantic table that becomes labeled cards on narrow screens. They accept module-owned content and contain no sample data or calculations.

The service worker cache key includes a release version; bump it in `public/sw.js` for each release. Activation removes older FamilyFin static caches. Hashed Next chunks are cache-first within one release, while the unhashed manifest and icons refresh network-first and fall back to the current static cache while offline. A new worker waits for open tabs to close before activation so an existing page can finish using its current asset set.

Focused API-health checks run with `npm test`. To reproduce the UI transition manually, sign in, leave a protected section open, and block the same-origin API request while keeping the browser online (for example, route `/api/v1/auth/session` to a local endpoint that returns 503). The protected shell must switch to the reconnect state; unblocking it and selecting “לנסות שוב” must perform a fresh session check. Returning to a visible tab also rechecks the session. Returning 401 from any API route must immediately switch to sign-in.

The login request currently sends `{ username, password }` to `POST /api/v1/auth/session`. Session bootstrap expects `data.user.id` and `data.user.display_name`, with an optional in-memory `csrf_token`. These frontend DTO details should be aligned with T01's concrete auth response before integration. The bootstrap username/password policy, CSRF token response and header name, sign-in failure semantics, session expiry UX, reverse-proxy development setup, production process supervision, and static-export decision remain unresolved by the T00 contracts.

The shell uses no copied Shadcn Fintech source code. It follows the audited visual direction and replaces the demo with a private FamilyFin identity and empty module shells.
