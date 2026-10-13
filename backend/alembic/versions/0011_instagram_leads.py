"""leads may arrive from Instagram, not only the Telegram bot

Revision ID: 0011_instagram_leads
Revises: 0010_clip_backdrop
Create Date: 2026-09-01 14:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0011_instagram_leads'
down_revision = '0010_clip_backdrop'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('ig_user_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_leads_ig_user_id'), 'leads', ['ig_user_id'])
    # A lead from Instagram has no Telegram id and never will.
    op.alter_column('leads', 'telegram_user_id', existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column('leads', 'telegram_user_id', existing_type=sa.BigInteger(), nullable=False)
    op.drop_index(op.f('ix_leads_ig_user_id'), table_name='leads')
    op.drop_column('leads', 'ig_user_id')
