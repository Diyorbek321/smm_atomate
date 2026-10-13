"""clip_shapes table — structural memory for the video path

Revision ID: 0009_clip_shapes
Revises: 0008_brand_kit
Create Date: 2026-09-01 10:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0009_clip_shapes'
down_revision = '0008_brand_kit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'clip_shapes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('topic', sa.String(length=300), nullable=False),
        sa.Column('skeleton', sa.String(length=32), nullable=False),
        sa.Column('opening', sa.String(length=48), nullable=False),
        sa.Column('archetypes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scenes', sa.Integer(), nullable=False),
        sa.Column('mood', sa.String(length=24), nullable=False),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_clip_shapes_business_created', 'clip_shapes', ['business_id', 'created_at'])
    op.create_index(op.f('ix_clip_shapes_id'), 'clip_shapes', ['id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_clip_shapes_id'), table_name='clip_shapes')
    op.drop_index('ix_clip_shapes_business_created', table_name='clip_shapes')
    op.drop_table('clip_shapes')
