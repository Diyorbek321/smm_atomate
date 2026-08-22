"""businesses.plan — service tier (start/standard/pro)

Existing clients are grandfathered onto `pro` so no capability they already
use disappears at deploy time; new businesses start on `start`.

Revision ID: 0005_business_plan
Revises: 0004_leads
Create Date: 2026-08-22 08:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0005_business_plan'
down_revision = '0004_leads'
branch_labels = None
depends_on = None

PLAN_TYPE = sa.String(length=32)


def upgrade() -> None:
    op.add_column(
        'businesses',
        sa.Column('plan', PLAN_TYPE, nullable=False, server_default='start'),
    )
    op.create_index('ix_businesses_plan', 'businesses', ['plan'])
    op.create_check_constraint(
        'ck_businesses_plan',
        'businesses',
        "plan IN ('start', 'standard', 'pro')",
    )
    # Grandfather everyone who signed up before tiers existed.
    op.execute("UPDATE businesses SET plan = 'pro'")


def downgrade() -> None:
    op.drop_constraint('ck_businesses_plan', 'businesses', type_='check')
    op.drop_index('ix_businesses_plan', table_name='businesses')
    op.drop_column('businesses', 'plan')
