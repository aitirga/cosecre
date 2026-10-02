import { Menu, app, shell, type MenuItemConstructorOptions } from 'electron'

const REPO_URL = 'https://github.com/aitirga/cosecre'

export interface MenuActions {
  onCheckForUpdates(): void
  onReload(): void
}

/**
 * The application menu.
 *
 * Not decoration: on macOS the Edit menu is what wires up ⌘C/⌘V/⌘A. Without a
 * menu those shortcuts silently do nothing, which in an app built around typing
 * into forms is a real bug rather than a missing nicety.
 */
export function buildMenu(actions: MenuActions): void {
  const isMac = process.platform === 'darwin'

  const template: MenuItemConstructorOptions[] = [
    ...(isMac
      ? ([
          {
            label: app.getName(),
            submenu: [
              { role: 'about' },
              { label: 'Busca actualitzacions…', click: actions.onCheckForUpdates },
              { type: 'separator' },
              { role: 'services' },
              { type: 'separator' },
              { role: 'hide' },
              { role: 'hideOthers' },
              { role: 'unhide' },
              { type: 'separator' },
              { role: 'quit' },
            ],
          },
        ] as MenuItemConstructorOptions[])
      : []),
    {
      label: 'Fitxer',
      submenu: [
        { label: 'Recarrega', accelerator: 'CmdOrCtrl+R', click: actions.onReload },
        ...(isMac
          ? ([{ role: 'close' }] as MenuItemConstructorOptions[])
          : ([
              { label: 'Busca actualitzacions…', click: actions.onCheckForUpdates },
              { type: 'separator' },
              { role: 'quit' },
            ] as MenuItemConstructorOptions[])),
      ],
    },
    {
      label: 'Edita',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'Visualització',
      submenu: [
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { role: 'toggleDevTools' },
      ],
    },
    {
      label: 'Finestra',
      submenu: isMac
        ? [{ role: 'minimize' }, { role: 'zoom' }, { type: 'separator' }, { role: 'front' }]
        : [{ role: 'minimize' }, { role: 'close' }],
    },
    {
      role: 'help',
      submenu: [
        {
          label: 'Cosecre a GitHub',
          click: () => void shell.openExternal(REPO_URL),
        },
      ],
    },
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}
