/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { 
  Building2, 
  Search, 
  Plus, 
  MoreHorizontal, 
  Trash2, 
  Edit2,
  Globe,
  Settings
} from 'lucide-react';
import { useApp } from '../AppContext';
import { Business, Industry, BrandVoice } from '../types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogTrigger 
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger 
} from '@/components/ui/dropdown-menu';

export function BusinessManager() {
  const { businesses, addBusiness, deleteBusiness } = useApp();
  const [search, setSearch] = useState('');
  const [isAddOpen, setIsAddOpen] = useState(false);

  const filtered = businesses.filter(b => b.name.toLowerCase().includes(search.toLowerCase()));

  const handleAdd = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    addBusiness({
      name: formData.get('name') as string,
      industry: formData.get('industry') as Industry,
      brandVoice: formData.get('brandVoice') as BrandVoice,
      targetAudience: formData.get('targetAudience') as string,
      knowledgeBase: formData.get('knowledgeBase') as string,
      integrations: {
        ai: { llmProvider: 'Gemini 1.5 Pro', imageModel: 'Flux.1', active: true }
      }
    });
    setIsAddOpen(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Businesses</h1>
          <p className="text-slate-400 mt-1">Manage client profiles and brand identities.</p>
        </div>
        <div className="flex gap-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <Input 
              placeholder="Search businesses..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 bg-slate-900 border-slate-800 text-slate-200 w-full md:w-64"
            />
          </div>
          <Dialog open={isAddOpen} onOpenChange={setIsAddOpen}>
            <DialogTrigger
              render={
                <Button className="bg-indigo-600 hover:bg-indigo-700">
                  <Plus className="w-4 h-4 mr-2" /> New Business
                </Button>
              }
            />
            <DialogContent className="bg-slate-900 border-slate-800 text-slate-200 sm:max-w-[500px]">
              <DialogHeader>
                <DialogTitle>Add New Business</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleAdd} className="space-y-4 py-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">Business Name</Label>
                    <Input id="name" name="name" required className="bg-slate-950 border-slate-800" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="industry">Industry</Label>
                    <Select name="industry" defaultValue="Tech">
                      <SelectTrigger className="bg-slate-950 border-slate-800">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
                        <SelectItem value="Tech">Tech</SelectItem>
                        <SelectItem value="E-commerce">E-commerce</SelectItem>
                        <SelectItem value="Food & Beverage">Food & Beverage</SelectItem>
                        <SelectItem value="Retail">Retail</SelectItem>
                        <SelectItem value="EdTech">EdTech</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="brandVoice">Brand Voice</Label>
                  <Select name="brandVoice" defaultValue="Professional">
                    <SelectTrigger className="bg-slate-950 border-slate-800">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-950 border-slate-800 text-slate-200">
                      <SelectItem value="Professional">Professional</SelectItem>
                      <SelectItem value="Casual">Casual</SelectItem>
                      <SelectItem value="Youthful/Gen-Z">Youthful/Gen-Z</SelectItem>
                      <SelectItem value="Bold">Bold</SelectItem>
                      <SelectItem value="Humorous">Humorous</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="targetAudience">Target Audience</Label>
                  <Input id="targetAudience" name="targetAudience" className="bg-slate-950 border-slate-800" placeholder="e.g., Tech professionals aged 25-40" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="knowledgeBase">Knowledge Base (Core USP, Promos)</Label>
                  <Textarea id="knowledgeBase" name="knowledgeBase" className="bg-slate-950 border-slate-800 min-h-[100px]" placeholder="Key details the AI should know about the brand..." />
                </div>
                <Button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700">Create Profile</Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filtered.map((business) => (
          <Card key={business.id} className="bg-slate-900 border-slate-800 overflow-hidden group hover:border-indigo-500/50 transition-colors">
            <CardContent className="p-0">
              <div className="p-6">
                <div className="flex justify-between items-start mb-4">
                  <div className="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center">
                    <Building2 className="w-6 h-6 text-indigo-400" />
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button variant="ghost" size="icon" className="text-slate-500 hover:text-white">
                          <MoreHorizontal className="w-4 h-4" />
                        </Button>
                      }
                    />
                    <DropdownMenuContent className="bg-slate-900 border-slate-800 text-slate-200">
                      <DropdownMenuItem className="focus:bg-slate-800 focus:text-white">
                        <Edit2 className="w-4 h-4 mr-2" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem 
                        onClick={() => deleteBusiness(business.id)}
                        className="focus:bg-red-950 focus:text-red-400 text-red-500"
                      >
                        <Trash2 className="w-4 h-4 mr-2" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <h3 className="text-xl font-bold text-white mb-1">{business.name}</h3>
                <p className="text-sm text-slate-500 mb-4">{business.industry} • {business.brandVoice}</p>
                
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Globe className="w-3 h-3" />
                    <span>2 Channels Connected</span>
                  </div>
                  <div className="flex gap-2">
                    <div className="px-2 py-1 bg-indigo-500/10 text-indigo-400 rounded text-[10px] font-medium border border-indigo-500/20">
                      Telegram
                    </div>
                    <div className="px-2 py-1 bg-pink-500/10 text-pink-400 rounded text-[10px] font-medium border border-pink-500/20">
                      Instagram
                    </div>
                  </div>
                </div>
              </div>
              <div className="px-6 py-4 bg-slate-950/50 border-t border-slate-800 flex justify-between items-center">
                <span className="text-xs text-slate-500 italic">Target: {business.targetAudience.slice(0, 30)}...</span>
                <Button variant="ghost" size="sm" className="text-indigo-400 hover:text-indigo-300 p-0 h-auto">
                  Manage <Settings className="w-3 h-3 ml-1" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
