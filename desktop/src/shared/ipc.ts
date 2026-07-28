/** Channel names, shared by the main process and the preload bridge. */
export const IPC = {
  bootstrap: 'cosecre:bootstrap',
  setHubUrl: 'cosecre:set-hub-url',
  setToken: 'cosecre:set-token',
  removeToken: 'cosecre:remove-token',
  openExternal: 'cosecre:open-external',
  getUpdateState: 'cosecre:update:get',
  checkForUpdates: 'cosecre:update:check',
  applyUpdate: 'cosecre:update:apply',
  updateStateChanged: 'cosecre:update:changed',
} as const
