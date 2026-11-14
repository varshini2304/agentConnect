"""Coordinates routing, notification creation, and independent agent processing."""
from sqlalchemy.orm import Session

from app.db.models import Post
from app.services.agent_runner import AgentRunner
from app.services.notification_service import create_selected_notifications
from app.services.response_generation import AgentResponseService
from app.services.routing_service import evaluate_and_persist_routing


def run_post_workflow(
    db: Session,
    post: Post,
    response_service: AgentResponseService,
):
    # Routing decisions and notifications commit before any external model request.
    results = evaluate_and_persist_routing(db, post)
    create_selected_notifications(db, post, results)
    AgentRunner(response_service).run_post(db, post.id)
