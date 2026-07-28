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
  exercises: {
    title: 'Exercicis',
    lead: 'Els exercicis que has escrit. Redacta els blocs, refina’ls amb la IA i publica’ls perquè la resta del claustre els pugui fer servir.',
    create: 'Nou exercici',
    createTitle: 'Com es diu?',
    createPlaceholder: 'Àrea sota una paràbola',
    empty: 'Encara no has escrit cap exercici.',
    draft: 'Esborrany',
    published: 'Publicat',
    needsRefine: 'Sense refinar',
    open: 'Obre',
    remove: 'Esborra',
    removeTitle: 'Esborrar l’exercici?',
    removeBody: (title: string) => `S’esborrarà «${title}». Aquesta acció no es pot desfer.`,
    by: (who: string) => `de ${who}`,
  },
  library: {
    title: 'Biblioteca',
    lead: 'Exercicis que el professorat d’aquest institut ha publicat. Copia’n un i queda-te’l com a esborrany teu.',
    empty: 'Encara no hi ha res publicat.',
    clone: 'Copia’l',
    cloned: 'Copiat als teus exercicis.',
    allTopics: 'Tots els temes',
    search: 'Cerca per títol…',
  },
  wizard: {
    back: 'Enrere',
    next: 'Següent',
    steps: {
      title: 'Títol',
      statement: 'Plantejament',
      difficulty: 'Dificultat',
      issues: 'Entrebancs',
      plots: 'Gràfics',
      review: 'Revisió',
    },
    help: {
      title: 'Com vols que es digui aquest exercici.',
      statement: 'Escriu el problema tal com el diries a classe. La IA el deixarà ben format; no cal que quedi bonic.',
      difficulty:
        'Quins passos ha de fer l’alumne, del més senzill al més exigent, i què fas quan un pas ja el domina.',
      issues: 'On sols encallar-se l’alumnat amb aquest problema, i què els desencalla.',
      plots: 'Quines figures ajudarien. Descriu-les amb paraules; la IA en farà l’especificació.',
      review: 'Això és el que veurà el tutor de cada alumne.',
    },
    placeholders: {
      statement: 'Calcula l’àrea entre la corba y = x² i l’eix d’abscisses per a x entre 0 i 2…',
      difficulty: '1. Dibuixar la corba.\n2. Plantejar la integral.\n3. Resoldre-la.',
      issues: 'Confonen àrea amb pendent i comencen derivant…',
      plots: 'La paràbola amb l’àrea ombrejada entre 0 i 2.',
    },
    refine: 'Refina amb la IA',
    refineAgain: 'Torna a refinar',
    refining: 'Refinant…',
    focus: 'Alguna cosa a canviar?',
    focusPlaceholder: 'Fes-lo més curt, afegeix un graó més fàcil…',
    generatePlots: 'Genera els gràfics',
    generatingPlots: 'Generant…',
    regeneratePlot: 'Regenera aquest gràfic',
    publish: 'Publica a la biblioteca',
    published: 'Publicat a la biblioteca.',
    saved: 'Desat',
    saving: 'Desant…',
    ladder: 'Escala de dificultat',
    issuesHeading: 'Entrebancs previstos',
    signal: 'Senyal',
    hint: 'Pista',
    escalation: 'Si ja ho domina',
    notRefinedYet: 'Refina l’exercici per veure com quedarà.',
    topics: 'Temes',
    level: 'Nivell',
    levelPlaceholder: '2n de batxillerat',
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
