export interface StreamCheckResponse {
  hash: string
  cached: boolean
  head_ready: boolean
  path: string
  size: number
  mime: string
}

export interface TorrentStatus {
  hash: string
  name?: string
  work_code?: string
  ready: boolean
  cached: boolean
  head_ready: boolean
  peers: number
  progress: number
  download_rate: number
  upload_rate: number
  video_file?: string
  video_size: number
  local_size: number
  mime: string
  state: string
  verified_pieces: number
  quality: string
  piece_segments: [number, number, number][]
  /** Hash-check progress 0-100 while state is checking_*; 0 otherwise. */
  check_progress?: number
}

export interface CacheMetrics {
  total: number
  completed: number
  downloading: number
  used_bytes: number
  used_human: string
  max_bytes: number
  max_human: string
}

export interface Title {
  code: string
  title?: string
  date?: string
  resolution?: string
  cover_url?: string
  cover_thumb_url?: string
  cover_mid_url?: string
  cover_w?: number
  cover_h?: number
  magnet?: string
  magnet_status?: string
  number?: number
  user_liked?: boolean
}

export interface XPost {
  id: string
  text: string
  url: string
  /** UTC ISO-8601, e.g. 2026-10-16T05:00:00Z */
  posted_at: string | null
  /** pbs.twimg.com "small" variants, at most 4 */
  media: string[]
  stats: { replies?: number; reposts?: number; likes?: number; views?: number }
  pinned: boolean
  /** Status author; differs from the profile handle on reposts */
  author: string
}

/** Injected X binding. handle null + checked_at = checked, no account. */
export interface XProfile {
  handle: string | null
  name: string
  avatar: string
  checked_at: string | null
  posts: XPost[]
}

export interface XInjectResult {
  star: string | null
  name?: string
  ok: boolean
  handle?: string | null
  posts?: number
  received?: number
  error?: string
}

export interface Star {
  name: string
  jp?: string
  handle?: string
  code: string
  type?: string
  note?: string
  number?: number
  titles: Title[]
  x?: XProfile | null
}

export interface SearchResultStar {
  name: string
  url: string
  followed: boolean
}

export interface SearchResultActress extends SearchResultStar {
  image?: string
}

export interface SearchResultMagnet {
  magnet: string
  resolution?: string
  size?: string
  seeds?: number
  is_hd?: boolean
}

export interface SearchResultItem {
  code: string
  title?: string
  release_date?: string
  views?: number
  likes?: number
  cover_url?: string
  resolution?: string
  size?: string
  seeds?: number
  in_library: boolean
  source?: 'ijav' | 'sukebei'
  stars: SearchResultStar[]
  magnets?: SearchResultMagnet[]
}

export interface SearchResponse {
  query: string
  count: number
  items: SearchResultItem[]
  actresses?: SearchResultActress[]
}
