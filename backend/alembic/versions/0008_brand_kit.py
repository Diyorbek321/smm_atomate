"""knowledge_bases.brand_kit — the parts of a brand that are not colour

Colours were already per-business, and that solved half the complaint the
system was built to answer: every client's feed looked the same. The other
half is everything colour cannot carry. Typography was hardcoded for everyone,
so two clients in different trades shipped cards set in identical type. Voice
was a six-value enum, which cannot tell a law firm from a barbershop. And the
banned-phrase list was global, so a brand could not forbid the one word its
owner hates.

JSONB rather than columns for the same reason as `visual_style`: the shape is
still moving, and each new brand attribute is not worth a migration. Empty is
valid everywhere — the defaults in app/services/brand_kit.py apply.

Revision ID: 0008_brand_kit
Revises: 0007_content_metrics
Create Date: 2026-08-24 14:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0008_brand_kit'
down_revision = '0007_content_metrics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'knowledge_bases',
        sa.Column(
            'brand_kit',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade() -> None:
    op.drop_column('knowledge_bases', 'brand_kit')
