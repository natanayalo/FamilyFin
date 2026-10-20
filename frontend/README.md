# FamilyFin PWA workspace

This Next.js workspace owns the Hebrew-first browser shell and the same-origin API client. It is configured on Tailwind CSS 4 and the shadcn base-nova component conventions, with RTL generation, FamilyFin semantic color tokens, and system/light/dark theme support. It contains sign-in/session UX, route shells for the financial sections, and the API-connected Data Quality, FamilyBiz import, and reconciliation module.

## Local development

Use the repository-root launcher for the real API, isolated data, hot reload,
and disconnected operation:

```sh
./dev setup
./dev init-data
./dev start
```

Run these from the repository root. Use `./dev start --qa` for built-app/PWA
acceptance and `./dev check` for checks with disposable test data.
Use Ctrl-C or repository-root `./dev stop` to stop the local servers. See the
[local runbook](../docs/local_development.md) for debugging, accounts, and data
refresh. For frontend-only work:

Use Node `22.22.2` (see the repository `.nvmrc`) and npm:

```sh
npm ci
npm run dev
```

The browser expects the API at the same origin under `/api/v1`. The launcher
enables a local Next rewrite to loopback FastAPI; frontend-only startup does not
enable it. No cross-origin API URL or credentialed CORS mode is built into the
client. Production commands are `npm run build` and `npm run start`.

## Privacy behavior

- Session and feature requests use same-origin cookies, `cache: "no-store"`, and `credentials: "same-origin"`.
- No household response, session token, upload, preview, or form draft is written to browser persistence. The only local preference is `familyfin-theme`.
- The service worker bypasses `/api/`, all non-GET requests, and navigation HTML. It caches only Next static assets, local icons, the manifest, and the generic offline page.
- API 401, 5xx, and fetch failures are broadcast to shared session/connectivity state. Any 401 clears in-memory auth and CSRF state; an unavailable API hides protected content even if `navigator.onLine` remains true. The app revalidates on visible-tab resume, browser reconnect, or the reconnect button.
- Every financial section requires a reachable authenticated API and contains no demo financial records. Internet connectivity is unnecessary when the local API is reachable.

The shared patterns in `src/components/ui/` provide Tailwind/shadcn buttons, cards, and inputs; loading, empty, and error/retry states; field validation and form actions; a semantic table that becomes labeled cards on narrow screens; and a theme toggle. They accept module-owned content and contain no sample data or calculations.

Desktop navigation groups all nine routes. On phones, four primary destinations stay visible and a keyboard/touch-accessible “עוד” menu groups the other five under review, planning tools, and management.

The service worker cache key includes a release version; bump it in `public/sw.js` for each release. Activation removes older FamilyFin static caches. Hashed Next chunks are cache-first within one release, while the unhashed manifest and icons refresh network-first and fall back to the current static cache while offline. A new worker waits for open tabs to close before activation so an existing page can finish using its current asset set.

Run `npm test` for API-health and component checks, `npm run test:e2e` for Chromium browser acceptance, `npm run lint`, `npm run typecheck`, and `npm run build`. Browser coverage checks RTL sign-in, desktop/mobile navigation, keyboard and touch access, form/table patterns, light/dark contrast, manifest/icons, static-only caching, and offline navigation. API-health tests cover 401, 5xx, fetch outage, CSRF clearing, and restoration after a successful API response.

Login sends `{ username, password }` to `POST /api/v1/auth/session`; session
bootstrap returns `data.user.id`, `data.user.display_name`, and an in-memory
`data.csrf_token`. Mutations send `X-CSRF-Token`. Existing browser acceptance
uses mocks; `./dev check` also runs a disposable real API/browser suite. Account
bootstrap/recovery is host-local. Production supervision is documented in
`docs/pwa/deployment.md`; static export is not configured.

See [ATTRIBUTION.md](ATTRIBUTION.md) for the pinned MIT visual reference and notice. FamilyFin's theme, RTL copy, module navigation, privacy controls, and financial workflows are custom; no demo records or demo product routes are included.
