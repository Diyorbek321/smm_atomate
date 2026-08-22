"""knowledge_bases.visual_style — the look every generated photo shares

Without an anchor each image comes back from the model on its own terms, and
twenty posts later the feed reads as a stock collage rather than one brand.
Empty is a valid value: the style is then derived from the brand colours.

Revision ID: 0006_visual_style
Revises: 0005_business_plan
Create Date: 2026-08-22 12:40:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0006_visual_style'
down_revision = '0005_business_plan'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'knowledge_bases',
        sa.Column(
            'visual_style',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade() -> None:
    op.drop_column('knowledge_bases', 'visual_style')
