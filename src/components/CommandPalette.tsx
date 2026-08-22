/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { Search, Building2, Calendar, Wand2, Command } from 'lucide-react';
import { useApp } from '../AppContext';
import { CATEGORY_LABELS, PLATFORM_LABELS } from './shared';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (tab: string) => void;
}

export function CommandPalette({ open, onOpenChange, onSelect }: CommandPaletteProps) {
  const { businesses, items, templates } = useApp();
  const [search, setSearch] = useState('');

  const filteredBusinesses = businesses.filter(b => b.name.toLowerCase().includes(search.toLowerCase())).slice(0, 3);
  const filteredPosts = items
    .filter(item => `${item.headline} ${item.topic}`.toLowerCase().includes(search.toLowerCase()))
    .slice(0, 3);
  const filteredTemplates = templates.filter(t => t.name.toLowerCase().includes(search.toLowerCase())).slice(0, 3);

  useEffect(() => {
    if (!open) setSearch('');
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="p-0 border-slate-800 bg-slate-900 overflow-hidden sm:max-w-[550px] top-[20%] translate-y-0">
        <div className="flex items-center border-b border-slate-800 px-4 py-3">
          <Search className="w-4 h-4 text-slate-500 mr-3" />
          <Input 
            placeholder="Search everything... (Businesses, Content, Templates)" 
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border-none bg-transparent focus-visible:ring-0 text-slate-200 h-8 p-0 placeholder:text-slate-600"
            autoFocus
          />
          <div className="flex items-center gap-1 ml-auto">
            <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-400 font-mono">ESC</kbd>
          </div>
        </div>
        
        <ScrollArea className="max-h-[300px]">
          <div className="p-2 space-y-4">
            {search === '' && (
              <div className="px-2 py-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                Quick Navigation
              </div>
            )}
            
            <div className="space-y-1">
              {filteredBusinesses.map(b => (
                <button 
                  key={b.id}
                  onClick={() => { onSelect('businesses'); onOpenChange(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-slate-800 text-left transition-colors group"
                >
                  <Building2 className="w-4 h-4 text-slate-500 group-hover:text-indigo-400" />
                  <div className="flex-1 overflow-hidden">
                    <p className="text-sm text-slate-200 truncate">{b.name}</p>
                    <p className="text-[10px] text-slate-500 truncate">{CATEGORY_LABELS[b.category]}</p>
                  </div>
                  <Badge className="bg-slate-950 text-[9px] h-4">Business</Badge>
                </button>
              ))}

              {filteredPosts.map(p => (
                <button 
                  key={p.id}
                  onClick={() => { onSelect('planner'); onOpenChange(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-slate-800 text-left transition-colors group"
                >
                  <Calendar className="w-4 h-4 text-slate-500 group-hover:text-indigo-400" />
                  <div className="flex-1 overflow-hidden">
                    <p className="text-sm text-slate-200 truncate">{p.headline || p.topic}</p>
                    <p className="text-[10px] text-slate-500 truncate">{PLATFORM_LABELS[p.platform]}</p>
                  </div>
                  <Badge className="bg-slate-950 text-[9px] h-4">Post</Badge>
                </button>
              ))}

              {filteredTemplates.map(t => (
                <button 
                  key={t.id}
                  onClick={() => { onSelect('prompts'); onOpenChange(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-slate-800 text-left transition-colors group"
                >
                  <Wand2 className="w-4 h-4 text-slate-500 group-hover:text-indigo-400" />
                  <div className="flex-1 overflow-hidden">
                    <p className="text-sm text-slate-200 truncate">{t.name}</p>
                    <p className="text-[10px] text-slate-500 truncate">{t.agent}</p>
                  </div>
                  <Badge className="bg-slate-950 text-[9px] h-4">Template</Badge>
                </button>
              ))}
            </div>

            {search !== '' && filteredBusinesses.length === 0 && filteredPosts.length === 0 && filteredTemplates.length === 0 && (
              <div className="py-8 text-center text-slate-500 text-sm">
                No results found for "{search}"
              </div>
            )}
          </div>
        </ScrollArea>
        <div className="p-3 border-t border-slate-800 bg-slate-950/50 flex justify-end gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><Command className="w-3 h-3" />K to search</span>
          <span className="flex items-center gap-1">↑↓ to navigate</span>
          <span className="flex items-center gap-1">⏎ to select</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Badge({ className, children }: { className?: string, children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 border-transparent bg-primary text-primary-foreground hover:bg-primary/80", className)}>
      {children}
    </span>
  );
}

function cn(...inputs: any[]) {
  return inputs.filter(Boolean).join(' ');
}
