"""Uniquely identify externally sourced posts."""
from alembic import op
import sqlalchemy as sa

revision = '0005_demo_source_id'
down_revision = '0004_governance'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('uq_posts_source_record', 'posts', ['source_type', 'source_ref'], unique=True)


def downgrade():
    op.drop_index('uq_posts_source_record', table_name='posts')
