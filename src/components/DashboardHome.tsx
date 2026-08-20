/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { 
  Building2, 
  CalendarCheck, 
  CheckCircle2, 
  DollarSign, 
  Plus, 
  Zap,
  MoreVertical,
  Instagram,
  Send,
  TrendingUp,
  TrendingDown,
  Trash2,
  Check,
  Calendar,
  X,
  Clock,
  AlertCircle
} from 'lucide-react';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as ChartTooltip, 
  ResponsiveContainer 
} from 'recharts';
import { useApp } from '../AppContext';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'motion/react';
import { Checkbox } from '@/components/ui/checkbox';

const chartData = [
  { day: 'Mon', reach: 1200, engagement: 800 },
  { day: 'Tue', reach: 1900, engagement: 1200 },
  { day: 'Wed', reach: 1500, engagement: 1000 },
  { day: 'Thu', reach: 2100, engagement: 1500 },
  { day: 'Fri', reach: 2800, engagement: 1900 },
  { day: 'Sat', reach: 3500, engagement: 2400 },
  { day: 'Sun', reach: 3100, engagement: 2100 },
];

export function DashboardHome() {
  const { stats, posts, bulkApprovePosts, bulkDeletePosts } = useApp();
  const [selectedPosts, setSelectedPosts] = useState<string[]>([]);

  const togglePostSelection = (postId: string) => {
    setSelectedPosts(prev => 
      prev.includes(postId) 
        ? prev.filter(id => id !== postId) 
        : [...prev, postId]
    );
  };

  const toggleAllSelection = () => {
    if (selectedPosts.length === posts.length) {
      setSelectedPosts([]);
    } else {
      setSelectedPosts(posts.map(p => p.id));
    }
  };

  const handleBulkApprove = () => {
    bulkApprovePosts(selectedPosts);
    setSelectedPosts([]);
  };

  const handleBulkDelete = () => {
    bulkDeletePosts(selectedPosts);
    setSelectedPosts([]);
  };

  const statConfig = [
    { label: 'Active Businesses', value: stats.activeBusinesses, icon: Building2, color: 'text-blue-400', trend: '+2', isPositive: true },
    { label: 'Scheduled Today', value: stats.scheduledToday, icon: CalendarCheck, color: 'text-indigo-400', trend: '+8', isPositive: true },
    { label: 'Auto-Published (24h)', value: stats.autoPublished24h, icon: CheckCircle2, color: 'text-emerald-400', trend: '-3%', isPositive: false },
    { label: 'Est. API Cost ($)', value: `$${stats.estApiCost.toFixed(2)}`, icon: DollarSign, color: 'text-amber-400', trend: '+15%', isPositive: true },
  ];

  return (
    <div className="space-y-8 pb-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Overview</h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">Real-time performance of your AI content ecosystem.</p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" className="border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300">
            <Plus className="w-4 h-4 mr-2" /> Add Business
          </Button>
          <Button className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-500/20">
            <Zap className="w-4 h-4 mr-2" /> Instant Post
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statConfig.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                  {stat.label}
                </CardTitle>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="text-2xl font-bold text-slate-900 dark:text-white">{stat.value}</div>
                  <div className={cn(
                    "flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded",
                    stat.isPositive ? "bg-emerald-500/10 text-emerald-500" : "bg-rose-500/10 text-rose-500"
                  )}>
                    {stat.isPositive ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
                    {stat.trend}
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 overflow-hidden">
        <CardHeader className="border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg text-slate-900 dark:text-white">Performance Overview</CardTitle>
              <CardDescription className="text-slate-500 dark:text-slate-400">Weekly reach and engagement growth data.</CardDescription>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full bg-indigo-500" />
                <span className="text-xs text-slate-500">Reach</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full bg-emerald-500" />
                <span className="text-xs text-slate-500">Engagement</span>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-6">
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorReach" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.1}/>
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorEngagement" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.1}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.1} />
                <XAxis 
                  dataKey="day" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fontSize: 12, fill: '#64748b' }}
                />
                <ChartTooltip 
                  contentStyle={{ 
                    backgroundColor: '#0f172a', 
                    border: '1px solid #1e293b',
                    borderRadius: '8px',
                    fontSize: '12px',
                    color: '#f1f5f9'
                  }}
                />
                <Area 
                  type="monotone" 
                  dataKey="reach" 
                  stroke="#6366f1" 
                  strokeWidth={2}
                  fillOpacity={1} 
                  fill="url(#colorReach)" 
                />
                <Area 
                  type="monotone" 
                  dataKey="engagement" 
                  stroke="#10b981" 
                  strokeWidth={2}
                  fillOpacity={1} 
                  fill="url(#colorEngagement)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 relative">
        <CardHeader className="flex flex-row items-center justify-between border-b border-slate-200 dark:border-slate-800">
          <CardTitle className="text-lg font-semibold text-slate-900 dark:text-white">Content Pipeline</CardTitle>
          <Button variant="ghost" size="icon" className="text-slate-400">
            <MoreVertical className="w-4 h-4" />
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <AnimatePresence>
            {selectedPosts.length > 0 && (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                className="absolute top-[64px] left-0 right-0 z-20 px-6 py-3 bg-indigo-600 flex items-center justify-between"
              >
                <div className="flex items-center gap-4 text-white">
                  <button onClick={() => setSelectedPosts([])} className="p-1 hover:bg-white/20 rounded-md transition-colors">
                    <X className="w-4 h-4" />
                  </button>
                  <span className="text-sm font-medium">{selectedPosts.length} posts selected</span>
                </div>
                <div className="flex items-center gap-2">
                  <Button 
                    onClick={handleBulkApprove}
                    className="bg-white text-indigo-600 hover:bg-slate-100 text-xs h-8"
                  >
                    <Check className="w-3.5 h-3.5 mr-1.5" /> Approve Selected
                  </Button>
                  <Button 
                    onClick={handleBulkDelete}
                    variant="destructive"
                    className="bg-rose-500 hover:bg-rose-600 text-xs h-8 border-none"
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Delete Selected
                  </Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <Table>
            <TableHeader className="border-slate-200 dark:border-slate-800">
              <TableRow className="hover:bg-transparent border-slate-200 dark:border-slate-800">
                <TableHead className="w-[50px] pl-6">
                  <Checkbox 
                    checked={selectedPosts.length === posts.length && posts.length > 0}
                    onCheckedChange={toggleAllSelection}
                  />
                </TableHead>
                <TableHead className="text-slate-500">Post Detail</TableHead>
                <TableHead className="text-slate-500">Platform</TableHead>
                <TableHead className="text-slate-500">Scheduled Time</TableHead>
                <TableHead className="text-slate-500 text-right pr-6">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {posts.length > 0 ? (
                posts.map((post) => (
                  <TableRow key={post.id} className="border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <TableCell className="pl-6">
                      <Checkbox 
                        checked={selectedPosts.includes(post.id)}
                        onCheckedChange={() => togglePostSelection(post.id)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium text-slate-900 dark:text-slate-200">{post.headline}</span>
                        <span className="text-xs text-slate-500 truncate max-w-[200px]">{post.caption}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                        {post.platform === 'Instagram' ? (
                          <Instagram className="w-4 h-4 text-pink-500" />
                        ) : (
                          <Send className="w-4 h-4 text-sky-400" />
                        )}
                        <span className="text-sm">{post.platform}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-slate-500 text-sm">
                      {new Date(post.scheduledFor || post.scheduledAt || '').toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right pr-6">
                      <Badge 
                        variant="secondary" 
                        className={cn(
                          "bg-opacity-10",
                          post.status === 'Published' && "bg-emerald-500 text-emerald-400",
                          post.status === 'Pending' && "bg-amber-500 text-amber-400",
                          post.status === 'Draft' && "bg-slate-500 text-slate-400"
                        )}
                      >
                        {post.status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-12 text-slate-500 border-none">
                    No posts in the pipeline. Start by adding a business!
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}


