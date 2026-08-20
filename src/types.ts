/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export type BrandVoice = 'Casual' | 'Professional' | 'Youthful/Gen-Z' | 'Bold' | 'Humorous';

export type Industry = 'Food & Beverage' | 'EdTech' | 'E-commerce' | 'Retail' | 'Tech' | 'Healthcare' | 'Real Estate';

export interface Business {
  id: string;
  name: string;
  industry: Industry;
  brandVoice: BrandVoice;
  targetAudience: string;
  knowledgeBase: string;
  integrations: {
    telegram?: {
      botToken: string;
      channelId: string;
      active: boolean;
    };
    instagram?: {
      accountId: string;
      accessToken: string;
      pageId: string;
      active: boolean;
    };
    ai?: {
      llmProvider: 'Gemini 1.5 Pro' | 'GPT-4o';
      imageModel: 'Flux.1' | 'DALL-E 3';
      active: boolean;
    };
  };
}

export type PostStatus = 'Pending' | 'Approved' | 'Published' | 'Failed';
export type Platform = 'Telegram' | 'Instagram';

export interface Post {
  id: string;
  businessId: string;
  platform: Platform;
  headline: string;
  caption: string;
  imageUrl?: string;
  imagePrompt?: string;
  scheduledAt: string;
  status: PostStatus;
  createdAt: string;
}

export interface PromptVersion {
  id: string;
  systemPrompt: string;
  timestamp: string;
}

export interface AIPromptTemplate {
  id: string;
  name: string;
  category: 'Promotional' | 'Educational' | 'Interactive';
  systemPrompt: string;
  imageStyle: 'Cinematic' | 'Flat Lay' | 'Minimalist 3D';
  aspectRatio: '1:1' | '4:5' | '9:16';
  negativePrompt?: string;
  usageCount: number;
  engagementLift: number;
  versions: PromptVersion[];
}

export interface DashboardStats {
  activeBusinesses: number;
  scheduledToday: number;
  autoPublished24h: number;
  estApiCost: number;
}
