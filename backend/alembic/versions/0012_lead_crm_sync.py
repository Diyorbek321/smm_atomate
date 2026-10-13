"""leads remember whether the client's CRM has them

Revision ID: 0012_lead_crm_sync
Revises: 0011_instagram_leads
Create Date: 2026-10-13 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0012_lead_crm_sync'
down_revision = '0011_instagram_leads'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('crm_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leads', sa.Column('crm_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('leads', sa.Column('crm_error', sa.String(length=255), nullable=True))
    # The retry sweep asks "what has a phone and is not in the CRM yet".
    op.create_index('ix_leads_crm_pending', 'leads', ['crm_synced_at', 'crm_attempts'])


def downgrade() -> None:
    op.drop_index('ix_leads_crm_pending', table_name='leads')
    op.drop_column('leads', 'crm_error')
    op.drop_column('leads', 'crm_attempts')
    op.drop_column('leads', 'crm_synced_at')
