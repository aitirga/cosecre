import { ref } from 'vue'

/** A register entry open in a floating card, where it was put. */
export type DocumentCardState = { reference: string; x: number; y: number }

const CARD_W = 320

/**
 * Register entries opened beside the bank lines they paid. Each view keeps its
 * own set; the same entry opened twice closes instead.
 */
export function useDocumentCards() {
  const cards = ref<DocumentCardState[]>([])

  function isOpen(reference: string) {
    return cards.value.some((c) => c.reference === reference)
  }

  function toggle(reference: string, event: MouseEvent) {
    if (isOpen(reference)) {
      cards.value = cards.value.filter((c) => c.reference !== reference)
      return
    }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
    const right = window.innerWidth - 8
    const x = rect.right + 8 + CARD_W <= right ? rect.right + 8 : Math.max(8, rect.left - CARD_W - 8)
    const y = Math.min(Math.max(8, rect.top - 4), window.innerHeight - 360)
    cards.value.push({ reference, x, y })
  }

  function close(card: DocumentCardState) {
    cards.value = cards.value.filter((c) => c !== card)
  }

  return { cards, isOpen, toggle, close }
}
