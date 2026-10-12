import type { CosecreModule } from '../types'
import SettingsPanel from './SettingsPanel.vue'

export const sferaModule: CosecreModule = {
  id: 'sfera',
  platforms: ['desktop'],
  appSlug: 'cosecre-sfera',
  roles: ['admin', 'administratiu'],
  routes: [
    { path: 'eines/sfera', name: 'sfera', component: () => import('./SferaView.vue') },
    { path: 'eines/sfera/dades', name: 'sfera-data', component: () => import('./DashboardView.vue') },
    { path: 'eines/sfera/prova-extractes', name: 'sfera-invoice-poc', component: () => import('./InvoicePocView.vue') },
    { path: 'eines/sfera/plans', name: 'sfera-plans', component: () => import('./ExportPlansView.vue') },
  ],
  navGroups: [{ id: 'eines', label: 'Eines' }, { id: 'sfera', label: 'Esfer@', icon: 'link', parent: 'eines' }],
  nav: [
    { name: 'sfera', label: 'Navegador', icon: 'monitor', group: 'sfera' },
    { name: 'sfera-data', label: 'Tauler econòmic', icon: 'chart', group: 'sfera' },
    { name: 'sfera-invoice-poc', label: 'Prova d’extractes', icon: 'file', group: 'sfera' },
    { name: 'sfera-plans', label: 'Plans d’exportació', icon: 'check', group: 'sfera' },
    { name: 'sfera-settings', to: { name: 'settings', query: { tab: 'sfera' } }, label: 'Configuració', icon: 'sliders', group: 'sfera', adminOnly: true },
  ],
  settingsSections: [{ id: 'sfera', label: 'Esfer@', icon: 'link', component: SettingsPanel }],
}
