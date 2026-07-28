import { execFile } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { app, shell } from 'electron'
// electron-updater is CommonJS and this main process is ESM — the named export
// has to come off the default import or the bundle throws at load.
import electronUpdater, { type AppUpdater, type UpdateInfo } from 'electron-updater'

import type { UpdateState } from '../shared/types.js'

/** Keep in sync with the `publish` block in electron-builder.yml. */
const REPO = 'aitirga/cosecre'
const LATEST_RELEASE_URL = `https://github.com/${REPO}/releases/latest`

/** Long enough that the first check never competes with window startup. */
const FIRST_CHECK_DELAY_MS = 8_000
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000

/**
 * Whether this build can replace itself in place.
 *
 * Windows and Linux always can. macOS only can when the bundle carries a
 * Developer ID signature: Squirrel.Mac reads the running app's designated code
 * requirement before swapping it, so an unsigned — or merely ad-hoc signed —
 * bundle fails with an opaque signature error.
 *
 * This asks `codesign` rather than hardcoding "macOS cannot", so adding a
 * certificate to the release workflow switches macOS to real in-place updates
 * with no code change here.
 */
async function detectSelfInstall(): Promise<boolean> {
  if (process.platform !== 'darwin') return true

  // …/Cosecre.app/Contents/MacOS/Cosecre → …/Cosecre.app
  const bundle = resolve(dirname(process.execPath), '..', '..')
  const stderr = await new Promise<string | null>((done) => {
    // Startup waits on this, so it gets a tight leash rather than a default
    // timeout: a local bundle takes well under a second, and anything slower is
    // a hang, not a slow answer.
    execFile(
      '/usr/bin/codesign',
      ['-dv', '--verbose=2', bundle],
      { timeout: 5_000 },
      (error, _stdout, errorOutput) => done(error ? null : errorOutput),
    )
  })

  // codesign writes its report to stderr and exits non-zero when the bundle is
  // not signed at all. An ad-hoc signature exits zero but names no authority,
  // which is why the Authority line is what gets matched.
  return stderr ? /^Authority=Developer ID Application/m.test(stderr) : false
}

export interface UpdaterEvents {
  onState(state: UpdateState): void
}

export class Updater {
  private state: UpdateState
  /**
   * Null in development. `electronUpdater.autoUpdater` is a lazy getter that
   * constructs the platform updater on first property access, so it is resolved
   * in `init` rather than at import time: a dev build never touches it, and a
   * construction failure cannot stop the app from starting.
   */
  private feed: AppUpdater | null = null
  private firstCheck: ReturnType<typeof setTimeout> | null = null
  private interval: ReturnType<typeof setInterval> | null = null

  constructor(private readonly events: UpdaterEvents) {
    this.state = {
      // An unpackaged app has no update feed to read, and electron-updater
      // throws rather than no-opping, so dev never enters the state machine.
      phase: app.isPackaged ? 'idle' : 'unsupported',
      currentVersion: app.getVersion(),
      // The pessimistic answer until init() has asked codesign. Correct as-is
      // for Windows and Linux, which can always self-install.
      canSelfInstall: process.platform !== 'darwin',
    }
  }

  async init(): Promise<void> {
    if (!app.isPackaged) return

    const canSelfInstall = await detectSelfInstall()
    this.state = { ...this.state, canSelfInstall }

    const autoUpdater = electronUpdater.autoUpdater
    this.feed = autoUpdater
    autoUpdater.autoDownload = canSelfInstall
    autoUpdater.autoInstallOnAppQuit = canSelfInstall
    // Silent by default — a failed check is not the user's problem. Set
    // COSECRE_UPDATER_DEBUG=1 to trace the feed request.
    autoUpdater.logger = process.env['COSECRE_UPDATER_DEBUG'] ? console : null

    autoUpdater.on('checking-for-update', () => this.patch({ phase: 'checking' }))

    autoUpdater.on('update-not-available', () =>
      this.patch({ phase: 'up-to-date', newVersion: undefined, percent: undefined }),
    )

    autoUpdater.on('update-available', (info: UpdateInfo) =>
      this.patch({
        // With autoDownload on, the download has already started by the time
        // this fires, so 'available' would be a state nobody could act on.
        phase: canSelfInstall ? 'downloading' : 'available',
        newVersion: info.version,
        percent: canSelfInstall ? 0 : undefined,
        releaseUrl: `https://github.com/${REPO}/releases/tag/v${info.version}`,
      }),
    )

    autoUpdater.on('download-progress', (progress: { percent: number }) =>
      this.patch({ phase: 'downloading', percent: Math.round(progress.percent) }),
    )

    autoUpdater.on('update-downloaded', (info: UpdateInfo) =>
      this.patch({ phase: 'ready', newVersion: info.version, percent: 100 }),
    )

    autoUpdater.on('error', (error: Error) =>
      this.patch({ phase: 'error', message: friendly(error.message) }),
    )

    this.firstCheck = setTimeout(() => void this.check(), FIRST_CHECK_DELAY_MS)
    this.interval = setInterval(() => void this.check(), CHECK_INTERVAL_MS)
  }

  get(): UpdateState {
    return this.state
  }

  /** Ask GitHub whether there is a newer release. Never throws. */
  async check(): Promise<UpdateState> {
    if (!this.feed) return this.state
    try {
      await this.feed.checkForUpdates()
    } catch (error) {
      this.patch({ phase: 'error', message: friendly(describe(error)) })
    }
    return this.state
  }

  /**
   * Restart into the new version. Where the bundle cannot be swapped in place,
   * open the release page so the installer can be downloaded by hand.
   */
  async apply(): Promise<void> {
    if (!this.state.canSelfInstall) {
      await shell.openExternal(this.state.releaseUrl ?? LATEST_RELEASE_URL)
      return
    }
    if (this.state.phase !== 'ready' || !this.feed) return

    // Let the IPC call return before the process goes away, or the renderer
    // sees the channel drop as an error.
    const feed = this.feed
    setImmediate(() => feed.quitAndInstall())
  }

  dispose(): void {
    if (this.firstCheck) clearTimeout(this.firstCheck)
    if (this.interval) clearInterval(this.interval)
    this.firstCheck = null
    this.interval = null
  }

  private patch(patch: Partial<UpdateState>): void {
    this.state = { ...this.state, ...patch }
    this.events.onState(this.state)
  }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * Translate the electron-updater messages a normal user might actually hit.
 *
 * Before the first release exists it reports "Unable to find latest version on
 * GitHub (…releases.atom), please ensure a production release exists" —
 * accurate for a maintainer, baffling for anyone else. And a `--dir` build has
 * no app-update.yml, because electron-builder only writes one for a real
 * installer target, so the raw ENOENT leaks an absolute path for no reason.
 */
function friendly(message: string): string {
  if (message.includes('Unable to find latest version')) {
    return 'No releases have been published yet.'
  }
  if (message.includes('app-update.yml')) {
    return 'This build was not packaged for updates.'
  }
  return message
}
