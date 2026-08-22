/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { 
  LayoutDashboard, 
  Building2, 
  Wand2, 
  Calendar, 
  Settings2, 
  Terminal,
  Zap,
  Sun,
  Moon
} from 'lucide-react';
import { useApp } from '../../AppContext';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Switch } from '@/components/ui/switch';

interface SidebarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'businesses', label: 'Businesses', icon: Building2 },
  { id: 'prompts', label: 'AI Prompt Studio', icon: Wand2 },
  { id: 'planner', label: 'Content Planner', icon: Calendar },
  { id: 'integrations', label: 'Integrations', icon: Settings2 },
  { id: 'logs', label: 'System Logs', icon: Terminal },
];

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  const { theme, toggleTheme, summary, connection, providers } = useApp();

  const status =
    connection === 'offline'
      ? { label: 'Backend offline', detail: 'Cannot reach the API', dot: 'bg-rose-500' }
      : providers?.gemini.configured
        ? { label: 'Agents ready', detail: providers.gemini.fast_model, dot: 'bg-emerald-500' }
        : { label: 'Connected', detail: 'No GEMINI_API_KEY set', dot: 'bg-amber-500' };

  return (
    <div className="flex flex-col w-64 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-slate-500 dark:text-slate-400 h-screen overflow-hidden">
      <div className="p-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-slate-900 dark:text-white text-lg tracking-tight">AutoSMM AI</span>
        </div>
        <button 
          onClick={toggleTheme}
          className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-900 rounded-md transition-colors"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-600" />}
        </button>
      </div>

      <ScrollArea className="flex-1 min-h-0 px-4">
        <div className="space-y-1 py-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={cn(
                "flex items-center gap-3 w-full px-3 py-2 rounded-md transition-colors",
                activeTab === item.id 
                  ? "bg-slate-900 text-indigo-400 shadow-sm" 
                  : "hover:bg-slate-900/50 hover:text-slate-200"
              )}
            >
              <item.icon className="w-4 h-4" />
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          ))}
        </div>
      </ScrollArea>

      <div className="mt-auto p-4 space-y-4">
        <div className="bg-slate-100/60 dark:bg-slate-900/50 rounded-lg p-4 border border-slate-200 dark:border-slate-800 space-y-2">
          <div className="flex justify-between text-xs">
            <span>Pending review</span>
            <span className="text-amber-500 font-medium">{summary.pending_review}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span>Published (24h)</span>
            <span className="text-emerald-500 font-medium">{summary.published_24h}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span>Est. AI spend</span>
            <span className="text-indigo-400 font-medium">${summary.est_api_cost_usd.toFixed(2)}</span>
          </div>
        </div>

        <Separator className="bg-slate-200 dark:bg-slate-800" />

        <div className="flex items-center gap-3 px-2">
          <Avatar className="w-8 h-8 border border-slate-200 dark:border-slate-800">
            <AvatarFallback className="bg-indigo-950 text-indigo-400 text-xs">AD</AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
              {status.label}
            </p>
            <p className="text-xs text-slate-500 truncate">{status.detail}</p>
          </div>
          <span className={cn('w-2 h-2 rounded-full shrink-0', status.dot)} />
        </div>
      </div>
    </div>
  );
}
