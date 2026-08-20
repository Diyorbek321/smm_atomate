/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { Download, Database, Shield, Zap, FileJson, FileSpreadsheet } from 'lucide-react';
import { useApp } from '../AppContext';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger 
} from '@/components/ui/dropdown-menu';

export function SystemLogs() {
  const { apiLogs } = useApp();

  const downloadJSON = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(apiLogs, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", `api_logs_${new Date().toISOString()}.json`);
    document.body.appendChild(downloadAnchorNode);
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
  };

  const downloadCSV = () => {
    const headers = ['ID', 'Endpoint', 'Status', 'Tokens', 'Cost', 'Timestamp'];
    const rows = apiLogs.map(log => [
      log.id,
      log.endpoint,
      log.status,
      log.tokens,
      log.cost,
      log.timestamp
    ]);
    
    const csvContent = [
      headers.join(','),
      ...rows.map(e => e.join(","))
    ].join("\n");

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", `api_logs_${new Date().toISOString()}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.appendChild(link);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">System Logs & API Usage</h2>
          <p className="text-slate-500 dark:text-slate-400">Monitor your AI consumption and system health.</p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger render={
            <Button className="bg-indigo-600 hover:bg-indigo-700">
              <Download className="w-4 h-4 mr-2" /> Export Logs
            </Button>
          } />
          <DropdownMenuContent className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
            <DropdownMenuItem onClick={downloadJSON} className="cursor-pointer">
              <FileJson className="w-4 h-4 mr-2" /> Export as JSON
            </DropdownMenuItem>
            <DropdownMenuItem onClick={downloadCSV} className="cursor-pointer">
              <FileSpreadsheet className="w-4 h-4 mr-2" /> Export as CSV
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Tokens Used</CardTitle>
            <Zap className="h-4 w-4 text-indigo-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">12,450</div>
            <p className="text-xs text-emerald-500 font-medium">+12% from last month</p>
          </CardContent>
        </Card>
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">API Reliability</CardTitle>
            <Shield className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">99.8%</div>
            <p className="text-xs text-slate-500 dark:text-slate-400">Past 30 days</p>
          </CardContent>
        </Card>
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Estimated Cost</CardTitle>
            <Database className="h-4 w-4 text-indigo-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">$14.50</div>
            <p className="text-xs text-slate-500 dark:text-slate-400">Current billing cycle</p>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
        <CardHeader>
          <CardTitle>API Consumption Logs</CardTitle>
          <CardDescription>Real-time tracking of AI generation requests.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-200 dark:border-slate-800 hover:bg-transparent">
                <TableHead className="text-slate-500">Timestamp</TableHead>
                <TableHead className="text-slate-500">Endpoint</TableHead>
                <TableHead className="text-slate-500">Status</TableHead>
                <TableHead className="text-slate-500">Tokens</TableHead>
                <TableHead className="text-slate-500 text-right">Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {apiLogs.map((log) => (
                <TableRow key={log.id} className="border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <TableCell className="font-medium text-slate-700 dark:text-slate-300">
                    {new Date(log.timestamp).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-slate-500">
                    <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-[10px]">{log.endpoint}</code>
                  </TableCell>
                  <TableCell>
                    <Badge variant={log.status < 300 ? 'default' : 'destructive'} className={log.status < 300 ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : ''}>
                      {log.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-slate-500">{log.tokens.toLocaleString()}</TableCell>
                  <TableCell className="text-right text-indigo-500 font-mono text-xs">
                    ${log.cost.toFixed(4)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
