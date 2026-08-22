"""leads table — bot-captured contacts from post CTAs

Revision ID: 0004_leads
Revises: 0003_video_url
Create Date: 2026-08-21 17:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0004_leads'
down_revision = '0003_video_url'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'leads',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('full_name', sa.String(length=160), nullable=False),
        sa.Column('username', sa.String(length=160), nullable=False),
        sa.Column('phone', sa.String(length=64), nullable=False),
        sa.Column('interest', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_leads_business_created', 'leads', ['business_id', 'created_at'])
    op.create_index(op.f('ix_leads_telegram_user_id'), 'leads', ['telegram_user_id'])
    op.create_index(op.f('ix_leads_id'), 'leads', ['id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_leads_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_telegram_user_id'), table_name='leads')
    op.drop_index('ix_leads_business_created', table_name='leads')
    op.drop_table('leads')
