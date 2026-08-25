"""content_items.metrics — what a post actually did after it went out

Until now the system could plan, write, render and publish, but never learn:
nothing that happened after publishing came back. A strategist that cannot see
which pillar earned reactions is guessing every week, and guessing forever.

JSONB rather than columns because the shape differs per platform and will keep
changing — Telegram gives anonymous reaction counts, Instagram gives something
else entirely, and neither is worth a migration each time it moves.

Revision ID: 0007_content_metrics
Revises: 0006_visual_style
Create Date: 2026-08-23 15:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0007_content_metrics'
down_revision = '0006_visual_style'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_items',
        sa.Column(
            'metrics',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column('content_items', 'metrics')
