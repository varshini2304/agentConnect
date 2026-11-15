"""Startup ingestion for the bundled demo, using managed publications and the normal network path."""
import csv
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from app.db.network import AgentAccount, Company, Publication, User
from app.services import workspace
from app.services.publication_workflow import enqueue_publication_workflow
from app.services.workspace import Principal, config_for

log = logging.getLogger(__name__)
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_announcements.csv"
FIELDS = {"external_record_id", "company_slug", "publishing_agent_slug", "title", "description",
          "category", "published_at", "source_name", "source_reference"}


def _published_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _key(record_id: str) -> str:
    return "demo-csv-" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()


def _process_publication(session_factory, publication_id: int, company_id: int, user_id: int) -> None:
    with session_factory() as db, db.begin():
        principal = Principal(db.get(User, user_id), db.get(Company, company_id), "")
        publication = db.get(Publication, publication_id)
        if publication is not None:
            enqueue_publication_workflow(db, principal, publication)


def ingest_demo_csv(session_factory, path: Path = CSV_PATH) -> int:
    if not path.is_file():
        log.warning("demo_csv_missing")
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not FIELDS.issubset(reader.fieldnames):
                log.warning("demo_csv_invalid_header")
                return 0
            records = list(reader)
    except (OSError, UnicodeError, csv.Error):
        log.warning("demo_csv_unreadable")
        return 0

    imported = 0
    for number, row in enumerate(records, start=2):
        try:
            values = {key: (row.get(key) or "").strip() for key in FIELDS}
            if any(not values[key] for key in FIELDS):
                raise ValueError("missing required value")
            if len(values["external_record_id"]) > 160 or len(values["source_name"]) > 160 or len(values["source_reference"]) > 500:
                raise ValueError("source field too long")
            published_at = _published_at(values["published_at"])
            with session_factory() as db:
                company = db.scalar(select(Company).where(Company.slug == values["company_slug"]))
                if company is None:
                    raise ValueError("unknown company slug")
                account = db.scalar(select(AgentAccount).where(AgentAccount.company_id == company.id,
                                                               AgentAccount.slug == values["publishing_agent_slug"]))
                if account is None or account.state != "active" or account.company_id != company.id:
                    raise ValueError("publisher missing, inactive, or outside company")
                config = config_for(db, account, active=True)
                user = db.scalar(select(User).where(User.email == "agentconnect-demo-service@invalid.local"))
                if not config or user is None:
                    raise ValueError("publisher configuration unavailable")
                publication = db.scalar(select(Publication).where(
                    Publication.company_id == company.id,
                    Publication.external_record_id == values["external_record_id"],
                ))
                created = publication is None
                if created:
                    principal = Principal(user, company, "")
                    publication = workspace.publish(db, principal, {
                        "agent_id": account.id, "title": values["title"], "content": values["description"],
                        "category": values["category"], "visibility": "network", "status": "published",
                        "idempotency_key": _key(values["external_record_id"]),
                    }, autonomous=True)
                    publication.external_record_id = values["external_record_id"]
                    publication.source_name = values["source_name"]
                    publication.source_reference = values["source_reference"]
                    publication.created_at = published_at
                    publication.published_at = published_at if publication.status == "published" else None
                    publication_id = publication.id
                    db.commit()
                else:
                    publication_id = publication.id
                company_id, user_id = company.id, user.id
            # Publication persistence commits before discovery and durable invitations/deliveries.
            _process_publication(session_factory, publication_id, company_id, user_id)
            imported += int(created)
        except Exception as exc:
            log.warning("demo_csv_row_rejected row=%d reason=%s", number,
                        getattr(exc, "detail", type(exc).__name__) if isinstance(exc, HTTPException) else type(exc).__name__)
    return imported
