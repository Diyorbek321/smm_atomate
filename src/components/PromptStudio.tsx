/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useMemo } from 'react';
import { 
  Wand2, 
  Code2, 
  Image as ImageIcon, 
  Sparkles,
  Save,
  ChevronRight,
  Monitor,
  History,
  TrendingUp,
  Hash,
  Eye,
  X,
  RefreshCcw,
  Zap
} from 'lucide-react';
import { useApp } from '../AppContext';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator
} from '@/components/ui/dropdown-menu';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'motion/react';

export function PromptStudio() {
  const { templates, updateTemplate } = useApp();
  const [activeTemplate, setActiveTemplate] = useState(templates[0]);
  const [showPreview, setShowPreview] = useState(false);
  const [previewData] = useState({
    business_name: 'Luna Coffee Co.',
    offer: '20% off all Lattes',
    industry: 'Food & Beverage',
    brand_voice: 'Warm & Artisanal',
    date: 'August 24th',
    day_of_week: 'Monday',
    product_name: 'Signature Cold Brew',
    key_benefit: 'Smooth & Bold'
  });

  const tags = [
    { label: '{{business_name}}', category: 'business' },
    { label: '{{industry}}', category: 'business' },
    { label: '{{brand_voice}}', category: 'business' },
    { label: '{{offer}}', category: 'custom' },
    { label: '{{product_name}}', category: 'custom' },
    { label: '{{key_benefit}}', category: 'custom' },
    { label: '{{date}}', category: 'system' },
    { label: '{{day_of_week}}', category: 'system' },
  ];

  const renderedPreview = useMemo(() => {
    let result = activeTemplate.systemPrompt;
    Object.entries(previewData).forEach(([key, val]) => {
      result = result.replaceAll(`{{${key}}}`, val);
    });
    return result;
  }, [activeTemplate.systemPrompt, previewData]);

  const handleSave = () => {
    updateTemplate(activeTemplate.id, activeTemplate);
  };

  const handleRevert = (version: { systemPrompt: string }) => {
    setActiveTemplate({ ...activeTemplate, systemPrompt: version.systemPrompt });
  };

  return (
    <div className="space-y-6 relative">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">AI Prompt Studio</h1>
          <p className="text-slate-400 mt-1">Fine-tune your brand's AI persona and image styles.</p>
        </div>
        <Button 
          variant={showPreview ? "secondary" : "outline"} 
          onClick={() => setShowPreview(!showPreview)}
          className={cn(
            "border-slate-800 transition-all",
            showPreview ? "bg-indigo-600 text-white border-indigo-500" : "text-slate-400"
          )}
        >
          {showPreview ? <Eye className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
          {showPreview ? 'Hide Preview' : 'Show Preview'}
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-4 space-y-4">
          <Card className="bg-slate-900 border-slate-800">
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-slate-400 uppercase tracking-wider">System Templates</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {templates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setActiveTemplate(t)}
                  className={`w-full text-left p-3 rounded-lg border transition-all group ${
                    activeTemplate.id === t.id 
                      ? 'bg-indigo-600/10 border-indigo-600 text-white' 
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <div className="font-medium text-sm flex items-center justify-between mb-2">
                    {t.name}
                    <ChevronRight className={cn(
                      "w-3 h-3 transition-transform",
                      activeTemplate.id === t.id ? "translate-x-1 opacity-100" : "opacity-30"
                    )} />
                  </div>
                  
                  <div className="flex flex-wrap gap-2">
                    <div className="flex items-center gap-1 px-1.5 py-0.5 bg-slate-900 rounded border border-slate-800 text-[9px] font-bold text-emerald-400">
                      <TrendingUp className="w-2.5 h-2.5" />
                      +{t.engagementLift}% Lift
                    </div>
                    <div className="flex items-center gap-1 px-1.5 py-0.5 bg-slate-900 rounded border border-slate-800 text-[9px] font-bold text-indigo-400">
                      <Hash className="w-2.5 h-2.5" />
                      {t.usageCount} uses
                    </div>
                  </div>
                </button>
              ))}
              <Button variant="outline" className="w-full border-dashed border-slate-800 bg-transparent text-slate-500 hover:text-white">
                + New Template
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-8 space-y-6">
          <Tabs defaultValue="prompt" className="w-full">
            <TabsList className="bg-slate-900 border border-slate-800 p-1">
              <TabsTrigger value="prompt" className="data-[state=active]:bg-slate-800 data-[state=active]:text-white gap-2">
                <Code2 className="w-4 h-4" /> System Prompt
              </TabsTrigger>
              <TabsTrigger value="image" className="data-[state=active]:bg-slate-800 data-[state=active]:text-white gap-2">
                <ImageIcon className="w-4 h-4" /> Image Config
              </TabsTrigger>
            </TabsList>

            <TabsContent value="prompt" className="mt-6 space-y-6">
              <Card className="bg-slate-900 border-slate-800">
                <CardHeader>
                  <div className="flex justify-between items-start">
                    <div>
                      <CardTitle className="text-white">Copywriting Engine</CardTitle>
                      <CardDescription className="text-slate-500">Define how the AI writes for this template.</CardDescription>
                    </div>
                    <div className="flex gap-2">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" size="sm" className="border-slate-800 text-slate-400 hover:text-white">
                            <History className="w-4 h-4 mr-2" /> Versions
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="bg-slate-950 border-slate-800 text-slate-200 w-64">
                          <DropdownMenuLabel>Prompt History</DropdownMenuLabel>
                          <DropdownMenuSeparator className="bg-slate-800" />
                          {activeTemplate.versions.length > 0 ? (
                            activeTemplate.versions.map((v) => (
                              <DropdownMenuItem 
                                key={v.id} 
                                onClick={() => handleRevert(v)}
                                className="flex flex-col items-start gap-1 p-3 focus:bg-indigo-600/10 cursor-pointer"
                              >
                                <div className="flex items-center justify-between w-full">
                                  <span className="text-[10px] font-bold text-indigo-400">
                                    {new Date(v.timestamp).toLocaleDateString()}
                                  </span>
                                  <RefreshCcw className="w-3 h-3 opacity-40" />
                                </div>
                                <p className="text-[11px] text-slate-400 line-clamp-2">
                                  {v.systemPrompt}
                                </p>
                              </DropdownMenuItem>
                            ))
                          ) : (
                            <div className="p-4 text-center text-xs text-slate-500">No versions found</div>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Badge variant="outline" className="border-indigo-500/30 text-indigo-400 h-9 px-3">
                        <Sparkles className="w-3 h-3 mr-1" /> Gemini 1.5 Pro
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-slate-400 text-xs font-bold uppercase tracking-wider">Dynamic Tags</Label>
                    <div className="flex flex-wrap gap-2">
                      {tags.map(tag => (
                        <button
                          key={tag.label}
                          onClick={() => {}} // Mock edit definition
                          className={cn(
                            "px-2.5 py-1 rounded text-[10px] font-bold border transition-all hover:brightness-125 active:scale-95",
                            tag.category === 'business' && "bg-violet-500/10 border-violet-500/30 text-violet-400",
                            tag.category === 'custom' && "bg-indigo-500/10 border-indigo-500/30 text-indigo-400",
                            tag.category === 'system' && "bg-slate-500/10 border-slate-500/30 text-slate-400"
                          )}
                        >
                          {tag.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-slate-400">System Instruction</Label>
                    <Textarea 
                      value={activeTemplate.systemPrompt}
                      onChange={(e) => setActiveTemplate({ ...activeTemplate, systemPrompt: e.target.value })}
                      className="bg-slate-950 border-slate-800 min-h-[300px] font-mono text-xs text-slate-300 leading-relaxed focus:ring-indigo-500 focus:border-indigo-500"
                    />
                  </div>
                  <div className="flex justify-between items-center">
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" className="border-slate-800 text-slate-400 text-xs">
                        Export JSON
                      </Button>
                      <Button variant="outline" size="sm" className="border-slate-800 text-slate-400 text-xs">
                        Import Config
                      </Button>
                    </div>
                    <Button 
                      onClick={handleSave}
                      className="bg-indigo-600 hover:bg-indigo-700 shadow-lg shadow-indigo-500/20"
                    >
                      <Save className="w-4 h-4 mr-2" /> Save Template
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="image" className="mt-6 space-y-6">
              <Card className="bg-slate-900 border-slate-800">
                <CardHeader>
                  <CardTitle className="text-white">Visual Identity Settings</CardTitle>
                  <CardDescription className="text-slate-500">Configure default AI image styles for generated posts.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label className="text-slate-400">Style Preset</Label>
                      <Select defaultValue={activeTemplate.imageStyle}>
                        <SelectTrigger className="bg-slate-950 border-slate-800">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
                          <SelectItem value="Cinematic">Cinematic</SelectItem>
                          <SelectItem value="Flat Lay">Flat Lay</SelectItem>
                          <SelectItem value="Minimalist 3D">Minimalist 3D</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-400">Aspect Ratio</Label>
                      <Select defaultValue={activeTemplate.aspectRatio}>
                        <SelectTrigger className="bg-slate-950 border-slate-800">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
                          <SelectItem value="1:1">1:1 (Square)</SelectItem>
                          <SelectItem value="4:5">4:5 (Portrait)</SelectItem>
                          <SelectItem value="9:16">9:16 (Story)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-slate-400">Negative Prompt</Label>
                    <Textarea 
                      placeholder="e.g., text, blurry, low resolution, distorted faces..."
                      className="bg-slate-950 border-slate-800 text-xs"
                    />
                  </div>
                  
                  <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Monitor className="w-5 h-5 text-indigo-400" />
                      <div>
                        <p className="text-sm font-medium text-slate-200">Flux.1 Integration</p>
                        <p className="text-xs text-slate-500">Optimized for high-fidelity brand photography.</p>
                      </div>
                    </div>
                    <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">Connected</Badge>
                  </div>

                  <div className="flex justify-end">
                    <Button className="bg-indigo-600 hover:bg-indigo-700">
                      <Save className="w-4 h-4 mr-2" /> Save Config
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>

      {/* Template Preview Side Panel */}
      <AnimatePresence>
        {showPreview && (
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed top-0 right-0 w-[450px] h-full bg-slate-950 border-l border-slate-800 shadow-2xl z-50 flex flex-col"
          >
            <div className="p-6 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Zap className="w-5 h-5 text-indigo-400" />
                  Live Injection Preview
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">Simulated rendering with mock data</p>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setShowPreview(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </Button>
            </div>
            
            <ScrollArea className="flex-1 p-6">
              <div className="space-y-6">
                <div className="p-4 bg-indigo-600/10 border border-indigo-500/20 rounded-xl">
                  <div className="flex items-center gap-2 mb-3">
                    <Badge variant="outline" className="bg-indigo-500 text-white border-none text-[10px] uppercase font-bold">Preview Output</Badge>
                    <span className="text-[10px] text-slate-500 font-medium">Rendered System Instructions</span>
                  </div>
                  <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-800">
                    <p className="text-sm text-slate-300 leading-relaxed font-mono whitespace-pre-wrap">
                      {renderedPreview}
                    </p>
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Mock Variables</h4>
                  <div className="grid grid-cols-2 gap-3">
                    {Object.entries(previewData).map(([key, val]) => (
                      <div key={key} className="p-3 bg-slate-900 border border-slate-800 rounded-lg">
                        <Label className="text-[10px] text-slate-500 uppercase tracking-wider">{key}</Label>
                        <p className="text-xs text-slate-200 mt-1 font-medium">{val}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </ScrollArea>
            
            <div className="p-6 border-t border-slate-800 bg-slate-950">
              <Button className="w-full bg-slate-800 hover:bg-slate-700 text-white" onClick={() => setShowPreview(false)}>
                Close Preview
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
