/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { Bell, Circle } from 'lucide-react';
import { useApp } from '../AppContext';
import { 
  Popover, 
  PopoverContent, 
  PopoverTrigger 
} from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';

export function NotificationBell() {
  const { notifications } = useApp();

  return (
    <Popover>
      <PopoverTrigger
        render={
          <button className="relative p-2 hover:bg-slate-100 dark:hover:bg-slate-900 rounded-full transition-colors text-slate-500 dark:text-slate-400">
            <Bell className="w-5 h-5" />
            {notifications.length > 0 && (
              <span className="absolute top-2 right-2 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
            )}
          </button>
        }
      />
      <PopoverContent className="w-80 p-0 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800" align="end">
        <div className="p-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold dark:text-white">Recent Activity</h3>
          <span className="text-[10px] bg-indigo-500/10 text-indigo-500 px-2 py-0.5 rounded-full font-medium">System</span>
        </div>
        <Separator className="bg-slate-100 dark:bg-slate-800" />
        <ScrollArea className="h-[300px]">
          {notifications.length > 0 ? (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {notifications.map((log) => (
                <div key={log.id} className="p-4 flex gap-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                  <div className={`mt-1 h-2 w-2 rounded-full shrink-0 ${
                    log.type === 'success' ? 'bg-emerald-500' : 
                    log.type === 'error' ? 'bg-rose-500' : 'bg-indigo-500'
                  }`} />
                  <div className="space-y-1">
                    <p className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">{log.message}</p>
                    <p className="text-[10px] text-slate-400">
                      {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-12 text-center text-slate-500 text-sm">
              No recent notifications
            </div>
          )}
        </ScrollArea>
        <div className="p-3 bg-slate-50 dark:bg-slate-950/50 border-t border-slate-100 dark:border-slate-800">
          <button className="w-full text-xs text-indigo-500 hover:text-indigo-400 font-medium">
            View All Logs
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
