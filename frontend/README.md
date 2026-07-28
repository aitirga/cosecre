# @cosecre/web

The Cosecre web client — Vue 3 + Vite, installable as a PWA, which is what makes
phone camera capture work.

It is also **the UI the desktop app renders**. [`desktop/`](../desktop) imports
this package's sources as `@web/*` rather than a built bundle, so there is one
copy of the interface and a change lands in both clients with no publish step in
between.

## Running it

From the repository root, so the workspace links are in place:

```bash
npm install
```

```bash
npm run dev:web
```

The dev server proxies `/api` to the [hub](../hub), so the browser stays on one
origin and there is no CORS to configure. Point it somewhere else with
`COSECRE_HUB_URL` — see [.env.example](.env.example).

## What is where

```
src/
├── api/
│   ├── client.ts       # the hub client: runtime base URL, pluggable token store
│   └── types.ts        # the hub's wire types
├── app.ts              # createCosecreApp() — the entry point both shells call
├── platform.ts         # what the surrounding shell can do that the app cannot
├── style.css           # design tokens + shared primitives
├── components/
├── views/
└── main.ts             # the browser's three-line entry point
```

### The shared entry point

`main.ts` is deliberately trivial. Everything that differs between a browser tab
and an Electron window — where the hub is, where tokens live, how routing works,
what extra panels Settings shows — is an option to `createCosecreApp`:

```ts
createCosecreApp({
  apiBaseUrl: 'https://hub.example.com/api/v1',
  storage: someTokenStore,
  history: 'hash',
  client: 'desktop',
  platform: { name: 'desktop', changeHub, settingsPanel: UpdatePanel },
})
```

Views ask `usePlatform()` for capabilities they might not have, instead of
checking which shell they are in.

### Why refresh is coalesced

The hub rotates refresh tokens and revokes the one it was handed. Two concurrent
refreshes would therefore race — the second presents a spent token and loses the
session — so `client.ts` funnels them all through one shared promise. That is a
correctness requirement, not an optimisation.

## Design

Tokens, the rationale behind each family, and the measured contrast ratio behind
every text colour are documented in [src/style.css](src/style.css). Shared
primitives (`.btn`, `.input`, `.card`, `.table`, `.badge`) live there too, so a
button is the same button everywhere.

One light theme, pinned with `color-scheme: light` — without it Chromium draws
its own widgets dark on a warm cream page when the OS is in dark mode.
