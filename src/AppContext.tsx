/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, errorMessage } from './api/client';
import type {
  AnalyticsSummary,
  Business,
  BusinessCreate,
  BusinessUpdate,
  ContentItem,
  ContentItemStatus,
  ContentItemUpdate,
  ContentPlan,
  GenerateItemRequest,
  GeneratePlanRequest,
  ItemFilters,
  ProviderStatus,
  PromptTemplate,
  PromptTemplateCreate,
  PromptTemplateUpdate,
} from './api/types';

export type Theme = 'light' | 'dark';
export type ConnectionState = 'connecting' | 'online' | 'offline';

export interface SystemLog {
  id: string;
  message: string;
  type: 'info' | 'success' | 'error';
  timestamp: string;
}

const EMPTY_SUMMARY: AnalyticsSummary = {
  active_businesses: 0,
  total_businesses: 0,
  scheduled_today: 0,
  pending_review: 0,
  published_24h: 0,
  failed_24h: 0,
  published_total: 0,
  approval_rate: 0,
  avg_quality_score: 0,
  pillar_distribution: {},
  content_type_distribution: {},
  upcoming: [],
  est_api_cost_usd: 0,
};

/** How often the dashboard re-reads the queue and the summary. */
const POLL_INTERVAL_MS = 20_000;
const ITEM_PAGE_SIZE = 50;

interface AppContextType {
  // --- connection -------------------------------------------------------
  connection: ConnectionState;
  connectionError: string | null;
  retryConnection: () => void;

  // --- data -------------------------------------------------------------
  businesses: Business[];
  items: ContentItem[];
  plans: ContentPlan[];
  templates: PromptTemplate[];
  summary: AnalyticsSummary;
  providers: ProviderStatus | null;
  loading: boolean;

  // --- selection / filters ---------------------------------------------
  selectedBusinessId: string | null;
  selectBusiness: (id: string | null) => void;
  itemFilters: ItemFilters;
  setItemFilters: (filters: ItemFilters) => void;

  // --- ui ---------------------------------------------------------------
  theme: Theme;
  toggleTheme: () => void;
  notifications: SystemLog[];
  addNotification: (message: string, type: SystemLog['type']) => void;

  // --- actions ----------------------------------------------------------
  refreshAll: () => Promise<void>;
  refreshItems: () => Promise<void>;

  addBusiness: (payload: BusinessCreate) => Promise<Business | null>;
  updateBusiness: (id: string, payload: BusinessUpdate) => Promise<void>;
  deleteBusiness: (id: string) => Promise<void>;

  updateItem: (id: string, payload: ContentItemUpdate) => Promise<void>;
  approveItem: (id: string) => Promise<void>;
  rejectItem: (id: string) => Promise<void>;
  deleteItem: (id: string) => Promise<void>;
  bulkStatus: (ids: string[], status: ContentItemStatus) => Promise<void>;
  regenerateItem: (id: string, instruction?: string, withImage?: boolean) => Promise<void>;
  publishItem: (id: string, force?: boolean) => Promise<void>;

  generatePlan: (payload: GeneratePlanRequest) => Promise<void>;
  generateItem: (payload: GenerateItemRequest) => Promise<void>;
  approvePlan: (id: string) => Promise<void>;

  addTemplate: (payload: PromptTemplateCreate) => Promise<void>;
  updateTemplate: (id: string, payload: PromptTemplateUpdate) => Promise<void>;
  rollbackTemplate: (id: string, version: number) => Promise<void>;
  deleteTemplate: (id: string) => Promise<void>;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem('autosmm_theme') as Theme) || 'dark',
  );
  const [notifications, setNotifications] = useState<SystemLog[]>([]);

  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [items, setItems] = useState<ContentItem[]>([]);
  const [plans, setPlans] = useState<ContentPlan[]>([]);
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummary>(EMPTY_SUMMARY);
  const [providers, setProviders] = useState<ProviderStatus | null>(null);

  const [selectedBusinessId, setSelectedBusinessId] = useState<string | null>(
    () => localStorage.getItem('autosmm_business') || null,
  );
  const [itemFilters, setItemFilters] = useState<ItemFilters>({});

  const notify = useCallback((message: string, type: SystemLog['type']) => {
    setNotifications((prev) =>
      [
        { id: crypto.randomUUID(), message, type, timestamp: new Date().toISOString() },
        ...prev,
      ].slice(0, 30),
    );
  }, []);

  /** Runs an API call, turning failures into a notification instead of a crash. */
  const guard = useCallback(
    async <T,>(action: () => Promise<T>, successMessage?: string): Promise<T | null> => {
      try {
        const result = await action();
        if (successMessage) notify(successMessage, 'success');
        setConnection('online');
        setConnectionError(null);
        return result;
      } catch (error) {
        const message = errorMessage(error);
        notify(message, 'error');
        if (error instanceof ApiError && error.isOffline) {
          setConnection('offline');
          setConnectionError(message);
        }
        return null;
      }
    },
    [notify],
  );

  // ---------------------------------------------------------------- theme
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('autosmm_theme', theme);
  }, [theme]);

  useEffect(() => {
    if (selectedBusinessId) localStorage.setItem('autosmm_business', selectedBusinessId);
    else localStorage.removeItem('autosmm_business');
  }, [selectedBusinessId]);

  // ----------------------------------------------------------- data loads
  const filtersRef = useRef(itemFilters);
  filtersRef.current = itemFilters;
  const businessRef = useRef(selectedBusinessId);
  businessRef.current = selectedBusinessId;

  const loadItems = useCallback(async () => {
    const filters: ItemFilters = { limit: ITEM_PAGE_SIZE, ...filtersRef.current };
    if (!filters.business_id && businessRef.current) filters.business_id = businessRef.current;
    const page = await api.items.list(filters);
    setItems(page.items);
  }, []);

  const loadEverything = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [businessPage, summaryData, templatePage, planPage] = await Promise.all([
          api.businesses.list({ limit: 100 }),
          api.analytics.summary(),
          api.prompts.list({ limit: 100 }),
          api.plans.list({ limit: 25 }),
        ]);

        setBusinesses(businessPage.items);
        setSummary(summaryData);
        setTemplates(templatePage.items);
        setPlans(planPage.items);
        await loadItems();

        setConnection('online');
        setConnectionError(null);
      } catch (error) {
        const message = errorMessage(error);
        setConnectionError(message);
        setConnection(error instanceof ApiError && error.isOffline ? 'offline' : 'online');
        if (!silent) notify(message, 'error');
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [loadItems, notify],
  );

  // Providers change rarely — refetch only when the connection comes back.
  useEffect(() => {
    if (connection === 'offline') return;
    api.system
      .providers()
      .then(setProviders)
      .catch(() => setProviders(null));
  }, [connection]);

  useEffect(() => {
    void loadEverything();
  }, [loadEverything]);

  // Re-query the queue whenever the filter or the active business changes.
  useEffect(() => {
    void guard(loadItems);
  }, [itemFilters, selectedBusinessId, guard, loadItems]);

  // Background refresh so generation and publishing progress show up by itself.
  useEffect(() => {
    if (connection === 'offline') return;
    const timer = setInterval(() => void loadEverything(true), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [connection, loadEverything]);

  // Keep a valid selection at all times.
  useEffect(() => {
    if (!businesses.length) return;
    if (!selectedBusinessId || !businesses.some((b) => b.id === selectedBusinessId)) {
      setSelectedBusinessId(businesses[0].id);
    }
  }, [businesses, selectedBusinessId]);

  // --------------------------------------------------------------- actions
  const refreshAll = useCallback(async () => {
    await loadEverything();
  }, [loadEverything]);

  const refreshItems = useCallback(async () => {
    await guard(loadItems);
  }, [guard, loadItems]);

  const addBusiness = useCallback(
    async (payload: BusinessCreate) => {
      const created = await guard(() => api.businesses.create(payload), `"${payload.name}" created`);
      if (created) {
        setBusinesses((prev) => [created, ...prev]);
        setSelectedBusinessId(created.id);
        void loadEverything(true);
      }
      return created;
    },
    [guard, loadEverything],
  );

  const updateBusiness = useCallback(
    async (id: string, payload: BusinessUpdate) => {
      const updated = await guard(() => api.businesses.update(id, payload), 'Business updated');
      if (updated) setBusinesses((prev) => prev.map((b) => (b.id === id ? updated : b)));
    },
    [guard],
  );

  const deleteBusiness = useCallback(
    async (id: string) => {
      const done = await guard(() => api.businesses.remove(id), 'Business deleted');
      if (done) {
        setBusinesses((prev) => prev.filter((b) => b.id !== id));
        if (selectedBusinessId === id) setSelectedBusinessId(null);
        void loadEverything(true);
      }
    },
    [guard, loadEverything, selectedBusinessId],
  );

  const replaceItem = useCallback((updated: ContentItem) => {
    setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  }, []);

  const updateItem = useCallback(
    async (id: string, payload: ContentItemUpdate) => {
      const updated = await guard(() => api.items.update(id, payload), 'Post updated');
      if (updated) replaceItem(updated);
    },
    [guard, replaceItem],
  );

  const approveItem = useCallback(
    async (id: string) => {
      const updated = await guard(() => api.items.approve(id), 'Approved — it will publish on schedule');
      if (updated) replaceItem(updated);
    },
    [guard, replaceItem],
  );

  const rejectItem = useCallback(
    async (id: string) => {
      const updated = await guard(() => api.items.reject(id), 'Post rejected');
      if (updated) replaceItem(updated);
    },
    [guard, replaceItem],
  );

  const deleteItem = useCallback(
    async (id: string) => {
      const done = await guard(() => api.items.remove(id), 'Post deleted');
      if (done) setItems((prev) => prev.filter((item) => item.id !== id));
    },
    [guard],
  );

  const bulkStatus = useCallback(
    async (ids: string[], status: ContentItemStatus) => {
      if (!ids.length) return;
      const result = await guard(() => api.items.bulkStatus(ids, status));
      if (result) {
        notify(`${result.updated} of ${result.requested} posts → ${status.replace('_', ' ')}`, 'success');
        await guard(loadItems);
      }
    },
    [guard, loadItems, notify],
  );

  const regenerateItem = useCallback(
    async (id: string, instruction = '', withImage = false) => {
      const task = await guard(() => api.generate.regenerate(id, instruction, withImage));
      if (!task) return;
      notify(task.status === 'queued' ? 'Regeneration queued' : 'Regenerated', 'success');
      await guard(loadItems);
    },
    [guard, loadItems, notify],
  );

  const publishItem = useCallback(
    async (id: string, force = false) => {
      const task = await guard(() => api.generate.publishNow(id, force));
      if (!task) return;
      notify(task.message || 'Publishing…', 'info');
      await guard(loadItems);
    },
    [guard, loadItems, notify],
  );

  const generatePlan = useCallback(
    async (payload: GeneratePlanRequest) => {
      const task = await guard(() => api.generate.plan(payload));
      if (!task) return;
      notify(
        task.status === 'queued'
          ? 'Weekly plan queued — posts appear as the agents finish'
          : 'Generating the plan in-process…',
        'info',
      );
      setTimeout(() => void loadEverything(true), 4000);
    },
    [guard, loadEverything, notify],
  );

  const generateItem = useCallback(
    async (payload: GenerateItemRequest) => {
      const task = await guard(() => api.generate.item(payload));
      if (!task) return;
      notify(task.status === 'queued' ? 'Post generation queued' : 'Generating the post…', 'info');
      setTimeout(() => void loadEverything(true), 4000);
    },
    [guard, loadEverything, notify],
  );

  const approvePlan = useCallback(
    async (id: string) => {
      const result = await guard(() => api.plans.approve(id));
      if (result) {
        notify(`${result.approved} posts approved`, 'success');
        await loadEverything(true);
      }
    },
    [guard, loadEverything, notify],
  );

  const addTemplate = useCallback(
    async (payload: PromptTemplateCreate) => {
      const created = await guard(() => api.prompts.create(payload), 'Prompt saved');
      if (created) setTemplates((prev) => [created, ...prev]);
    },
    [guard],
  );

  const updateTemplate = useCallback(
    async (id: string, payload: PromptTemplateUpdate) => {
      const updated = await guard(() => api.prompts.update(id, payload), 'Prompt updated');
      if (updated) setTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)));
    },
    [guard],
  );

  const rollbackTemplate = useCallback(
    async (id: string, version: number) => {
      const updated = await guard(() => api.prompts.rollback(id, version), `Rolled back to v${version}`);
      if (updated) setTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)));
    },
    [guard],
  );

  const deleteTemplate = useCallback(
    async (id: string) => {
      const done = await guard(() => api.prompts.remove(id), 'Prompt deleted');
      if (done) setTemplates((prev) => prev.filter((t) => t.id !== id));
    },
    [guard],
  );

  const retryConnection = useCallback(() => {
    setConnection('connecting');
    void loadEverything();
  }, [loadEverything]);

  const value = useMemo<AppContextType>(
    () => ({
      connection,
      connectionError,
      retryConnection,
      businesses,
      items,
      plans,
      templates,
      summary,
      providers,
      loading,
      selectedBusinessId,
      selectBusiness: setSelectedBusinessId,
      itemFilters,
      setItemFilters,
      theme,
      toggleTheme: () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark')),
      notifications,
      addNotification: notify,
      refreshAll,
      refreshItems,
      addBusiness,
      updateBusiness,
      deleteBusiness,
      updateItem,
      approveItem,
      rejectItem,
      deleteItem,
      bulkStatus,
      regenerateItem,
      publishItem,
      generatePlan,
      generateItem,
      approvePlan,
      addTemplate,
      updateTemplate,
      rollbackTemplate,
      deleteTemplate,
    }),
    [
      connection,
      connectionError,
      retryConnection,
      businesses,
      items,
      plans,
      templates,
      summary,
      providers,
      loading,
      selectedBusinessId,
      itemFilters,
      theme,
      notifications,
      notify,
      refreshAll,
      refreshItems,
      addBusiness,
      updateBusiness,
      deleteBusiness,
      updateItem,
      approveItem,
      rejectItem,
      deleteItem,
      bulkStatus,
      regenerateItem,
      publishItem,
      generatePlan,
      generateItem,
      approvePlan,
      addTemplate,
      updateTemplate,
      rollbackTemplate,
      deleteTemplate,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
};

/** Convenience selector for the business currently in focus. */
export function useSelectedBusiness(): Business | null {
  const { businesses, selectedBusinessId } = useApp();
  return businesses.find((b) => b.id === selectedBusinessId) ?? null;
}
