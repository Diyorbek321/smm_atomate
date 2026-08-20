/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { createContext, useContext, useEffect, useState } from 'react';
import { Business, Post, AIPromptTemplate, DashboardStats } from './types';

export type Theme = 'light' | 'dark';

export interface SystemLog {
  id: string;
  message: string;
  type: 'info' | 'success' | 'error';
  timestamp: string;
}

export interface ApiUsageLog {
  id: string;
  endpoint: string;
  status: number;
  tokens: number;
  cost: number;
  timestamp: string;
}

interface AppContextType {
  businesses: Business[];
  posts: Post[];
  templates: AIPromptTemplate[];
  stats: DashboardStats;
  theme: Theme;
  notifications: SystemLog[];
  apiLogs: ApiUsageLog[];
  toggleTheme: () => void;
  addNotification: (message: string, type: SystemLog['type']) => void;
  addBusiness: (b: Omit<Business, 'id'>) => void;
  updateBusiness: (id: string, b: Partial<Business>) => void;
  deleteBusiness: (id: string) => void;
  addPost: (p: Omit<Post, 'id' | 'createdAt'>) => void;
  updatePost: (id: string, p: Partial<Post>) => void;
  deletePost: (id: string) => void;
  bulkApprovePosts: (ids: string[]) => void;
  bulkDeletePosts: (ids: string[]) => void;
  bulkReschedulePosts: (ids: string[], date: string) => void;
  addTemplate: (t: Omit<AIPromptTemplate, 'id' | 'usageCount' | 'engagementLift' | 'versions'>) => void;
  updateTemplate: (id: string, t: Partial<AIPromptTemplate>) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('autosmm_theme');
    return (saved as Theme) || 'dark';
  });

  const [notifications, setNotifications] = useState<SystemLog[]>(() => {
    const saved = localStorage.getItem('autosmm_logs');
    return saved ? JSON.parse(saved) : [
      { id: '1', message: 'System initialized', type: 'info', timestamp: new Date().toISOString() },
      { id: '2', message: 'Gemini API Connected', type: 'success', timestamp: new Date().toISOString() },
    ];
  });

  const [apiLogs] = useState<ApiUsageLog[]>([
    { id: '1', endpoint: '/api/generate', status: 200, tokens: 450, cost: 0.0012, timestamp: new Date(Date.now() - 3600000).toISOString() },
    { id: '2', endpoint: '/api/generate', status: 200, tokens: 820, cost: 0.0024, timestamp: new Date(Date.now() - 7200000).toISOString() },
    { id: '3', endpoint: '/api/publish', status: 201, tokens: 120, cost: 0.0004, timestamp: new Date(Date.now() - 10800000).toISOString() },
    { id: '4', endpoint: '/api/generate', status: 500, tokens: 0, cost: 0.0000, timestamp: new Date(Date.now() - 14400000).toISOString() },
    { id: '5', endpoint: '/api/generate', status: 200, tokens: 310, cost: 0.0009, timestamp: new Date(Date.now() - 18000000).toISOString() },
  ]);

  const [businesses, setBusinesses] = useState<Business[]>(() => {
    const saved = localStorage.getItem('autosmm_businesses');
    return saved ? JSON.parse(saved) : [];
  });

  const [posts, setPosts] = useState<Post[]>(() => {
    const saved = localStorage.getItem('autosmm_posts');
    return saved ? JSON.parse(saved) : [];
  });

  const [templates, setTemplates] = useState<AIPromptTemplate[]>(() => {
    const saved = localStorage.getItem('autosmm_templates');
    return saved ? JSON.parse(saved) : [
      {
        id: '1',
        name: 'Promo Engine',
        category: 'Promotional',
        systemPrompt: 'Generate a high-converting promotional post for {{business_name}} focusing on {{offer}}.',
        imageStyle: 'Cinematic',
        aspectRatio: '1:1',
        usageCount: 142,
        engagementLift: 24,
        versions: [
          { id: 'v1', systemPrompt: 'Initial promo version', timestamp: new Date(Date.now() - 604800000).toISOString() }
        ]
      },
      {
        id: '2',
        name: 'Educational Tip',
        category: 'Educational',
        systemPrompt: 'Create an educational post for {{business_name}} about {{topic}}.',
        imageStyle: 'Minimalist 3D',
        aspectRatio: '1:1',
        usageCount: 89,
        engagementLift: 18,
        versions: [
          { id: 'v1', systemPrompt: 'First educational draft', timestamp: new Date(Date.now() - 1209600000).toISOString() }
        ]
      }
    ];
  });

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('autosmm_theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('autosmm_businesses', JSON.stringify(businesses));
  }, [businesses]);

  useEffect(() => {
    localStorage.setItem('autosmm_posts', JSON.stringify(posts));
  }, [posts]);

  useEffect(() => {
    localStorage.setItem('autosmm_templates', JSON.stringify(templates));
  }, [templates]);

  useEffect(() => {
    localStorage.setItem('autosmm_logs', JSON.stringify(notifications));
  }, [notifications]);

  const toggleTheme = () => setTheme(prev => prev === 'dark' ? 'light' : 'dark');

  const addNotification = (message: string, type: SystemLog['type']) => {
    const newLog = { id: crypto.randomUUID(), message, type, timestamp: new Date().toISOString() };
    setNotifications(prev => [newLog, ...prev].slice(0, 5));
  };

  const addBusiness = (b: Omit<Business, 'id'>) => {
    const newBusiness = { ...b, id: crypto.randomUUID() };
    setBusinesses([...businesses, newBusiness]);
    addNotification(`Business "${b.name}" added`, 'success');
  };

  const updateBusiness = (id: string, b: Partial<Business>) => {
    setBusinesses(businesses.map(item => item.id === id ? { ...item, ...b } : item));
  };

  const deleteBusiness = (id: string) => {
    setBusinesses(businesses.filter(item => item.id !== id));
    addNotification('Business deleted', 'info');
  };

  const addPost = (p: Omit<Post, 'id' | 'createdAt'>) => {
    const newPost = { ...p, id: crypto.randomUUID(), createdAt: new Date().toISOString() };
    setPosts([newPost, ...posts]);
    addNotification('New post scheduled', 'success');
  };

  const updatePost = (id: string, p: Partial<Post>) => {
    setPosts(posts.map(item => item.id === id ? { ...item, ...p } : item));
  };

  const deletePost = (id: string) => {
    setPosts(posts.filter(p => p.id !== id));
    addNotification('Post deleted', 'info');
  };

  const bulkApprovePosts = (ids: string[]) => {
    setPosts(posts.map(p => ids.includes(p.id) ? { ...p, status: 'Published' as const } : p));
    addNotification(`${ids.length} posts approved`, 'success');
  };

  const bulkDeletePosts = (ids: string[]) => {
    setPosts(posts.filter(p => !ids.includes(p.id)));
    addNotification(`${ids.length} posts deleted`, 'info');
  };

  const bulkReschedulePosts = (ids: string[], date: string) => {
    setPosts(posts.map(p => ids.includes(p.id) ? { ...p, scheduledFor: date } : p));
    addNotification(`${ids.length} posts rescheduled`, 'info');
  };

  const addTemplate = (t: Omit<AIPromptTemplate, 'id' | 'usageCount' | 'engagementLift' | 'versions'>) => {
    setTemplates([...templates, { 
      ...t, 
      id: crypto.randomUUID(),
      usageCount: 0,
      engagementLift: 0,
      versions: []
    }]);
    addNotification('New template saved', 'success');
  };

  const updateTemplate = (id: string, t: Partial<AIPromptTemplate>) => {
    setTemplates(templates.map(item => {
      if (item.id === id) {
        const updated = { ...item, ...t };
        // If systemPrompt changed, add to versions
        if (t.systemPrompt && t.systemPrompt !== item.systemPrompt) {
          const newVersion = {
            id: crypto.randomUUID(),
            systemPrompt: item.systemPrompt,
            timestamp: new Date().toISOString()
          };
          updated.versions = [newVersion, ...item.versions].slice(0, 10);
        }
        return updated;
      }
      return item;
    }));
    addNotification('Template updated', 'success');
  };

  const stats: DashboardStats = {
    activeBusinesses: businesses.length,
    scheduledToday: posts.filter(p => p.status === 'Pending').length,
    autoPublished24h: posts.filter(p => p.status === 'Published').length,
    estApiCost: businesses.length * 0.45 // Mock calculation
  };

  return (
    <AppContext.Provider value={{ 
      businesses, 
      posts, 
      templates, 
      stats, 
      theme,
      notifications,
      apiLogs,
      toggleTheme,
      addNotification,
      addBusiness, 
      updateBusiness, 
      deleteBusiness,
      addPost,
      updatePost,
      deletePost,
      bulkApprovePosts,
      bulkDeletePosts,
      bulkReschedulePosts,
      addTemplate,
      updateTemplate
    }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
};
