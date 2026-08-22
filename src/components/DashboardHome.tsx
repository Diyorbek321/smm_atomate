/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Building2,
  CalendarCheck,
  CheckCircle2,
  Check,
  Clock,
  DollarSign,
  Instagram,
  Loader2,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { useApp } from '../AppContext';
import {
  CONTENT_TYPE_LABELS,
  PILLAR_HEX,
  PILLAR_LABELS,
  STATUS_COLORS,
  STATUS_LABELS,
  formatDateTime,
  formatRelative,
  humanize,
} from '../types';
import type { ContentItem, ContentPillar } from '../types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';

function platformIcon(item: ContentItem) {
  if (item.platform === 'instagram') return <Instagram className="w-4 h-4 text-pink-500" />;
  if (item.platform === 'telegram') return <Send className="w-4 h-4 text-sky-400" />;
  return (
    <span className="flex items-center gap-1">
      <Send className="w-3.5 h-3.5 text-sky-400" />
      <Instagram className="w-3.5 h-3.5 text-pink-500" />
    </span>
  );
}

export function DashboardHome() {
  const {
    summary,
    items,
    plans,
    loading,
    bulkStatus,
    deleteItem,
    refreshAll,
    approvePlan,
    connection,
  } = useApp();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const pipeline = useMemo(
    () =>
      [...items]
        .sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
        .slice(0, 25),
    [items],
  );

  const pillarData = useMemo(
    () =>
      Object.entries(summary.pillar_distribution).map(([pillar, count]) => ({
        pillar: PILLAR_LABELS[pillar as ContentPillar] ?? humanize(pillar),
        count,
        fill: PILLAR_HEX[pillar as ContentPillar] ?? '#6366f1',
      })),
    [summary.pillar_distribution],
  );

  const typeData = useMemo(
    () =>
      Object.entries(summary.content_type_distribution).map(([type, count]) => ({
        type: CONTENT_TYPE_LABELS[type as keyof typeof CONTENT_TYPE_LABELS] ?? humanize(type),
        count,
      })),
    [summary.content_type_distribution],
  );

  const pendingPlan = plans.find((plan) => plan.status === 'pending_review');

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const toggleAll = () =>
    setSelected((prev) => (prev.length === pipeline.length ? [] : pipeline.map((p) => p.id)));

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
      setSelected([]);
    } finally {
      setBusy(false);
    }
  };

  const stats = [
    {
      label: 'Active businesses',
      value: summary.active_businesses,
      hint: `${summary.total_businesses} total`,
      icon: Building2,
      color: 'text-blue-400',
    },
    {
      label: 'Scheduled today',
      value: summary.scheduled_today,
      hint: `${summary.pending_review} awaiting review`,
      icon: CalendarCheck,
      color: 'text-indigo-400',
    },
    {
      label: 'Published (24h)',
      value: summary.published_24h,
      hint: `${summary.published_total} all-time`,
      icon: CheckCircle2,
      color: 'text-emerald-400',
    },
    {
      label: 'Est. AI cost',
      value: `$${summary.est_api_cost_usd.toFixed(2)}`,
      hint: `avg quality ${summary.avg_quality_score.toFixed(1)}/10`,
      icon: DollarSign,
      color: 'text-amber-400',
    },
  ];

  return (
    <div className="space-y-8 pb-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Overview</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Live state of the content pipeline, straight from the backend.
          </p>
        </div>
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => void refreshAll()}
            disabled={loading}
            className="border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4 mr-2" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      {summary.failed_24h > 0 && (
        <div className="flex items-center gap-3 p-4 rounded-xl border border-rose-500/20 bg-rose-500/5">
          <AlertTriangle className="w-5 h-5 text-rose-500 shrink-0" />
          <p className="text-sm text-rose-500">
            <b>{summary.failed_24h}</b> post{summary.failed_24h === 1 ? '' : 's'} failed to publish in the
            last 24 hours. Check System Logs for the reason.
          </p>
        </div>
      )}

      {pendingPlan && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-indigo-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {pendingPlan.title || `${pendingPlan.year}-W${pendingPlan.week_number}`} is waiting for review
              </p>
              <p className="text-xs text-slate-500">
                {pendingPlan.strategy?.theme ?? 'Weekly content plan'} · {pendingPlan.starts_on} →{' '}
                {pendingPlan.ends_on}
              </p>
            </div>
          </div>
          <Button
            onClick={() => void approvePlan(pendingPlan.id)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            <Check className="w-4 h-4 mr-2" /> Approve whole plan
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
          >
            <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                  {stat.label}
                </CardTitle>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-slate-900 dark:text-white">{stat.value}</div>
                <p className="text-[11px] text-slate-500 mt-1">{stat.hint}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="border-b border-slate-200 dark:border-slate-800">
            <CardTitle className="text-lg text-slate-900 dark:text-white">Content pillars</CardTitle>
            <CardDescription className="text-slate-500">
              Target mix is 30% sales · 30% educational · 25% social proof · 15% interactive.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-6">
            <div className="h-[240px] w-full">
              {pillarData.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={pillarData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.15} />
                    <XAxis
                      dataKey="pillar"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 11, fill: '#64748b' }}
                    />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
                    <ChartTooltip
                      cursor={{ fill: '#6366f110' }}
                      contentStyle={{
                        backgroundColor: '#0f172a',
                        border: '1px solid #1e293b',
                        borderRadius: '8px',
                        fontSize: '12px',
                        color: '#f1f5f9',
                      }}
                    />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {pillarData.map((entry) => (
                        <Cell key={entry.pillar} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="No content generated yet" />
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="border-b border-slate-200 dark:border-slate-800">
            <CardTitle className="text-lg text-slate-900 dark:text-white">Formats</CardTitle>
            <CardDescription className="text-slate-500">
              What the agents have produced across every business.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-6">
            <div className="h-[240px] w-full">
              {typeData.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={typeData} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#334155" opacity={0.15} />
                    <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
                    <YAxis
                      type="category"
                      dataKey="type"
                      axisLine={false}
                      tickLine={false}
                      width={90}
                      tick={{ fontSize: 11, fill: '#64748b' }}
                    />
                    <ChartTooltip
                      cursor={{ fill: '#6366f110' }}
                      contentStyle={{
                        backgroundColor: '#0f172a',
                        border: '1px solid #1e293b',
                        borderRadius: '8px',
                        fontSize: '12px',
                        color: '#f1f5f9',
                      }}
                    />
                    <Bar dataKey="count" fill="#6366f1" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="No content generated yet" />
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 relative">
        <CardHeader className="flex flex-row items-center justify-between border-b border-slate-200 dark:border-slate-800">
          <div>
            <CardTitle className="text-lg font-semibold text-slate-900 dark:text-white">
              Content pipeline
            </CardTitle>
            <CardDescription className="text-slate-500">
              Next {pipeline.length} scheduled posts.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <AnimatePresence>
            {selected.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                className="absolute top-[80px] left-0 right-0 z-20 px-6 py-3 bg-indigo-600 flex items-center justify-between"
              >
                <div className="flex items-center gap-4 text-white">
                  <button
                    onClick={() => setSelected([])}
                    className="p-1 hover:bg-white/20 rounded-md transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                  <span className="text-sm font-medium">{selected.length} selected</span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    disabled={busy}
                    onClick={() => void run(() => bulkStatus(selected, 'approved'))}
                    className="bg-white text-indigo-600 hover:bg-slate-100 text-xs h-8"
                  >
                    <Check className="w-3.5 h-3.5 mr-1.5" /> Approve
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() => void run(() => bulkStatus(selected, 'rejected'))}
                    variant="destructive"
                    className="bg-rose-500 hover:bg-rose-600 text-xs h-8 border-none"
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Reject
                  </Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <Table>
            <TableHeader className="border-slate-200 dark:border-slate-800">
              <TableRow className="hover:bg-transparent border-slate-200 dark:border-slate-800">
                <TableHead className="w-[50px] pl-6">
                  <Checkbox
                    checked={selected.length === pipeline.length && pipeline.length > 0}
                    onCheckedChange={toggleAll}
                  />
                </TableHead>
                <TableHead className="text-slate-500">Post</TableHead>
                <TableHead className="text-slate-500">Pillar</TableHead>
                <TableHead className="text-slate-500">Channel</TableHead>
                <TableHead className="text-slate-500">Scheduled</TableHead>
                <TableHead className="text-slate-500 text-right pr-6">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pipeline.length > 0 ? (
                pipeline.map((item) => (
                  <TableRow
                    key={item.id}
                    className="border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <TableCell className="pl-6">
                      <Checkbox checked={selected.includes(item.id)} onCheckedChange={() => toggle(item.id)} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium text-slate-900 dark:text-slate-200">
                          {item.headline || item.topic || 'Untitled'}
                        </span>
                        <span className="text-xs text-slate-500 truncate max-w-[280px]">
                          {item.caption_tg || item.caption_ig}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-slate-500">{PILLAR_LABELS[item.pillar]}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                        {platformIcon(item)}
                        <span className="text-xs">{CONTENT_TYPE_LABELS[item.content_type]}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-slate-500 text-sm">
                      <div className="flex flex-col">
                        <span>{formatDateTime(item.scheduled_at)}</span>
                        <span className="text-[10px] text-slate-400 flex items-center gap-1">
                          <Clock className="w-2.5 h-2.5" /> {formatRelative(item.scheduled_at)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right pr-6">
                      <div className="flex items-center justify-end gap-2">
                        <Badge variant="outline" className={cn('text-[10px]', STATUS_COLORS[item.status])}>
                          {STATUS_LABELS[item.status]}
                        </Badge>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-slate-400 hover:text-rose-500"
                          onClick={() => void deleteItem(item.id)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12 text-slate-500 border-none">
                    {connection === 'offline'
                      ? 'Backend unreachable — start it with `docker compose up -d` in backend/.'
                      : 'Nothing scheduled yet. Add a business, then generate a weekly plan.'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-full w-full flex items-center justify-center text-sm text-slate-500">{label}</div>
  );
}
