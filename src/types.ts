/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * The dashboard speaks the backend's language directly — these are re-exports
 * of the API contracts plus the labels used to render them.
 */

export * from './api/types';

import type {
  BusinessCategory,
  Plan,
  ContentItemStatus,
  ContentPillar,
  ContentType,
  Language,
  Platform,
  PublishState,
  ToneOfVoice,
} from './api/types';

export const PLAN_LABELS: Record<Plan, string> = {
  start: 'Start',
  standard: 'Standard',
  pro: 'Pro',
};

/** One line per tier, shown while choosing a plan for a new client. */
export const PLAN_HINTS: Record<Plan, string> = {
  start: 'Telegram only · up to 4 posts/week · posts and quizzes',
  standard: 'Adds Instagram, carousels, stories and the video editor · up to 8 posts/week',
  pro: 'Everything: video, reels, AI clips, lead auto-reply · up to 20 posts/week',
};

/** Badge colours: the tier should be readable at a glance in the list. */
export const PLAN_BADGE: Record<Plan, string> = {
  start: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  standard: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300',
  pro: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
};

export const CATEGORY_LABELS: Record<BusinessCategory, string> = {
  education: 'Education',
  food_beverage: 'Food & Beverage',
  ecommerce: 'E-commerce',
  retail: 'Retail',
  tech: 'Tech',
  healthcare: 'Healthcare',
  real_estate: 'Real Estate',
  beauty: 'Beauty',
  other: 'Other',
};

export const TONE_LABELS: Record<ToneOfVoice, string> = {
  casual: 'Casual',
  professional: 'Professional',
  youthful: 'Youthful / Gen-Z',
  bold: 'Bold',
  humorous: 'Humorous',
  expert: 'Expert',
};

export const LANGUAGE_LABELS: Record<Language, string> = {
  uz: "O'zbek",
  ru: 'Русский',
  en: 'English',
};

export const PILLAR_LABELS: Record<ContentPillar, string> = {
  sales: 'Sales',
  educational: 'Educational',
  social_proof: 'Social proof',
  interactive: 'Interactive',
};

/** Tailwind classes per pillar, used for badges and chart segments. */
export const PILLAR_COLORS: Record<ContentPillar, string> = {
  sales: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  educational: 'bg-sky-500/10 text-sky-500 border-sky-500/20',
  social_proof: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  interactive: 'bg-violet-500/10 text-violet-500 border-violet-500/20',
};

export const PILLAR_HEX: Record<ContentPillar, string> = {
  sales: '#f59e0b',
  educational: '#0ea5e9',
  social_proof: '#10b981',
  interactive: '#8b5cf6',
};

export const CONTENT_TYPE_LABELS: Record<ContentType, string> = {
  feed_post: 'Feed post',
  carousel: 'Carousel',
  story: 'Story',
  telegram_quiz: 'Telegram quiz',
  reels_script: 'Reels script',
  video_post: 'Edited video',
};

export const STATUS_LABELS: Record<ContentItemStatus, string> = {
  draft: 'Draft',
  generating: 'Generating',
  pending_review: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  publishing: 'Publishing',
  published: 'Published',
  failed: 'Failed',
};

export const STATUS_COLORS: Record<ContentItemStatus, string> = {
  draft: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  generating: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  pending_review: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  approved: 'bg-sky-500/10 text-sky-500 border-sky-500/20',
  rejected: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  publishing: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  published: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  failed: 'bg-rose-500/10 text-rose-500 border-rose-500/20',
};

export const PLATFORM_LABELS: Record<Platform, string> = {
  telegram: 'Telegram',
  instagram: 'Instagram',
  both: 'Telegram + Instagram',
};

export const PUBLISH_STATE_LABELS: Record<PublishState, string> = {
  pending: 'Pending',
  success: 'Sent',
  failed: 'Failed',
  skipped: 'Skipped',
};

/** `feed_post` → `Feed post`, for values not covered by a map. */
export function humanize(value: string): string {
  const text = value.replace(/_/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return '—';
  const diff = new Date(value).getTime() - Date.now();
  const minutes = Math.round(diff / 60_000);
  const abs = Math.abs(minutes);
  if (abs < 60) return minutes >= 0 ? `in ${abs}m` : `${abs}m ago`;
  const hours = Math.round(abs / 60);
  if (hours < 24) return minutes >= 0 ? `in ${hours}h` : `${hours}h ago`;
  const days = Math.round(hours / 24);
  return minutes >= 0 ? `in ${days}d` : `${days}d ago`;
}
