"""Frozen additive governance schema; historical tables and rows are unchanged."""
from alembic import op
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa

revision = '0004_governance'
down_revision = '0003_phase1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('actor_type', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=100), nullable=True),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('resource_type', sa.String(length=50), nullable=False),
    sa.Column('resource_id', sa.String(length=100), nullable=True),
    sa.Column('outcome', sa.String(length=30), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_company_created', 'audit_events', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_audit_event_type', 'audit_events', ['event_type'], unique=False)
    op.create_table('user_notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('recipient_user_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('resource_type', sa.String(length=40), nullable=False),
    sa.Column('resource_id', sa.String(length=100), nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('recipient_user_id', 'dedupe_key')
    )
    op.create_index('ix_user_notification_inbox', 'user_notifications', ['company_id', 'recipient_user_id', 'read_at', 'created_at'], unique=False)
    op.create_table('approval_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=True),
    sa.Column('requesting_user_id', sa.Integer(), nullable=True),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('source_type', sa.String(length=30), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('proposed_content', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('triggered_policy', sa.JSON(), nullable=False),
    sa.Column('config_version_id', sa.Integer(), nullable=True),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=True),
    sa.Column('decision_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewer_comments', sa.String(length=1000), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], ),
    sa.ForeignKeyConstraint(['requesting_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_type', 'source_id')
    )
    op.create_index('ix_approval_company_status', 'approval_requests', ['company_id', 'status', 'created_at'], unique=False)
    db = op.get_bind()
    approvals = sa.Table('approval_requests', sa.MetaData(), autoload_with=db)
    now = datetime.now(timezone.utc)
    pending = db.execute(sa.text('''
        SELECT a.id, a.agent_id, a.content, ac.company_id, r.config_version_id,
               r.policy_version, c.created_by
        FROM run_approvals a JOIN agent_runs r ON r.id=a.run_id
        JOIN agent_accounts ac ON ac.id=a.agent_id
        JOIN conversations c ON c.id=a.conversation_id
        WHERE a.status='pending'
    ''')).mappings()
    for row in pending:
        db.execute(approvals.insert().values(
            company_id=row['company_id'], agent_id=row['agent_id'],
            requesting_user_id=row['created_by'], action_type='message.reply',
            source_type='run_approval', source_id=row['id'],
            proposed_content=row['content'] or '', category='general_information',
            reason='human_review_required', triggered_policy=['legacy.pending_approval'],
            config_version_id=row['config_version_id'], policy_version=row['policy_version'],
            status='pending', expires_at=now + timedelta(hours=24), created_at=now,
        ))


def downgrade():
    raise RuntimeError("Downgrade can destroy governance records; restore a verified backup instead.")
