from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from backend.services import file_vault as vault_svc
from core.db import file_vault as vault_db
from core.db.write_queue import db_read, db_write

router = APIRouter(prefix="/api/files/vault", tags=["files-vault"], dependencies=[Depends(require_auth)])


class VaultCreateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=2048)
    kind: str = Field(..., pattern="^(file|dir)$")
    password: str = Field(..., min_length=1, max_length=256)


class VaultUnlockRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=2048)
    password: str = Field(..., min_length=1, max_length=256)


class VaultPasswordRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=2048)
    old_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


class VaultMoveRequest(BaseModel):
    from_path: str = Field(..., min_length=1, max_length=2048)
    to_path: str = Field(..., min_length=1, max_length=2048)


@router.get("")
async def vault_list():
    items = await db_read(vault_db.list_vault_paths)
    return {"items": items}


@router.post("")
async def vault_create(req: VaultCreateRequest):
    try:
        kdf_salt = vault_svc.new_kdf_salt()
        ph = vault_svc.hash_password(req.password, kdf_salt)
        await db_write(vault_db.upsert_vault, req.path, req.kind, ph, kdf_salt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": req.path.strip().strip("/"), "kind": req.kind, "kdf_salt": kdf_salt}


@router.post("/unlock")
async def vault_unlock(req: VaultUnlockRequest):
    try:
        row = await db_read(vault_db.get_vault, req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Not encrypted")
    if not vault_svc.verify_password(req.password, row["kdf_salt"], row["password_hash"]):
        raise HTTPException(status_code=403, detail="Wrong password")
    return {"ok": True, "path": row["path"], "kind": row["kind"], "kdf_salt": row["kdf_salt"]}


@router.post("/password")
async def vault_change_password(req: VaultPasswordRequest):
    try:
        row = await db_read(vault_db.get_vault, req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Not encrypted")
    if not vault_svc.verify_password(req.old_password, row["kdf_salt"], row["password_hash"]):
        raise HTTPException(status_code=403, detail="Wrong password")
    kdf_salt = vault_svc.new_kdf_salt()
    ph = vault_svc.hash_password(req.new_password, kdf_salt)
    await db_write(vault_db.upsert_vault, row["path"], row["kind"], ph, kdf_salt)
    return {"ok": True, "path": row["path"], "kdf_salt": kdf_salt}


@router.post("/move")
async def vault_move(req: VaultMoveRequest):
    try:
        n = await db_write(vault_db.move_vault, req.from_path, req.to_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"moved": n}


@router.delete("")
async def vault_delete(path: str, recursive: bool = False):
    try:
        if recursive:
            n = await db_write(vault_db.delete_vault_prefix, path)
        else:
            ok = await db_write(vault_db.delete_vault, path)
            n = 1 if ok else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not n:
        raise HTTPException(status_code=404, detail="Not encrypted")
    return {"deleted": n}
