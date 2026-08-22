"""review chat/message ids to BIGINT — Telegram ids exceed int32

Revision ID: 0002_review_ids_bigint
Revises: 0001_initial
Create Date: 2026-08-21 12:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0002_review_ids_bigint'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('content_items', 'review_message_id', type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column('content_items', 'review_chat_id', type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    op.alter_column('content_items', 'review_chat_id', type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column('content_items', 'review_message_id', type_=sa.Integer(), existing_type=sa.BigInteger())
