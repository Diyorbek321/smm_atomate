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
  User,
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
  const { theme, toggleTheme } = useApp();

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

      <ScrollArea className="flex-1 px-4">
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
        <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-800">
          <div className="flex justify-between text-xs mb-2">
            <span>API Credits</span>
            <span className="text-indigo-400">84% used</span>
          </div>
          <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
            <div className="bg-indigo-600 h-full w-[84%]" />
          </div>
          <p className="text-[10px] mt-2 text-slate-500">Resetting in 12 days</p>
        </div>

        <Separator className="bg-slate-800" />

        <div className="flex items-center gap-3 px-2">
          <Avatar className="w-8 h-8 border border-slate-800">
            <AvatarFallback className="bg-indigo-950 text-indigo-400 text-xs">AD</AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200 truncate">Admin Profile</p>
            <p className="text-xs text-slate-500 truncate">admin@autosmm.ai</p>
          </div>
          <button className="p-1 hover:bg-slate-800 rounded-md">
            <User className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
