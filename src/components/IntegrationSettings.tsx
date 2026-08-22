/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Building2,
  CheckCircle2,
  Cpu,
  Image as ImageIcon,
  Instagram,
  Key,
  Loader2,
  Mic,
  RefreshCw,
  Save,
  Send,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import { errorLabel } from './shared';
import type { Credentials, CredentialsCheck } from '../types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function IntegrationSettings() {
  const { businesses, selectedBusinessId, selectBusiness, providers, addNotification } = useApp();

  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [check, setCheck] = useState<CredentialsCheck | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);

  // Secrets come back masked, so an empty field means "leave the stored value".
  const [tgToken, setTgToken] = useState('');
  const [tgChannel, setTgChannel] = useState('');
  const [igToken, setIgToken] = useState('');
  const [igAccount, setIgAccount] = useState('');

  const businessItems = Object.fromEntries(businesses.map((business) => [business.id, business.name]));

  useEffect(() => {
    if (!selectedBusinessId) {
      setCredentials(null);
      return;
    }
    setLoading(true);
    setCheck(null);
    api.businesses
      .credentials(selectedBusinessId)
      .then((data) => {
        setCredentials(data);
        setTgToken('');
        setIgToken('');
        setTgChannel(data.tg_channel_id ?? '');
        setIgAccount(data.ig_account_id ?? '');
      })
      .catch((error) => addNotification(errorLabel(error), 'error'))
      .finally(() => setLoading(false));
  }, [selectedBusinessId, addNotification]);

  const save = async () => {
    if (!selectedBusinessId || !credentials) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        tg_channel_id: tgChannel,
        ig_account_id: igAccount,
        telegram_enabled: credentials.telegram_enabled,
        instagram_enabled: credentials.instagram_enabled,
      };
      if (tgToken.trim()) payload.tg_bot_token = tgToken.trim();
      if (igToken.trim()) payload.ig_access_token = igToken.trim();

      const updated = await api.businesses.saveCredentials(selectedBusinessId, payload);
      setCredentials(updated);
      setTgToken('');
      setIgToken('');
      addNotification('Credentials saved (encrypted at rest)', 'success');
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setSaving(false);
    }
  };

  const verify = async () => {
    if (!selectedBusinessId) return;
    setVerifying(true);
    try {
      const result = await api.businesses.verifyCredentials(selectedBusinessId);
      setCheck(result);
      const ok = [result.telegram.ok, result.instagram.ok].filter(Boolean).length;
      addNotification(ok > 0 ? `${ok} channel(s) responded` : 'No channel responded', ok > 0 ? 'success' : 'error');
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setVerifying(false);
    }
  };

  const refreshIgToken = async () => {
    if (!selectedBusinessId) return;
    try {
      const result = await api.businesses.refreshInstagramToken(selectedBusinessId);
      addNotification(
        result.expires_at ? `Token refreshed, expires ${new Date(result.expires_at).toLocaleDateString()}` : 'Token refreshed',
        'success',
      );
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    }
  };

  return (
    <div className="space-y-8 pb-10">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Integrations</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">
            Channel tokens per business, plus the AI providers the backend has configured.
          </p>
        </div>
        <Select value={selectedBusinessId ?? ''} onValueChange={selectBusiness} items={businessItems}>
          <SelectTrigger className="w-[240px] bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
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
      </div>

      {!selectedBusinessId && (
        <Card className="bg-white dark:bg-slate-900 border-dashed border-slate-200 dark:border-slate-800">
          <CardContent className="py-16 text-center text-sm text-slate-500">
            Create a business first — credentials are stored per business.
          </CardContent>
        </Card>
      )}

      {selectedBusinessId && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <CardHeader className="flex flex-row items-center gap-4">
              <div className="p-2 bg-sky-500/10 rounded-lg">
                <Send className="w-6 h-6 text-sky-400" />
              </div>
              <div className="flex-1">
                <CardTitle className="text-slate-900 dark:text-white">Telegram channel</CardTitle>
                <CardDescription>The bot must be an admin of the target channel.</CardDescription>
              </div>
              <Switch
                checked={credentials?.telegram_enabled ?? false}
                onCheckedChange={(value) =>
                  setCredentials((prev) => (prev ? { ...prev, telegram_enabled: value } : prev))
                }
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-slate-500 text-xs uppercase tracking-wider">Bot token</Label>
                <Input
                  type="password"
                  value={tgToken}
                  onChange={(event) => setTgToken(event.target.value)}
                  placeholder={credentials?.tg_bot_token ?? '712345678:AAF-...'}
                  className="bg-slate-50 dark:bg-slate-950 font-mono text-xs"
                />
                {credentials?.tg_bot_token && !tgToken && (
                  <p className="text-[10px] text-slate-500">
                    Stored: {credentials.tg_bot_token} — leave empty to keep it.
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label className="text-slate-500 text-xs uppercase tracking-wider">Channel id</Label>
                <Input
                  value={tgChannel}
                  onChange={(event) => setTgChannel(event.target.value)}
                  placeholder="@my_channel or -100123456789"
                  className="bg-slate-50 dark:bg-slate-950"
                />
              </div>
              <StatusRow
                ready={credentials?.telegram_ready ?? false}
                result={check?.telegram}
                detail={check?.telegram?.bot ? `@${check.telegram.bot} → ${check.telegram.channel ?? '—'}` : undefined}
              />
            </CardContent>
          </Card>

          <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <CardHeader className="flex flex-row items-center gap-4">
              <div className="p-2 bg-pink-500/10 rounded-lg">
                <Instagram className="w-6 h-6 text-pink-400" />
              </div>
              <div className="flex-1">
                <CardTitle className="text-slate-900 dark:text-white">Instagram business</CardTitle>
                <CardDescription>Meta Graph API — needs a public image URL to publish.</CardDescription>
              </div>
              <Switch
                checked={credentials?.instagram_enabled ?? false}
                onCheckedChange={(value) =>
                  setCredentials((prev) => (prev ? { ...prev, instagram_enabled: value } : prev))
                }
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-slate-500 text-xs uppercase tracking-wider">Access token</Label>
                <div className="flex gap-2">
                  <Input
                    type="password"
                    value={igToken}
                    onChange={(event) => setIgToken(event.target.value)}
                    placeholder={credentials?.ig_access_token ?? 'EAAZ...'}
                    className="bg-slate-50 dark:bg-slate-950 font-mono text-xs"
                  />
                  <Button variant="outline" onClick={() => void refreshIgToken()} title="Exchange for a long-lived token">
                    <RefreshCw className="w-4 h-4" />
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <Label className="text-slate-500 text-xs uppercase tracking-wider">IG account id</Label>
                <Input
                  value={igAccount}
                  onChange={(event) => setIgAccount(event.target.value)}
                  placeholder="17841400000000000"
                  className="bg-slate-50 dark:bg-slate-950 font-mono text-xs"
                />
              </div>
              <StatusRow
                ready={credentials?.instagram_ready ?? false}
                result={check?.instagram}
                detail={
                  check?.instagram?.username
                    ? `@${check.instagram.username} · ${check.instagram.followers ?? 0} followers`
                    : undefined
                }
              />
            </CardContent>
          </Card>

          <div className="md:col-span-2 flex flex-col sm:flex-row gap-3">
            <Button
              onClick={() => void save()}
              disabled={saving || loading}
              className="bg-indigo-600 hover:bg-indigo-700 text-white flex-1"
            >
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save credentials
            </Button>
            <Button variant="outline" onClick={() => void verify()} disabled={verifying} className="flex-1">
              {verifying ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <ShieldCheck className="w-4 h-4 mr-2" />
              )}
              Test the connection
            </Button>
          </div>
        </div>
      )}

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
        <CardHeader>
          <CardTitle className="text-slate-900 dark:text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" /> AI providers
          </CardTitle>
          <CardDescription>
            Configured in the backend's <code className="text-[11px]">.env</code> — shown here read-only, so
            keys never reach the browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <ProviderCard
            icon={<Key className="w-4 h-4" />}
            title="Gemini"
            subtitle={providers ? `${providers.gemini.fast_model} / ${providers.gemini.pro_model}` : '—'}
            configured={providers?.gemini.configured ?? false}
          />
          <ProviderCard
            icon={<ImageIcon className="w-4 h-4" />}
            title="Image model"
            subtitle={providers ? providers.images.provider : '—'}
            configured={providers?.images.configured ?? false}
          />
          <ProviderCard
            icon={<Mic className="w-4 h-4" />}
            title="Transcription"
            subtitle={providers ? providers.transcription.provider : '—'}
            configured={providers?.transcription.configured ?? false}
          />
          <ProviderCard
            icon={<Send className="w-4 h-4" />}
            title="System bot"
            subtitle="Approval workflow"
            configured={providers?.telegram_bot.configured ?? false}
          />
        </CardContent>
        {providers && (
          <CardContent className="pt-0">
            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 text-[11px] text-slate-500 flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                Public base URL: <code>{providers.public_base_url}</code>. Instagram downloads images from
                here, so it must be reachable from the internet before IG publishing works.
              </span>
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function StatusRow({
  ready,
  result,
  detail,
}: {
  ready: boolean;
  result?: { configured: boolean; ok?: boolean; error?: string };
  detail?: string;
}) {
  const state = result?.ok === true ? 'ok' : result?.ok === false ? 'error' : ready ? 'ready' : 'missing';
  return (
    <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-950 rounded-lg border border-slate-200 dark:border-slate-800">
      <div className="flex items-center gap-2 min-w-0">
        {state === 'ok' && <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />}
        {state === 'error' && <XCircle className="w-4 h-4 text-rose-500 shrink-0" />}
        {state === 'ready' && <CheckCircle2 className="w-4 h-4 text-sky-500 shrink-0" />}
        {state === 'missing' && <AlertCircle className="w-4 h-4 text-slate-400 shrink-0" />}
        <span className="text-xs text-slate-600 dark:text-slate-300 truncate">
          {state === 'ok' && (detail ?? 'Connection verified')}
          {state === 'error' && (result?.error ?? 'Connection failed')}
          {state === 'ready' && 'Configured — not tested yet'}
          {state === 'missing' && 'Not configured'}
        </span>
      </div>
    </div>
  );
}

function ProviderCard({
  icon,
  title,
  subtitle,
  configured,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  configured: boolean;
}) {
  return (
    <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
          {icon}
          <span className="text-sm font-medium">{title}</span>
        </div>
        <Badge
          variant="outline"
          className={
            configured
              ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px]'
              : 'bg-slate-500/10 text-slate-400 border-slate-500/20 text-[10px]'
          }
        >
          {configured ? 'Ready' : 'Missing key'}
        </Badge>
      </div>
      <p className="text-[11px] text-slate-500 font-mono truncate">{subtitle}</p>
    </div>
  );
}
