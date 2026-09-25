# Pinned Shadcn Fintech template audit

Audit date: 2026-09-25. The source was fetched and inspected at the exact upstream main commit below; do not build from the moving main branch.

## Pin and license

- Source: [abderrahimghazali/shadcn-fintech](https://github.com/abderrahimghazali/shadcn-fintech)
- Audited commit: [e338240d10c908ab49403adbcd0bb4cc980ebfce](https://github.com/abderrahimghazali/shadcn-fintech/commit/e338240d10c908ab49403adbcd0bb4cc980ebfce)
- License: MIT, copyright 2026 Abderrahim Ghazali. Reuse and modification are permitted; retain the copyright and license text with copied source or substantial portions. Review individual dependency and asset licenses when vendoring them.
- The code reports itself as a Next.js/shadcn fintech dashboard; it is a UI/demo foundation, not an application backend or production authentication system.

## Runtime and dependencies at the pin

The package scripts are next dev, next build, next start, and eslint. Production is the ordinary Next server. next.config.ts is empty; no static export, PWA plugin, manifest, or service worker is configured. The app uses the Next App Router, React 19, TypeScript, and a mix of Server Components and client components marked with use client. The client components support charts, menus, drag-and-drop, dialogs, and interactions. There is no data API/server action that the FamilyFin backend could reuse.

Production dependencies listed in package.json:

- @base-ui/react, @dnd-kit/core, @dnd-kit/sortable
- @react-three/drei, @react-three/fiber, three, three-globe
- class-variance-authority, clsx, cmdk, date-fns, lucide-react
- motion, next, next-themes, react, react-day-picker, react-dom
- recharts, tailwind-merge, tw-animate-css

Development dependencies:

- @tailwindcss/postcss, @types/node, @types/react, @types/react-dom, @types/three
- eslint, eslint-config-next, shadcn, tailwindcss, typescript

Versions are pinned by the upstream package manifest and pnpm lockfile at the audited commit. Keep only dependencies used by the FamilyFin implementation. In particular, the 3D globe stack, drag-and-drop, and Motion are not requirements for the financial workflows. Recharts may be useful for the current charts. Clerk is mentioned in the README but is not a package dependency and no Clerk integration was found; do not rely on it for household authentication.

## External requests and browser storage

The source scan found no fetch, Axios, XMLHttpRequest, WebSocket, or EventSource calls in app TypeScript. The demo ticker is simulated locally. Images/logos are checked-in assets. The app metadata contains the template’s public Vercel origin, which must be replaced with the private FamilyFin origin or removed. README badges, demo, sponsor, and documentation links are not app data calls.

The root layout imports Geist and Geist Mono using next/font/google. Next fetches these fonts during build and bundles them for runtime. That build-time dependency is unnecessary for Hebrew; replace it with locally packaged Noto Sans Hebrew or another verified Hebrew font. The theme provider and dashboard customizer use browser storage for theme/layout preference. The customizer stores widget order only, but remove the demo customizer and do not persist financial values, uploaded files, preview tokens, drafts, or API responses.

## SSR, RTL, and PWA findings

| Concern | Finding | FamilyFin requirement |
| --- | --- | --- |
| Rendering | App Router and next start require a Next production server in this configuration. No static export is enabled. No evidence that the demo needs server-rendered financial data; the app uses local demo data. | T00 assumes a Node front-end process with no household data rendered or shared-cached by SSR. Static export may be evaluated later but is not verified at this pin. |
| RTL | components.json sets rtl to false and root layout sets lang=en without dir. Some individual components include RTL-aware selectors, including sidebar and calendar behavior, so component support is partial. | Set lang=he and dir=rtl at the root, enable shadcn RTL generation, use logical CSS properties and test all layouts in Hebrew. Do not claim the template is RTL-ready. |
| Font | Geist and Geist Mono are imported from Google Fonts at build time and request Latin subsets. | Bundle a Hebrew-capable font locally; verify numerals, punctuation, currency, and mixed Hebrew/Latin transaction descriptions. |
| PWA | No web app manifest, icons for installability, service worker, cache policy, update strategy, or offline screen was found. | Add installability separately. Cache static assets only; never cache API or personalized financial content. Offline mode must ask the user to reconnect. |
| Responsive | README advertises desktop, tablet, and mobile layouts; the source contains responsive navigation and table/card patterns. | Reuse patterns selectively and verify narrow-phone forms and dense financial tables with RTL. This is not evidence of FamilyFin mobile acceptance. |
| Authentication | The README says Clerk-powered sign-in, but Clerk is absent from the manifest and the source contains demo auth screens without an authenticated FamilyFin API. | Remove demo sign-in/up and implement exactly two application identities in the Python/API boundary. Tailscale membership alone does not identify the app user. |

## Keep, replace, and remove

- Keep as visual reference: shadcn component conventions, neutral theme tokens, responsive shell/sidebar, form and dialog patterns, table/card layouts, and chart presentation where they serve existing FamilyFin data.
- Replace: demo seed objects, demo account/transaction/crypto data, fake actions, template metadata origin, English layout, font loading, and demo sign-in/up.
- Remove from the financial product: transfers, cards, crypto trading, linked-bank/account demos, investment ticker, generic budgets, and demo notifications. They are not current FamilyFin capabilities and must not appear as working navigation.
- Add separately: Hebrew translations, RTL root behavior, authenticated API client, request/error state, upload/preview/commit screens, revision history controls, Tailscale-hosted same-origin deployment, manifest, icons, and static-only service-worker caching.

## Audit limits

This audit identifies the exact source revision and scans the checked-out application sources, package manifest, README, layout, component configuration, and network/storage APIs. It is not a security review of all transitive packages, a legal opinion, or a production readiness certification. Re-run dependency/license and external-request checks against the exact vendored files when the UI foundation PR is opened.
