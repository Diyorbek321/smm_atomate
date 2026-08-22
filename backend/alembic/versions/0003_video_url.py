"""content_items.video_url — motion clips rendered by the video service

Revision ID: 0003_video_url
Revises: 0002_review_ids_bigint
Create Date: 2026-08-21 16:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0003_video_url'
down_revision = '0002_review_ids_bigint'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('content_items', sa.Column('video_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column('content_items', 'video_url')
