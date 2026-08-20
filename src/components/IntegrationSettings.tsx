/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { 
  Send, 
  Instagram, 
  Cpu, 
  Key, 
  CheckCircle2, 
  AlertCircle,
  ExternalLink,
  ShieldCheck
} from 'lucide-react';
import { useApp } from '../AppContext';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';

export function IntegrationSettings() {
  return (
    <div className="space-y-8 pb-10">
      <div>
        <h1 className="text-3xl font-bold text-white tracking-tight">Integrations</h1>
        <p className="text-slate-400 mt-1">Configure your channel connections and API providers.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Telegram */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="flex flex-row items-center gap-4">
            <div className="p-2 bg-sky-500/10 rounded-lg">
              <Send className="w-6 h-6 text-sky-400" />
            </div>
            <div>
              <CardTitle className="text-white">Telegram Channel</CardTitle>
              <CardDescription>Automate posts to your public channels or groups.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label className="text-slate-400">Bot API Token</Label>
              <div className="flex gap-2">
                <Input type="password" placeholder="712345678:AAF-..." className="bg-slate-950 border-slate-800 font-mono text-xs" />
                <Button variant="outline" className="border-slate-800">Verify</Button>
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-slate-400">Target Channel ID</Label>
              <Input placeholder="@my_awesome_channel" className="bg-slate-950 border-slate-800" />
            </div>
            <div className="flex items-center justify-between p-3 bg-slate-950 rounded-lg border border-slate-800">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-xs text-slate-300">Connection: Active</span>
              </div>
              <Button variant="ghost" size="sm" className="text-indigo-400 text-xs px-2 h-7">Test Ping</Button>
            </div>
          </CardContent>
        </Card>

        {/* Instagram */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="flex flex-row items-center gap-4">
            <div className="p-2 bg-pink-500/10 rounded-lg">
              <Instagram className="w-6 h-6 text-pink-400" />
            </div>
            <div>
              <CardTitle className="text-white">Instagram Business</CardTitle>
              <CardDescription>Connect via Meta Graph API for scheduled posting.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label className="text-slate-400">Long-Lived Access Token</Label>
              <div className="flex gap-2 text-xs">
                <Input type="password" value="EAAZ..." readOnly className="bg-slate-950 border-slate-800 opacity-50" />
                <Button className="bg-indigo-600">Reconnect</Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label className="text-[10px] text-slate-500 uppercase tracking-widest">Account ID</Label>
                <div className="text-sm text-slate-300 font-mono">178414...</div>
              </div>
              <div className="space-y-1">
                <Label className="text-[10px] text-slate-500 uppercase tracking-widest">Webhook</Label>
                <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-[10px]">Healthy</Badge>
              </div>
            </div>
            <p className="text-[10px] text-slate-500 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" /> Token expires in 58 days.
            </p>
          </CardContent>
        </Card>

        {/* AI Providers */}
        <Card className="bg-slate-900 border-slate-800 md:col-span-2">
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle className="text-white flex items-center gap-2">
                  <Cpu className="w-5 h-5 text-indigo-400" /> AI Provider Configuration
                </CardTitle>
                <CardDescription>Manage your LLM and Image generation engine API keys.</CardDescription>
              </div>
              <Badge className="bg-indigo-600">Enterprise Suite</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Key className="w-4 h-4 text-slate-500" />
                      <span className="text-sm font-medium text-slate-200">Gemini 1.5 Pro</span>
                    </div>
                    <Switch checked />
                  </div>
                  <Input type="password" placeholder="AI Studio Secret Key" className="bg-slate-950 border-slate-800" />
                  <p className="text-xs text-slate-500">System-wide default for content generation.</p>
                </div>
                
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <ImageIcon className="w-4 h-4 text-slate-500" />
                      <span className="text-sm font-medium text-slate-200">Flux.1 Pro</span>
                    </div>
                    <Switch checked />
                  </div>
                  <Input type="password" placeholder="Fal.ai / Replicate API Key" className="bg-slate-950 border-slate-800" />
                  <p className="text-xs text-slate-500">Premium image generation for brand visuals.</p>
                </div>
              </div>

              <div className="pt-6 border-t border-slate-800">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-indigo-500/5 rounded-xl border border-indigo-500/10">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-indigo-500/20 flex items-center justify-center">
                      <ShieldCheck className="w-6 h-6 text-indigo-400" />
                    </div>
                    <div>
                      <p className="text-sm font-bold text-white">Security & Rate Limits</p>
                      <p className="text-xs text-slate-400">Keys are encrypted and stored in your secure workspace environment.</p>
                    </div>
                  </div>
                  <Button variant="outline" size="sm" className="border-indigo-500/20 text-indigo-400 hover:bg-indigo-500/10">
                    Audit Logs <ExternalLink className="w-3 h-3 ml-2" />
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ImageIcon(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  );
}
