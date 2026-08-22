/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  Loader2,
  RefreshCw,
  Shield,
  Zap,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import { PUBLISH_STATE_LABELS, errorLabel, formatDateTime } from './shared';
import type { FailureEntry, PublishLogEntry } from '../types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const WINDOWS = [
  { value: '24', label: 'Last 24 hours' },
  { value: '72', label: 'Last 3 days' },
  { value: '168', label: 'Last 7 days' },
];

const WINDOW_ITEMS = Object.fromEntries(WINDOWS.map((option) => [option.value, option.label]));

export function SystemLogs() {
  const { summary, items, notifications, addNotification } = useApp();

  const [hours, setHours] = useState('24');
  const [failures, setFailures] = useState<FailureEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [itemLogs, setItemLogs] = useState<PublishLogEntry[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFailures(await api.analytics.failures(Number(hours)));
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setLoading(false);
    }
  }, [hours, addNotification]);

  useEffect(() => {
    void load();
  }, [load]);

  const openItemLogs = async (itemId: string) => {
    setSelectedItem(itemId);
    try {
      setItemLogs(await api.items.logs(itemId));
    } catch (error) {
      addNotification(errorLabel(error), 'error');
      setItemLogs([]);
    }
  };

  const download = (format: 'json' | 'csv') => {
    const payload =
      format === 'json'
        ? JSON.stringify(failures, null, 2)
        : [
            'created_at,platform,item_id,attempt,message',
            ...failures.map((entry) =>
              [
                entry.created_at,
                entry.platform,
                entry.item_id,
                entry.attempt,
                `"${(entry.message ?? '').replace(/"/g, "'")}"`,
              ].join(','),
            ),
          ].join('\n');

    const blob = new Blob([payload], {
      type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8;',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `autosmm_failures_${new Date().toISOString().slice(0, 10)}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const failedItems = items.filter((item) => item.status === 'failed');

  return (
    <div className="space-y-6 pb-10">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">System logs</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Publication attempts recorded by the backend, plus this session's activity.
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={hours} onValueChange={setHours} items={WINDOW_ITEMS}>
            <SelectTrigger className="w-[160px] bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button className="bg-indigo-600 hover:bg-indigo-700 text-white">
                  <Download className="w-4 h-4 mr-2" /> Export
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => download('json')} className="cursor-pointer">
                <FileJson className="w-4 h-4 mr-2" /> JSON
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => download('csv')} className="cursor-pointer">
                <FileSpreadsheet className="w-4 h-4 mr-2" /> CSV
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-500" />}
          label="Published (24h)"
          value={summary.published_24h}
          hint={`${summary.published_total} all-time`}
        />
        <MetricCard
          icon={<AlertTriangle className="h-4 w-4 text-rose-500" />}
          label="Failed (24h)"
          value={summary.failed_24h}
          hint={`${failures.length} attempts in window`}
        />
        <MetricCard
          icon={<Shield className="h-4 w-4 text-indigo-500" />}
          label="Approval rate"
          value={`${Math.round(summary.approval_rate * 100)}%`}
          hint={`${summary.pending_review} pending`}
        />
        <MetricCard
          icon={<Database className="h-4 w-4 text-amber-500" />}
          label="Est. AI spend"
          value={`$${summary.est_api_cost_usd.toFixed(2)}`}
          hint={`avg quality ${summary.avg_quality_score.toFixed(1)}/10`}
        />
      </div>

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
        <CardHeader>
          <CardTitle className="text-slate-900 dark:text-white">Failed publications</CardTitle>
          <CardDescription>
            Every failed attempt from `publish_logs`. Click a row to see the full attempt trail.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-200 dark:border-slate-800 hover:bg-transparent">
                <TableHead className="text-slate-500">When</TableHead>
                <TableHead className="text-slate-500">Channel</TableHead>
                <TableHead className="text-slate-500">Attempt</TableHead>
                <TableHead className="text-slate-500">Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {failures.length ? (
                failures.map((entry, index) => (
                  <TableRow
                    key={`${entry.item_id}-${index}`}
                    onClick={() => void openItemLogs(entry.item_id)}
                    className="border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer"
                  >
                    <TableCell className="text-slate-600 dark:text-slate-300 text-sm">
                      {formatDateTime(entry.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">
                        {entry.platform}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-slate-500 text-sm">#{entry.attempt}</TableCell>
                    <TableCell className="text-rose-500 text-xs max-w-[420px] truncate">
                      {entry.message ?? '—'}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center py-10 text-slate-500 border-none">
                    No failed publications in this window. 🎉
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selectedItem && (
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-slate-900 dark:text-white text-base">Attempt trail</CardTitle>
              <CardDescription className="font-mono text-[11px]">{selectedItem}</CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setSelectedItem(null)}>
              Close
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {itemLogs.length ? (
              itemLogs.map((log, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between gap-4 p-3 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <Badge
                      variant="outline"
                      className={
                        log.state === 'success'
                          ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px]'
                          : log.state === 'failed'
                            ? 'bg-rose-500/10 text-rose-500 border-rose-500/20 text-[10px]'
                            : 'text-[10px] text-slate-500'
                      }
                    >
                      {PUBLISH_STATE_LABELS[log.state]}
                    </Badge>
                    <span className="text-xs text-slate-500">{log.platform} · attempt #{log.attempt}</span>
                    <span className="text-xs text-slate-400 truncate">{log.message ?? log.external_id ?? ''}</span>
                  </div>
                  <span className="text-[10px] text-slate-400 shrink-0">
                    {formatDateTime(log.created_at)}
                    {log.duration_ms ? ` · ${log.duration_ms}ms` : ''}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500 py-4 text-center">No attempts recorded yet.</p>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader>
            <CardTitle className="text-slate-900 dark:text-white text-base">Items needing attention</CardTitle>
            <CardDescription>Posts currently in a failed state.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {failedItems.length ? (
              failedItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => void openItemLogs(item.id)}
                  className="w-full text-left p-3 rounded-lg bg-rose-500/5 border border-rose-500/20 hover:border-rose-500/40 transition-colors"
                >
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
                    {item.headline || item.topic}
                  </p>
                  <p className="text-xs text-rose-500 mt-1">{item.last_error}</p>
                  <p className="text-[10px] text-slate-500 mt-1">
                    {item.retry_count} retries · scheduled {formatDateTime(item.scheduled_at)}
                  </p>
                </button>
              ))
            ) : (
              <p className="text-sm text-slate-500 py-6 text-center">Nothing failing right now.</p>
            )}
          </CardContent>
        </Card>

        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader>
            <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
              <Zap className="w-4 h-4 text-indigo-500" /> Session activity
            </CardTitle>
            <CardDescription>What this dashboard did since it was opened.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[320px] overflow-auto">
            {notifications.length ? (
              notifications.map((log) => (
                <div key={log.id} className="flex gap-3 p-2">
                  <span
                    className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${
                      log.type === 'success'
                        ? 'bg-emerald-500'
                        : log.type === 'error'
                          ? 'bg-rose-500'
                          : 'bg-indigo-500'
                    }`}
                  />
                  <div className="min-w-0">
                    <p className="text-xs text-slate-700 dark:text-slate-300 break-words">{log.message}</p>
                    <p className="text-[10px] text-slate-400">{formatDateTime(log.timestamp)}</p>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500 py-6 text-center">No activity yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  hint: string;
}) {
  return (
    <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-xs font-medium text-slate-400 uppercase tracking-wider">{label}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
        <p className="text-[11px] text-slate-500 mt-1">{hint}</p>
      </CardContent>
    </Card>
  );
}
