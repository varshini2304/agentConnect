"""Frozen 0002_phase2 schema; independent of live application models."""
from alembic import op
import sqlalchemy as sa

revision = '0002_phase2'
down_revision = '0001_day2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('network_opt_in', sa.Boolean(), nullable=False),
    sa.Column('policy', sa.JSON(), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('runtime_mutex',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('agent_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('active_version_id', sa.Integer(), nullable=True),
    sa.Column('config_version_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['active_version_id'], ['agent_versions.id'], use_alter=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], use_alter=True),
    sa.ForeignKeyConstraint(['id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'slug')
    )
    op.create_index(op.f('ix_agent_accounts_company_id'), 'agent_accounts', ['company_id'], unique=False)
    op.create_table('agent_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'version')
    )
    op.create_index(op.f('ix_agent_versions_agent_id'), 'agent_versions', ['agent_id'], unique=False)
    op.create_table('company_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'user_id')
    )
    op.create_index(op.f('ix_company_members_company_id'), 'company_members', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_members_user_id'), 'company_members', ['user_id'], unique=False)
    op.create_table('knowledge_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('source_url', sa.String(length=2000), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_sources_agent_id'), 'knowledge_sources', ['agent_id'], unique=False)
    op.create_index(op.f('ix_knowledge_sources_company_id'), 'knowledge_sources', ['company_id'], unique=False)
    op.create_table('login_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_login_sessions_user_id'), 'login_sessions', ['user_id'], unique=False)
    op.create_table('publications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('author_type', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('agent_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('config_version_id', sa.Integer(), nullable=True),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'content_hash'),
    sa.UniqueConstraint('company_id', 'idempotency_key')
    )
    op.create_index(op.f('ix_publications_company_id'), 'publications', ['company_id'], unique=False)
    op.create_index(op.f('ix_publications_created_at'), 'publications', ['created_at'], unique=False)
    op.create_index(op.f('ix_publications_published_at'), 'publications', ['published_at'], unique=False)
    op.create_table('conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('publication_id', sa.Integer(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('created_by', 'idempotency_key')
    )
    op.create_table('discovery_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('publication_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('agent_name', sa.String(length=160), nullable=False),
    sa.Column('eligible', sa.Boolean(), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('score', sa.Double(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('signals', sa.JSON(), nullable=False),
    sa.Column('audit_json', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('publication_id', 'agent_id')
    )
    op.create_index(op.f('ix_discovery_records_publication_id'), 'discovery_records', ['publication_id'], unique=False)
    op.create_table('publishing_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('requested_by', sa.Integer(), nullable=False),
    sa.Column('config_version_id', sa.Integer(), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('brief', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('attempt_history', sa.JSON(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_token', sa.String(length=64), nullable=True),
    sa.Column('error', sa.String(length=80), nullable=True),
    sa.Column('publication_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], ),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'idempotency_key')
    )
    op.create_index('ix_publishing_claim', 'publishing_jobs', ['status', 'available_at'], unique=False)
    op.create_index(op.f('ix_publishing_jobs_agent_id'), 'publishing_jobs', ['agent_id'], unique=False)
    op.create_table('conversation_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('config_version_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('history_from_seq', sa.Integer(), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'agent_id')
    )
    op.create_index(op.f('ix_conversation_members_agent_id'), 'conversation_members', ['agent_id'], unique=False)
    op.create_index(op.f('ix_conversation_members_conversation_id'), 'conversation_members', ['conversation_id'], unique=False)
    op.create_table('invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('inviter_agent_id', sa.Integer(), nullable=False),
    sa.Column('recipient_agent_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('requires_approval', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.ForeignKeyConstraint(['inviter_agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['recipient_agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invitations_conversation_id'), 'invitations', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_invitations_recipient_agent_id'), 'invitations', ['recipient_agent_id'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('sender_agent_id', sa.Integer(), nullable=False),
    sa.Column('sender_user_id', sa.Integer(), nullable=True),
    sa.Column('author_type', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('reply_depth', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.ForeignKeyConstraint(['sender_agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'sender_agent_id', 'idempotency_key'),
    sa.UniqueConstraint('conversation_id', 'sequence')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_table('message_deliveries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_token', sa.String(length=64), nullable=True),
    sa.Column('error', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id', 'agent_id')
    )
    op.create_index('ix_delivery_claim', 'message_deliveries', ['status', 'available_at'], unique=False)
    op.create_index(op.f('ix_message_deliveries_agent_id'), 'message_deliveries', ['agent_id'], unique=False)
    op.create_table('agent_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('delivery_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('config_version_id', sa.Integer(), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('action', sa.String(length=24), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['config_version_id'], ['agent_versions.id'], ),
    sa.ForeignKeyConstraint(['delivery_id'], ['message_deliveries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('delivery_id')
    )
    op.create_index(op.f('ix_agent_runs_agent_id'), 'agent_runs', ['agent_id'], unique=False)
    op.create_table('agent_run_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.String(length=80), nullable=True),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'number')
    )
    op.create_index(op.f('ix_agent_run_attempts_run_id'), 'agent_run_attempts', ['run_id'], unique=False)
    op.create_table('run_approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )

def downgrade():
    raise RuntimeError("Downgrade can destroy historical data; restore a verified backup instead.")
