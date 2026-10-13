/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useMemo, useState } from 'react';
import { Building2, Check, Clapperboard, Copy, Loader2, Sparkles } from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import type { VideoPromptAspect, VideoPromptFormat, VideoPromptResult } from '../api/types';
import { errorLabel } from './shared';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const FORMAT_LABELS: Record<VideoPromptFormat, string> = {
  showreel: 'Shou-ril (brend imidji)',
  promo: 'Promo (taklif / aksiya)',
  explainer: 'Tushuntiruvchi',
  elon: "E'lon / yangilik",
  natija: 'Natija va isbot',
};

const ASPECT_LABELS: Record<VideoPromptAspect, string> = {
  '9:16': '9:16 — Reels / Shorts',
  '1:1': '1:1 — kvadrat',
  '4:5': '4:5 — Instagram feed',
  '16:9': '16:9 — YouTube',
};

export function VideoPromptStudio() {
  const { businesses, selectedBusinessId, selectBusiness, addNotification } = useApp();
  const [format, setFormat] = useState<VideoPromptFormat>('promo');
  const [aspect, setAspect] = useState<VideoPromptAspect>('9:16');
  const [duration, setDuration] = useState(15);
  const [goal, setGoal] = useState('');
  const [extra, setExtra] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VideoPromptResult | null>(null);
  const [copied, setCopied] = useState(false);

  const businessItems = useMemo(
    () => Object.fromEntries(businesses.map((business) => [business.id, business.name])),
    [businesses],
  );

  const generate = async () => {
    if (!selectedBusinessId) return;
    setBusy(true);
    setCopied(false);
    try {
      const data = await api.generate.videoPrompt({
        business_id: selectedBusinessId,
        format,
        aspect,
        duration,
        goal,
        extra,
      });
      setResult(data);
      if (data.fallback) {
        addNotification("Model javob bermadi — profil asosidagi zaxira prompt berildi", 'info');
      }
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.prompt);
      setCopied(true);
    } catch {
      addNotification('Nusxa olinmadi — matnni qo\'lda belgilang', 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">Video Prompt</h1>
          <p className="text-sm text-slate-500 mt-1">
            Biznes profili va brend kit asosida HyperFrames uchun tayyor video prompt.
          </p>
        </div>
        <Select
          value={selectedBusinessId ?? ''}
          onValueChange={(value) => selectBusiness(value)}
          items={businessItems}
        >
          <SelectTrigger className="w-[220px] bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <Building2 className="w-4 h-4 mr-2 text-indigo-400" />
            <SelectValue placeholder="Biznesni tanlang" />
          </SelectTrigger>
          <SelectContent>
            {businesses.map((business) => (
              <SelectItem key={business.id} value={business.id}>
                {business.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <Card className="xl:col-span-4 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 h-fit">
          <CardContent className="p-6 space-y-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Clapperboard className="w-4 h-4 text-indigo-500" />
              Rolik parametrlari
            </div>

            <div className="space-y-2">
              <Label>Format</Label>
              <Select value={format} onValueChange={(v) => setFormat(v as VideoPromptFormat)} items={FORMAT_LABELS}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(FORMAT_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>O'lcham</Label>
                <Select value={aspect} onValueChange={(v) => setAspect(v as VideoPromptAspect)} items={ASPECT_LABELS}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(ASPECT_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>{label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Davomiylik (s)</Label>
                <Input
                  type="number"
                  min={6}
                  max={60}
                  value={duration}
                  onChange={(e) => setDuration(Math.max(6, Math.min(60, Number(e.target.value) || 15)))}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Maqsad</Label>
              <Textarea
                rows={3}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="Sentabr IELTS guruhiga yozilish"
              />
            </div>

            <div className="space-y-2">
              <Label>Qo'shimcha talab (ixtiyoriy)</Label>
              <Textarea
                rows={2}
                value={extra}
                onChange={(e) => setExtra(e.target.value)}
                placeholder="Logotip oxirida chiqsin, narx ko'rsatilmasin"
              />
            </div>

            <Button className="w-full" onClick={() => void generate()} disabled={busy || !selectedBusinessId}>
              {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
              Prompt yozish
            </Button>
          </CardContent>
        </Card>

        <Card className="xl:col-span-8 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardContent className="p-6 space-y-4">
            {result ? (
              <>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-white">
                      {result.concept.title || 'Video prompt'}
                    </div>
                    {result.concept.concept && (
                      <p className="text-xs text-slate-500 mt-1">{result.concept.concept}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {result.fallback && <Badge variant="outline">zaxira</Badge>}
                    <Button variant="outline" size="sm" onClick={() => void copy()}>
                      {copied ? <Check className="w-4 h-4 mr-1" /> : <Copy className="w-4 h-4 mr-1" />}
                      {copied ? 'Nusxa olindi' : 'Nusxa olish'}
                    </Button>
                  </div>
                </div>
                {result.unverified.length > 0 && (
                  <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
                    Bilim bazasida yo'q raqamlar: {result.unverified.join(', ')} — promptda belgilandi, tekshiring.
                  </div>
                )}
                <Textarea
                  className="min-h-[520px] font-mono text-xs leading-relaxed"
                  value={result.prompt}
                  onChange={(e) => setResult({ ...result, prompt: e.target.value })}
                />
              </>
            ) : (
              <div className="min-h-[520px] flex flex-col items-center justify-center text-center text-slate-500 gap-2">
                <Clapperboard className="w-8 h-8 opacity-40" />
                <p className="text-sm">Parametrlarni tanlang va «Prompt yozish» ni bosing.</p>
                <p className="text-xs max-w-md">
                  Tayyor matnni Claude Code'ga joylang — u HyperFrames bilan MP4 render qiladi.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
