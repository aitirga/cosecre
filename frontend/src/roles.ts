import type { Role } from './api/types'

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Secretari/a',
  administratiu: 'Administratiu/va',
  professor: 'Professor/a',
}

/** In the order a picker offers them: most common first. */
export const ROLES: Role[] = ['professor', 'administratiu', 'admin']

export const ROLE_HINTS: Record<Role, string> = {
  admin: 'Tot, inclosos els comptes i la configuració.',
  administratiu: 'Registre, extractes i sol·licituds. No gestiona comptes.',
  professor: 'Envia sol·licituds i valida les factures que puja.',
}
