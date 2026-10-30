import type { OstoreEntry } from '~/types/api'
import { decryptBytes, encryptBytes, isVaultBlob } from '~/utils/fileVaultCrypto'

export function useFileVaultOps() {
  const ostore = useOstore()
  const vault = useFileVault()

  async function uploadPlain(dir: string, name: string, data: Uint8Array, mime?: string) {
    const file = new File([data], name, { type: mime ?? 'application/octet-stream' })
    await ostore.upload(dir, [file], () => {})
  }

  async function encryptBytesAtPath(path: string, key: CryptoKey) {
    const raw = await ostore.downloadBytes(path)
    if (isVaultBlob(raw)) return
    const enc = await encryptBytes(raw, key)
    const name = path.slice(path.lastIndexOf('/') + 1)
    const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
    await uploadPlain(dir, name, enc)
  }

  async function decryptBytesAtPath(path: string, key: CryptoKey) {
    const raw = await ostore.downloadBytes(path)
    if (!isVaultBlob(raw)) return
    const plain = await decryptBytes(raw, key)
    const name = path.slice(path.lastIndexOf('/') + 1)
    const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
    await uploadPlain(dir, name, plain)
  }

  async function filesUnderVault(path: string, kind: 'file' | 'dir'): Promise<OstoreEntry[]> {
    if (kind === 'file') {
      return [{ name: path.slice(path.lastIndexOf('/') + 1), path, type: 'file', size: 0, mtime: 0 }]
    }
    return ostore.listRecursive(path)
  }

  async function encryptExisting(path: string, kind: 'file' | 'dir', key: CryptoKey) {
    const files = await filesUnderVault(path, kind)
    for (const f of files) await encryptBytesAtPath(f.path, key)
  }

  async function decryptExisting(path: string, kind: 'file' | 'dir', key: CryptoKey) {
    const files = await filesUnderVault(path, kind)
    for (const f of files) await decryptBytesAtPath(f.path, key)
  }

  async function changePasswordWithReencrypt(path: string, oldPassword: string, newPassword: string) {
    const row = vault.vaultRowForPath(path)
    if (!row) throw new Error('Not encrypted')
    const oldKey = vault.keyForPath(path) ?? await vault.unlock(path, oldPassword)
    const plains: { path: string; data: Uint8Array }[] = []
    for (const f of await filesUnderVault(path, row.kind)) {
      const raw = await ostore.downloadBytes(f.path)
      if (isVaultBlob(raw)) {
        plains.push({ path: f.path, data: await decryptBytes(raw, oldKey) })
      } else {
        plains.push({ path: f.path, data: raw })
      }
    }
    await vault.changePassword(path, oldPassword, newPassword)
    const newKey = vault.keyForPath(path)!
    for (const p of plains) {
      const enc = await encryptBytes(p.data, newKey)
      const name = p.path.slice(p.path.lastIndexOf('/') + 1)
      const dir = p.path.includes('/') ? p.path.slice(0, p.path.lastIndexOf('/')) : ''
      await uploadPlain(dir, name, enc)
    }
  }

  return {
    encryptBytesAtPath,
    decryptBytesAtPath,
    encryptExisting,
    decryptExisting,
    changePasswordWithReencrypt,
  }
}
