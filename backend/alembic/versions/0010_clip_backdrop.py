"""clip_shapes.backdrop — which picture a clip ran on

Revision ID: 0010_clip_backdrop
Revises: 0009_clip_shapes
Create Date: 2026-09-01 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0010_clip_backdrop'
down_revision = '0009_clip_shapes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'clip_shapes',
        sa.Column('backdrop', sa.String(length=160), nullable=False, server_default=''),
    )
    # The default exists only to fill the rows already there; new rows are
    # written by the repository, which always supplies the column.
    op.alter_column('clip_shapes', 'backdrop', server_default=None)


def downgrade() -> None:
    op.drop_column('clip_shapes', 'backdrop')
