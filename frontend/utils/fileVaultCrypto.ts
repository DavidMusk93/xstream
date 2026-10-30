/** Client-side AES-GCM encryption for ostore objects (xstream file vault). */

export const VAULT_MAGIC = new TextEncoder().encode('XSTRMENC1')
export const VAULT_MAGIC_LEN = VAULT_MAGIC.length
export const VAULT_NONCE_LEN = 12

function b64urlToBytes(s: string): Uint8Array {
  const pad = s.length % 4 ? '='.repeat(4 - (s.length % 4)) : ''
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

export async function deriveVaultKey(password: string, kdfSalt: string): Promise<CryptoKey> {
  const enc = new TextEncoder()
  const baseKey = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey'])
  const salt = b64urlToBytes(kdfSalt)
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: 120_000, hash: 'SHA-256' },
    baseKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

export function isVaultBlob(buf: ArrayBuffer | Uint8Array): boolean {
  const u = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  if (u.length < VAULT_MAGIC_LEN + VAULT_NONCE_LEN + 16) return false
  for (let i = 0; i < VAULT_MAGIC_LEN; i++) {
    if (u[i] !== VAULT_MAGIC[i]) return false
  }
  return true
}

export async function encryptBytes(plain: Uint8Array, key: CryptoKey): Promise<Uint8Array> {
  const nonce = crypto.getRandomValues(new Uint8Array(VAULT_NONCE_LEN))
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, plain))
  const out = new Uint8Array(VAULT_MAGIC_LEN + VAULT_NONCE_LEN + ct.length)
  out.set(VAULT_MAGIC, 0)
  out.set(nonce, VAULT_MAGIC_LEN)
  out.set(ct, VAULT_MAGIC_LEN + VAULT_NONCE_LEN)
  return out
}

export async function decryptBytes(blob: Uint8Array, key: CryptoKey): Promise<Uint8Array> {
  if (!isVaultBlob(blob)) throw new Error('Not an encrypted file')
  const nonce = blob.subarray(VAULT_MAGIC_LEN, VAULT_MAGIC_LEN + VAULT_NONCE_LEN)
  const ct = blob.subarray(VAULT_MAGIC_LEN + VAULT_NONCE_LEN)
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, key, ct)
  return new Uint8Array(plain)
}

export async function encryptFile(file: File, key: CryptoKey): Promise<File> {
  const plain = new Uint8Array(await file.arrayBuffer())
  const enc = await encryptBytes(plain, key)
  return new File([enc], file.name, { type: 'application/octet-stream', lastModified: file.lastModified })
}
