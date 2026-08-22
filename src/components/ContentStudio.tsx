/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  Building2,
  CalendarRange,
  Check,
  CheckCircle2,
  Instagram,
  Loader2,
  RefreshCw,
  RotateCcw,
  Send,
  Smartphone,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react';
import { useApp } from '../AppContext';
import {
  CONTENT_PILLARS,
  CONTENT_TYPES,
  CONTENT_TYPE_LABELS,
  PILLAR_COLORS,
  PILLAR_LABELS,
  PLATFORMS,
  PLATFORM_LABELS,
  STATUS_COLORS,
  STATUS_LABELS,
  formatDateTime,
  mediaUrl,
} from './shared';
import type { ContentItem, ContentPillar, ContentType, Platform } from '../types';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

const REVIEW_STATUSES: ContentItem['status'][] = ['pending_review', 'approved', 'failed'];

export function ContentStudio() {
  const {
    businesses,
    items,
    selectedBusinessId,
    selectBusiness,
    itemFilters,
    setItemFilters,
    generateItem,
    generatePlan,
    approveItem,
    rejectItem,
    regenerateItem,
    publishItem,
    updateItem,
    refreshItems,
    loading,
  } = useApp();

  const [contentType, setContentType] = useState<ContentType>('feed_post');
  const [pillar, setPillar] = useState<ContentPillar>('sales');
  const [platform, setPlatform] = useState<Platform>('both');
  const [topic, setTopic] = useState('');
  const [instructions, setInstructions] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<'telegram' | 'instagram'>('telegram');
  const [draft, setDraft] = useState<{ caption_tg: string; caption_ig: string; headline: string } | null>(
    null,
  );
  const [editInstruction, setEditInstruction] = useState('');
  const [acting, setActing] = useState(false);

  const businessItems = useMemo(
    () => Object.fromEntries(businesses.map((business) => [business.id, business.name])),
    [businesses],
  );

  const queue = useMemo(
    () =>
      [...items].sort(
        (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
      ),
    [items],
  );

  const selected = queue.find((item) => item.id === selectedId) ?? queue[0] ?? null;

  useEffect(() => {
    if (!selected) {
      setDraft(null);
      return;
    }
    setDraft({
      headline: selected.headline,
      caption_tg: selected.caption_tg,
      caption_ig: selected.caption_ig,
    });
    setPreviewMode(selected.platform === 'instagram' ? 'instagram' : 'telegram');
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    Boolean(selected && draft) &&
    (draft!.headline !== selected!.headline ||
      draft!.caption_tg !== selected!.caption_tg ||
      draft!.caption_ig !== selected!.caption_ig);

  const submitGeneration = async () => {
    if (!selectedBusinessId) return;
    setSubmitting(true);
    try {
      await generateItem({
        business_id: selectedBusinessId,
        content_type: contentType,
        pillar,
        platform: contentType === 'telegram_quiz' ? 'telegram' : platform,
        topic: topic.trim(),
        extra_instructions: instructions.trim(),
        render_image: true,
        send_for_review: true,
      });
      setTopic('');
      setInstructions('');
    } finally {
      setSubmitting(false);
    }
  };

  const act = async (action: () => Promise<void>) => {
    setActing(true);
    try {
      await action();
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 pb-10">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Content Studio</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Ask the agents for content, then review exactly what the audience will see.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={selectedBusinessId ?? ''}
            onValueChange={(value) => selectBusiness(value)}
            items={businessItems}
          >
            <SelectTrigger className="w-[220px] bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
              <Building2 className="w-4 h-4 mr-2 text-indigo-400" />
              <SelectValue placeholder="Select business" />
            </SelectTrigger>
            <SelectContent>
              {businesses.map((business) => (
                <SelectItem key={business.id} value={business.id}>
                  {business.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => void refreshItems()} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* ------------------------------------------------ generation form */}
        <Card className="xl:col-span-4 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 h-fit">
          <CardContent className="p-6 space-y-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Wand2 className="w-4 h-4 text-indigo-400" /> Generate
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-wider text-slate-500">Format</Label>
              <Select
                value={contentType}
                onValueChange={(value) => setContentType(value as ContentType)}
                items={CONTENT_TYPE_LABELS}
              >
                <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONTENT_TYPES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {CONTENT_TYPE_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-wider text-slate-500">Pillar</Label>
              <div className="grid grid-cols-2 gap-2">
                {CONTENT_PILLARS.map((value) => (
                  <button
                    key={value}
                    onClick={() => setPillar(value)}
                    className={cn(
                      'px-3 py-2 rounded-lg border text-xs font-medium transition-all',
                      pillar === value
                        ? PILLAR_COLORS[value]
                        : 'border-slate-200 dark:border-slate-800 text-slate-500 hover:border-slate-300',
                    )}
                  >
                    {PILLAR_LABELS[value]}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-wider text-slate-500">Channel</Label>
              <Select
                value={contentType === 'telegram_quiz' ? 'telegram' : platform}
                onValueChange={(value) => setPlatform(value as Platform)}
                disabled={contentType === 'telegram_quiz'}
                items={PLATFORM_LABELS}
              >
                <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLATFORMS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {PLATFORM_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-wider text-slate-500">Topic</Label>
              <Input
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
                placeholder="Sentabr guruhlariga chegirma"
                className="bg-slate-50 dark:bg-slate-950"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-wider text-slate-500">
                Extra instructions (optional)
              </Label>
              <Textarea
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder="Narxni ta'kidla, 4 ta joy qolganini yoz…"
                className="bg-slate-50 dark:bg-slate-950 min-h-[80px] text-sm"
              />
            </div>

            <Button
              onClick={() => void submitGeneration()}
              disabled={submitting || !selectedBusinessId}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              {submitting ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4 mr-2" />
              )}
              Generate one post
            </Button>

            <Button
              variant="outline"
              disabled={!selectedBusinessId}
              onClick={() =>
                selectedBusinessId &&
                void generatePlan({ business_id: selectedBusinessId, horizon_days: 7 })
              }
              className="w-full"
            >
              <CalendarRange className="w-4 h-4 mr-2" /> Generate a full week
            </Button>

            <p className="text-[11px] text-slate-500 leading-relaxed">
              Generation runs on the backend worker: Strategist → Copywriter → Visual → Editor. Posts land
              here (and in the Telegram bot) as <b>pending review</b>.
            </p>
          </CardContent>
        </Card>

        {/* ------------------------------------------------------ the queue */}
        <Card className="xl:col-span-4 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardContent className="p-0">
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2">
              <Select
                value={itemFilters.status ?? 'all'}
                onValueChange={(value) =>
                  setItemFilters({
                    ...itemFilters,
                    status: value === 'all' ? undefined : (value as ContentItem['status']),
                  })
                }
                items={{ all: 'All statuses', ...STATUS_LABELS }}
              >
                <SelectTrigger className="h-8 text-xs bg-slate-50 dark:bg-slate-950">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {REVIEW_STATUSES.map((status) => (
                    <SelectItem key={status} value={status}>
                      {STATUS_LABELS[status]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Badge variant="outline" className="text-[10px] shrink-0">
                {queue.length}
              </Badge>
            </div>

            <ScrollArea className="h-[560px]">
              {queue.length === 0 ? (
                <div className="p-10 text-center text-sm text-slate-500">
                  Nothing here yet — generate a post or a full week.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-slate-800">
                  {queue.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => setSelectedId(item.id)}
                      className={cn(
                        'w-full text-left p-4 transition-colors',
                        selected?.id === item.id
                          ? 'bg-indigo-500/5 border-l-2 border-l-indigo-500'
                          : 'hover:bg-slate-50 dark:hover:bg-slate-800/40 border-l-2 border-l-transparent',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <span className="text-sm font-medium text-slate-900 dark:text-slate-200 line-clamp-1">
                          {item.headline || item.topic || 'Untitled'}
                        </span>
                        <Badge variant="outline" className={cn('text-[9px] shrink-0', STATUS_COLORS[item.status])}>
                          {STATUS_LABELS[item.status]}
                        </Badge>
                      </div>
                      <p className="text-xs text-slate-500 line-clamp-2 mb-2">
                        {item.caption_tg || item.caption_ig}
                      </p>
                      <div className="flex items-center gap-2 text-[10px] text-slate-400">
                        <span>{CONTENT_TYPE_LABELS[item.content_type]}</span>
                        <span>·</span>
                        <span>{PILLAR_LABELS[item.pillar]}</span>
                        <span>·</span>
                        <span>{formatDateTime(item.scheduled_at)}</span>
                        {item.quality_score > 0 && (
                          <>
                            <span>·</span>
                            <span className="text-indigo-400 font-medium">
                              {item.quality_score.toFixed(1)}/10
                            </span>
                          </>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* ------------------------------------------------ preview + edit */}
        <div className="xl:col-span-4 space-y-4">
          {selected && draft ? (
            <>
              <div className="flex justify-between items-center px-1">
                <span className="text-sm font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                  <Smartphone className="w-4 h-4" /> Preview
                </span>
                <div className="flex bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-0.5 rounded-lg">
                  <button
                    onClick={() => setPreviewMode('telegram')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      previewMode === 'telegram'
                        ? 'bg-white dark:bg-slate-800 text-sky-500 shadow-sm'
                        : 'text-slate-500',
                    )}
                  >
                    <Send className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setPreviewMode('instagram')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      previewMode === 'instagram'
                        ? 'bg-white dark:bg-slate-800 text-pink-500 shadow-sm'
                        : 'text-slate-500',
                    )}
                  >
                    <Instagram className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <PhonePreview
                item={selected}
                mode={previewMode}
                headline={draft.headline}
                caption={previewMode === 'telegram' ? draft.caption_tg : draft.caption_ig}
              />

              <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
                <CardContent className="p-4 space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs uppercase tracking-wider text-slate-500">Headline</Label>
                    <Input
                      value={draft.headline}
                      onChange={(event) => setDraft({ ...draft, headline: event.target.value })}
                      className="bg-slate-50 dark:bg-slate-950"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs uppercase tracking-wider text-slate-500">
                      {previewMode === 'telegram' ? 'Telegram caption' : 'Instagram caption'}
                    </Label>
                    <Textarea
                      value={previewMode === 'telegram' ? draft.caption_tg : draft.caption_ig}
                      onChange={(event) =>
                        setDraft(
                          previewMode === 'telegram'
                            ? { ...draft, caption_tg: event.target.value }
                            : { ...draft, caption_ig: event.target.value },
                        )
                      }
                      className="bg-slate-50 dark:bg-slate-950 min-h-[140px] text-sm"
                    />
                  </div>

                  {dirty && (
                    <Button
                      onClick={() =>
                        void act(() =>
                          updateItem(selected.id, {
                            headline: draft.headline,
                            caption_tg: draft.caption_tg,
                            caption_ig: draft.caption_ig,
                          }),
                        )
                      }
                      disabled={acting}
                      variant="outline"
                      className="w-full"
                    >
                      Save edits
                    </Button>
                  )}

                  <div className="space-y-2">
                    <Label className="text-xs uppercase tracking-wider text-slate-500">
                      Ask the AI to change something
                    </Label>
                    <div className="flex gap-2">
                      <Input
                        value={editInstruction}
                        onChange={(event) => setEditInstruction(event.target.value)}
                        placeholder="Narxni 400 ming qil"
                        className="bg-slate-50 dark:bg-slate-950 text-sm"
                      />
                      <Button
                        variant="outline"
                        disabled={acting}
                        onClick={() =>
                          void act(async () => {
                            await regenerateItem(selected.id, editInstruction, false);
                            setEditInstruction('');
                          })
                        }
                      >
                        <RotateCcw className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2">
                    <Button
                      disabled={acting || selected.status === 'approved'}
                      onClick={() => void act(() => approveItem(selected.id))}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                    >
                      <CheckCircle2 className="w-4 h-4 mr-2" /> Approve
                    </Button>
                    <Button
                      disabled={acting}
                      variant="outline"
                      onClick={() => void act(() => regenerateItem(selected.id, '', true))}
                    >
                      <Sparkles className="w-4 h-4 mr-2" /> Regenerate
                    </Button>
                    <Button
                      disabled={acting}
                      variant="outline"
                      onClick={() => void act(() => publishItem(selected.id))}
                    >
                      <Upload className="w-4 h-4 mr-2" /> Publish now
                    </Button>
                    <Button
                      disabled={acting}
                      variant="outline"
                      onClick={() => void act(() => rejectItem(selected.id))}
                      className="text-rose-500 hover:text-rose-600"
                    >
                      <Trash2 className="w-4 h-4 mr-2" /> Reject
                    </Button>
                  </div>

                  <ItemMeta item={selected} />
                </CardContent>
              </Card>
            </>
          ) : (
            <Card className="bg-white dark:bg-slate-900 border-dashed border-slate-200 dark:border-slate-800">
              <CardContent className="py-24 text-center text-sm text-slate-500">
                Select a post to preview it.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function ItemMeta({ item }: { item: ContentItem }) {
  const issues = item.editor_report?.issues ?? [];
  return (
    <div className="pt-3 border-t border-slate-100 dark:border-slate-800 space-y-2 text-[11px] text-slate-500">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>Quality: <b className="text-indigo-400">{item.quality_score.toFixed(1)}/10</b></span>
        <span>Telegram: {item.tg_state}</span>
        <span>Instagram: {item.ig_state}</span>
        {item.regeneration_count > 0 && <span>Regenerated ×{item.regeneration_count}</span>}
      </div>
      {item.hashtags.length > 0 && (
        <p className="text-sky-500 break-words">{item.hashtags.join(' ')}</p>
      )}
      {item.last_error && <p className="text-rose-500">Error: {item.last_error}</p>}
      {issues.length > 0 && (
        <ul className="space-y-0.5">
          {issues.slice(0, 3).map((issue, index) => (
            <li key={index} className={issue.severity === 'critical' ? 'text-rose-500' : 'text-amber-500'}>
              • {issue.field}: {issue.problem}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface PhonePreviewProps {
  item: ContentItem;
  mode: 'telegram' | 'instagram';
  headline: string;
  caption: string;
}

function PhonePreview({ item, mode, headline, caption }: PhonePreviewProps) {
  const slides = item.carousel_slides?.filter((slide) => slide.image_url) ?? [];
  const image = mediaUrl(item.image_url ?? slides[0]?.image_url ?? null);
  const isStory = item.content_type === 'story' || item.content_type === 'reels_script';

  return (
    <div className="bg-slate-950 rounded-[2.5rem] border-[8px] border-slate-900 overflow-hidden shadow-2xl">
      <div className="h-8 px-6 flex justify-between items-center bg-black/30">
        <span className="text-[10px] font-bold text-white">9:41</span>
        <div className="flex gap-1.5">
          <div className="w-3 h-3 bg-white/20 rounded-full" />
          <div className="w-3 h-3 bg-white/20 rounded-full" />
        </div>
      </div>

      <ScrollArea className="h-[420px]">
        <div className={mode === 'telegram' ? 'p-3' : ''}>
          {mode === 'telegram' ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 bg-sky-500 rounded-full flex items-center justify-center text-white text-[10px] font-bold">
                  A
                </div>
                <div className="flex flex-col">
                  <span className="text-[11px] font-bold text-white">AutoSMM channel</span>
                  <span className="text-[9px] text-slate-500">bot</span>
                </div>
              </div>

              {item.content_type === 'telegram_quiz' ? (
                <QuizPreview item={item} />
              ) : (
                <div className="bg-[#1c242f] rounded-xl overflow-hidden border border-white/5">
                  {image && (
                    <img
                      src={image}
                      alt=""
                      className={cn('w-full object-cover', isStory ? 'aspect-[9/16]' : 'aspect-[4/5]')}
                    />
                  )}
                  <div className="p-3">
                    {headline && <p className="text-white text-xs font-bold mb-1">{headline}</p>}
                    <p className="text-slate-300 text-[11px] leading-relaxed whitespace-pre-wrap">
                      {stripHtml(caption)}
                    </p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-black">
              <div className="p-3 flex items-center gap-2 border-b border-white/5">
                <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-yellow-400 to-purple-600 p-0.5">
                  <div className="w-full h-full rounded-full bg-black" />
                </div>
                <span className="text-[11px] font-bold text-white">autosmm_ai</span>
              </div>
              {image ? (
                <img
                  src={image}
                  alt=""
                  className={cn('w-full object-cover', isStory ? 'aspect-[9/16]' : 'aspect-[4/5]')}
                />
              ) : (
                <div className="aspect-[4/5] flex items-center justify-center text-xs text-slate-600">
                  No image rendered
                </div>
              )}
              <div className="p-3 space-y-2">
                <div className="flex gap-3 text-white text-sm">❤ 🗨 ✈</div>
                <p className="text-slate-200 text-[11px] leading-relaxed whitespace-pre-wrap">
                  <span className="font-bold text-white mr-1">autosmm_ai</span>
                  {stripHtml(caption)}
                </p>
              </div>
            </div>
          )}

          {slides.length > 1 && (
            <div className="flex gap-2 p-3 overflow-x-auto">
              {slides.map((slide) => (
                <img
                  key={slide.index}
                  src={mediaUrl(slide.image_url)}
                  alt=""
                  className="w-16 rounded-md border border-white/10"
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function QuizPreview({ item }: { item: ContentItem }) {
  const quiz = item.options ?? {};
  return (
    <div className="bg-[#1c242f] rounded-xl p-3 border border-white/5 space-y-2">
      <p className="text-white text-xs font-bold">{quiz.question}</p>
      {(quiz.answers ?? []).map((answer, index) => (
        <div
          key={index}
          className={cn(
            'text-[11px] px-2 py-1.5 rounded-lg border',
            index === (quiz.correct_option_id ?? 0)
              ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
              : 'border-white/10 text-slate-300',
          )}
        >
          {answer}
        </div>
      ))}
      {quiz.explanation && <p className="text-[10px] text-slate-500 italic">{quiz.explanation}</p>}
    </div>
  );
}

/** Telegram captions carry `<b>`/`<i>` tags — the preview shows plain text. */
function stripHtml(text: string): string {
  return text.replace(/<[^>]+>/g, '');
}
