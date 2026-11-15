"""Allow repeatable legacy scenario posts to share a source reference."""
from alembic import op

revision = '0007_remove_legacy_post_source_uniqueness'
down_revision = '0006_publication_sources'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('uq_posts_source_record', table_name='posts')


def downgrade():
    op.create_index('uq_posts_source_record', 'posts', ['source_type', 'source_ref'], unique=True)
