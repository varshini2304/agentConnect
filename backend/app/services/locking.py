"""One short database lock serializes company governance and runtime reservations."""
from fastapi import HTTPException
from sqlalchemy import update

from app.db.network import RuntimeMutex


def lock_runtime(db):
    result = db.execute(update(RuntimeMutex).where(RuntimeMutex.id == 1).values(value=RuntimeMutex.value + 1))
    if result.rowcount != 1:
        raise HTTPException(503, "Runtime is not initialized")
    db.expire_all()
