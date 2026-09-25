# FamilyFin PWA workspace

This Next.js workspace owns the Hebrew-first browser shell and the same-origin API client. It is configured on Tailwind CSS 4 and the shadcn base-nova component conventions, with RTL generation, FamilyFin semantic color tokens, and system/light/dark theme support. It currently contains sign-in/session UX and route shells for the nine existing Streamlit sections. Feature modules will connect these routes to their matching `/api/v1` contracts in later work.

## Local development

Use Node `22.14.0` (see the repository `.nvmrc`) and npm:

```sh
npm ci
npm run dev
```

The browser expects the Python API at the same origin under `/api/v1`. For local development, configure a same-origin proxy in front of Next and FastAPI; no cross-origin API URL or credentialed CORS mode is built into the client. Production commands are `npm run build` and `npm run start`.

## Privacy behavior

- Session and feature requests use same-origin cookies, `cache: "no-store"`, and `credentials: "same-origin"`.
- No household response, session token, upload, preview, or form draft is written to browser persistence. The only local preference is `familyfin-theme`.
- The service worker bypasses `/api/`, all non-GET requests, and navigation HTML. It caches only Next static assets, local icons, the manifest, and the generic offline page.
- API 401, 5xx, and fetch failures are broadcast to shared session/connectivity state. Any 401 clears in-memory auth and CSRF state; an unavailable API hides protected content even if `navigator.onLine` remains true. The app revalidates on visible-tab resume, browser reconnect, or the reconnect button.
- Every financial section remains unavailable offline and contains no demo financial records.

The shared patterns in `src/components/ui/` provide Tailwind/shadcn buttons, cards, and inputs; loading, empty, and error/retry states; field validation and form actions; a semantic table that becomes labeled cards on narrow screens; and a theme toggle. They accept module-owned content and contain no sample data or calculations.

Desktop navigation groups all nine routes. On phones, four primary destinations stay visible and a keyboard/touch-accessible “עוד” menu groups the other five under review, planning tools, and management.

The service worker cache key includes a release version; bump it in `public/sw.js` for each release. Activation removes older FamilyFin static caches. Hashed Next chunks are cache-first within one release, while the unhashed manifest and icons refresh network-first and fall back to the current static cache while offline. A new worker waits for open tabs to close before activation so an existing page can finish using its current asset set.

Run `npm test` for API-health and component checks, `npm run test:e2e` for Chromium browser acceptance, `npm run lint`, `npm run typecheck`, and `npm run build`. Browser coverage checks RTL sign-in, desktop/mobile navigation, keyboard and touch access, form/table patterns, light/dark contrast, manifest/icons, static-only caching, and offline navigation. API-health tests cover 401, 5xx, fetch outage, CSRF clearing, and restoration after a successful API response.

The login request sends `{ username, password }` to `POST /api/v1/auth/session`. Session bootstrap expects `data.user.id`, `data.user.display_name`, and an in-memory `data.csrf_token`, which matches the current auth contract in T01 PR #5; mutations send `X-CSRF-Token`. The browser acceptance suite still mocks that shape until PR #5 merges, when a live session integration check can run. Account bootstrap/recovery policy, reverse-proxy development setup, production process supervision, and static-export verification remain open.

See [ATTRIBUTION.md](ATTRIBUTION.md) for the pinned MIT visual reference and notice. FamilyFin's theme, RTL copy, module navigation, privacy controls, and financial workflows are custom; no demo records or demo product routes are included.
