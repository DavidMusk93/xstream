import type { FileVaultItem, FileVaultUnlockResponse } from '~/types/api'
import { deriveVaultKey } from '~/utils/fileVaultCrypto'

/** In-memory unlock: vault path -> AES key (cleared on refresh). */
const unlockedKeys = new Map<string, CryptoKey>()

export function useFileVault() {
  const config = useRuntimeConfig()
  const vaultPaths = useState<FileVaultItem[]>('fileVaultPaths', () => [])

  async function refreshIndex(): Promise<void> {
    const res = await $fetch<{ items: FileVaultItem[] }>('/api/files/vault', {
      baseURL: config.public.apiBase,
    })
    vaultPaths.value = res.items
  }

  function vaultRowForPath(path: string): FileVaultItem | undefined {
    return vaultPaths.value.find(v => v.path === path)
  }

  /** Closest vault ancestor (encrypted folder) or exact file row. */
  function vaultContextForPath(path: string): FileVaultItem | undefined {
    const parts = path.split('/').filter(Boolean)
    for (let i = parts.length; i >= 0; i--) {
      const p = parts.slice(0, i).join('/')
      const row = vaultRowForPath(p)
      if (row) return row
    }
    return undefined
  }

  function isEncryptedPath(path: string): boolean {
    const ctx = vaultContextForPath(path)
    if (!ctx) return false
    if (ctx.path === path) return true
    return ctx.kind === 'dir'
  }

  function isLockedPath(path: string): boolean {
    if (!isEncryptedPath(path)) return false
    const ctx = vaultContextForPath(path)!
    return !unlockedKeys.has(ctx.path)
  }

  function rememberUnlock(path: string, key: CryptoKey) {
    unlockedKeys.set(path, key)
  }

  function forgetUnlock(path: string) {
    unlockedKeys.delete(path)
  }

  function keyForPath(path: string): CryptoKey | undefined {
    const ctx = vaultContextForPath(path)
    if (!ctx) return undefined
    return unlockedKeys.get(ctx.path)
  }

  async function createVault(path: string, kind: 'file' | 'dir', password: string): Promise<FileVaultItem> {
    const res = await $fetch<FileVaultItem & { kdf_salt: string }>('/api/files/vault', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { path, kind, password },
    })
    const key = await deriveVaultKey(password, res.kdf_salt)
    rememberUnlock(res.path, key)
    await refreshIndex()
    return res
  }

  async function unlock(path: string, password: string): Promise<CryptoKey> {
    const res = await $fetch<FileVaultUnlockResponse>('/api/files/vault/unlock', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { path, password },
    })
    const key = await deriveVaultKey(password, res.kdf_salt)
    rememberUnlock(res.path, key)
    return key
  }

  async function changePassword(path: string, oldPassword: string, newPassword: string): Promise<void> {
    const res = await $fetch<{ ok: boolean; path: string; kdf_salt: string }>('/api/files/vault/password', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { path, old_password: oldPassword, new_password: newPassword },
    })
    const key = await deriveVaultKey(newPassword, res.kdf_salt)
    rememberUnlock(res.path, key)
    await refreshIndex()
  }

  async function removeVault(path: string, recursive = false): Promise<void> {
    await $fetch('/api/files/vault', {
      baseURL: config.public.apiBase,
      method: 'DELETE',
      query: { path, recursive },
    })
    forgetUnlock(path)
    await refreshIndex()
  }

  async function moveVault(from: string, to: string): Promise<void> {
    await $fetch('/api/files/vault/move', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { from_path: from, to_path: to },
    })
    const key = unlockedKeys.get(from)
    if (key) {
      unlockedKeys.delete(from)
      unlockedKeys.set(to, key)
    }
    await refreshIndex()
  }

  return {
    vaultPaths,
    refreshIndex,
    vaultRowForPath,
    vaultContextForPath,
    isEncryptedPath,
    isLockedPath,
    keyForPath,
    rememberUnlock,
    forgetUnlock,
    createVault,
    unlock,
    changePassword,
    removeVault,
    moveVault,
  }
}
