/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Typed client for the AutoSMM AI backend.
 *
 * Requests go to a same-origin `/api/v1/...` path by default; the Express
 * server proxies them and injects `X-API-Key` so the key never reaches the
 * browser. Set `VITE_API_URL` to talk to a backend directly (CORS must allow
 * the dashboard origin), and `VITE_API_KEY` when doing so.
 */

import type {
  Admin,
  AnalyticsSummary,
  ApiEnvelope,
  Business,
  BusinessAnalytics,
  BusinessCreate,
  BusinessUpdate,
  ContentItem,
  ContentItemStatus,
  ContentItemUpdate,
  ContentPlan,
  ContentPlanDetail,
  Credentials,
  CredentialsCheck,
  CredentialsUpdate,
  FailureEntry,
  GenerateItemRequest,
  GeneratePlanRequest,
  GenerationTask,
  ItemFilters,
  KnowledgeBase,
  KnowledgeBaseUpdate,
  KnowledgeIngestResult,
  Paged,
  ProviderStatus,
  PromptTemplate,
  PromptTemplateCreate,
  PromptTemplateUpdate,
  PublishLogEntry,
} from './types';

const BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');
const API_KEY = import.meta.env.VITE_API_KEY ?? '';
const DEFAULT_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, code: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** True when the backend is unreachable rather than rejecting the request. */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE_URL}/api/v1${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(
  path: string,
  init: RequestInit & { query?: Query } = {},
): Promise<{ data: T; meta: ApiEnvelope<T>['meta'] }> {
  const { query, ...options } = init;
  const headers = new Headers(options.headers);
  // FormData sets its own multipart boundary — forcing JSON would corrupt it.
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (API_KEY) headers.set('X-API-Key', API_KEY);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    throw new ApiError(
      aborted ? 'Request timed out' : 'Backend is unreachable — is it running?',
      aborted ? 'timeout' : 'network_error',
      0,
      String(error),
    );
  } finally {
    clearTimeout(timer);
  }

  let body: ApiEnvelope<T> | null = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text) as ApiEnvelope<T>;
    } catch {
      throw new ApiError(
        `Unexpected response (HTTP ${response.status})`,
        'bad_response',
        response.status,
        text.slice(0, 400),
      );
    }
  }

  if (!response.ok || body?.success === false) {
    const err = body?.error;
    throw new ApiError(
      err?.message ?? `HTTP ${response.status}`,
      err?.code ?? `http_${response.status}`,
      response.status,
      err?.details,
    );
  }

  return { data: (body?.data ?? null) as T, meta: body?.meta ?? null };
}

async function get<T>(path: string, query?: Query): Promise<T> {
  return (await request<T>(path, { method: 'GET', query })).data;
}

async function getPaged<T>(path: string, query?: Query): Promise<Paged<T>> {
  const { data, meta } = await request<T[]>(path, { method: 'GET', query });
  return {
    items: data ?? [],
    meta: meta ?? { total: data?.length ?? 0, page: 1, limit: data?.length ?? 0 },
  };
}

async function send<T>(method: string, path: string, payload?: unknown): Promise<T> {
  return (
    await request<T>(path, {
      method,
      body: payload === undefined ? undefined : JSON.stringify(payload),
    })
  ).data;
}

async function sendFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append('file', file, file.name);
  return (await request<T>(path, { method: 'POST', body: form })).data;
}

export const api = {
  businesses: {
    list: (query?: { q?: string; is_active?: boolean; page?: number; limit?: number }) =>
      getPaged<Business>('/businesses', query),
    get: (id: string) => get<Business>(`/businesses/${id}`),
    create: (payload: BusinessCreate) => send<Business>('POST', '/businesses', payload),
    update: (id: string, payload: BusinessUpdate) =>
      send<Business>('PATCH', `/businesses/${id}`, payload),
    remove: (id: string) => send<{ message: string }>('DELETE', `/businesses/${id}`),

    credentials: (id: string) => get<Credentials>(`/businesses/${id}/credentials`),
    saveCredentials: (id: string, payload: CredentialsUpdate) =>
      send<Credentials>('PUT', `/businesses/${id}/credentials`, payload),
    verifyCredentials: (id: string) =>
      send<CredentialsCheck>('POST', `/businesses/${id}/credentials/verify`),
    refreshInstagramToken: (id: string) =>
      send<{ refreshed: boolean; expires_at: string | null }>(
        'POST',
        `/businesses/${id}/credentials/refresh-token`,
      ),

    knowledge: (id: string) => get<KnowledgeBase>(`/businesses/${id}/knowledge`),
    saveKnowledge: (id: string, payload: KnowledgeBaseUpdate) =>
      send<KnowledgeBase>('PUT', `/businesses/${id}/knowledge`, payload),
    ingestKnowledge: (id: string, text: string) =>
      send<KnowledgeIngestResult>('POST', `/businesses/${id}/knowledge/ingest`, { text }),
    ingestKnowledgeFile: (id: string, file: File) =>
      sendFile<KnowledgeIngestResult>(`/businesses/${id}/knowledge/ingest-file`, file),

    admins: (id: string) => get<Admin[]>(`/businesses/${id}/admins`),
    addAdmin: (id: string, payload: { telegram_user_id: number; full_name?: string; role?: string }) =>
      send<Admin>('POST', `/businesses/${id}/admins`, payload),
    removeAdmin: (id: string, adminId: string) =>
      send<{ message: string }>('DELETE', `/businesses/${id}/admins/${adminId}`),
  },

  plans: {
    list: (query?: { business_id?: string; page?: number; limit?: number }) =>
      getPaged<ContentPlan>('/plans', query),
    get: (id: string) => get<ContentPlanDetail>(`/plans/${id}`),
    approve: (id: string) => send<{ plan_id: string; approved: number }>('POST', `/plans/${id}/approve`),
    remove: (id: string) => send<{ message: string }>('DELETE', `/plans/${id}`),
  },

  items: {
    list: (filters?: ItemFilters) => getPaged<ContentItem>('/items', filters as Query),
    get: (id: string) => get<ContentItem>(`/items/${id}`),
    update: (id: string, payload: ContentItemUpdate) =>
      send<ContentItem>('PATCH', `/items/${id}`, payload),
    approve: (id: string) => send<ContentItem>('POST', `/items/${id}/approve`),
    reject: (id: string) => send<ContentItem>('POST', `/items/${id}/reject`),
    remove: (id: string) => send<{ message: string }>('DELETE', `/items/${id}`),
    bulkStatus: (itemIds: string[], status: ContentItemStatus) =>
      send<{ requested: number; updated: number }>('POST', '/items/bulk-status', {
        item_ids: itemIds,
        status,
      }),
    logs: (id: string) => get<PublishLogEntry[]>(`/items/${id}/logs`),
  },

  generate: {
    plan: (payload: GeneratePlanRequest) => send<GenerationTask>('POST', '/generate/plan', payload),
    item: (payload: GenerateItemRequest) => send<GenerationTask>('POST', '/generate/item', payload),
    regenerate: (itemId: string, instruction = '', regenerateImage = false) =>
      send<GenerationTask>('POST', `/generate/item/${itemId}/regenerate`, {
        instruction,
        regenerate_image: regenerateImage,
      }),
    publishNow: (itemId: string, force = false) =>
      send<GenerationTask>('POST', `/generate/item/${itemId}/publish`, { force }),
    task: (taskId: string) =>
      get<{ task_id: string; state: string; ready?: boolean; result?: unknown; error?: string }>(
        `/generate/task/${taskId}`,
      ),
  },

  prompts: {
    list: (query?: { business_id?: string; agent?: string; page?: number; limit?: number }) =>
      getPaged<PromptTemplate>('/prompts', query),
    get: (id: string) => get<PromptTemplate>(`/prompts/${id}`),
    create: (payload: PromptTemplateCreate) => send<PromptTemplate>('POST', '/prompts', payload),
    update: (id: string, payload: PromptTemplateUpdate) =>
      send<PromptTemplate>('PATCH', `/prompts/${id}`, payload),
    rollback: (id: string, version: number) =>
      send<PromptTemplate>('POST', `/prompts/${id}/rollback/${version}`),
    remove: (id: string) => send<{ message: string }>('DELETE', `/prompts/${id}`),
    agents: () => get<string[]>('/prompts/agents'),
    default: (agent: string) => get<{ agent: string; system_prompt: string }>(`/prompts/defaults/${agent}`),
  },

  analytics: {
    summary: () => get<AnalyticsSummary>('/analytics/summary'),
    business: (id: string) => get<BusinessAnalytics>(`/analytics/business/${id}`),
    failures: (hours = 24) => get<FailureEntry[]>('/analytics/failures', { hours }),
  },

  system: {
    providers: () => get<ProviderStatus>('/system/providers'),
    health: async (): Promise<boolean> => {
      try {
        const response = await fetch(`${BASE_URL}/health`);
        return response.ok;
      } catch {
        return false;
      }
    },
  },
};

/**
 * URL the browser should load a rendered card from.
 *
 * The backend stamps absolute URLs using its own `PUBLIC_BASE_URL`, which the
 * browser cannot always reach (different port, private network, container
 * hostname). Rewrite them onto the dashboard's own `/media` proxy so an image
 * loads wherever the dashboard itself loads.
 */
export function mediaUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;

  const marker = '/media/';
  const index = url.indexOf(marker);
  const path = index >= 0 ? url.slice(index) : url.startsWith('/') ? url : `/media/${url}`;
  return `${BASE_URL}${path}`;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
