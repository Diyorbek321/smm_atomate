/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState } from 'react';
import { CheckCircle2, Copy, Link2, Loader2, MessageSquare, XCircle } from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api/client';
import { errorLabel } from './shared';
import type { Credentials, TelegramConnectResult } from '../types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';

/**
 * One field and one button: the admin adds the bot to the channel and its
 * discussion group, types the channel, and the backend asks Telegram for the
 * rest — each requirement comes back as its own ✅ / ❌ line.
 */
interface TelegramConnectProps {
  businessId: string;
  credentials: Credentials | null;
  onConnected: () => void;
}

export function TelegramConnect({ businessId, credentials, onConnected }: TelegramConnectProps) {
  const { addNotification } = useApp();
  const [bot, setBot] = useState('');
  const [channel, setChannel] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TelegramConnectResult | null>(null);

  useEffect(() => {
    setResult(null);
    setChannel('');
    api.businesses
      .telegramBot(businessId)
      .then((data) => setBot(data.username))
      .catch(() => setBot(''));
  }, [businessId]);

  const connect = async () => {
    if (!channel.trim()) return;
    setBusy(true);
    try {
      const data = await api.businesses.connectTelegram(businessId, channel.trim());
      setResult(data);
      if (data.saved) {
        addNotification(
          data.comments_ok ? `${data.title} connected — comments will be answered` : `${data.title} connected (publishing only)`,
          data.comments_ok ? 'success' : 'info',
        );
        onConnected();
      }
    } catch (error) {
      addNotification(errorLabel(error), 'error');
    } finally {
      setBusy(false);
    }
  };

  const copyBot = () => {
    void navigator.clipboard?.writeText(`@${bot}`).then(() => addNotification('Bot username copied', 'info'));
  };

  const connected = Boolean(credentials?.tg_channel_id);
  const commentsOn = Boolean(credentials?.tg_discussion_chat_id);

  return (
    <Card className="md:col-span-2 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
      <CardHeader className="flex flex-row items-center gap-4">
        <div className="p-2 bg-sky-500/10 rounded-lg">
          <Link2 className="w-6 h-6 text-sky-400" />
        </div>
        <div className="flex-1">
          <CardTitle className="text-slate-900 dark:text-white">Connect a Telegram channel</CardTitle>
          <CardDescription>Publishing to the channel and answering its comments, in three steps.</CardDescription>
        </div>
        {connected && (
          <Badge variant="outline" className={commentsOn ? 'text-emerald-500 border-emerald-500/40' : 'text-amber-500 border-amber-500/40'}>
            {commentsOn ? 'Channel + comments' : 'Channel only'}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-5">
        <ol className="space-y-2 text-sm text-slate-600 dark:text-slate-300 list-decimal pl-5">
          <li>
            Add{' '}
            {bot ? (
              <button type="button" onClick={copyBot} className="inline-flex items-center gap-1 font-mono text-sky-500 hover:underline">
                @{bot} <Copy className="w-3 h-3" />
              </button>
            ) : (
              'the platform bot'
            )}{' '}
            to the channel as an <b>admin</b> with “Post messages”.
          </li>
          <li>
            Add the same bot to the channel’s <b>discussion group</b> as an admin (needed to read comments).
          </li>
          <li>Type the channel below and press Connect.</li>
        </ol>

        <div className="flex flex-col sm:flex-row gap-2">
          <Input
            value={channel}
            onChange={(event) => setChannel(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && void connect()}
            placeholder="@channel, t.me/channel or -100…"
            className="bg-slate-50 dark:bg-slate-950"
          />
          <Button onClick={() => void connect()} disabled={busy || !channel.trim()} className="bg-sky-600 hover:bg-sky-700 text-white">
            {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <MessageSquare className="w-4 h-4 mr-2" />}
            Check & connect
          </Button>
        </div>

        {result && (
          <ul className="space-y-2">
            {result.steps.map((step) => (
              <li key={step.key} className="flex items-start gap-2 text-sm">
                {step.ok ? (
                  <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500" />
                ) : (
                  <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-rose-500" />
                )}
                <span className={step.ok ? 'text-slate-700 dark:text-slate-200' : 'text-rose-600 dark:text-rose-400'}>
                  {step.message}
                </span>
              </li>
            ))}
            {!result.saved && (
              <li className="text-xs text-slate-500 pl-6">Nothing was saved. Fix the red step and press Connect again.</li>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
