/**
 * Search, filters and sorting for a table whose rows are all on the client.
 *
 * Every list in the app is loaded whole — a school's register is hundreds of
 * rows, not millions — so narrowing and ordering it here is instant and needs
 * nothing from the hub. The state lives in the URL query, so a reload, the back
 * button or a pasted link all bring back the same view.
 */
import { computed, reactive, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter, type LocationQuery } from 'vue-router'

export type SortValue = string | number | boolean | null | undefined
export type SortDirection = 'asc' | 'desc'

export interface TableQueryOptions<T, F extends string> {
  rows: Ref<readonly T[]>
  /** How each sortable column reads a row. Keys are what `SortTh` names. */
  sorts?: Record<string, (row: T) => SortValue>
  /** Starting order, as `key` or `-key` for descending. */
  defaultSort?: string
  /** The text a row is searched by. Matched without case or accents. */
  search?: (row: T) => SortValue[]
  /**
   * Named filters. Each is a string — `''` meaning "any" — and a predicate the
   * row must pass when it is set.
   */
  filters?: Record<F, (row: T, value: string) => boolean>
  /**
   * Prefix for the URL query keys, so two tables on one page do not share a
   * search. `false` keeps the state out of the URL.
   */
  urlPrefix?: string | false
}

/** Lower case, no accents, single spaces: "Pérez  S.L." finds "perez s.l.". */
export function fold(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

const collator = new Intl.Collator('ca', { sensitivity: 'base', numeric: true })

function isBlank(value: SortValue) {
  return value === null || value === undefined || value === ''
}

/** Blank values go last whichever way the column is sorted: they are noise. */
function compare(a: SortValue, b: SortValue, direction: SortDirection): number {
  if (isBlank(a) || isBlank(b)) return isBlank(a) === isBlank(b) ? 0 : isBlank(a) ? 1 : -1
  const sign = direction === 'asc' ? 1 : -1
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * sign
  if (typeof a === 'boolean' && typeof b === 'boolean') return (Number(a) - Number(b)) * sign
  return collator.compare(String(a), String(b)) * sign
}

function parseSort(raw: string | undefined | null): { key: string; direction: SortDirection } | null {
  if (!raw) return null
  return raw.startsWith('-')
    ? { key: raw.slice(1), direction: 'desc' }
    : { key: raw, direction: 'asc' }
}

function firstString(value: LocationQuery[string] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? ''
}

export function useTableQuery<T, F extends string = never>(options: TableQueryOptions<T, F>) {
  const route = useRoute()
  const router = useRouter()
  const prefix = options.urlPrefix === false ? null : (options.urlPrefix ?? '')
  const filterNames = Object.keys(options.filters ?? {}) as F[]

  const keys = {
    search: `${prefix}q`,
    sort: `${prefix}sort`,
    filter: (name: string) => `${prefix}${name}`,
  }

  const query = prefix === null ? null : route.query

  const search = ref(query ? firstString(query[keys.search]) : '')
  const filters = reactive(
    Object.fromEntries(
      filterNames.map((name) => [name, query ? firstString(query[keys.filter(name)]) : '']),
    ),
  ) as Record<F, string>
  const sort = ref(
    parseSort(query ? firstString(query[keys.sort]) || options.defaultSort : options.defaultSort),
  )

  function toggleSort(key: string) {
    const current = sort.value
    // Ascending, then descending, then back to the table's own order.
    if (!current || current.key !== key) sort.value = { key, direction: 'asc' }
    else if (current.direction === 'asc') sort.value = { key, direction: 'desc' }
    else sort.value = parseSort(options.defaultSort)
  }

  function sortDirection(key: string): SortDirection | null {
    return sort.value?.key === key ? sort.value.direction : null
  }

  const isFiltered = computed(
    () => search.value.trim() !== '' || filterNames.some((name) => filters[name] !== ''),
  )

  function reset() {
    search.value = ''
    for (const name of filterNames) filters[name] = ''
  }

  const visible = computed<T[]>(() => {
    const term = fold(search.value)
    const words = term ? term.split(' ') : []
    let rows = options.rows.value.filter((row) => {
      for (const name of filterNames) {
        const value = filters[name]
        if (value !== '' && !options.filters![name](row, value)) return false
      }
      if (!words.length || !options.search) return true
      const haystack = fold(
        options
          .search(row)
          .filter((value) => !isBlank(value))
          .join(' '),
      )
      // Every word somewhere: "llibres 2026" finds the 2026 book invoices.
      return words.every((word) => haystack.includes(word))
    })

    const order = sort.value
    const read = order ? options.sorts?.[order.key] : undefined
    if (order && read) {
      // `sort` is stable, so equal rows keep the order the hub sent them in.
      rows = rows
        .map((row, index) => ({ row, index, value: read(row) }))
        .sort((a, b) => compare(a.value, b.value, order.direction) || a.index - b.index)
        .map((entry) => entry.row)
    }
    return rows
  })

  if (prefix !== null) {
    watch(
      [search, () => ({ ...filters }), sort],
      () => {
        const next: LocationQuery = { ...route.query }
        const set = (key: string, value: string) => {
          if (value) next[key] = value
          else delete next[key]
        }
        set(keys.search, search.value.trim())
        for (const name of filterNames) set(keys.filter(name), filters[name])
        const sortRaw = sort.value
          ? `${sort.value.direction === 'desc' ? '-' : ''}${sort.value.key}`
          : ''
        set(keys.sort, sortRaw === (options.defaultSort ?? '') ? '' : sortRaw)
        void router.replace({ query: next })
      },
      { deep: true },
    )
  }

  return { search, filters, sort, toggleSort, sortDirection, isFiltered, reset, visible }
}

export type TableQuery = Pick<ReturnType<typeof useTableQuery>, 'toggleSort' | 'sortDirection'>
