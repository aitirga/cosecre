/** Esfer@ screens that share the hidden portal session: moving between them keeps it. */
export const PORTAL_ROUTES: readonly string[] = ['sfera', 'sfera-data', 'sfera-invoice-poc', 'sfera-plans']
export const keepsPortal = (name: unknown) => PORTAL_ROUTES.includes(String(name))
