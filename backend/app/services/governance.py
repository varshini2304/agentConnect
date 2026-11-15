"""Aggregate execution budgets, counted under the existing transactional runtime mutex."""
import os
from sqlalchemy import func, select
from app.db.network import AgentAccount, AgentRun, AgentRunAttempt, PublishingJob


def company_budget_exhausted(db, company, now):
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count(AgentRunAttempt.id)).join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
        .join(AgentAccount, AgentAccount.id == AgentRun.agent_id).where(AgentAccount.company_id == company.id, AgentRunAttempt.started_at >= midnight))
    used += sum(1 for history in db.scalars(select(PublishingJob.attempt_history).where(PublishingJob.company_id == company.id))
        for attempt in history if attempt.get("started_at", "") >= midnight.isoformat())
    used += legacy_attempt_count(db, now=now, company_id=company.id)
    maximum = min(max(0, int(os.getenv("AGENTCONNECT_DAILY_COMPANY_BUDGET", "1000"))), company.policy.get("daily_execution_budget", 1000))
    return used >= maximum


def legacy_attempt_count(db, *, now, agent_id=None, company_id=None):
    from app.db.models import AgentInteraction
    from app.services.security import aware
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    query = select(AgentInteraction)
    if agent_id is not None:
        query = query.where(AgentInteraction.agent_id == agent_id)
    if company_id is not None:
        query = query.where(AgentInteraction.company_id == company_id)
    count = 0
    for row in db.scalars(query):
        history = (row.decision_json or {}).get("attempt_history")
        if history is not None:
            count += sum(1 for attempt in history if attempt.get("started_at", "") >= midnight.isoformat())
        elif aware(row.started_at) >= midnight:
            count += 1  # Historical executions predate the per-attempt ledger.
    return count


def legacy_running_count(db, agent_id):
    from app.db.models import AgentInteraction
    return db.scalar(select(func.count(AgentInteraction.id)).where(AgentInteraction.agent_id == agent_id, AgentInteraction.status == "running"))
