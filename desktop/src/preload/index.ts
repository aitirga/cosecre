import { contextBridge, ipcRenderer } from 'electron'

import { IPC } from '../shared/ipc.js'
import type { Bootstrap, CosecreDesktopApi, UpdateState } from '../shared/types.js'

// Read synchronously at preload time. The renderer needs the hub URL and the
// stored session before it makes its first request, and awaiting an async
// channel there would mean rendering a signed-out app for a frame.
const bootstrap = ipcRenderer.sendSync(IPC.bootstrap) as Bootstrap

const api: CosecreDesktopApi = {
  bootstrap,

  setHubUrl: (url) => ipcRenderer.invoke(IPC.setHubUrl, url) as Promise<void>,
  // Fire-and-forget: token writes must not block a response the app already has.
  setToken: (key, value) => ipcRenderer.send(IPC.setToken, key, value),
  removeToken: (key) => ipcRenderer.send(IPC.removeToken, key),
  openExternal: (url) => ipcRenderer.invoke(IPC.openExternal, url) as Promise<void>,

  getUpdateState: () => ipcRenderer.invoke(IPC.getUpdateState) as Promise<UpdateState>,
  checkForUpdates: () => ipcRenderer.invoke(IPC.checkForUpdates) as Promise<UpdateState>,
  applyUpdate: () => ipcRenderer.invoke(IPC.applyUpdate) as Promise<void>,

  onUpdateState: (callback) => {
    const listener = (_event: unknown, state: UpdateState): void => callback(state)
    ipcRenderer.on(IPC.updateStateChanged, listener)
    return () => ipcRenderer.removeListener(IPC.updateStateChanged, listener)
  },
}

contextBridge.exposeInMainWorld('cosecreDesktop', api)
