"""Connect published network announcements to relevant agents and durable replies."""
import logging

from sqlalchemy import select

from app.db.network import Invitation, Publication
from app.schemas.network import ConversationCreate
from app.services import conversations, workspace
from app.services.workspace import Principal

log = logging.getLogger(__name__)


def enqueue_publication_workflow(db, principal: Principal, publication: Publication) -> int:
    if publication.status != "published" or publication.visibility != "network":
        return 0
    decisions = workspace.discover(db, principal, publication)
    queued = 0
    for decision in decisions:
        if not decision.selected or decision.agent_id == publication.agent_id:
            continue
        try:
            with db.begin_nested():
                key = f"publication-{publication.id}-{decision.agent_id}"
                conversation = conversations.create_conversation(db, principal, ConversationCreate(
                    kind="direct", title=publication.title[:200], agent_id=publication.agent_id,
                    recipient_agent_id=decision.agent_id, publication_id=publication.id,
                    idempotency_key=key,
                ))
                invitation = db.scalar(select(Invitation).where(
                    Invitation.conversation_id == conversation.id,
                    Invitation.recipient_agent_id == decision.agent_id,
                ))
                if invitation is not None and invitation.status == "pending":
                    # Relevance selection on a public post is the recipient authorization
                    # for this scoped thread; do not wait for a separate invitation review.
                    invitation.requires_approval = False
                    conversations.join_invitation(db, invitation, publication.published_at or publication.created_at)
                if invitation is not None and invitation.status == "accepted":
                    member = conversations.membership(db, conversation.id, publication.agent_id)
                    if member is not None:
                        conversations.enqueue_message(db, conversation, member, publication.content,
                            f"publication-{publication.id}", publication.published_at or publication.created_at)
                queued += 1
        except Exception as exc:
            # Isolate one recipient's current policy/membership failure from other selected agents.
            log.warning("publication_recipient_skipped publication=%d agent=%d reason=%s",
                        publication.id, decision.agent_id, type(exc).__name__)
    return queued
