/**
 * The small part of Markdown the Assistent writes, rendered to HTML.
 *
 * Safe for `v-html` by construction: every piece of text is escaped before any
 * markup is added, and links are only ever `http(s)` or in-app paths. Not a
 * general parser — paragraphs, headings, lists, quotes, code and pipe tables,
 * with bold, italics, inline code and links inside them, which is what the
 * model is told to use.
 */

function escape(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inline(text: string): string {
  const codes: string[] = []
  // Code first, so nothing inside it is read as markup.
  let html = escape(text).replace(/`([^`]+)`/g, (_, code: string) => {
    codes.push(`<code>${code}</code>`)
    return `\u0000${codes.length - 1}\u0000`
  })
  html = html
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g, (_, label: string, href: string) => {
      const external = href.startsWith('http')
      return `<a href="${href}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${label}</a>`
    })
  return html.replace(/\u0000(\d+)\u0000/g, (_, index: string) => codes[Number(index)] ?? '')
}

function isTableRow(line: string) {
  return /^\s*\|.*\|\s*$/.test(line)
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function table(lines: string[]): string {
  const [head, , ...body] = lines
  const align = cells(lines[1] ?? '').map((spec) =>
    spec.endsWith(':') ? (spec.startsWith(':') ? 'center' : 'right') : '',
  )
  const cell = (tag: 'th' | 'td', value: string, index: number) =>
    `<${tag}${align[index] ? ` style="text-align:${align[index]}"` : ''}>${inline(value)}</${tag}>`
  return (
    '<div class="md-table"><table><thead><tr>' +
    cells(head ?? '').map((value, index) => cell('th', value, index)).join('') +
    '</tr></thead><tbody>' +
    body.map((row) => `<tr>${cells(row).map((value, index) => cell('td', value, index)).join('')}</tr>`).join('') +
    '</tbody></table></div>'
  )
}

export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const out: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''

    if (/^\s*```/.test(line)) {
      const code: string[] = []
      index += 1
      while (index < lines.length && !/^\s*```/.test(lines[index] ?? '')) code.push(lines[index++] ?? '')
      index += 1
      out.push(`<pre><code>${escape(code.join('\n'))}</code></pre>`)
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = Math.min(6, (heading[1]?.length ?? 1) + 2)
      out.push(`<h${level}>${inline(heading[2] ?? '')}</h${level}>`)
      index += 1
      continue
    }

    if (isTableRow(line) && /^\s*\|?\s*:?-{2,}/.test(lines[index + 1] ?? '')) {
      const rows: string[] = []
      while (index < lines.length && isTableRow(lines[index] ?? '')) rows.push(lines[index++] ?? '')
      out.push(table(rows))
      continue
    }

    const listItem = /^\s*([-*]|\d+[.)])\s+(.*)$/
    if (listItem.test(line)) {
      const ordered = /^\s*\d/.test(line)
      const items: string[] = []
      while (index < lines.length && listItem.test(lines[index] ?? '')) {
        items.push(`<li>${inline(listItem.exec(lines[index] ?? '')?.[2] ?? '')}</li>`)
        index += 1
      }
      out.push(ordered ? `<ol>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`)
      continue
    }

    if (/^\s*>/.test(line)) {
      const quoted: string[] = []
      while (index < lines.length && /^\s*>/.test(lines[index] ?? '')) {
        quoted.push((lines[index++] ?? '').replace(/^\s*>\s?/, ''))
      }
      out.push(`<blockquote>${inline(quoted.join(' '))}</blockquote>`)
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    const paragraph: string[] = []
    while (
      index < lines.length &&
      (lines[index] ?? '').trim() &&
      !/^\s*(```|#{1,4}\s|[-*]\s|\d+[.)]\s|>)/.test(lines[index] ?? '') &&
      !isTableRow(lines[index] ?? '')
    ) {
      paragraph.push(lines[index++] ?? '')
    }
    if (!paragraph.length) {
      // A line no rule above took (a lone `|`, say): show it as text.
      paragraph.push(lines[index++] ?? '')
    }
    out.push(`<p>${paragraph.map(inline).join('<br>')}</p>`)
  }
  return out.join('')
}
