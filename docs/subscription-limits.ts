/**
 * Subscription limit helpers — mirror DB enforcement in the app layer.
 * Copy to Lovable: src/lib/subscription-limits.ts
 *
 * DB triggers (migration 20260809120000) are the source of truth;
 * these helpers provide friendly errors and UI state before requests fail.
 */

import { ApiError } from "@/lib/api/errors";
import { dbError, requireOrgId } from "@/lib/db/context";
import { supabase } from "@/integrations/supabase/client";
import { plans, type PlanId } from "@/lib/pricing";

export type UsageSummary = {
  plan_code: PlanId;
  plan_name: string;
  scans_used: number;
  scans_included: number | null;
  scans_remaining: number | null;
  scan_limit_label: string;
  blocked: boolean;
  cooldown_until: string | null;
  stores_used: number;
  stores_included: number | null;
  seats_used: number;
  seats_included: number | null;
  seat_limit_label: string;
  history_days: number | null;
  period_end: string | null;
  platform_bypass?: boolean;
  platform_bypass_note?: string | null;
};

/** Internal testers — bypass plan enforcement but still display selected plan in UI. */
export const PLATFORM_BYPASS_EMAILS = ["apurv@aislix.com"] as const;

export function hasPlatformBypass(email?: string | null): boolean {
  if (!email) return false;
  return PLATFORM_BYPASS_EMAILS.includes(email.toLowerCase().trim() as (typeof PLATFORM_BYPASS_EMAILS)[number]);
}

function planCatalogDefaults(planCode: PlanId) {
  const plan = plans.find((p) => p.id === planCode) ?? plans.find((p) => p.id === "free")!;
  const scansUsedFallback = 0;
  const scansIncluded = plan.monthlyScanQuota;
  return {
    plan_name: plan.name,
    scans_included: scansIncluded,
    scans_remaining:
      scansIncluded === null ? null : Math.max(0, scansIncluded - scansUsedFallback),
    scan_limit_label: plan.scanLimitLabel,
    stores_included: plan.storeLimit,
    seats_included: plan.seatLimit,
    seat_limit_label:
      plan.seatLimit === null ? "Unlimited users" : `${plan.seatLimit} user${plan.seatLimit === 1 ? "" : "s"}`,
    history_days: plan.historyDays,
  };
}

/** Safe defaults when RPC returns partial/null fields (prevents "undefined stores" UI bugs). */
export function normalizeUsageSummary(raw: Partial<UsageSummary> | null | undefined): UsageSummary {
  const planCode = (raw?.plan_code ?? "free") as PlanId;
  const catalog = planCatalogDefaults(planCode);
  const scansUsed = raw?.scans_used ?? 0;
  const scansIncluded = raw?.scans_included ?? catalog.scans_included;
  const scansRemaining =
    raw?.scans_remaining ??
    (scansIncluded === null ? null : Math.max(0, scansIncluded - scansUsed));
  return {
    plan_code: planCode,
    plan_name: raw?.plan_name ?? catalog.plan_name,
    scans_used: scansUsed,
    scans_included: scansIncluded,
    scans_remaining: scansRemaining,
    scan_limit_label: raw?.scan_limit_label ?? catalog.scan_limit_label,
    blocked: raw?.blocked ?? false,
    cooldown_until: raw?.cooldown_until ?? null,
    stores_used: raw?.stores_used ?? 0,
    stores_included: raw?.stores_included ?? catalog.stores_included,
    seats_used: raw?.seats_used ?? 1,
    seats_included: raw?.seats_included ?? catalog.seats_included,
    seat_limit_label: raw?.seat_limit_label ?? catalog.seat_limit_label,
    history_days: raw?.history_days ?? catalog.history_days,
    period_end: raw?.period_end ?? null,
    platform_bypass: raw?.platform_bypass ?? false,
    platform_bypass_note: raw?.platform_bypass_note ?? null,
  };
}

export class ScanLimitError extends ApiError {
  cooldown_until?: string | null;

  constructor(message: string, cooldown_until?: string | null) {
    super({ message, kind: "quota_exceeded", status: 402 });
    this.cooldown_until = cooldown_until;
  }
}

export class StoreLimitError extends ApiError {
  constructor(message = "You've reached the maximum number of stores for your plan.") {
    super({
      message: `${message} Upgrade your plan to add more stores.`,
      kind: "quota_exceeded",
      status: 402,
    });
  }
}

export class SeatLimitError extends ApiError {
  constructor(message = "You've reached the maximum number of team members for your plan.") {
    super({
      message: `${message} Upgrade your plan to invite more users.`,
      kind: "quota_exceeded",
      status: 402,
    });
  }
}

export class HistoryLimitError extends ApiError {
  constructor() {
    super({
      message:
        "Scan history older than 7 days is available on paid plans. Upgrade to view your full history.",
      kind: "quota_exceeded",
      status: 402,
    });
  }
}

/** Loads usage from the DB RPC (keeps UI in sync with triggers). */
export async function fetchUsageSummary(orgId?: string): Promise<UsageSummary> {
  const id = orgId ?? (await requireOrgId());
  const { data, error } = await supabase.rpc("get_org_usage_summary", { p_org_id: id });
  if (error) dbError(error, "Could not load plan usage.");
  const usage = normalizeUsageSummary(data as Partial<UsageSummary>);

  const { data: authData } = await supabase.auth.getUser();
  if (hasPlatformBypass(authData.user?.email) || usage.platform_bypass) {
    return { ...usage, blocked: false, cooldown_until: null, platform_bypass: true };
  }
  return usage;
}

/** Pre-flight before creating a shelf_scans row. DB trigger is the backstop. */
export async function assertCanStartScan(orgId?: string): Promise<UsageSummary> {
  const id = orgId ?? (await requireOrgId());
  const { data: authData } = await supabase.auth.getUser();
  if (hasPlatformBypass(authData.user?.email)) {
    return fetchUsageSummary(id);
  }

  const usage = await fetchUsageSummary(id);

  if (usage.blocked) {
    if (usage.plan_code === "free" && usage.cooldown_until) {
      const unlock = new Date(usage.cooldown_until);
      throw new ScanLimitError(
        `You've used your 5 free scans. You can scan again after ${unlock.toLocaleString()}.`,
        usage.cooldown_until,
      );
    }
    throw new ScanLimitError(
      "You've reached your monthly scan limit. Upgrade your plan for more scans.",
    );
  }

  return usage;
}

/** Pre-flight before inserting a store row. DB trigger is the backstop. */
export async function assertCanAddStore(orgId?: string): Promise<UsageSummary> {
  const id = orgId ?? (await requireOrgId());
  const { data: authData } = await supabase.auth.getUser();
  if (hasPlatformBypass(authData.user?.email)) {
    return fetchUsageSummary(id);
  }

  const usage = await fetchUsageSummary(id);

  if (
    usage.stores_included !== null &&
    usage.stores_used >= usage.stores_included
  ) {
    throw new StoreLimitError();
  }

  return usage;
}

/** Pre-flight before inviting a team member. DB trigger is the backstop. */
export async function assertCanInviteMember(orgId?: string): Promise<UsageSummary> {
  const id = orgId ?? (await requireOrgId());
  const { data: authData } = await supabase.auth.getUser();
  if (hasPlatformBypass(authData.user?.email)) {
    return fetchUsageSummary(id);
  }

  const usage = await fetchUsageSummary(id);

  if (usage.seats_included !== null && usage.seats_used >= usage.seats_included) {
    throw new SeatLimitError();
  }

  return usage;
}

/** Free plan: hide scan history older than 7 days (data stays in DB). */
export function historyCutoffForPlan(planCode: PlanId, email?: string | null): Date | null {
  if (hasPlatformBypass(email)) return null;
  if (planCode !== "free") return null;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  return cutoff;
}

export function formatUsageLabel(usage: UsageSummary): string {
  if (usage.plan_code === "free") {
    return `${usage.scans_used} / 5 scans used`;
  }
  // Only Enterprise has unlimited monthly scans (scans_included === null).
  if (usage.scans_included === null) {
    return `${usage.scans_used.toLocaleString("en-IN")} scans · unlimited plan`;
  }
  return `${usage.scans_used.toLocaleString("en-IN")} / ${usage.scans_included.toLocaleString("en-IN")} scans used this month`;
}

/** Avoid epoch-zero dates (Dec 31 1969) when DB/demo data is missing or invalid. */
export function formatDisplayDate(value: string | number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || value === "" || value === 0) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime()) || date.getTime() < 86400000) return fallback;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function isUpgradeable(planCode: PlanId): boolean {
  return planCode !== "enterprise";
}
