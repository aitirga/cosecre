/**
 * What the surrounding shell can do that the app itself cannot.
 *
 * The same Vue app runs in a browser tab and inside Electron. Rather than
 * scatter `if (isDesktop)` through the views, the shell provides this object
 * once and the views ask for capabilities they might not have.
 */
import { inject, type Component, type InjectionKey } from 'vue'

import type { PrintBridge } from './print/contract'

export interface PlatformIntegration {
  /** Which shell is hosting the app. Shown in Settings, and used for copy. */
  name: 'web' | 'desktop'
  /** Version of the host — the Electron app's, when there is one. */
  version?: string
  /** The hub this client is pointed at, when the shell owns that choice. */
  hubUrl?: string
  /**
   * Repoint the client at another hub. Present only where it makes sense: the
   * web app is served *by* its hub, so it has nothing to switch to.
   */
  changeHub?: (url: string) => Promise<void>
  /** Extra card rendered at the bottom of Settings, e.g. the desktop updater. */
  settingsPanel?: Component
  /**
   * Local printing — printers, LibreOffice, the spooler. Only a desktop shell
   * can reach those; the print tool tells a browser tab where to get one.
   */
  print?: PrintBridge
}

export const PLATFORM_KEY: InjectionKey<PlatformIntegration> = Symbol('cosecre.platform')

const WEB: PlatformIntegration = { name: 'web' }

export function usePlatform(): PlatformIntegration {
  return inject(PLATFORM_KEY, WEB)
}
