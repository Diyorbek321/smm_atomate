"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-20 16:40:40.291119
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Generated with `alembic revision --autogenerate`; reviewed by hand.
    op.create_table('businesses',
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=True),
    sa.Column('category', sa.Enum('education', 'food_beverage', 'ecommerce', 'retail', 'tech', 'healthcare', 'real_estate', 'beauty', 'other', name='business_category', native_enum=False, length=32), nullable=False),
    sa.Column('tone_of_voice', sa.Enum('casual', 'professional', 'youthful', 'bold', 'humorous', 'expert', name='tone_of_voice', native_enum=False, length=32), nullable=False),
    sa.Column('target_audience', sa.Text(), nullable=False),
    sa.Column('language', sa.Enum('uz', 'ru', 'en', name='language', native_enum=False, length=32), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_businesses'))
    )
    op.create_index(op.f('ix_businesses_id'), 'businesses', ['id'], unique=False)
    op.create_index(op.f('ix_businesses_is_active'), 'businesses', ['is_active'], unique=False)
    op.create_index(op.f('ix_businesses_slug'), 'businesses', ['slug'], unique=True)
    op.create_table('business_admins',
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=True),
    sa.Column('username', sa.String(length=80), nullable=True),
    sa.Column('role', sa.Enum('owner', 'manager', 'viewer', name='admin_role', native_enum=False, length=32), nullable=False),
    sa.Column('receives_reviews', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_business_admins_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_admins')),
    sa.UniqueConstraint('business_id', 'telegram_user_id', name='uq_admin_business_tg_user')
    )
    op.create_index(op.f('ix_business_admins_id'), 'business_admins', ['id'], unique=False)
    op.create_index('ix_business_admins_tg_user', 'business_admins', ['telegram_user_id'], unique=False)
    op.create_table('business_credentials',
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('tg_bot_token', sa.String(length=512), nullable=True),
    sa.Column('tg_channel_id', sa.String(length=128), nullable=True),
    sa.Column('tg_discussion_chat_id', sa.String(length=128), nullable=True),
    sa.Column('ig_access_token', sa.String(length=1024), nullable=True),
    sa.Column('ig_account_id', sa.String(length=64), nullable=True),
    sa.Column('ig_page_id', sa.String(length=64), nullable=True),
    sa.Column('ig_token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('telegram_enabled', sa.Boolean(), nullable=False),
    sa.Column('instagram_enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_business_credentials_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_credentials')),
    sa.UniqueConstraint('business_id', name=op.f('uq_business_credentials_business_id'))
    )
    op.create_index(op.f('ix_business_credentials_id'), 'business_credentials', ['id'], unique=False)
    op.create_table('content_plans',
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('week_number', sa.Integer(), nullable=False),
    sa.Column('month_number', sa.Integer(), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'generating', 'pending_review', 'approved', 'published', 'archived', name='content_plan_status', native_enum=False, length=32), nullable=False),
    sa.Column('strategy', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('generation_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_content_plans_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_plans')),
    sa.UniqueConstraint('business_id', 'year', 'week_number', name='uq_plan_business_year_week')
    )
    op.create_index('ix_content_plans_business_status', 'content_plans', ['business_id', 'status'], unique=False)
    op.create_index(op.f('ix_content_plans_id'), 'content_plans', ['id'], unique=False)
    op.create_index(op.f('ix_content_plans_status'), 'content_plans', ['status'], unique=False)
    op.create_table('knowledge_bases',
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('key_offerings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('prices', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('usps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('teacher_profiles', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('faq', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('success_stories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raw_notes', sa.Text(), nullable=False),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('telegram_username', sa.String(length=80), nullable=True),
    sa.Column('instagram_username', sa.String(length=80), nullable=True),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('working_hours', sa.String(length=160), nullable=True),
    sa.Column('brand_colors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('logo_url', sa.String(length=512), nullable=True),
    sa.Column('banned_topics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('preferred_hashtags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('competitors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('completeness_score', sa.Float(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_knowledge_bases_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_bases')),
    sa.UniqueConstraint('business_id', name=op.f('uq_knowledge_bases_business_id'))
    )
    op.create_index(op.f('ix_knowledge_bases_id'), 'knowledge_bases', ['id'], unique=False)
    op.create_table('prompt_templates',
    sa.Column('business_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('pillar', sa.Enum('sales', 'educational', 'social_proof', 'interactive', name='prompt_pillar', native_enum=False, length=32), nullable=True),
    sa.Column('system_prompt', sa.Text(), nullable=False),
    sa.Column('image_style', sa.String(length=64), nullable=False),
    sa.Column('aspect_ratio', sa.String(length=16), nullable=False),
    sa.Column('negative_prompt', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.Column('engagement_lift', sa.Float(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_prompt_templates_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prompt_templates')),
    sa.UniqueConstraint('business_id', 'name', name='uq_prompt_business_name')
    )
    op.create_index(op.f('ix_prompt_templates_agent'), 'prompt_templates', ['agent'], unique=False)
    op.create_index(op.f('ix_prompt_templates_id'), 'prompt_templates', ['id'], unique=False)
    op.create_table('content_items',
    sa.Column('content_plan_id', sa.UUID(), nullable=True),
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('content_type', sa.Enum('feed_post', 'carousel', 'story', 'telegram_quiz', 'reels_script', name='content_type', native_enum=False, length=32), nullable=False),
    sa.Column('pillar', sa.Enum('sales', 'educational', 'social_proof', 'interactive', name='content_pillar', native_enum=False, length=32), nullable=False),
    sa.Column('platform', sa.Enum('telegram', 'instagram', 'both', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('topic', sa.String(length=300), nullable=False),
    sa.Column('headline', sa.String(length=300), nullable=False),
    sa.Column('hook', sa.String(length=300), nullable=False),
    sa.Column('cta', sa.String(length=300), nullable=False),
    sa.Column('caption_tg', sa.Text(), nullable=False),
    sa.Column('caption_ig', sa.Text(), nullable=False),
    sa.Column('hashtags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('image_url', sa.String(length=1024), nullable=True),
    sa.Column('image_prompt', sa.Text(), nullable=True),
    sa.Column('carousel_slides', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('script', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('draft', 'generating', 'pending_review', 'approved', 'rejected', 'publishing', 'published', 'failed', name='content_item_status', native_enum=False, length=32), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('regeneration_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('review_message_id', sa.Integer(), nullable=True),
    sa.Column('review_chat_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=False),
    sa.Column('sent_for_review', sa.Boolean(), nullable=False),
    sa.Column('tg_state', sa.Enum('pending', 'success', 'failed', 'skipped', name='publish_state', native_enum=False, length=32), nullable=False),
    sa.Column('ig_state', sa.Enum('pending', 'success', 'failed', 'skipped', name='publish_state_ig', native_enum=False, length=32), nullable=False),
    sa.Column('tg_message_id', sa.String(length=64), nullable=True),
    sa.Column('ig_media_id', sa.String(length=64), nullable=True),
    sa.Column('quality_score', sa.Float(), nullable=False),
    sa.Column('editor_report', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ai_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_content_items_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['content_plan_id'], ['content_plans.id'], name=op.f('fk_content_items_content_plan_id_content_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_items'))
    )
    op.create_index(op.f('ix_content_items_id'), 'content_items', ['id'], unique=False)
    op.create_index(op.f('ix_content_items_scheduled_at'), 'content_items', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_content_items_status'), 'content_items', ['status'], unique=False)
    op.create_index('ix_items_business_status', 'content_items', ['business_id', 'status'], unique=False)
    op.create_index('ix_items_due', 'content_items', ['status', 'scheduled_at'], unique=False)
    op.create_index('ix_items_plan', 'content_items', ['content_plan_id'], unique=False)
    op.create_table('publish_logs',
    sa.Column('content_item_id', sa.UUID(), nullable=False),
    sa.Column('business_id', sa.UUID(), nullable=False),
    sa.Column('platform', sa.Enum('telegram', 'instagram', 'both', name='log_platform', native_enum=False, length=32), nullable=False),
    sa.Column('state', sa.Enum('pending', 'success', 'failed', 'skipped', name='log_state', native_enum=False, length=32), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_publish_logs_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['content_item_id'], ['content_items.id'], name=op.f('fk_publish_logs_content_item_id_content_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publish_logs'))
    )
    op.create_index(op.f('ix_publish_logs_business_id'), 'publish_logs', ['business_id'], unique=False)
    op.create_index(op.f('ix_publish_logs_id'), 'publish_logs', ['id'], unique=False)
    op.create_index('ix_publish_logs_item', 'publish_logs', ['content_item_id', 'created_at'], unique=False)


def downgrade() -> None:
    # Generated with `alembic revision --autogenerate`; reviewed by hand.
    op.drop_index('ix_publish_logs_item', table_name='publish_logs')
    op.drop_index(op.f('ix_publish_logs_id'), table_name='publish_logs')
    op.drop_index(op.f('ix_publish_logs_business_id'), table_name='publish_logs')
    op.drop_table('publish_logs')
    op.drop_index('ix_items_plan', table_name='content_items')
    op.drop_index('ix_items_due', table_name='content_items')
    op.drop_index('ix_items_business_status', table_name='content_items')
    op.drop_index(op.f('ix_content_items_status'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_scheduled_at'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_id'), table_name='content_items')
    op.drop_table('content_items')
    op.drop_index(op.f('ix_prompt_templates_id'), table_name='prompt_templates')
    op.drop_index(op.f('ix_prompt_templates_agent'), table_name='prompt_templates')
    op.drop_table('prompt_templates')
    op.drop_index(op.f('ix_knowledge_bases_id'), table_name='knowledge_bases')
    op.drop_table('knowledge_bases')
    op.drop_index(op.f('ix_content_plans_status'), table_name='content_plans')
    op.drop_index(op.f('ix_content_plans_id'), table_name='content_plans')
    op.drop_index('ix_content_plans_business_status', table_name='content_plans')
    op.drop_table('content_plans')
    op.drop_index(op.f('ix_business_credentials_id'), table_name='business_credentials')
    op.drop_table('business_credentials')
    op.drop_index('ix_business_admins_tg_user', table_name='business_admins')
    op.drop_index(op.f('ix_business_admins_id'), table_name='business_admins')
    op.drop_table('business_admins')
    op.drop_index(op.f('ix_businesses_slug'), table_name='businesses')
    op.drop_index(op.f('ix_businesses_is_active'), table_name='businesses')
    op.drop_index(op.f('ix_businesses_id'), table_name='businesses')
    op.drop_table('businesses')
