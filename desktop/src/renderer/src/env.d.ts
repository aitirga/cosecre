/// <reference types="vite/client" />

import type { CosecreDesktopApi } from '../../shared/types'

declare global {
  interface Window {
    cosecreDesktop: CosecreDesktopApi
  }
}

export {}
