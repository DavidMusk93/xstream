/**
 * Minimal Markdown → HTML for file previews. Safety comes from order: the
 * whole source is HTML-escaped first, then only a fixed set of constructs is
 * turned into tags, and link targets are restricted to http(s)/mailto/
 * relative. Raw HTML in the source therefore always renders as text.
 */

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function safeHref(url: string): string | null {
  const u = url.trim()
  if (/^(https?:|mailto:)/i.test(u) || /^[./#\w-][^:]*$/.test(u)) return u
  return null
}

function inline(s: string): string {
  const codes: string[] = []
  // Code spans first so their content is not formatted further.
  let out = s.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(c)
    return `\u0000${codes.length - 1}\u0000`
  })
  out = out
    .replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, (m, alt, url) => {
      const href = safeHref(url)
      return href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${alt || 'image'}</a>` : m
    })
    .replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, (m, text, url) => {
      const href = safeHref(url)
      return href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>` : m
    })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`)
}

export function renderMarkdown(src: string): string {
  const lines = escapeHtml(src.replace(/\r\n?/g, '\n')).split('\n')
  const html: string[] = []
  let para: string[] = []
  let list: { tag: 'ul' | 'ol'; items: string[] } | null = null

  const flushPara = () => {
    if (para.length) html.push(`<p>${inline(para.join(' '))}</p>`)
    para = []
  }
  const flushList = () => {
    if (list) html.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`)
    list = null
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const fence = line.match(/^\s*(```|~~~)/)
    if (fence) {
      flushPara(); flushList()
      const body: string[] = []
      while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i])
      html.push(`<pre><code>${body.join('\n')}</code></pre>`)
      continue
    }
    const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/)
    if (h) {
      flushPara(); flushList()
      html.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`)
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara(); flushList()
      html.push('<hr>')
      continue
    }
    const quote = line.match(/^&gt;\s?(.*)$/)
    if (quote) {
      flushPara(); flushList()
      const body = [quote[1]]
      while (i + 1 < lines.length && /^&gt;/.test(lines[i + 1])) body.push(lines[++i].replace(/^&gt;\s?/, ''))
      html.push(`<blockquote>${inline(body.join(' '))}</blockquote>`)
      continue
    }
    const li = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/)
    if (li) {
      flushPara()
      const tag = /\d/.test(li[1]) ? 'ol' : 'ul'
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] } }
      list.items.push(li[2])
      continue
    }
    if (!line.trim()) {
      flushPara(); flushList()
      continue
    }
    if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`
      continue
    }
    flushList()
    para.push(line.trim())
  }
  flushPara(); flushList()
  return html.join('\n')
}
