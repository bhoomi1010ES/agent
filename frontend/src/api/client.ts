import {
  SAMPLE_ARTIFACT_PAYLOADS,
  SAMPLE_ARTIFACTS,
  SAMPLE_AUDIT_TRAIL,
  SAMPLE_GATES,
  SAMPLE_JOB_DETAILS,
  SAMPLE_JOBS,
} from '../data/sampleWorkloads';
import type {
  ArtifactDetailResponse,
  ArtifactListResponse,
  AuditEventListResponse,
  GateDecisionRequest,
  GateDecisionResponse,
  GateDetailResponse,
  GateListResponse,
  JobCreateRequest,
  JobCreateResponse,
  JobDetailResponse,
  JobListResponse,
  JobStatus,
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Session storage keys for state persistence across reloads
const AUTH_TOKEN_KEY = 'modernization_auth_token';
const ACTIVE_ROLE_KEY = 'modernization_active_role';
const ACTIVE_TENANT_KEY = 'modernization_active_tenant';

export class APIError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.data = data;
  }
}

export function getAuthToken(): string {
  return sessionStorage.getItem(AUTH_TOKEN_KEY) || '';
}

export function setAuthToken(token: string): void {
  if (token) {
    sessionStorage.setItem(AUTH_TOKEN_KEY, token);
  } else {
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

export function getActiveRole(): string {
  return sessionStorage.getItem(ACTIVE_ROLE_KEY) || 'reviewer';
}

export function setActiveRole(role: string): void {
  sessionStorage.setItem(ACTIVE_ROLE_KEY, role);
}

export function getActiveTenantId(): string {
  return sessionStorage.getItem(ACTIVE_TENANT_KEY) || '00000000-0000-0000-0000-000000000001';
}

export function setActiveTenantId(tenantId: string): void {
  sessionStorage.setItem(ACTIVE_TENANT_KEY, tenantId);
}

/**
 * Universal request handler attaching credentials, correlation IDs, and standardizing error handling.
 */
async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const token = getAuthToken();

  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  // Attach Authorization header if token is present
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // Attach correlation ID for traceability
  if (!headers.has('X-Correlation-ID')) {
    headers.set('X-Correlation-ID', `req-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status} ${response.statusText}`;
    let errorData: unknown = null;

    try {
      errorData = await response.json();
      if (typeof errorData === 'object' && errorData !== null) {
        const payload = errorData as Record<string, unknown>;
        if (typeof payload.detail === 'string') {
          errorDetail = payload.detail;
        } else if (Array.isArray(payload.detail)) {
          // Pydantic validation errors
          errorDetail = payload.detail
            .map((err) => `${(err.loc || []).join('.')}: ${err.msg}`)
            .join('; ');
        }
      }
    } catch {
      // Non-JSON error body fallback
    }

    throw new APIError(response.status, errorDetail, errorData);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

// ==========================================
// Jobs API
// ==========================================

export async function listJobs(params?: {
  offset?: number;
  limit?: number;
  status?: JobStatus;
}): Promise<JobListResponse> {
  const query = new URLSearchParams();
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.status) query.set('status', params.status);

  const qs = query.toString();
  return request<JobListResponse>(`/jobs${qs ? `?${qs}` : ''}`);
}

export async function getJob(jobId: string): Promise<JobDetailResponse> {
  try {
    return await request<JobDetailResponse>(`/jobs/${jobId}`);
  } catch (err) {
    if (SAMPLE_JOB_DETAILS[jobId]) {
      return SAMPLE_JOB_DETAILS[jobId];
    }
    throw err;
  }
}

export async function createJob(payload: JobCreateRequest): Promise<JobCreateResponse> {
  return request<JobCreateResponse>('/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ==========================================
// Artifacts API
// ==========================================

export async function listJobArtifacts(
  jobId: string,
  artifactType?: string
): Promise<ArtifactListResponse> {
  const qs = artifactType ? `?artifact_type=${encodeURIComponent(artifactType)}` : '';
  try {
    return await request<ArtifactListResponse>(`/jobs/${jobId}/artifacts${qs}`);
  } catch (err) {
    if (SAMPLE_ARTIFACTS[jobId]) {
      let filtered = SAMPLE_ARTIFACTS[jobId];
      if (artifactType) {
        filtered = filtered.filter((a) => a.artifact_type === artifactType);
      }
      return { items: filtered, total: filtered.length };
    }
    throw err;
  }
}

export async function getJobArtifact(
  jobId: string,
  artifactType: string,
  version?: number
): Promise<ArtifactDetailResponse> {
  const qs = version ? `?version=${version}` : '';
  try {
    return await request<ArtifactDetailResponse>(`/jobs/${jobId}/artifacts/${artifactType}${qs}`);
  } catch (err) {
    const list = SAMPLE_ARTIFACTS[jobId] || [];
    const found = list.find(
      (a) => a.artifact_type === artifactType && (version === undefined || a.version === version)
    );
    if (found) return found;
    throw err;
  }
}

export async function getJobArtifactContent(
  jobId: string,
  artifactType: string,
  version?: number
): Promise<unknown> {
  const qs = version ? `?version=${version}` : '';
  const url = `${API_BASE_URL}/jobs/${jobId}/artifacts/${artifactType}/content${qs}`;
  const token = getAuthToken();

  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const response = await fetch(url, { headers });
    if (!response.ok) {
      throw new APIError(response.status, `Failed to fetch artifact content: HTTP ${response.status}`);
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return response.json();
    }
    return response.text();
  } catch (err) {
    if (SAMPLE_ARTIFACT_PAYLOADS[artifactType]) {
      return SAMPLE_ARTIFACT_PAYLOADS[artifactType];
    }
    throw err;
  }
}

// ==========================================
// Audit API
// ==========================================

export async function listJobAuditEvents(
  jobId: string,
  params?: { offset?: number; limit?: number }
): Promise<AuditEventListResponse> {
  const query = new URLSearchParams();
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.limit !== undefined) query.set('limit', String(params.limit));

  const qs = query.toString();
  try {
    return await request<AuditEventListResponse>(`/jobs/${jobId}/audit${qs ? `?${qs}` : ''}`);
  } catch (err) {
    const events = SAMPLE_AUDIT_TRAIL.filter((e) => e.job_id === jobId);
    if (events.length > 0 || SAMPLE_JOB_DETAILS[jobId]) {
      return {
        items: events,
        pagination: {
          offset: params?.offset || 0,
          limit: params?.limit || 50,
          total: events.length,
        },
      };
    }
    throw err;
  }
}

// ==========================================
// Gates API
// ==========================================

export async function listJobGates(jobId: string, state?: string): Promise<GateListResponse> {
  const qs = state ? `?state=${encodeURIComponent(state)}` : '';
  try {
    return await request<GateListResponse>(`/jobs/${jobId}/gates${qs}`);
  } catch (err) {
    if (SAMPLE_GATES[jobId]) {
      let gates = SAMPLE_GATES[jobId];
      if (state) {
        gates = gates.filter((g) => g.state === state);
      }
      return { items: gates, total: gates.length };
    }
    throw err;
  }
}

export async function getJobGate(jobId: string, gateId: string): Promise<GateDetailResponse> {
  try {
    return await request<GateDetailResponse>(`/jobs/${jobId}/gates/${gateId}`);
  } catch (err) {
    const gates = SAMPLE_GATES[jobId] || [];
    const found = gates.find((g) => g.gate_id === gateId);
    if (found) return found;
    throw err;
  }
}

export async function decideGate(
  jobId: string,
  gateId: string,
  payload: GateDecisionRequest
): Promise<GateDecisionResponse> {
  try {
    return await request<GateDecisionResponse>(`/jobs/${jobId}/gates/${gateId}/decisions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const gates = SAMPLE_GATES[jobId];
    if (gates) {
      const g = gates.find((item) => item.gate_id === gateId);
      if (g) {
        g.state = payload.decision;
        g.resolved_at = new Date().toISOString();
        return {
          gate_id: gateId,
          decision_id: `dec-${Date.now()}`,
          decision: payload.decision,
          decided_at: g.resolved_at,
        };
      }
    }
    throw err;
  }
}

/**
 * Convenience utility to seed the running backend database with the enterprise demo workloads.
 */
export async function seedDemoWorkloadsToBackend(): Promise<string[]> {
  const createdIds: string[] = [];
  for (const job of SAMPLE_JOBS) {
    try {
      const res = await createJob({
        source_repository: job.source_ref.split('@')[0],
        source_revision: job.source_ref.split('@')[1] || 'main',
        target_stack: {
          runtime: job.target_stack_spec.runtime,
          framework: job.target_stack_spec.framework,
          architecture: job.target_stack_spec.architecture,
        },
        budget: {
          max_total_cost_usd: job.budget.max_total_cost_usd,
          max_duration_seconds: job.budget.max_duration_seconds,
        },
      });
      createdIds.push(res.job_id);
    } catch {
      // Continue seeding other workloads
    }
  }
  return createdIds;
}

