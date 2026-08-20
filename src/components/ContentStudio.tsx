/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { 
  Wand2, 
  RotateCcw, 
  Palette, 
  CheckCircle2, 
  Send, 
  Instagram,
  Smartphone,
  Calendar,
  Image as ImageIcon,
  Loader2,
  Crop,
  Maximize2,
  Square,
  Layout
} from 'lucide-react';
import { useApp } from '../AppContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

export function ContentStudio() {
  const { businesses, templates, addPost } = useApp();
  const [selectedBusiness, setSelectedBusiness] = useState(businesses[0]?.id || '');
  const [selectedTemplate, setSelectedTemplate] = useState(templates[0]?.id || '');
  const [platform, setPlatform] = useState<'Telegram' | 'Instagram'>('Telegram');
  const [isGenerating, setIsGenerating] = useState(false);
  const [previewMode, setPreviewMode] = useState<'Telegram' | 'Instagram'>(platform);
  const [activeAspectRatio, setActiveAspectRatio] = useState<'1:1' | '9:16' | '4:5' | '16:9'>('1:1');
  const [showCropOverlay, setShowCropOverlay] = useState(false);

  const [content, setContent] = useState({
    headline: '',
    caption: '',
    imagePrompt: '',
    imageUrl: 'https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?auto=format&fit=crop&q=80&w=800'
  });

  const generateContent = async () => {
    const business = businesses.find(b => b.id === selectedBusiness);
    const template = templates.find(t => t.id === selectedTemplate);
    if (!business || !template) return;

    setIsGenerating(true);
    try {
      const prompt = `Write a ${platform} post for ${business.name} (${business.industry}). 
      Target Audience: ${business.targetAudience}. 
      Brand Voice: ${business.brandVoice}. 
      Template Objective: ${template.name}.
      Knowledge Base: ${business.knowledgeBase}.
      Provide a Headline and a Caption. Format: [HEADLINE]: text [CAPTION]: text`;

      const res = await fetch('/api/ai/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          systemInstruction: template.systemPrompt
        })
      });

      const data = await res.json();
      const text = data.text;
      
      const headline = text.match(/\[HEADLINE\]: (.*?)\[CAPTION\]/s)?.[1]?.trim() || 'Exciting Update!';
      const caption = text.match(/\[CAPTION\]: (.*)/s)?.[1]?.trim() || text;

      setContent(prev => ({
        ...prev,
        headline,
        caption,
        imagePrompt: `A ${template.imageStyle} visual for ${business.name} showing ${headline}`
      }));
    } catch (err) {
      console.error(err);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = () => {
    addPost({
      businessId: selectedBusiness,
      platform,
      headline: content.headline,
      caption: content.caption,
      imageUrl: content.imageUrl,
      imagePrompt: content.imagePrompt,
      scheduledAt: new Date(Date.now() + 86400000).toISOString(),
      status: 'Approved'
    });
    alert('Post approved and added to queue!');
  };

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] overflow-hidden">
      <div className="flex items-center justify-between mb-6 px-1">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Content Studio</h1>
          <p className="text-slate-400 mt-1">AI-powered generation with real-time mockup preview.</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={selectedBusiness} onValueChange={setSelectedBusiness}>
            <SelectTrigger className="w-[200px] bg-slate-900 border-slate-800">
              <Building2 className="w-4 h-4 mr-2 text-indigo-400" />
              <SelectValue placeholder="Select Business" />
            </SelectTrigger>
            <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
              {businesses.map(b => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={selectedTemplate} onValueChange={setSelectedTemplate}>
            <SelectTrigger className="w-[200px] bg-slate-900 border-slate-800">
              <Wand2 className="w-4 h-4 mr-2 text-indigo-400" />
              <SelectValue placeholder="Select Template" />
            </SelectTrigger>
            <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
              {templates.map(t => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex gap-6 flex-1 overflow-hidden">
        {/* Left Panel: Editor */}
        <div className="flex-1 flex flex-col gap-6 overflow-hidden">
          <Card className="bg-slate-900 border-slate-800 flex-1 overflow-hidden flex flex-col">
            <ScrollArea className="flex-1">
              <CardContent className="p-6 space-y-6">
                <div className="flex gap-4">
                  <div className="flex-1 space-y-2">
                    <Label className="text-slate-400">Target Platform</Label>
                    <div className="flex gap-2">
                      <Button 
                        variant={platform === 'Telegram' ? 'default' : 'outline'}
                        onClick={() => { setPlatform('Telegram'); setPreviewMode('Telegram'); }}
                        className={platform === 'Telegram' ? 'bg-sky-600' : 'border-slate-800'}
                      >
                        <Send className="w-4 h-4 mr-2" /> Telegram
                      </Button>
                      <Button 
                        variant={platform === 'Instagram' ? 'default' : 'outline'}
                        onClick={() => { setPlatform('Instagram'); setPreviewMode('Instagram'); }}
                        className={platform === 'Instagram' ? 'bg-pink-600' : 'border-slate-800'}
                      >
                        <Instagram className="w-4 h-4 mr-2" /> Instagram
                      </Button>
                    </div>
                  </div>
                  <div className="flex-1 space-y-2 text-right">
                    <Label className="text-slate-400">Generation</Label>
                    <div>
                      <Button 
                        onClick={generateContent} 
                        disabled={isGenerating || !selectedBusiness}
                        className="bg-indigo-600 hover:bg-indigo-700"
                      >
                        {isGenerating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
                        Generate Copy
                      </Button>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-slate-400">Headline</Label>
                    <Input 
                      value={content.headline}
                      onChange={(e) => setContent({ ...content, headline: e.target.value })}
                      className="bg-slate-950 border-slate-800 text-slate-100" 
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-slate-400">Post Caption</Label>
                    <Textarea 
                      value={content.caption}
                      onChange={(e) => setContent({ ...content, caption: e.target.value })}
                      className="bg-slate-950 border-slate-800 min-h-[150px] text-slate-200" 
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-slate-400 flex justify-between">
                      AI Image Prompt
                      <Button variant="ghost" size="sm" className="h-6 text-[10px] text-indigo-400">
                        <RotateCcw className="w-3 h-3 mr-1" /> Re-roll
                      </Button>
                    </Label>
                    <Textarea 
                      value={content.imagePrompt}
                      onChange={(e) => setContent({ ...content, imagePrompt: e.target.value })}
                      className="bg-slate-950 border-slate-800 text-xs text-slate-400" 
                    />
                  </div>
                </div>
              </CardContent>
            </ScrollArea>
            
            <div className="p-4 border-t border-slate-800 bg-slate-950/30 flex items-center justify-between">
              <div className="flex gap-2 text-xs text-slate-500">
                <Calendar className="w-3 h-3" />
                <span>Next available slot: Tomorrow, 10:00 AM</span>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" className="border-slate-800 text-slate-400">Edit Manually</Button>
                <Button onClick={handleApprove} className="bg-emerald-600 hover:bg-emerald-700">
                  <CheckCircle2 className="w-4 h-4 mr-2" /> Approve & Queue
                </Button>
              </div>
            </div>
          </Card>
        </div>

        {/* Right Panel: Mobile Preview */}
        <div className="w-[380px] flex flex-col gap-4">
          <div className="flex justify-between items-center px-1">
            <span className="text-sm font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
              <Smartphone className="w-4 h-4" /> Live Preview
            </span>
            <div className="flex bg-slate-900 border border-slate-800 p-0.5 rounded-lg">
              <button 
                onClick={() => setPreviewMode('Telegram')}
                className={`p-1.5 rounded-md transition-all ${previewMode === 'Telegram' ? 'bg-slate-800 text-sky-400 shadow-sm' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Send className="w-4 h-4" />
              </button>
              <button 
                onClick={() => setPreviewMode('Instagram')}
                className={`p-1.5 rounded-md transition-all ${previewMode === 'Instagram' ? 'bg-slate-800 text-pink-400 shadow-sm' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Instagram className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 bg-slate-950 rounded-[3rem] border-[8px] border-slate-900 relative overflow-hidden shadow-2xl">
            {/* Status Bar */}
            <div className="absolute top-0 w-full h-10 px-8 flex justify-between items-center z-10 bg-black/20 backdrop-blur-sm">
              <span className="text-[10px] font-bold text-white">9:41</span>
              <div className="flex gap-1.5">
                <div className="w-3.5 h-3.5 bg-white/20 rounded-full" />
                <div className="w-3.5 h-3.5 bg-white/20 rounded-full" />
              </div>
            </div>

            <ScrollArea className="h-full pt-10">
              <div className="p-4">
                {previewMode === 'Telegram' ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-8 h-8 bg-sky-500 rounded-full flex items-center justify-center text-white text-[10px] font-bold">A</div>
                      <div className="flex flex-col">
                        <span className="text-[11px] font-bold text-white">AutoSMM Bot</span>
                        <span className="text-[9px] text-slate-500">bot service</span>
                      </div>
                    </div>
                    <div className="bg-[#1c242f] rounded-xl overflow-hidden border border-white/5 relative">
                      <div className={cn(
                        "transition-all duration-300 relative overflow-hidden",
                        activeAspectRatio === '1:1' && "aspect-square",
                        activeAspectRatio === '9:16' && "aspect-[9/16]",
                        activeAspectRatio === '4:5' && "aspect-[4/5]",
                        activeAspectRatio === '16:9' && "aspect-[16/9]"
                      )}>
                        <img src={content.imageUrl} className="w-full h-full object-cover" alt="preview" />
                        {showCropOverlay && (
                          <div className="absolute inset-0 pointer-events-none border border-indigo-500/50">
                            <div className="grid grid-cols-3 grid-rows-3 w-full h-full">
                              {[...Array(9)].map((_, i) => (
                                <div key={i} className="border-[0.5px] border-white/10" />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                      <div className="p-3 space-y-2">
                        <p className="text-white text-xs font-bold leading-snug">{content.headline}</p>
                        <p className="text-slate-300 text-[11px] leading-relaxed whitespace-pre-wrap">{content.caption}</p>
                        <p className="text-[9px] text-sky-400">#AI #Automation #SaaS</p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-0 bg-black h-full -mx-4 -mt-2">
                    <div className="p-3 flex items-center gap-2 border-b border-white/5">
                      <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-yellow-400 to-purple-600 p-0.5">
                        <div className="w-full h-full rounded-full bg-black flex items-center justify-center text-[10px] text-white">A</div>
                      </div>
                      <span className="text-[11px] font-bold text-white">autosmm_ai</span>
                    </div>
                    <div className="relative group">
                      <div className={cn(
                        "transition-all duration-300 relative overflow-hidden",
                        activeAspectRatio === '1:1' && "aspect-square",
                        activeAspectRatio === '9:16' && "aspect-[9/16]",
                        activeAspectRatio === '4:5' && "aspect-[4/5]",
                        activeAspectRatio === '16:9' && "aspect-[16/9]"
                      )}>
                        <img src={content.imageUrl} className="w-full h-full object-cover" alt="insta" />
                        {showCropOverlay && (
                          <div className="absolute inset-0 pointer-events-none border border-indigo-500/50">
                            <div className="grid grid-cols-3 grid-rows-3 w-full h-full">
                              {[...Array(9)].map((_, i) => (
                                <div key={i} className="border-[0.5px] border-white/20" />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="p-3 space-y-2">
                      <div className="flex gap-3 mb-2">
                        <span className="text-white">❤</span>
                        <span className="text-white">🗨</span>
                        <span className="text-white">✈</span>
                      </div>
                      <p className="text-xs text-white leading-snug font-semibold">{content.headline}</p>
                      <p className="text-slate-300 text-[11px] leading-relaxed line-clamp-3">
                        <span className="font-bold text-white mr-1">autosmm_ai</span>
                        {content.caption}
                      </p>
                      <p className="text-[10px] text-slate-500 uppercase">2 minutes ago</p>
                    </div>
                  </div>
                )}
              </div>
            </ScrollArea>

            {/* Aspect Ratio & Crop Controls Overlay */}
            <div className="absolute -right-4 top-1/2 -translate-y-1/2 flex flex-col gap-2 z-30">
              <div className="p-1.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-xl rounded-xl flex flex-col gap-1">
                <Button 
                  size="icon" 
                  variant="ghost" 
                  onClick={() => setShowCropOverlay(!showCropOverlay)}
                  className={cn("h-9 w-9", showCropOverlay ? "text-indigo-500 bg-indigo-500/10" : "text-slate-500")}
                >
                  <Crop className="w-4 h-4" />
                </Button>
                <div className="h-px w-full bg-slate-100 dark:bg-slate-800 my-1" />
                {[
                  { val: '1:1', icon: Square },
                  { val: '9:16', icon: Smartphone },
                  { val: '4:5', icon: Maximize2 },
                  { val: '16:9', icon: Layout },
                ].map((ratio) => (
                  <Button
                    key={ratio.val}
                    size="icon"
                    variant="ghost"
                    onClick={() => setActiveAspectRatio(ratio.val as any)}
                    className={cn(
                      "h-9 w-9 flex flex-col items-center justify-center gap-0.5",
                      activeAspectRatio === ratio.val ? "text-indigo-500 bg-indigo-500/10" : "text-slate-500"
                    )}
                  >
                    <ratio.icon className="w-3.5 h-3.5" />
                    <span className="text-[8px] font-bold">{ratio.val}</span>
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Building2(props: any) { return <Building2Icon {...props} />; }
function Building2Icon(props: any) {
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
      <rect width="16" height="20" x="4" y="2" rx="2" ry="2" />
      <path d="M9 22v-4h6v4" />
      <path d="M8 6h.01" />
      <path d="M16 6h.01" />
      <path d="M12 6h.01" />
      <path d="M12 10h.01" />
      <path d="M12 14h.01" />
      <path d="M16 10h.01" />
      <path d="M16 14h.01" />
      <path d="M8 10h.01" />
      <path d="M8 14h.01" />
    </svg>
  );
}

function Sparkles(props: any) {
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
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
      <path d="M5 3v4" />
      <path d="M19 17v4" />
      <path d="M3 5h4" />
      <path d="M17 19h4" />
    </svg>
  );
}
