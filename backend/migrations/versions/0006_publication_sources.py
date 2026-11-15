"""Track source identity and provenance on managed publications."""
from alembic import op
import sqlalchemy as sa

revision = '0006_publication_sources'
down_revision = '0005_demo_source_id'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('publications', sa.Column('external_record_id', sa.String(length=160), nullable=True))
    op.add_column('publications', sa.Column('source_name', sa.String(length=160), nullable=True))
    op.add_column('publications', sa.Column('source_reference', sa.String(length=500), nullable=True))
    op.create_index('uq_publication_external_record', 'publications', ['company_id', 'external_record_id'], unique=True)


def downgrade():
    op.drop_index('uq_publication_external_record', table_name='publications')
    op.drop_column('publications', 'source_reference')
    op.drop_column('publications', 'source_name')
    op.drop_column('publications', 'external_record_id')
