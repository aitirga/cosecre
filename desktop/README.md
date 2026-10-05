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
| Printing | not available | *Eines → Impressió*, via `PlatformIntegration.print` |

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
│   ├── menu.ts     # the application menu (⌘C/⌘V live here on macOS)
│   └── print/      # the print tool's engine — see below
├── preload/    # contextBridge API (`window.cosecreDesktop`)
└── renderer/   # entry point + the desktop-only Updates panel and CSS
```

### The print tool

*Eines → Impressió* used to be a separate app, Cosecre-print. Its engine now
runs here, in `src/main/print/`, and its UI is a module of the web app
(`frontend/src/modules/print.ts`), handed the engine as
`PlatformIntegration.print`. The contract between the two is
`frontend/src/print/contract.ts`, which the main process imports as
`@print/contract`.

- **Everything becomes a PDF first.** Word files go through LibreOffice
  (`soffice --convert-to pdf`, one profile directory per concurrent process —
  instances sharing a profile silently drop conversions), so the preview is
  exactly what prints.
- **Printers work in parallel**, each with its own serial queue. macOS and
  Linux submit with `lp` and track the CUPS job id; Windows runs the
  SumatraPDF that `pdf-to-printer` ships — unpacked from the asar, see
  `asarUnpack` in `electron-builder.yml` — and matches jobs by name.
- **Settings and history** are JSON under `<userData>/print/`; a diagnostic
  log is written to `<userData>/print/logs/print.log` (there is no viewer in
  the app).
- **The preview uses pdf.js's legacy build.** pdf.js 6 relies on
  `Map#getOrInsertComputed`, which this Electron's Chromium does not have yet.

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
