/**
 * pdf.js, for the print preview.
 *
 * Imported only by the preview, which only the desktop shell ever renders, so
 * a browser tab never downloads it.
 */
// The legacy build, not the modern one: pdf.js 6 calls `Map#getOrInsertComputed`,
// which the desktop app's Chromium does not have yet. Legacy carries the
// polyfills, in the worker too.
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs'
// `?url` keeps the worker a separate asset that Vite fingerprints; importing it
// directly would inline a second copy of the library.
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export type PdfDocument = pdfjs.PDFDocumentProxy
export type RenderTask = ReturnType<pdfjs.PDFPageProxy['render']>

export interface LoadedPdf {
  doc: PdfDocument
  /** Tears down the document *and* its worker. */
  destroy(): Promise<void>
}

export async function loadPdf(data: Uint8Array): Promise<LoadedPdf> {
  // pdf.js takes ownership of the buffer it is given, so hand it a copy.
  const task = pdfjs.getDocument({ data: new Uint8Array(data) })
  const doc = await task.promise
  // `destroy` lives on the loading task, not the document proxy; calling it is
  // what actually releases the worker.
  return { doc, destroy: () => task.destroy() }
}

/** True for the error pdf.js throws when a render is cancelled. */
export function isCancellation(error: unknown): boolean {
  return error instanceof Error && error.name === 'RenderingCancelledException'
}

/**
 * Draw one page into a canvas at device resolution.
 *
 * `onTask` hands the caller the in-flight render so it can cancel it: pdf.js
 * refuses to render the same page into the same canvas twice at once, and
 * without cancelling, a second draw blanks the page while the first paints.
 */
export async function renderPage(
  doc: PdfDocument,
  pageNumber: number,
  canvas: HTMLCanvasElement,
  width: number,
  onTask?: (task: RenderTask) => void,
): Promise<void> {
  const page = await doc.getPage(pageNumber)
  const base = page.getViewport({ scale: 1 })
  const viewport = page.getViewport({ scale: width / base.width })

  const ratio = window.devicePixelRatio || 1
  canvas.width = Math.floor(viewport.width * ratio)
  canvas.height = Math.floor(viewport.height * ratio)
  canvas.style.width = `${Math.floor(viewport.width)}px`
  canvas.style.height = `${Math.floor(viewport.height)}px`

  const context = canvas.getContext('2d')
  if (!context) throw new Error('No s’ha pogut dibuixar la pàgina.')

  const task = page.render({
    canvas,
    canvasContext: context,
    viewport,
    transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
  })
  onTask?.(task)
  await task.promise
}
