# Cosecre Desktop

Cosecre for Windows, macOS and Linux. It is a client: everything it shows comes
from a [Cosecre Hub](../hub) you point it at on first launch.

The window renders the **same Vue app as the web client**, imported from the
[`frontend`](../frontend) workspace as `@web/*`. There is one copy of the UI, and
a change to it lands in both clients with no publish step in between. What the
desktop shell substitutes is only what has to differ:

| | Web | Desktop |
|---|---|---|
| Hub address | the page's own origin | chosen on first launch, stored in `userData` |
| Session tokens | `localStorage` | the main process, namespaced per hub |
| Routing | `history` | `hash` — a packaged renderer is loaded from `file://` |
| Updates | reload the page | GitHub Releases, via electron-updater |

## Developing

From the repository root, so the workspace links are in place:

```bash
npm install
```

```bash
npm run dev:desktop
```

The app opens on the hub picker until a hub is saved. For a hub on the same
machine, enter `http://127.0.0.1:8000` — the `/api/v1` suffix is added for you.

## Building

```bash
npm run build:mac --workspace cosecre-desktop
```

```bash
npm run build:win --workspace cosecre-desktop
```

Installers land in `release/`. Builds are **unsigned** — macOS needs Gatekeeper
approval on first launch and Windows shows a SmartScreen warning.

`build:win` must run **on Windows** (or on a Windows CI runner); electron-builder
cannot reliably produce the NSIS installer from macOS.

## How it fits together

```
src/
├── shared/     # IPC channel names + types, shared by all three processes
├── main/
│   ├── store.ts    # atomic JSON: hub URL + per-hub session tokens
│   ├── updater.ts  # GitHub Releases check, with runtime signature detection
│   └── menu.ts     # the application menu (⌘C/⌘V live here on macOS)
├── preload/    # contextBridge API (`window.cosecreDesktop`)
└── renderer/   # entry point + the desktop-only Updates panel and CSS
```

### Why tokens live in the main process

A packaged renderer runs on `file://`, where web storage is not something to
rely on. The main process keeps them in an atomically-written JSON file under
`userData` and hands the renderer a snapshot at preload time — synchronously,
because the API client has to attach a token to its very first request.

They are keyed by hub URL. Switching hubs therefore cannot carry a session to a
server it does not belong to.

### Why the renderer is locked down

`contextIsolation` is on and `nodeIntegration` off, so the page cannot reach
Node. The one relaxation is `sandbox: false`, because Electron will not load an
ES-module preload into a sandboxed renderer — isolation is what does the actual
work here, and it stays on.

The CSP in `src/renderer/index.html` allows arbitrary `http:`/`https:` in
`connect-src` and nothing else: the hub address is chosen by whoever installs the
app, so there is no origin to pin. External links and in-place navigations are
both intercepted in the main process and handed to the real browser.

### Pinned Electron version

`electron` is pinned exactly in `package.json` **and** repeated as
`electronVersion` in `electron-builder.yml`. In an npm workspace, Electron is
hoisted to the repository root, where electron-builder cannot find it to read its
version — and it refuses to guess from a range. Keep the two in step.

## Updating

See the [Updating section of the root README](../README.md#updating) for what
happens on each platform and how to enable in-place macOS updates.
