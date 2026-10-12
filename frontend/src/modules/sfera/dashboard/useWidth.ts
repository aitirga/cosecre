import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** The element's content width, kept current, so charts draw at real pixels instead of scaling text. */
export function useWidth(el: Ref<HTMLElement | null>, fallback = 600) {
  const width = ref(fallback)
  let observer: ResizeObserver | undefined
  onMounted(() => {
    if (!el.value) return
    width.value = el.value.clientWidth || fallback
    observer = new ResizeObserver(([entry]) => { width.value = Math.max(200, Math.round(entry.contentRect.width)) })
    observer.observe(el.value)
  })
  onBeforeUnmount(() => observer?.disconnect())
  return width
}
