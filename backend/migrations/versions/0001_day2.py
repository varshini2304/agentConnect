"""Frozen 0001_day2 schema; independent of live application models."""
from alembic import op
import sqlalchemy as sa

revision = '0001_day2'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('agents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('company_name', sa.String(length=160), nullable=False),
    sa.Column('role', sa.String(length=200), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agents_company_name', 'agents', ['company_name'], unique=False)
    op.create_index(op.f('ix_agents_is_active'), 'agents', ['is_active'], unique=False)
    op.create_index(op.f('ix_agents_slug'), 'agents', ['slug'], unique=True)
    op.create_table('agent_interests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('interest_type', sa.String(length=16), nullable=False),
    sa.Column('value', sa.String(length=160), nullable=False),
    sa.Column('weight', sa.Double(), nullable=False),
    sa.CheckConstraint("interest_type IN ('category', 'keyword', 'exclude')", name='ck_agent_interests_type'),
    sa.CheckConstraint('weight >= 0', name='ck_agent_interests_nonnegative_weight'),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'interest_type', 'value', name='uq_agent_interest_value')
    )
    op.create_index(op.f('ix_agent_interests_agent_id'), 'agent_interests', ['agent_id'], unique=False)
    op.create_index('ix_agent_interests_type_value', 'agent_interests', ['interest_type', 'value'], unique=False)
    op.create_table('agent_relationships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_agent_id', sa.Integer(), nullable=False),
    sa.Column('target_agent_id', sa.Integer(), nullable=False),
    sa.Column('relation', sa.String(length=16), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.CheckConstraint("relation IN ('partner', 'block')", name='ck_agent_relationship_relation'),
    sa.CheckConstraint('source_agent_id <> target_agent_id', name='ck_agent_relationship_not_self'),
    sa.CheckConstraint('weight >= 0', name='ck_agent_relationship_nonnegative_weight'),
    sa.ForeignKeyConstraint(['source_agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_agent_id', 'target_agent_id', name='uq_agent_relationship_pair')
    )
    op.create_index('ix_agent_relationship_target_relation', 'agent_relationships', ['target_agent_id', 'relation'], unique=False)
    op.create_table('posts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('author_agent_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_ref', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash', name='uq_posts_content_hash')
    )
    op.create_index('ix_posts_author_agent_id', 'posts', ['author_agent_id'], unique=False)
    op.create_index('ix_posts_category', 'posts', ['category'], unique=False)
    op.create_index('ix_posts_created_at_id', 'posts', ['created_at', 'id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('recipient_agent_id', sa.Integer(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('reason_json', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed', 'skipped')", name='ck_notification_status'),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'recipient_agent_id', name='uq_notification_post_recipient')
    )
    op.create_index('ix_notifications_recipient_created', 'notifications', ['recipient_agent_id', 'created_at'], unique=False)
    op.create_table('routing_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('eligible', sa.Boolean(), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('reason_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'agent_id', name='uq_routing_decision_post_agent')
    )
    op.create_index('ix_routing_decisions_post_selected', 'routing_decisions', ['post_id', 'selected'], unique=False)
    op.create_table('agent_interactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('notification_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decision_json', sa.JSON(), nullable=True),
    sa.Column('error', sa.String(length=240), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('running', 'responded', 'skipped', 'failed')", name='ck_interaction_status'),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('notification_id', name='uq_interaction_notification'),
    sa.UniqueConstraint('post_id', 'agent_id', name='uq_interaction_post_agent')
    )
    op.create_index('ix_interactions_status', 'agent_interactions', ['status'], unique=False)
    op.create_table('comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('interaction_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.String(length=400), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['interaction_id'], ['agent_interactions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('interaction_id', name='uq_comment_interaction'),
    sa.UniqueConstraint('post_id', 'agent_id', name='uq_comment_post_agent')
    )
    op.create_index('ix_comments_post_created', 'comments', ['post_id', 'created_at'], unique=False)

def downgrade():
    raise RuntimeError("Downgrade can destroy historical data; restore a verified backup instead.")
