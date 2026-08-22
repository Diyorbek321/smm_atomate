/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { AlertTriangle, Building2, Loader2, Moon, RefreshCw, Sun } from 'lucide-react';
import { useApp } from '../AppContext';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/** Warns — and offers a retry — when the backend cannot be reached. */
export function ConnectionBanner() {
  const { connection, connectionError, retryConnection } = useApp();

  if (connection !== 'offline') return null;

  return (
    <div className="px-8 py-3 bg-rose-500/10 border-b border-rose-500/20 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0" />
        <p className="text-xs text-rose-500 truncate">
          {connectionError ?? 'Backend unreachable.'} Start it with{' '}
          <code className="font-mono">docker compose up -d</code> inside <code className="font-mono">backend/</code>.
        </p>
      </div>
      <Button size="sm" variant="outline" onClick={retryConnection} className="shrink-0 border-rose-500/30">
        <RefreshCw className="w-3.5 h-3.5 mr-2" /> Retry
      </Button>
    </div>
  );
}

/** Business switcher + theme toggle, shown in the top bar. */
export function HeaderControls() {
  const { businesses, selectedBusinessId, selectBusiness, theme, toggleTheme, loading, connection } =
    useApp();

  // Base UI renders the raw value unless it knows the value → label mapping.
  const businessItems = Object.fromEntries(businesses.map((b) => [b.id, b.name]));

  return (
    <div className="flex items-center gap-2">
      {loading && connection !== 'offline' && (
        <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" aria-label="Loading" />
      )}

      {businesses.length > 0 && (
        <Select
          value={selectedBusinessId ?? ''}
          onValueChange={selectBusiness}
          items={businessItems}
        >
          <SelectTrigger className="h-8 w-[190px] text-xs bg-slate-100 dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <Building2 className="w-3.5 h-3.5 mr-2 text-indigo-400" />
            <SelectValue placeholder="Business" />
          </SelectTrigger>
          <SelectContent>
            {businesses.map((business) => (
              <SelectItem key={business.id} value={business.id}>
                {business.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <button
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
        className="p-2 rounded-full text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-900 transition-colors"
      >
        {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>
    </div>
  );
}
