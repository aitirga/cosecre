import type { Role } from './api/types'

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Administrador/a',
  secretaria: 'Secretaria',
  professor: 'Professor/a',
}

/** In the order a picker offers them: most common first. */
export const ROLES: Role[] = ['professor', 'secretaria', 'admin']

export const ROLE_HINTS: Record<Role, string> = {
  admin: 'Tot, inclosos els comptes i la configuració.',
  secretaria: 'Registre, extractes i sol·licituds. No gestiona comptes.',
  professor: 'Només envia sol·licituds i factures a secretaria.',
}
