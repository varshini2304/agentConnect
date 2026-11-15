"""Run with `python -m app.worker [--once]`; start separately from the API server."""
import argparse
from datetime import datetime, timezone
import json
import logging
import signal
from threading import Event

from sqlalchemy import text

from app.db.network import RuntimeMutex
from app.db.session import SessionLocal
from app.services.runtime import run_once


def main():
    parser = argparse.ArgumentParser(description="AgentConnect durable delivery worker")
    parser.add_argument("--once", action="store_true", help="Process at most one ready delivery")
    args = parser.parse_args()
    from app.services.audit import install_audit_hooks
    from app.services.security import validate_configuration
    from app.db.migrations import HEAD
    validate_configuration()
    install_audit_hooks()
    # Schema initialization belongs to API startup; don't race a second process seeding its mutex.
    with SessionLocal() as db:
        if db.get(RuntimeMutex, 1) is None or db.scalar(text('SELECT version_num FROM alembic_version')) != HEAD:
            raise SystemExit("Apply verified database migrations before starting workers.")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stopping = Event()
    previous = {sig: signal.signal(sig, lambda _sig, _frame: stopping.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    log_event("worker_started")
    try:
        while not stopping.is_set():
            try:
                worked = run_once(SessionLocal)
            except Exception:
                # Never log provider payloads, configuration, message content or credentials.
                log_event("worker_transaction_failed", logging.ERROR)
                worked = False
            if args.once:
                break
            if not worked:
                stopping.wait(1)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        log_event("worker_stopped")


def log_event(event, level=logging.INFO):
    logging.log(level, json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level), "event": event}))


if __name__ == "__main__":
    main()
