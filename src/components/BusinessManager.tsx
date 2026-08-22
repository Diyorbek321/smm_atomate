/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  Brain,
  Building2,
  CalendarRange,
  Check,
  FileUp,
  Instagram,
  Loader2,
  Lock,
  MoreHorizontal,
  Plus,
  Save,
  Search,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import {
  BUSINESS_CATEGORIES,
  CATEGORY_LABELS,
  LANGUAGES,
  LANGUAGE_LABELS,
  PLANS,
  PLAN_BADGE,
  PLAN_HINTS,
  PLAN_LABELS,
  TONES_OF_VOICE,
  TONE_LABELS,
  errorLabel,
} from './shared';
import type { Business, BusinessCategory, KnowledgeBase, Language, Plan, ToneOfVoice } from '../types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export function BusinessManager() {
  const {
    businesses,
    addBusiness,
    updateBusiness,
    deleteBusiness,
    generatePlan,
    addNotification,
    selectBusiness,
    selectedBusinessId,
  } = useApp();

  const [search, setSearch] = useState('');
  const [planFilter, setPlanFilter] = useState<Plan | 'all'>('all');
  const [planChoice, setPlanChoice] = useState<Plan>('start');
  const [isAddOpen, setAddOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [knowledgeFor, setKnowledgeFor] = useState<Business | null>(null);

  const filtered = businesses.filter(
    (b) =>
      b.name.toLowerCase().includes(search.toLowerCase()) &&
      (planFilter === 'all' || b.plan === planFilter),
  );
  const planCounts = businesses.reduce<Record<string, number>>(
    (acc, b) => ({ ...acc, [b.plan]: (acc[b.plan] ?? 0) + 1 }),
    {},
  );

  const handleAdd = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const created = await addBusiness({
        name: String(form.get('name') ?? '').trim(),
        plan: planChoice,
        category: (form.get('category') as BusinessCategory) || 'education',
        tone_of_voice: (form.get('tone_of_voice') as ToneOfVoice) || 'casual',
        target_audience: String(form.get('target_audience') ?? ''),
        language: (form.get('language') as Language) || 'uz',
        timezone: String(form.get('timezone') ?? 'Asia/Tashkent'),
        settings: {
          posts_per_week: Number(form.get('posts_per_week') ?? 10),
          posting_hours: [9, 13, 18],
          auto_approve: false,
        },
      });
      if (created) {
        setAddOpen(false);
        const notes = String(form.get('knowledge') ?? '').trim();
        if (notes) {
          await api.businesses
            .saveKnowledge(created.id, { raw_notes: notes })
            .catch((error) => addNotification(errorLabel(error), 'error'));
        }
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Businesses</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Every client profile the agents write for.
          </p>
        </div>
        <div className="flex gap-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <Input
              placeholder="Search businesses..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="pl-10 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 w-full md:w-64"
            />
          </div>
          <Button onClick={() => setAddOpen(true)} className="bg-indigo-600 hover:bg-indigo-700 text-white">
            <Plus className="w-4 h-4 mr-2" /> New business
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-slate-500 mr-1">Plan</span>
        {(['all', ...PLANS] as const).map((value) => {
          const selected = planFilter === value;
          const count = value === 'all' ? businesses.length : (planCounts[value] ?? 0);
          return (
            <button
              key={value}
              type="button"
              onClick={() => setPlanFilter(value)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                selected
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-indigo-500/50'
              }`}
            >
              {value === 'all' ? 'All' : PLAN_LABELS[value]}
              <span className={selected ? 'ml-1.5 opacity-80' : 'ml-1.5 text-slate-400'}>{count}</span>
            </button>
          );
        })}
      </div>

      {filtered.length === 0 && (
        <Card className="bg-white dark:bg-slate-900 border-dashed border-slate-200 dark:border-slate-800">
          <CardContent className="py-16 text-center space-y-3">
            <Building2 className="w-8 h-8 mx-auto text-slate-400" />
            <p className="text-sm text-slate-500">
              {businesses.length === 0
                ? 'No businesses yet. Create one, fill its knowledge base, then generate a weekly plan.'
                : planFilter !== 'all' && !search
                  ? `No business on the ${PLAN_LABELS[planFilter]} plan.`
                  : `No business matches "${search}".`}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filtered.map((business) => (
          <BusinessCard
            key={business.id}
            business={business}
            isActive={business.id === selectedBusinessId}
            onSelect={() => selectBusiness(business.id)}
            onKnowledge={() => setKnowledgeFor(business)}
            onDelete={() => void deleteBusiness(business.id)}
            onToggleActive={(value) => void updateBusiness(business.id, { is_active: value })}
            onGeneratePlan={() =>
              void generatePlan({ business_id: business.id, horizon_days: 7, send_for_review: true })
            }
          />
        ))}
      </div>

      <Dialog open={isAddOpen} onOpenChange={setAddOpen}>
        <DialogContent className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Add a business</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAdd} className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" name="name" required minLength={2} className="bg-slate-50 dark:bg-slate-950" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="plan">Plan</Label>
                <Select
                  name="plan"
                  value={planChoice}
                  onValueChange={(value) => setPlanChoice(value as Plan)}
                  items={PLAN_LABELS}
                >
                  <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLANS.map((value) => (
                      <SelectItem key={value} value={value}>
                        {PLAN_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-slate-500">{PLAN_HINTS[planChoice]}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="category">Category</Label>
                <Select name="category" defaultValue="education" items={CATEGORY_LABELS}>
                  <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BUSINESS_CATEGORIES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {CATEGORY_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="tone_of_voice">Tone of voice</Label>
                <Select name="tone_of_voice" defaultValue="casual" items={TONE_LABELS}>
                  <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TONES_OF_VOICE.map((value) => (
                      <SelectItem key={value} value={value}>
                        {TONE_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="language">Language</Label>
                <Select name="language" defaultValue="uz" items={LANGUAGE_LABELS}>
                  <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {LANGUAGE_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="timezone">Timezone</Label>
                <Input
                  id="timezone"
                  name="timezone"
                  defaultValue="Asia/Tashkent"
                  className="bg-slate-50 dark:bg-slate-950"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="posts_per_week">Posts per week</Label>
                <Input
                  id="posts_per_week"
                  name="posts_per_week"
                  type="number"
                  min={4}
                  max={40}
                  defaultValue={10}
                  className="bg-slate-50 dark:bg-slate-950"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="target_audience">Target audience</Label>
              <Input
                id="target_audience"
                name="target_audience"
                placeholder="18-30 yosh, IELTS topshirmoqchi"
                className="bg-slate-50 dark:bg-slate-950"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="knowledge">Starter notes for the knowledge base</Label>
              <Textarea
                id="knowledge"
                name="knowledge"
                className="bg-slate-50 dark:bg-slate-950 min-h-[100px]"
                placeholder="Courses, prices, what makes you different, contacts…"
              />
            </div>

            <Button type="submit" disabled={saving} className="w-full bg-indigo-600 hover:bg-indigo-700 text-white">
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plus className="w-4 h-4 mr-2" />}
              Create profile
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <KnowledgeSheet business={knowledgeFor} onClose={() => setKnowledgeFor(null)} />
    </div>
  );
}

interface BusinessCardProps {
  business: Business;
  isActive: boolean;
  onSelect: () => void;
  onKnowledge: () => void;
  onDelete: () => void;
  onToggleActive: (value: boolean) => void;
  onGeneratePlan: () => void;
}

function BusinessCard({
  business,
  isActive,
  onSelect,
  onKnowledge,
  onDelete,
  onToggleActive,
  onGeneratePlan,
}: BusinessCardProps) {
  const [credentials, setCredentials] = useState<{ telegram: boolean; instagram: boolean } | null>(null);
  const capabilities = business.capabilities;

  useEffect(() => {
    let cancelled = false;
    api.businesses
      .credentials(business.id)
      .then((data) => {
        if (!cancelled) setCredentials({ telegram: data.telegram_ready, instagram: data.instagram_ready });
      })
      .catch(() => {
        if (!cancelled) setCredentials(null);
      });
    return () => {
      cancelled = true;
    };
  }, [business.id]);

  return (
    <Card
      onClick={onSelect}
      className={`bg-white dark:bg-slate-900 overflow-hidden group transition-colors cursor-pointer ${
        isActive
          ? 'border-indigo-500 ring-1 ring-indigo-500/30'
          : 'border-slate-200 dark:border-slate-800 hover:border-indigo-500/50'
      }`}
    >
      <CardContent className="p-0">
        <div className="p-6">
          <div className="flex justify-between items-start mb-4">
            <div className="w-10 h-10 bg-slate-100 dark:bg-slate-800 rounded-lg flex items-center justify-center">
              <Building2 className="w-5 h-5 text-indigo-400" />
            </div>
            <div className="flex items-center gap-2" onClick={(event) => event.stopPropagation()}>
              <Switch checked={business.is_active} onCheckedChange={onToggleActive} />
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button variant="ghost" size="icon" className="text-slate-500">
                      <MoreHorizontal className="w-4 h-4" />
                    </Button>
                  }
                />
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={onKnowledge}>
                    <Brain className="w-4 h-4 mr-2" /> Knowledge base
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onGeneratePlan}>
                    <Sparkles className="w-4 h-4 mr-2" /> Generate weekly plan
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onDelete} className="text-rose-500 focus:text-rose-500">
                    <Trash2 className="w-4 h-4 mr-2" /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-xl font-bold text-slate-900 dark:text-white">{business.name}</h3>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${PLAN_BADGE[business.plan]}`}
            >
              {PLAN_LABELS[business.plan]}
            </span>
          </div>
          <p className="text-sm text-slate-500 mb-4">
            {CATEGORY_LABELS[business.category]} · {TONE_LABELS[business.tone_of_voice]} ·{' '}
            {business.language.toUpperCase()}
          </p>

          <div className="flex gap-2 flex-wrap">
            <ChannelChip
              icon={<Send className="w-3 h-3" />}
              label="Telegram"
              ready={credentials?.telegram ?? false}
            />
            <ChannelChip
              icon={<Instagram className="w-3 h-3" />}
              label="Instagram"
              ready={credentials?.instagram ?? false}
              locked={!business.capabilities?.instagram}
            />
            <Badge variant="outline" className="text-[10px] border-slate-200 dark:border-slate-700 text-slate-500">
              {Math.min(business.settings?.posts_per_week ?? 10, capabilities.max_posts_per_week)}/week
            </Badge>
            {capabilities.video && (
              <Badge variant="outline" className="text-[10px] border-amber-200 dark:border-amber-800 text-amber-600">
                Video
              </Badge>
            )}
          </div>
        </div>

        <div className="px-6 py-4 bg-slate-50 dark:bg-slate-950/50 border-t border-slate-200 dark:border-slate-800 flex justify-between items-center gap-3">
          <span className="text-xs text-slate-500 italic truncate">
            {business.target_audience ? `Target: ${business.target_audience}` : 'No audience set'}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={(event) => {
              event.stopPropagation();
              onKnowledge();
            }}
            className="text-indigo-500 hover:text-indigo-400 p-0 h-auto shrink-0"
          >
            Knowledge <Brain className="w-3 h-3 ml-1" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ChannelChip({
  icon,
  label,
  ready,
  locked = false,
}: {
  icon: React.ReactNode;
  label: string;
  ready: boolean;
  /** The tier does not include this channel — connecting it would not publish. */
  locked?: boolean;
}) {
  return (
    <span
      title={locked ? `${label} is not included in this plan` : undefined}
      className={`px-2 py-1 rounded text-[10px] font-medium border flex items-center gap-1 ${
        locked
          ? 'bg-slate-500/5 text-slate-400 border-slate-500/20 line-through'
          : ready
            ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
            : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
      }`}
    >
      {icon}
      {label}
      {locked ? <Lock className="w-2.5 h-2.5" /> : ready && <Check className="w-2.5 h-2.5" />}
    </span>
  );
}

function KnowledgeSheet({ business, onClose }: { business: Business | null; onClose: () => void }) {
  const { addNotification, generatePlan } = useApp();
  const [knowledge, setKnowledge] = useState<KnowledgeBase | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ingestText, setIngestText] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!business) {
      setKnowledge(null);
      return;
    }
    setLoading(true);
    api.businesses
      .knowledge(business.id)
      .then(setKnowledge)
      .catch((error) => addNotification(errorLabel(error), 'error'))
      .finally(() => setLoading(false));
  }, [business, addNotification]);

  const save = async () => {
    if (!business || !knowledge) return;
    setSaving(true);
    try {
      const updated = await api.businesses.saveKnowledge(business.id, {
        raw_notes: knowledge.raw_notes,
        phone: knowledge.phone,
        telegram_username: knowledge.telegram_username,
        instagram_username: knowledge.instagram_username,
        address: knowledge.address,
        working_hours: knowledge.working_hours,
        usps: knowledge.usps,
        preferred_hashtags: knowledge.preferred_hashtags,
        banned_topics: knowledge.banned_topics,
      });
      setKnowledge(updated);
      addNotification('Knowledge base saved', 'success');
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setSaving(false);
    }
  };

  const ingest = async () => {
    if (!business || !ingestText.trim()) return;
    setIngesting(true);
    try {
      const result = await api.businesses.ingestKnowledge(business.id, ingestText);
      addNotification(
        `${result.summary} (${Math.round(result.completeness * 100)}% complete)`,
        'success',
      );
      setIngestText('');
      setKnowledge(await api.businesses.knowledge(business.id));
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setIngesting(false);
    }
  };

  const uploadFile = async (file: File) => {
    if (!business) return;
    if (file.size > 12 * 1024 * 1024) {
      addNotification('File is too large — 12 MB max', 'error');
      return;
    }
    setUploading(true);
    try {
      const result = await api.businesses.ingestKnowledgeFile(business.id, file);
      addNotification(
        `${result.summary} (${Math.round(result.completeness * 100)}% complete)`,
        'success',
      );
      setKnowledge(await api.businesses.knowledge(business.id));
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const completeness = Math.round((knowledge?.completeness_score ?? 0) * 100);

  return (
    <Sheet open={Boolean(business)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-[560px] bg-white dark:bg-slate-950 border-slate-200 dark:border-slate-800 p-0">
        <SheetHeader className="p-6 border-b border-slate-200 dark:border-slate-800">
          <SheetTitle className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-indigo-400" />
            {business?.name} — knowledge base
          </SheetTitle>
          <div className="flex items-center gap-3 pt-2">
            <div className="flex-1 h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
              <div className="h-full bg-indigo-500 transition-all" style={{ width: `${completeness}%` }} />
            </div>
            <span className="text-xs font-medium text-slate-500">{completeness}%</span>
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-190px)]">
          <div className="p-6 space-y-6">
            {loading && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading…
              </div>
            )}

            {knowledge && (
              <>
                <div className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5 space-y-3">
                  <Label className="text-xs uppercase tracking-wider text-indigo-400">
                    Teach the AI (free-form)
                  </Label>
                  <Textarea
                    value={ingestText}
                    onChange={(event) => setIngestText(event.target.value)}
                    placeholder="IELTS intensiv 600 ming so'm, 3 oy. O'qituvchi Aziz 8.0 ball. Tel +998..."
                    className="bg-white dark:bg-slate-950 min-h-[90px] text-sm"
                  />
                  <Button
                    onClick={() => void ingest()}
                    disabled={ingesting || !ingestText.trim()}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white w-full"
                  >
                    {ingesting ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4 mr-2" />
                    )}
                    Extract facts with the OnboardingAgent
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="application/pdf,.pdf,.txt,.md"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void uploadFile(file);
                    }}
                  />
                  <Button
                    variant="outline"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    className="w-full border-indigo-500/30 text-indigo-500 hover:bg-indigo-500/10"
                  >
                    {uploading ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <FileUp className="w-4 h-4 mr-2" />
                    )}
                    {uploading ? 'Reading the document…' : 'Upload a PDF (price list, brandbook…)'}
                  </Button>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <StatBox label="Offerings" value={knowledge.key_offerings.length} />
                  <StatBox label="Prices" value={knowledge.prices.length} />
                  <StatBox label="USPs" value={knowledge.usps.length} />
                  <StatBox label="Teachers" value={knowledge.teacher_profiles.length} />
                  <StatBox label="FAQ" value={knowledge.faq.length} />
                  <StatBox label="Stories" value={knowledge.success_stories.length} />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <Field
                    label="Phone"
                    value={knowledge.phone ?? ''}
                    onChange={(value) => setKnowledge({ ...knowledge, phone: value })}
                  />
                  <Field
                    label="Telegram username"
                    value={knowledge.telegram_username ?? ''}
                    onChange={(value) => setKnowledge({ ...knowledge, telegram_username: value })}
                  />
                  <Field
                    label="Instagram username"
                    value={knowledge.instagram_username ?? ''}
                    onChange={(value) => setKnowledge({ ...knowledge, instagram_username: value })}
                  />
                  <Field
                    label="Working hours"
                    value={knowledge.working_hours ?? ''}
                    onChange={(value) => setKnowledge({ ...knowledge, working_hours: value })}
                  />
                </div>

                <Field
                  label="Address"
                  value={knowledge.address ?? ''}
                  onChange={(value) => setKnowledge({ ...knowledge, address: value })}
                />

                <ListField
                  label="Selling points (one per line)"
                  values={knowledge.usps}
                  onChange={(values) => setKnowledge({ ...knowledge, usps: values })}
                />
                <ListField
                  label="Brand hashtags (one per line)"
                  values={knowledge.preferred_hashtags}
                  onChange={(values) => setKnowledge({ ...knowledge, preferred_hashtags: values })}
                />
                <ListField
                  label="Topics the AI must avoid"
                  values={knowledge.banned_topics}
                  onChange={(values) => setKnowledge({ ...knowledge, banned_topics: values })}
                />

                <div className="space-y-2">
                  <Label className="text-xs uppercase tracking-wider text-slate-500">Raw notes</Label>
                  <Textarea
                    value={knowledge.raw_notes}
                    onChange={(event) => setKnowledge({ ...knowledge, raw_notes: event.target.value })}
                    className="bg-slate-50 dark:bg-slate-950 min-h-[140px] text-xs font-mono"
                  />
                </div>
              </>
            )}
          </div>
        </ScrollArea>

        <div className="p-4 border-t border-slate-200 dark:border-slate-800 flex gap-2">
          <Button
            variant="outline"
            className="flex-1"
            disabled={!business}
            onClick={() => {
              if (business) void generatePlan({ business_id: business.id, horizon_days: 7 });
            }}
          >
            <CalendarRange className="w-4 h-4 mr-2" /> Generate plan
          </Button>
          <Button
            onClick={() => void save()}
            disabled={saving || !knowledge}
            className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
            Save
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
      <p className="text-lg font-bold text-slate-900 dark:text-white">{value}</p>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs uppercase tracking-wider text-slate-500">{label}</Label>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="bg-slate-50 dark:bg-slate-950"
      />
    </div>
  );
}

function ListField({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs uppercase tracking-wider text-slate-500">{label}</Label>
      <Textarea
        value={values.join('\n')}
        onChange={(event) =>
          onChange(
            event.target.value
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean),
          )
        }
        className="bg-slate-50 dark:bg-slate-950 min-h-[80px] text-xs"
      />
    </div>
  );
}
