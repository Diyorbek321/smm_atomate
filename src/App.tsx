/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { AppProvider } from './AppContext';
import { Sidebar } from './components/layout/Sidebar';
import { DashboardHome } from './components/DashboardHome';
import { BusinessManager } from './components/BusinessManager';
import { PromptStudio } from './components/PromptStudio';
import { ContentStudio } from './components/ContentStudio';
import { IntegrationSettings } from './components/IntegrationSettings';
import { SystemLogs } from './components/SystemLogs';
import { NotificationBell } from './components/NotificationBell';
import { CommandPalette } from './components/CommandPalette';
import { ConnectionBanner, HeaderControls } from './components/AppChrome';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Search, Command as CommandIcon } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + K for search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen(true);
      }
      // N for new post (only if not typing in an input)
      if (e.key === 'n' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault();
        setActiveTab('planner');
      }
      // D for Dashboard
      if (e.key === 'd' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        setActiveTab('dashboard');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard': return <DashboardHome />;
      case 'businesses': return <BusinessManager />;
      case 'prompts': return <PromptStudio />;
      case 'planner': return <ContentStudio />;
      case 'logs': return <SystemLogs />;
      case 'integrations': return <IntegrationSettings />;
      default: return <DashboardHome />;
    }
  };

  return (
    <AppProvider>
      <TooltipProvider>
        <div className="flex h-screen bg-white dark:bg-slate-950 font-sans text-slate-900 dark:text-slate-200 antialiased overflow-hidden selection:bg-indigo-500/30 selection:text-indigo-200 transition-colors duration-300">
          {/* Global Sidebar */}
          <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

          {/* Main Stage */}
          <main className="flex-1 flex flex-col min-w-0">
            <header className="h-14 border-b border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-950/50 backdrop-blur-md flex items-center justify-between px-8 z-10 shrink-0">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
                  <span className="hover:text-indigo-500 transition-colors cursor-pointer capitalize">{activeTab}</span>
                  <span>/</span>
                  <span className="text-slate-900 dark:text-slate-300">Overview</span>
                </div>
                <button 
                  onClick={() => setIsCommandPaletteOpen(true)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-900 dark:hover:text-slate-200 transition-all group"
                >
                  <Search className="w-3.5 h-3.5 group-hover:scale-110 transition-transform" />
                  <span className="text-xs">Search...</span>
                  <div className="flex items-center gap-1 ml-4 opacity-50">
                    <CommandIcon className="w-2.5 h-2.5" />
                    <span className="text-[10px] font-mono">K</span>
                  </div>
                </button>
              </div>

              <div className="flex items-center gap-3">
                <HeaderControls />
                <NotificationBell />
                <div className="w-px h-4 bg-slate-200 dark:bg-slate-800 mx-1" />
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-[10px] font-bold text-white ring-2 ring-white dark:ring-slate-900">
                    A
                  </div>
                </div>
              </div>
            </header>

            <ConnectionBanner />

            {/* min-h-0 caps the flex item at the leftover space — without it the
                area grows with its content and the page can never scroll. */}
            <ScrollArea className="flex-1 min-h-0">
              <div className="max-w-[1400px] mx-auto p-8 lg:p-10">
                {renderContent()}
              </div>
            </ScrollArea>
          </main>

          <CommandPalette 
            open={isCommandPaletteOpen} 
            onOpenChange={setIsCommandPaletteOpen} 
            onSelect={setActiveTab}
          />
        </div>
      </TooltipProvider>
    </AppProvider>
  );
}

