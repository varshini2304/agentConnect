"""Add stored_embeddings table for semantic relevance vectors.

Revision ID: 0008_semantic_embeddings
Revises: 0007_remove_legacy_post_source_uniqueness
Create Date: 2026-11-17 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0008_semantic_embeddings'
down_revision = '0007_remove_legacy_post_source_uniqueness'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stored_embeddings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'entity_id', 'model_name', name='uq_stored_embeddings_entity'),
    )
    op.create_index('ix_stored_embeddings_entity_type', 'stored_embeddings', ['entity_type'], unique=False)
    op.create_index('ix_stored_embeddings_entity_id', 'stored_embeddings', ['entity_id'], unique=False)
    op.create_index('ix_stored_embeddings_content_hash', 'stored_embeddings', ['content_hash'], unique=False)
    op.create_index('ix_stored_embeddings_lookup', 'stored_embeddings', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_stored_embeddings_hash', 'stored_embeddings', ['entity_type', 'content_hash'], unique=False)


def downgrade():
    op.drop_index('ix_stored_embeddings_hash', table_name='stored_embeddings')
    op.drop_index('ix_stored_embeddings_lookup', table_name='stored_embeddings')
    op.drop_index('ix_stored_embeddings_content_hash', table_name='stored_embeddings')
    op.drop_index('ix_stored_embeddings_entity_id', table_name='stored_embeddings')
    op.drop_index('ix_stored_embeddings_entity_type', table_name='stored_embeddings')
    op.drop_table('stored_embeddings')

