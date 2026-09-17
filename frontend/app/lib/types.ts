// Mirrors backend/app/api/schemas.py — kept in lockstep manually for the prototype.
// A future Tier 1 task can codegen these from the FastAPI OpenAPI schema.

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Status =
  | "open"
  | "triaged"
  | "in_progress"
  | "fixed"
  | "auto_closed"
  | "risk_accepted"
  | "suppressed";
// Authorization collapsed to a single per-email flag: `is_admin` is true
// when the caller's email is in `config/rbac.yaml.admin_emails`, false
// otherwise. Everyone else who reaches the API (IAP gate is at the LB) is
// just an authenticated user with access to every non-/admin surface.
export type Me = {
  email: string;
  name: string;
  is_admin: boolean;
};

export type FindingSummary = {
  id: string;
  source: string;
  native_id: string;
  title: string;
  severity: Severity;
  status: Status;
  cve_id: string | null;
  asset_display: string;
  owner_team: string;
  first_seen_at: string;            // when WE ingested it (ingest provenance)
  last_seen_at: string;
  upstream_created_at: string | null; // source-system creation time
  reopened_at: string | null;         // set on auto_closed -> open
  sla_started_at: string;             // age + SLA anchor (use this in UI)
  age_days: number;
  sla_breached: boolean;
  wiz_category?: string | null;
  upstream_url?: string | null;
};

export type WizTitleGroup = {
  title: string;
  count: number;
  items: FindingSummary[];
};

export type WizCategoryGroup = {
  wiz_category: string;
  label: string;
  count: number;
  items: FindingSummary[];
  service_groups?: WizServiceGroup[] | null;
  title_groups?: WizTitleGroup[] | null;
};

export type WizServiceGroup = {
  wiz_service: string;
  service_label: string;
  owner_team: string;
  application?: string | null;
  count: number;
  items: FindingSummary[];
};

export type WizFindingsByCategoryResponse = {
  total: number;
  categories: WizCategoryGroup[];
};

export type FindingListResponse = {
  items: FindingSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type FindingEvent = {
  event_type: string;
  from_value: string | null;
  to_value: string;
  occurred_at: string;
  actor: string;
  reason: string | null;
};

export type FindingDetail = FindingSummary & {
  description: string;
  cwe_id: string | null;
  asset_id: string;
  asset_type: string;
  asset_root: string;
  correlation_group_id: string | null;
  consecutive_misses: number;
  raw_payload_uri: string;
  tags: string[];
  events: FindingEvent[];
};

// Open critical+high findings bucketed by age since `sla_started_at`.
// Powers the exec view's "what's been ignored?" horizontal stacked bar.
// Buckets are half-open at the top: `lte_7d` is (0, 7] days, `gt_90d` is
// (90, ∞). Always present — zeros when the scope is empty (so the bar
// renders deterministically without per-field null checks).
export type AgeBucketCounts = {
  lte_7d: number;
  lte_30d: number;
  lte_90d: number;
  gt_90d: number;
};

export type MetricsSummary = {
  open_criticals: number;
  // Nullable so we can distinguish honest "+0 WoW" (stable for a week) from
  // "we don't have 7d of observation history yet" (rendered as `history < 7d`
  // on the exec view). Backend nulls this when the in-scope earliest
  // `first_seen_at` is younger than 7d.
  open_criticals_wow_delta: number | null;
  sla_compliance_pct: number;
  mttr_critical_30d_seconds: number | null;
  // Earliest `first_seen_at` across findings in the response's scope. ISO-8601
  // UTC. Null when the scope is empty. Used by the exec view's KPI strip to
  // pick `history < 30d` vs `no closures in 30d` as the MTTR hint.
  observed_since: string | null;
  scanners_active: number;
  scanners_total: number;

  // ---- Executive-view extras --
  // Inflow / outflow counts of CRITICAL findings on a trailing 7d / 30d
  // window. Inflow = `discovered` ∪ `reopened` events; outflow = `fixed` ∪
  // `auto_closed`. Nulled when in-scope observation history is younger than
  // the window — the frontend renders `history < 7d` / `history < 30d`
  // hints from the null, NOT a confidently-wrong 0.
  new_critical_7d: number | null;
  closed_critical_7d: number | null;
  new_critical_30d: number | null;
  closed_critical_30d: number | null;
  age_buckets_open_crit_high: AgeBucketCounts;
  // Max `now - sla_started_at` across open criticals in scope. Null when
  // there are no open criticals — the KPI card renders "—".
  oldest_open_critical_age_seconds: number | null;
};

export type TrendPoint = { date: string; severity: Severity; open_count: number };
export type MetricsTrend = { window_days: number; points: TrendPoint[] };

// `open_criticals` + `open_highs` are surfaced separately so the executive
// offender list can render the per-severity breakdown next to each team /
// service row (a team with 5 criticals reads very differently from a team
// with 5 highs even when the totals match). `open_count` is kept as their
// sum for any older consumer.
export type TopTeamPoint = {
  team: string;
  open_criticals: number;
  open_highs: number;
  open_count: number;
};
export type TopAssetPoint = {
  asset_display: string;
  owner_team: string;
  open_criticals: number;
  open_highs: number;
  open_count: number;
};
export type SlaBreachItem = {
  finding_id: string;
  title: string;
  severity: Severity;
  owner_team: string;
  asset_display: string;
  age_days: number;
};

export type ScannerHealth = {
  source: string;
  last_seen_at: string | null;
  expected_cadence_seconds: number | null;
  status: "active" | "stale" | "dark" | "no_data";
};

export type ScannerHealthResponse = {
  items: ScannerHealth[];
  active: number;
  total: number;
};

export type TeamItem = {
  name: string;
  display_name: string | null;
  pillar: string | null;
  pillar_name: string | null;
};

export type TeamListResponse = { items: TeamItem[] };

// ---------------------------------------------------------------------------
// Security posture / rating
// ---------------------------------------------------------------------------

export type SourceSeverityCount = {
  criticals: number;
  highs: number;
};

export type SeverityBreakdown = {
  critical: number;
  high: number;
  medium: number;
  low: number;
};

export type RatingScoreBreakdown = {
  criticals_score: number;  // 0–35
  sla_score: number;        // 0–35
  mttr_score: number;       // 0–15
  highs_score: number;      // 0–15
};

export type SourceRating = {
  source: "sonarcloud" | "dependabot" | "pentest" | "wiz";
  grade: "A" | "B" | "C" | "D";
  open_criticals: number;
  open_highs: number;
  open_mediums: number;
  rationale: string;
};

export type SecurityPosture = {
  rating: "A" | "B" | "C" | "D";
  score: number;
  score_breakdown: RatingScoreBreakdown;
  open_criticals: number;
  open_highs: number;
  sonarcloud: SourceSeverityCount;
  dependabot: SourceSeverityCount;
  criticals_out_of_sla: number;
  highs_out_of_sla: number;
  pentest_open: SeverityBreakdown;
  pentest_out_of_sla: SeverityBreakdown;
  source_ratings: SourceRating[];
};

// ---------------------------------------------------------------------------
// Shared filter state (used by FindingsTable + server pages for deep-link init)
// ---------------------------------------------------------------------------

export type SlaFilter = "any" | "breached" | "ok";

export type FilterState = {
  severities?: Severity[];
  status?: Status | "";
  team?: string;
  source?: string;
  title?: string;
  asset?: string;
  sla?: SlaFilter;
};

export type ApiTokenSummary = {
  id: string;
  label: string | null;
  prefix: string;
  expires_at: string | null;
  created_at: string;
  last_used_at: string | null;
};

export type ApiTokenListResponse = {
  items: ApiTokenSummary[];
  max_active: number;
};

export type ApiTokenCreatedResponse = ApiTokenSummary & {
  token: string;
};

export type McpConfigResponse = {
  mcp_server_url: string;
};

export type DlqEventItem = {
  id: number;
  message_id: string;
  source: string | null;
  poll_id: string | null;
  raw_uri: string | null;
  failure_reason: string | null;
  delivery_attempt: number;
  received_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
};

export type DlqListResponse = {
  items: DlqEventItem[];
  unresolved_count: number;
};

export type PollerInfo = {
  source: "dependabot" | "sonarcloud";
  job_name: string | null;
  trigger_mode: "cloud_run" | "local";
};

export type PollerListResponse = {
  items: PollerInfo[];
  slack_configured: boolean;
};

export type PollerRunResponse = {
  source: "dependabot" | "sonarcloud";
  mode: "cloud_run" | "local";
  job_name: string | null;
  execution_name: string | null;
  message: string;
};

export type OwnershipStatusResponse = {
  owner_team_counts: { team: string; count: number }[];
  unowned_count: number;
  excluded_count: number;
  ownership_changed_7d: number;
  recent_events: {
    occurred_at: string;
    from_team: string | null;
    to_team: string;
    actor: string;
  }[];
  trigger_mode: "cloud_run" | "local";
};

export type OwnershipReresolveResponse = {
  mode: "cloud_run" | "local";
  job_name: string | null;
  execution_name: string | null;
  rollup_execution_name: string | null;
  message: string;
  scanned?: number;
  updated?: number;
  by_transition?: Record<string, number>;
  rollup_triggered?: boolean;
};

// --- Cloud security coverage -----------------------------------------------
// Coverage answers "how much of what should be protected is", so every figure
// is an X/Y with the denominator visible. `pct` is null when the denominator is
// empty — that is `na`, never 100%.
export type CoverageRag = "green" | "amber" | "red" | "na";

export type CoverageRatio = {
  covered: number;
  in_scope: number;
  excepted: number;
  gaps: number;
  pct: number | null;
};

export type CoverageSecondary = {
  key: string;
  label: string;
  unit: string;
  ratio: CoverageRatio;
};

export type CoverageMetric = {
  key: string;
  label: string;
  definition: string;
  unit: string;
  ratio: CoverageRatio;
  rag: CoverageRag;
  delta_pts: number | null;
  trend: number[];
  gap_items: string[];
  unavailable_sources: string[];
  secondary: CoverageSecondary | null;
};

export type CoverageLayer = {
  key: string;
  label: string;
  scope: string;
  metrics: CoverageMetric[];
};

export type CoverageProjectCell = {
  metric: string;
  label: string;
  ratio: CoverageRatio;
  rag: CoverageRag;
  note: string;
  unavailable_sources: string[];
};

export type CoverageProject = {
  key: string;
  label: string;
  flagship: boolean;
  cells: CoverageProjectCell[];
};

export type CoverageResponse = {
  as_of: string;
  collection_mode: "live" | "sample";
  stale: boolean;
  green_pct: number;
  amber_pct: number;
  layers: CoverageLayer[];
  projects: CoverageProject[];
  unmapped: { repos: number; cloud_accounts: number };
  degraded_sources: string[];
};
