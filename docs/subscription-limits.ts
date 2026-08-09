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
import type { PlanId } from "@/lib/pricing";

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
  const { data, error } = await supabase.rpc("get_org_usage_summary", { _org_id: id });
  if (error) dbError(error, "Could not load plan usage.");
  const usage = data as UsageSummary;

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
        `You've used your 3 free scans. You can scan again after ${unlock.toLocaleString()}.`,
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
    return `${usage.scans_used} / 3 scans used`;
  }
  if (usage.scans_included === null) {
    return `${usage.scans_used} scans · unlimited plan`;
  }
  return `${usage.scans_used} / ${usage.scans_included.toLocaleString("en-IN")} scans used this month`;
}

export function isUpgradeable(planCode: PlanId): boolean {
  return planCode !== "enterprise";
}
