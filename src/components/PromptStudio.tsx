/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  Code2,
  History,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  Wand2,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import { CONTENT_PILLARS, PILLAR_LABELS, errorLabel, formatDateTime } from './shared';
import type { ContentPillar, PromptTemplate } from '../types';
import { AGENTS } from '../types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

const AGENT_HINTS: Record<string, string> = {
  strategist: 'Plans the week and enforces the pillar mix.',
  copywriter: 'Writes the Telegram and Instagram captions.',
  visual: 'Writes the Flux image prompt and the card text.',
  editor: 'Reviews the copy and rewrites it when the score is low.',
  onboarding: 'Turns owner answers into structured knowledge.',
  feedback: 'Reads voice corrections and decides what to change.',
};

export function PromptStudio() {
  const {
    templates,
    businesses,
    selectedBusinessId,
    addTemplate,
    updateTemplate,
    rollbackTemplate,
    deleteTemplate,
    addNotification,
  } = useApp();

  const [activeId, setActiveId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState('');
  const [negative, setNegative] = useState('');
  const [saving, setSaving] = useState(false);
  const [isNewOpen, setNewOpen] = useState(false);
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [inspectAgent, setInspectAgent] = useState<string>('copywriter');

  const active = useMemo(
    () => templates.find((template) => template.id === activeId) ?? templates[0] ?? null,
    [templates, activeId],
  );

  useEffect(() => {
    if (!active) {
      setPrompt('');
      setNegative('');
      return;
    }
    setPrompt(active.system_prompt);
    setNegative(active.negative_prompt ?? '');
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // The built-in prompts are the starting point for any override.
  useEffect(() => {
    if (defaults[inspectAgent] !== undefined) return;
    api.prompts
      .default(inspectAgent)
      .then((result) => setDefaults((prev) => ({ ...prev, [inspectAgent]: result.system_prompt })))
      .catch((error) => addNotification(errorLabel(error), 'error'));
  }, [inspectAgent, defaults, addNotification]);

  const dirty = Boolean(
    active && (prompt !== active.system_prompt || negative !== (active.negative_prompt ?? '')),
  );

  const save = async () => {
    if (!active) return;
    setSaving(true);
    try {
      await updateTemplate(active.id, { system_prompt: prompt, negative_prompt: negative || null });
    } finally {
      setSaving(false);
    }
  };

  const createTemplate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const agent = String(form.get('agent') ?? 'copywriter');
    const pillarValue = String(form.get('pillar') ?? 'any');
    await addTemplate({
      name: String(form.get('name') ?? '').trim(),
      agent,
      pillar: pillarValue === 'any' ? null : (pillarValue as ContentPillar),
      business_id: String(form.get('scope') ?? 'global') === 'global' ? null : selectedBusinessId,
      system_prompt: defaults[agent] ?? 'Write high-converting Uzbek social posts.',
      image_style: 'cinematic',
      aspect_ratio: '4:5',
      is_active: true,
    });
    setNewOpen(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Prompt Studio</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Override any agent's system prompt without redeploying the backend.
          </p>
        </div>
        <Button onClick={() => setNewOpen(true)} className="bg-indigo-600 hover:bg-indigo-700 text-white">
          <Plus className="w-4 h-4 mr-2" /> New override
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-4 space-y-4">
          <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                Overrides ({templates.length})
              </CardTitle>
              <CardDescription className="text-xs">
                Resolution order: business+pillar → business → global+pillar → global → built-in.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {templates.length === 0 && (
                <p className="text-xs text-slate-500 py-6 text-center">
                  No overrides yet — every agent uses its built-in prompt.
                </p>
              )}
              {templates.map((template) => (
                <button
                  key={template.id}
                  onClick={() => setActiveId(template.id)}
                  className={cn(
                    'w-full text-left p-3 rounded-lg border transition-all',
                    active?.id === template.id
                      ? 'bg-indigo-600/10 border-indigo-600'
                      : 'bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 hover:border-slate-300',
                  )}
                >
                  <div className="font-medium text-sm text-slate-900 dark:text-slate-100 mb-2">
                    {template.name}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="text-[9px] border-indigo-500/30 text-indigo-400">
                      {template.agent}
                    </Badge>
                    {template.pillar && (
                      <Badge variant="outline" className="text-[9px]">
                        {PILLAR_LABELS[template.pillar]}
                      </Badge>
                    )}
                    <Badge variant="outline" className="text-[9px] text-slate-500">
                      {template.business_id ? 'business' : 'global'}
                    </Badge>
                    <Badge variant="outline" className="text-[9px] text-slate-500">
                      v{template.version} · {template.usage_count} uses
                    </Badge>
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                Built-in prompt
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select value={inspectAgent} onValueChange={setInspectAgent}>
                <SelectTrigger className="bg-slate-50 dark:bg-slate-950">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AGENTS.map((agent) => (
                    <SelectItem key={agent} value={agent}>
                      {agent}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-slate-500">{AGENT_HINTS[inspectAgent]}</p>
              <pre className="max-h-[220px] overflow-auto text-[10px] leading-relaxed p-3 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 text-slate-500 whitespace-pre-wrap">
                {defaults[inspectAgent] ?? 'Loading…'}
              </pre>
              {active && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full text-xs"
                  onClick={() => setPrompt(defaults[inspectAgent] ?? prompt)}
                >
                  Copy into the editor
                </Button>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-8">
          {active ? (
            <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
              <CardHeader>
                <div className="flex justify-between items-start gap-4">
                  <div>
                    <CardTitle className="text-slate-900 dark:text-white flex items-center gap-2">
                      <Code2 className="w-4 h-4 text-indigo-400" /> {active.name}
                    </CardTitle>
                    <CardDescription className="text-slate-500">
                      Applies to the <b>{active.agent}</b> agent
                      {active.pillar ? ` · ${PILLAR_LABELS[active.pillar]} posts` : ''}
                      {active.business_id
                        ? ` · ${businesses.find((b) => b.id === active.business_id)?.name ?? 'one business'}`
                        : ' · all businesses'}
                      .
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="flex items-center gap-2 mr-1">
                      <Switch
                        checked={active.is_active}
                        onCheckedChange={(value) => void updateTemplate(active.id, { is_active: value })}
                      />
                      <span className="text-xs text-slate-500">{active.is_active ? 'On' : 'Off'}</span>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button variant="outline" size="sm">
                            <History className="w-4 h-4 mr-2" /> v{active.version}
                          </Button>
                        }
                      />
                      <DropdownMenuContent align="end" className="w-72">
                        <DropdownMenuLabel>Version history</DropdownMenuLabel>
                        <DropdownMenuSeparator />
                        {active.versions.length ? (
                          [...active.versions].reverse().map((version) => (
                            <DropdownMenuItem
                              key={version.version}
                              onClick={() => void rollbackTemplate(active.id, version.version)}
                              className="flex flex-col items-start gap-1 p-3 cursor-pointer"
                            >
                              <div className="flex items-center justify-between w-full">
                                <span className="text-[10px] font-bold text-indigo-400">
                                  v{version.version} · {formatDateTime(version.saved_at)}
                                </span>
                                <RotateCcw className="w-3 h-3 opacity-40" />
                              </div>
                              <p className="text-[11px] text-slate-500 line-clamp-2">
                                {version.system_prompt}
                              </p>
                            </DropdownMenuItem>
                          ))
                        ) : (
                          <div className="p-4 text-center text-xs text-slate-500">
                            No previous versions
                          </div>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void deleteTemplate(active.id)}
                      className="text-rose-500"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-slate-500 text-xs uppercase tracking-wider">
                    System instruction
                  </Label>
                  <Textarea
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    className="bg-slate-50 dark:bg-slate-950 min-h-[340px] font-mono text-xs leading-relaxed"
                  />
                </div>

                {active.agent === 'visual' && (
                  <div className="space-y-2">
                    <Label className="text-slate-500 text-xs uppercase tracking-wider">
                      Negative prompt
                    </Label>
                    <Textarea
                      value={negative}
                      onChange={(event) => setNegative(event.target.value)}
                      placeholder="text, watermark, distorted faces…"
                      className="bg-slate-50 dark:bg-slate-950 text-xs"
                    />
                  </div>
                )}

                <div className="flex justify-between items-center pt-2">
                  <span className="text-[11px] text-slate-500">
                    Saving snapshots the current version so you can roll back.
                  </span>
                  <Button
                    onClick={() => void save()}
                    disabled={!dirty || saving}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white"
                  >
                    {saving ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4 mr-2" />
                    )}
                    Save as v{active.version + 1}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="bg-white dark:bg-slate-900 border-dashed border-slate-200 dark:border-slate-800">
              <CardContent className="py-24 text-center space-y-3">
                <Wand2 className="w-8 h-8 mx-auto text-slate-400" />
                <p className="text-sm text-slate-500">
                  Create an override to tune how an agent writes.
                </p>
                <Button onClick={() => setNewOpen(true)} variant="outline">
                  <Plus className="w-4 h-4 mr-2" /> New override
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Dialog open={isNewOpen} onOpenChange={setNewOpen}>
        <DialogContent className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>New prompt override</DialogTitle>
          </DialogHeader>
          <form onSubmit={createTemplate} className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="prompt-name">Name</Label>
              <Input id="prompt-name" name="name" required minLength={2} placeholder="Sales tone v2" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="prompt-agent">Agent</Label>
              <Select name="agent" defaultValue="copywriter">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AGENTS.map((agent) => (
                    <SelectItem key={agent} value={agent}>
                      {agent}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="prompt-pillar">Pillar</Label>
              <Select name="pillar" defaultValue="any" items={{ any: 'Any pillar', ...PILLAR_LABELS }}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any pillar</SelectItem>
                  {CONTENT_PILLARS.map((pillar) => (
                    <SelectItem key={pillar} value={pillar}>
                      {PILLAR_LABELS[pillar]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="prompt-scope">Scope</Label>
              <Select
                name="scope"
                defaultValue="global"
                items={{
                  global: 'All businesses',
                  business: businesses.find((b) => b.id === selectedBusinessId)?.name ?? 'Selected business',
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">All businesses</SelectItem>
                  <SelectItem value="business" disabled={!selectedBusinessId}>
                    {businesses.find((b) => b.id === selectedBusinessId)?.name ?? 'Selected business'}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white">
              <Sparkles className="w-4 h-4 mr-2" /> Create from the built-in prompt
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
