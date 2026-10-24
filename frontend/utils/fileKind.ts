/**
 * File-type classification for the ostore drive: one table drives the list
 * tile glyph, the preview renderer and the human type label.
 */

export type FileKind =
  | 'dir' | 'video' | 'audio' | 'image' | 'pdf'
  | 'markdown' | 'json' | 'csv' | 'text' | 'archive' | 'other'

const EXT_KIND: Record<string, FileKind> = {}
function reg(kind: FileKind, exts: string) {
  for (const e of exts.split(' ')) EXT_KIND[e] = kind
}
reg('video', 'mp4 m4v mov webm mkv avi wmv flv ts mpg mpeg 3gp')
reg('audio', 'mp3 m4a aac flac wav ogg oga opus weba')
reg('image', 'jpg jpeg jfif png gif webp bmp avif svg ico')
reg('pdf', 'pdf')
reg('markdown', 'md markdown mdown')
reg('json', 'json jsonl geojson ipynb')
reg('csv', 'csv tsv')
reg('text', 'txt log nfo srt vtt ass ssa sub cue m3u m3u8 ini conf cfg toml yaml yml xml html htm css scss js mjs cjs ts tsx jsx vue py rb rs go c h cc cpp hpp java kt swift sh bash zsh fish ps1 bat sql env diff patch rst tex lua php pl r dart')
reg('archive', 'zip rar 7z tar gz tgz bz2 xz zst lz4 iso dmg')

const NAME_KIND: Record<string, FileKind> = {
  dockerfile: 'text', makefile: 'text', readme: 'text', license: 'text',
  '.gitignore': 'text', '.env': 'text', caddyfile: 'text',
}

/** Images the ostore thumbnailer can render (the rest load full-size). */
const THUMB_EXTS = new Set(['jpg', 'jpeg', 'jfif', 'png', 'gif', 'webp', 'bmp'])

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toLowerCase() : ''
}

export function fileKind(name: string, type: 'file' | 'dir' = 'file'): FileKind {
  if (type === 'dir') return 'dir'
  return EXT_KIND[fileExt(name)] ?? NAME_KIND[name.toLowerCase()] ?? 'other'
}

export function hasThumb(name: string): boolean {
  return THUMB_EXTS.has(fileExt(name))
}

/** Kinds rendered from fetched text. */
export function isTextKind(kind: FileKind): boolean {
  return kind === 'markdown' || kind === 'json' || kind === 'csv' || kind === 'text'
}

const LABELS: Record<FileKind, string> = {
  dir: 'Folder', video: 'Video', audio: 'Audio', image: 'Image', pdf: 'PDF document',
  markdown: 'Markdown', json: 'JSON', csv: 'Spreadsheet', text: 'Text', archive: 'Archive', other: 'File',
}

export function kindLabel(name: string, kind: FileKind): string {
  const ext = fileExt(name)
  if (kind === 'other' || kind === 'archive' || kind === 'text') {
    return ext ? `${ext.toUpperCase()} ${kind === 'archive' ? 'archive' : 'file'}` : LABELS[kind]
  }
  return LABELS[kind]
}

export function humanSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}
