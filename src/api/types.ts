/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Data contracts mirroring the FastAPI backend (`backend/app/schemas`).
 * Keep these in sync with the Pydantic models — they are the wire format.
 */

// --------------------------------------------------------------------------
// Enums (string unions matching the backend `.value`s)
// --------------------------------------------------------------------------

export const PLANS = ['start', 'standard', 'pro'] as const;
export type Plan = (typeof PLANS)[number];

export const BUSINESS_CATEGORIES = [
  'education',
  'food_beverage',
  'ecommerce',
  'retail',
  'tech',
  'healthcare',
  'real_estate',
  'beauty',
  'other',
] as const;
export type BusinessCategory = (typeof BUSINESS_CATEGORIES)[number];

export const TONES_OF_VOICE = [
  'casual',
  'professional',
  'youthful',
  'bold',
  'humorous',
  'expert',
] as const;
export type ToneOfVoice = (typeof TONES_OF_VOICE)[number];

export const LANGUAGES = ['uz', 'ru', 'en'] as const;
export type Language = (typeof LANGUAGES)[number];

export const CONTENT_PILLARS = ['sales', 'educational', 'social_proof', 'interactive'] as const;
export type ContentPillar = (typeof CONTENT_PILLARS)[number];

export const CONTENT_TYPES = [
  'feed_post',
  'carousel',
  'story',
  'telegram_quiz',
  'reels_script',
  'video_post',
] as const;
export type ContentType = (typeof CONTENT_TYPES)[number];

export const ITEM_STATUSES = [
  'draft',
  'generating',
  'pending_review',
  'approved',
  'rejected',
  'publishing',
  'published',
  'failed',
] as const;
export type ContentItemStatus = (typeof ITEM_STATUSES)[number];

export type ContentPlanStatus =
  | 'draft'
  | 'generating'
  | 'pending_review'
  | 'approved'
  | 'published'
  | 'archived';

export const PLATFORMS = ['telegram', 'instagram', 'both'] as const;
export type Platform = (typeof PLATFORMS)[number];

export type PublishState = 'pending' | 'success' | 'failed' | 'skipped';

export type AdminRole = 'owner' | 'manager' | 'viewer';

export const AGENTS = [
  'strategist',
  'copywriter',
  'visual',
  'editor',
  'onboarding',
  'feedback',
] as const;
export type AgentName = (typeof AGENTS)[number];

// --------------------------------------------------------------------------
// Envelope
// --------------------------------------------------------------------------

export interface PageMeta {
  total: number;
  page: number;
  limit: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiErrorBody | null;
  meta: PageMeta | null;
}

export interface Paged<T> {
  items: T[];
  meta: PageMeta;
}

// --------------------------------------------------------------------------
// Business
// --------------------------------------------------------------------------

export interface BusinessSettings {
  posts_per_week?: number;
  posting_hours?: number[];
  auto_approve?: boolean;
  /** Single capabilities granted above the tier, e.g. { video: true }. */
  plan_overrides?: Partial<
    Record<'instagram' | 'video' | 'video_editing' | 'ai_video' | 'lead_autoreply', boolean>
  >;
  [key: string]: unknown;
}

/** Resolved from the tier by the backend — the dashboard never computes it. */
export interface PlanCapabilities {
  max_posts_per_week: number;
  content_types: ContentType[];
  instagram: boolean;
  video: boolean;
  video_editing: boolean;
  ai_video: boolean;
  lead_autoreply: boolean;
}

export interface Business {
  id: string;
  name: string;
  slug: string | null;
  plan: Plan;
  capabilities: PlanCapabilities;
  category: BusinessCategory;
  tone_of_voice: ToneOfVoice;
  target_audience: string;
  language: Language;
  timezone: string;
  is_active: boolean;
  settings: BusinessSettings;
  created_at: string;
  updated_at: string;
}

export interface BusinessCreate {
  name: string;
  plan: Plan;
  category: BusinessCategory;
  tone_of_voice: ToneOfVoice;
  target_audience?: string;
  language?: Language;
  timezone?: string;
  settings?: BusinessSettings;
}

export type BusinessUpdate = Partial<BusinessCreate> & { is_active?: boolean };

export interface Credentials {
  business_id: string;
  tg_bot_token: string | null;
  tg_channel_id: string | null;
  ig_access_token: string | null;
  ig_account_id: string | null;
  ig_page_id: string | null;
  telegram_enabled: boolean;
  instagram_enabled: boolean;
  telegram_ready: boolean;
  instagram_ready: boolean;
}

export interface CredentialsUpdate {
  tg_bot_token?: string;
  tg_channel_id?: string;
  ig_access_token?: string;
  ig_account_id?: string;
  ig_page_id?: string;
  telegram_enabled?: boolean;
  instagram_enabled?: boolean;
}

export interface CredentialsCheck {
  telegram: { configured: boolean; ok?: boolean; bot?: string; channel?: string; error?: string };
  instagram: {
    configured: boolean;
    ok?: boolean;
    username?: string;
    followers?: number;
    quota?: unknown;
    error?: string;
  };
}

export interface Admin {
  id: string;
  business_id: string;
  telegram_user_id: number;
  full_name: string | null;
  username: string | null;
  role: AdminRole;
  receives_reviews: boolean;
}

// --------------------------------------------------------------------------
// Knowledge base
// --------------------------------------------------------------------------

export interface KnowledgeBase {
  id: string;
  business_id: string;
  key_offerings: Array<Record<string, unknown>>;
  prices: Array<Record<string, unknown>>;
  usps: string[];
  teacher_profiles: Array<Record<string, unknown>>;
  faq: Array<Record<string, unknown>>;
  success_stories: Array<Record<string, unknown>>;
  raw_notes: string;
  phone: string | null;
  telegram_username: string | null;
  instagram_username: string | null;
  website: string | null;
  address: string | null;
  working_hours: string | null;
  brand_colors: Record<string, string>;
  logo_url: string | null;
  banned_topics: string[];
  preferred_hashtags: string[];
  competitors: string[];
  completeness_score: number;
  version: number;
}

export type KnowledgeBaseUpdate = Partial<Omit<KnowledgeBase, 'id' | 'business_id' | 'completeness_score' | 'version'>>;

export interface KnowledgeIngestResult {
  updated_fields: string[];
  completeness: number;
  next_question: string | null;
  summary: string;
  /** Present when the facts came from an uploaded file. */
  filename?: string;
}

// --------------------------------------------------------------------------
// Content
// --------------------------------------------------------------------------

export interface CarouselSlide {
  index: number;
  title?: string;
  body?: string;
  bullets?: string[];
  image_url?: string | null;
}

export interface QuizPayload {
  question?: string;
  answers?: string[];
  correct_option_id?: number;
  explanation?: string;
}

export interface ReelsScript {
  duration_sec?: number;
  voiceover?: string;
  scenes?: Array<{ t?: string; shot?: string; on_screen?: string; voice?: string }>;
}

export interface EditorIssue {
  severity: 'critical' | 'major' | 'minor';
  field: string;
  problem: string;
  suggestion: string;
}

export interface EditorReport {
  approved?: boolean;
  score?: number;
  issues?: EditorIssue[];
  summary?: string;
  visual_warnings?: string[];
}

export interface ContentItem {
  id: string;
  business_id: string;
  content_plan_id: string | null;
  content_type: ContentType;
  pillar: ContentPillar;
  platform: Platform;
  topic: string;
  headline: string;
  hook: string;
  cta: string;
  caption_tg: string;
  caption_ig: string;
  hashtags: string[];
  image_url: string | null;
  image_prompt: string | null;
  carousel_slides: CarouselSlide[];
  options: QuizPayload;
  script: ReelsScript;
  scheduled_at: string;
  published_at: string | null;
  status: ContentItemStatus;
  retry_count: number;
  regeneration_count: number;
  last_error: string | null;
  quality_score: number;
  editor_report: EditorReport;
  tg_state: PublishState;
  ig_state: PublishState;
  tg_message_id: string | null;
  ig_media_id: string | null;
  created_at: string;
}

export interface ContentItemUpdate {
  headline?: string;
  caption_tg?: string;
  caption_ig?: string;
  hashtags?: string[];
  image_prompt?: string;
  scheduled_at?: string;
  platform?: Platform;
  status?: ContentItemStatus;
}

export interface ItemFilters {
  business_id?: string;
  content_plan_id?: string;
  status?: ContentItemStatus;
  content_type?: ContentType;
  pillar?: ContentPillar;
  page?: number;
  limit?: number;
}

export interface ContentPlan {
  id: string;
  business_id: string;
  title: string;
  year: number;
  week_number: number;
  month_number: number;
  starts_on: string;
  ends_on: string;
  status: ContentPlanStatus;
  strategy: { theme?: string; objectives?: string[]; notes?: string; [key: string]: unknown };
  notes: string;
  generation_error: string | null;
  created_at: string;
}

export interface ContentPlanDetail extends ContentPlan {
  items: ContentItem[];
  pillar_counts: Record<string, number>;
}

export interface PublishLogEntry {
  platform: string;
  state: PublishState;
  attempt: number;
  external_id: string | null;
  message: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface FailureEntry {
  item_id: string;
  business_id: string;
  platform: string;
  attempt: number;
  message: string | null;
  created_at: string;
}

// --------------------------------------------------------------------------
// Prompt studio
// --------------------------------------------------------------------------

export interface PromptVersion {
  version: number;
  system_prompt: string;
  saved_at: string;
}

export interface PromptTemplate {
  id: string;
  business_id: string | null;
  name: string;
  agent: AgentName | string;
  pillar: ContentPillar | null;
  system_prompt: string;
  image_style: string;
  aspect_ratio: string;
  negative_prompt: string | null;
  is_active: boolean;
  version: number;
  versions: PromptVersion[];
  usage_count: number;
  engagement_lift: number;
  created_at: string;
  updated_at: string;
}

export interface PromptTemplateCreate {
  business_id?: string | null;
  name: string;
  agent: string;
  pillar?: ContentPillar | null;
  system_prompt: string;
  image_style?: string;
  aspect_ratio?: string;
  negative_prompt?: string | null;
  is_active?: boolean;
}

export type PromptTemplateUpdate = Partial<PromptTemplateCreate>;

// --------------------------------------------------------------------------
// Analytics / generation
// --------------------------------------------------------------------------

export interface UpcomingItem {
  id: string;
  business_id: string;
  title: string;
  content_type: string;
  status: string;
  scheduled_at: string;
}

export interface AnalyticsSummary {
  active_businesses: number;
  total_businesses: number;
  scheduled_today: number;
  pending_review: number;
  published_24h: number;
  failed_24h: number;
  published_total: number;
  approval_rate: number;
  avg_quality_score: number;
  pillar_distribution: Record<string, number>;
  content_type_distribution: Record<string, number>;
  upcoming: UpcomingItem[];
  est_api_cost_usd: number;
}

export interface BusinessAnalytics {
  business_id: string;
  business_name: string;
  items_total: number;
  published: number;
  pending_review: number;
  failed: number;
  approval_rate: number;
  avg_quality_score: number;
  knowledge_completeness: number;
  by_pillar: Record<string, number>;
  last_published_at: string | null;
}

export interface GenerationTask {
  task_id: string | null;
  status: string;
  message: string;
  plan_id: string | null;
  item_ids: string[];
}

export interface GeneratePlanRequest {
  business_id: string;
  starts_on?: string | null;
  horizon_days?: number;
  posts_count?: number | null;
  extra_instructions?: string;
  send_for_review?: boolean;
}

export interface GenerateItemRequest {
  business_id: string;
  content_type?: ContentType;
  pillar?: ContentPillar;
  topic?: string;
  platform?: Platform;
  scheduled_at?: string | null;
  extra_instructions?: string;
  render_image?: boolean;
  send_for_review?: boolean;
}

export interface ProviderStatus {
  gemini: { configured: boolean; fast_model: string; pro_model: string };
  images: { provider: string; configured: boolean };
  transcription: { provider: string; configured: boolean };
  telegram_bot: { configured: boolean };
  meta: { configured: boolean };
  public_base_url: string;
}
