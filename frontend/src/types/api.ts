/**
 * Typed contracts matching the backend FastAPI schemas exactly.
 */

export type JobStatus =
  | 'CREATED'
  | 'IN_PROGRESS'
  | 'PAUSED'
  | 'AWAITING_HUMAN'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export interface TargetStackSpec {
  runtime: string;
  framework: string;
  architecture: string;
  legacy_source?: string;
  [key: string]: unknown;
}

export interface JobBudget {
  max_total_cost_usd: number;
  max_duration_seconds: number;
  [key: string]: unknown;
}

export interface JobSummaryResponse {
  job_id: string;
  tenant_id: string;
  owner_user_id: string;
  status: JobStatus;
  source_ref: string;
  target_stack_spec: TargetStackSpec;
  budget: JobBudget;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface PaginationMetadata {
  offset: number;
  limit: number;
  total: number;
}

export interface JobListResponse {
  items: JobSummaryResponse[];
  pagination: PaginationMetadata;
}

export interface JobDetailResponse {
  job_id: string;
  tenant_id: string;
  owner_user_id: string;
  status: JobStatus;
  source_ref: string;
  target_stack_spec: TargetStackSpec;
  budget: JobBudget;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface JobCreateRequest {
  source_repository: string;
  source_revision: string;
  target_stack: TargetStackSpec;
  budget: JobBudget;
}

export interface JobCreateResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
}

export interface ArtifactDetailResponse {
  artifact_id: string;
  job_id: string;
  artifact_type: string;
  version: number;
  content_hash: string;
  storage_ref: string;
  derived_from: string[];
  artifact_metadata: Record<string, unknown>;
  created_at: string;
}

export interface ArtifactListResponse {
  items: ArtifactDetailResponse[];
  total: number;
}

export interface AuditEventResponse {
  event_id: string;
  job_id: string;
  actor: string;
  actor_user_id: string | null;
  action: string;
  correlation_id: string | null;
  payload: Record<string, unknown>;
  event_time: string;
  event_version: number;
}

export interface AuditEventListResponse {
  items: AuditEventResponse[];
  pagination: PaginationMetadata;
}

export interface GateFlag {
  code?: string;
  severity?: 'critical' | 'high' | 'medium' | 'low' | string;
  message?: string;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface GateDetailResponse {
  gate_id: string;
  job_id: string;
  gate_type: string;
  state: 'pending' | 'approved' | 'rejected' | 'timed_out' | 'paused' | string;
  requested_at: string;
  artifact_versions_shown: Record<string, unknown>;
  needs_human_flags: GateFlag[];
  budget_used_cents: number;
  resolved_at: string | null;
}

export interface GateListResponse {
  items: GateDetailResponse[];
  total: number;
}

export interface WaiverRequest {
  subject: string;
  reason: string;
}

export interface GateDecisionRequest {
  decision: 'approved' | 'rejected' | 'waived';
  feedback?: string | null;
  waivers?: WaiverRequest[];
}

export interface GateDecisionResponse {
  gate_id: string;
  decision_id: string;
  decision: string;
  decided_at: string;
}

export interface UserPrincipal {
  userId: string;
  tenantId: string;
  role: 'owner' | 'reviewer' | 'approver' | 'admin';
  token: string;
}
