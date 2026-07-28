/**
 * AIM's copy, in Catalan.
 *
 * A frozen object of typed constants rather than an i18n library, following
 * `document-config.ts`: there is no runtime lookup, no `$t`, and `vue-tsc`
 * catches a typo'd key at build time — which is exactly what a message
 * catalogue gives up. Values that interpolate are typed functions, not
 * `{placeholder}` strings a linter cannot check.
 *
 * The seam with the English shell is deliberate. AIM's own screens are Catalan
 * because its users are Catalan-speaking teachers and students; Settings,
 * Account and Sign out stay English because they belong to the hub. Half
 * translating one surface reads worse than a clean boundary — and the hub
 * already speaks Catalan in its domain (`Factures`, `Tiquets`, `proveidor`),
 * so this is house style rather than a new precedent.
 */
export const CA = {
  nav: {
    exercises: 'Exercicis',
    library: 'Biblioteca',
    sessions: 'Sessions',
    roster: 'Alumnat',
    tutor: 'Tutor',
  },
  roster: {
    title: 'Alumnat i professorat',
    lead: "Qui té accés a AIM, i amb quin paper. L'administració del hub compta com a professorat mentre no se li doni un paper propi.",
    teachers: 'Professorat',
    students: 'Alumnat',
    addSomeone: 'Afegeix algú',
    noCandidates: 'Tothom del hub ja té un paper a AIM.',
    empty: 'Encara no hi ha ningú a AIM.',
    implicit: 'per administració',
    roleTeacher: 'Professor/a',
    roleStudent: 'Alumne/a',
    makeTeacher: 'Fes-lo professor/a',
    makeStudent: 'Fes-lo alumne/a',
    remove: "Treu d'AIM",
    removeTitle: "Treure d'AIM?",
    removeBody: (who: string) => `${who} deixarà de veure AIM. El seu historial es conserva.`,
    cancel: 'Cancel·la',
  },
  student: {
    waitingTag: 'A punt',
    waitingTitle: "Espera que comenci l'exercici",
    waitingLead:
      'Quan el teu professor o professora obri la sessió, el plantejament apareixerà aquí i podràs començar a treballar amb el tutor.',
    account: 'El meu compte',
  },
  common: {
    retry: 'Torna-ho a provar',
    loading: 'Carregant…',
    save: 'Desa',
  },
  errors: {
    generic: 'Alguna cosa no ha anat bé.',
  },
} as const
