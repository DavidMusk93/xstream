# File vault — client-side encryption (xstream layer)

> 2026-10-30. Ciphertext lives on ostore; passwords never stored plaintext.

## Model

- **Metadata** in PostgreSQL `file_vault`: ostore-relative `path`, `kind` (`file`|`dir`),
  scrypt `password_hash`, per-item `kdf_salt` (also used for PBKDF2 key derivation in
  the browser).
- **Payload** on ostore: AES-256-GCM blobs prefixed with magic `XSTRMENC1` (12-byte
  nonce + ciphertext). Plaintext never hits the server.
- **Unlock** is in-memory for the tab session (`CryptoKey` map keyed by vault path).

Encrypted **folders** apply the folder password to new uploads and to a recursive
encrypt of existing files when encryption is enabled. Opening a locked folder shows
an unlock gate (Dropbox-style) before listing.

## API (`backend/routers/files_vault.py`, `Depends(require_auth)`)

| Method | Path | Role |
|--------|------|------|
| GET | `/api/files/vault` | List vault rows (no password hashes) |
| POST | `/api/files/vault` | Register `{path, kind, password}` |
| POST | `/api/files/vault/unlock` | Verify password → `{kdf_salt}` |
| POST | `/api/files/vault/password` | Change password (client re-encrypts blobs) |
| POST | `/api/files/vault/move` | Repoint paths after ostore rename |
| DELETE | `/api/files/vault?path=&recursive=` | Drop metadata |

Frontend: `useFileVault.ts`, `useFileVaultOps.ts`, `utils/fileVaultCrypto.ts`,
`/files` actions + `VaultPasswordSheet.vue`.

## Ops

Schema is created by `init_schema()` on backend start. No ostore changes.
