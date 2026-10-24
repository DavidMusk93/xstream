import type { FilesConfigResponse, OstoreEntry, OstoreListResponse } from '~/types/api'

/**
 * useOstore — client for the ostore network-drive service.
 *
 * The service lives at the same origin under `base_url` (e.g. "/ostore") and
 * authenticates with `Authorization: Bearer <token>` — or a `?token=` query
 * for <video> and EventSource, which cannot set headers. Config comes from
 * the xstream backend's /api/files/config (503 when unconfigured); the fetch
 * promise is cached for the session but reset on failure so a retry works.
 *
 * Live updates do not come from ostore directly: the backend bridges its
 * event stream onto /api/events as `files.changed` / `files.resync`.
 */

export class OstoreError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'OstoreError'
    this.status = status
    this.code = code
  }
}

let configPromise: Promise<FilesConfigResponse> | null = null

function encodePath(path: string): string {
  return path.split('/').filter(Boolean).map(encodeURIComponent).join('/')
}

async function parseError(res: Response): Promise<OstoreError> {
  let code = ''
  let message = res.statusText || `HTTP ${res.status}`
  try {
    const body = await res.json() as { error?: string; code?: string }
    if (body?.error) message = body.error
    if (body?.code) code = body.code
  } catch {
    // non-JSON error body — keep the status text
  }
  return new OstoreError(res.status, code, message)
}

export function useOstore() {
  async function init(): Promise<FilesConfigResponse> {
    if (!configPromise) {
      configPromise = useApi().filesConfig().catch((e) => {
        // Don't cache failures — a later refresh must be able to retry.
        configPromise = null
        throw e
      })
    }
    return configPromise
  }

  async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
    const { token } = await init()
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    let payload: BodyInit | undefined
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
    const res = await fetch(url, { method, headers, body: payload })
    if (!res.ok) throw await parseError(res)
    return await res.json() as T
  }

  async function list(path: string): Promise<OstoreListResponse> {
    const { base_url } = await init()
    const res = await request<{ path: string; entries: (Omit<OstoreEntry, 'mtime'> & { mtime: string | number })[] }>(
      'GET', `${base_url}/api/list?path=${encodeURIComponent(path)}`,
    )
    // ostore sends RFC 3339 timestamps; the UI works in epoch seconds.
    return {
      path: res.path,
      entries: res.entries.map(e => ({
        ...e,
        mtime: typeof e.mtime === 'number' ? e.mtime : Date.parse(e.mtime) / 1000,
      })),
    }
  }

  function upload(dir: string, files: File[], onProgress: (loaded: number, total: number) => void): Promise<{ uploaded: { path: string; size: number }[] }> {
    // XHR instead of fetch: fetch cannot report upload progress.
    return init().then(({ base_url, token }) => new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${base_url}/api/upload?path=${encodeURIComponent(dir)}`)
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded, e.total)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new OstoreError(xhr.status, 'bad_response', 'Invalid upload response'))
          }
        } else {
          let code = ''
          let message = xhr.statusText || `HTTP ${xhr.status}`
          try {
            const body = JSON.parse(xhr.responseText) as { error?: string; code?: string }
            if (body?.error) message = body.error
            if (body?.code) code = body.code
          } catch {
            // non-JSON error body
          }
          reject(new OstoreError(xhr.status, code, message))
        }
      }
      xhr.onerror = () => reject(new OstoreError(0, 'network', 'Network error during upload'))
      xhr.onabort = () => reject(new OstoreError(0, 'aborted', 'Upload aborted'))
      const form = new FormData()
      for (const file of files) form.append('files', file)
      xhr.send(form)
    }))
  }

  async function mkdir(path: string): Promise<void> {
    const { base_url } = await init()
    await request<unknown>('POST', `${base_url}/api/mkdir`, { path })
  }

  async function move(from: string, to: string): Promise<void> {
    const { base_url } = await init()
    await request<unknown>('POST', `${base_url}/api/move`, { from, to })
  }

  async function remove(path: string, recursive: boolean): Promise<void> {
    const { base_url } = await init()
    const suffix = recursive ? '?recursive=1' : ''
    await request<unknown>('DELETE', `${base_url}/api/files/${encodePath(path)}${suffix}`)
  }

  // Media tags cannot set Authorization — the token rides as a query param.
  async function fileUrl(path: string): Promise<string> {
    const { base_url, token } = await init()
    return `${base_url}/api/files/${encodePath(path)}?token=${encodeURIComponent(token)}`
  }

  return { init, list, upload, mkdir, move, remove, fileUrl }
}
