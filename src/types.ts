export interface AvatarItem {
  name: string
  short_name: string
  version: number
  created_at: string
  file_id: string
  url: string
  image_url: string | null
}

export interface TaskSnapshot {
  id: number
  name: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'timeout' | 'cancelled'
  downloaded: number
  total: number
  speed: number
  error: string
  save_path: string
}

export interface LoginResult {
  success: boolean
  requires_2fa: boolean
  fa_methods: string[]
  error: string | null
}
