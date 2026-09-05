// Aislix plan catalogue. This is product configuration (not scan data), so it
// is defined statically here and consumed by both /pricing and /billing.
// Prices are in INR. Annual pricing = 10 months (≈17% saving).

export type PlanId = "free" | "starter" | "growth" | "professional" | "enterprise";
export type BillingCycle = "monthly" | "annual";

export type Plan = {
  id: PlanId;
  name: string;
  tagline: string;
  /** Short audience label shown on pricing cards. */
  audience?: string;
  /** Monthly price in INR. `null` = quote-based (Enterprise). */
  monthlyPrice: number | null;
  /** Annual price in INR, billed yearly. `null` = quote-based. */
  annualPrice: number | null;
  scanLimitLabel: string;
  /** Included scans per billing month; null = unlimited. Free uses rolling 24h logic in DB. */
  monthlyScanQuota: number | null;
  /** Max active stores; null = unlimited. */
  storeLimit: number | null;
  /** Max team users (owner + invites); null = unlimited. */
  seatLimit: number | null;
  /** Scan history window in days; null = unlimited. */
  historyDays: number | null;
  features: string[];
  cta: string;
  popular?: boolean;
  contactSales?: boolean;
};

export const ANNUAL_MONTHS_BILLED = 10;

export const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "Try Aislix with your store",
    audience: "Try Aislix with your store",
    monthlyPrice: 0,
    annualPrice: 0,
    scanLimitLabel: "5 scans / 24 hours",
    monthlyScanQuota: 5,
    storeLimit: 1,
    seatLimit: 1,
    historyDays: 7,
    features: [
      "5 scans / 24 hours",
      "1 store",
      "1 user",
      "Scan history (last 7 days)",
      "AI product detection",
      "Annotated shelf image",
      "PDF audit report",
      "Basic dashboard analytics",
    ],
    cta: "Start free",
  },
  {
    id: "starter",
    name: "Starter",
    tagline: "For single-store retailers",
    audience: "Kirana & Local Stores",
    monthlyPrice: 999,
    annualPrice: 999 * ANNUAL_MONTHS_BILLED,
    scanLimitLabel: "300 scans / month",
    monthlyScanQuota: 300,
    storeLimit: 1,
    seatLimit: 1,
    historyDays: null,
    features: [
      "300 scans / month",
      "1 store",
      "1 user",
      "Unlimited scan history",
      "Multi-image upload",
      "AI shelf audit",
      "PDF & CSV reports",
      "Dashboard analytics",
      "Email support",
    ],
    cta: "Upgrade to Starter",
  },
  {
    id: "growth",
    name: "Growth",
    tagline: "For growing retail operations",
    audience: "Supermarkets & Multi-Store Retailers",
    monthlyPrice: 2999,
    annualPrice: 2999 * ANNUAL_MONTHS_BILLED,
    scanLimitLabel: "3,000 scans / month",
    monthlyScanQuota: 3000,
    storeLimit: 3,
    seatLimit: 3,
    historyDays: null,
    features: [
      "3,000 scans / month",
      "Up to 3 stores",
      "Up to 3 users",
      "Unlimited scan history",
      "Multi-store dashboard",
      "Advanced shelf analytics",
      "PDF & CSV reports",
      "Historical trends",
      "Email support",
    ],
    cta: "Upgrade to Growth",
    popular: true,
  },
  {
    id: "professional",
    name: "Professional",
    tagline: "For professional retail operations",
    audience: "Dark Stores & Retail Operations",
    monthlyPrice: 4999,
    annualPrice: 4999 * ANNUAL_MONTHS_BILLED,
    scanLimitLabel: "5,000 scans / month",
    monthlyScanQuota: 5000,
    storeLimit: 5,
    seatLimit: 5,
    historyDays: null,
    features: [
      "5,000 scans / month",
      "Up to 5 stores",
      "Up to 5 users",
      "Unlimited scan history",
      "Faster AI processing",
      "Advanced shelf analytics",
      "Historical trends",
      "Low stock alerts",
      "Priority support",
      "REST API access",
    ],
    cta: "Upgrade to Professional",
  },
  {
    id: "enterprise",
    name: "Enterprise",
    tagline: "For large-scale retail operations",
    audience: "Retail Chains & Enterprise",
    monthlyPrice: null,
    annualPrice: null,
    scanLimitLabel: "Unlimited scans",
    monthlyScanQuota: null,
    storeLimit: null,
    seatLimit: null,
    historyDays: null,
    features: [
      "Unlimited scans",
      "Unlimited stores",
      "Unlimited users",
      "Multi-location dashboard",
      "Custom AI models",
      "Custom integrations",
      "SLA",
      "Dedicated account manager",
      "SSO & audit logs",
    ],
    cta: "Contact sales",
    contactSales: true,
  },
];

export function getPlan(id?: string | null): Plan | undefined {
  return plans.find((p) => p.id === id);
}

export function formatInr(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}

export function priceFor(plan: Plan, cycle: BillingCycle): string {
  if (plan.monthlyPrice === null) return "Custom";
  if (plan.monthlyPrice === 0) return "₹0";
  if (cycle === "monthly") return formatInr(plan.monthlyPrice);
  return formatInr(Math.round((plan.annualPrice ?? 0) / 12));
}

export function annualSaving(plan: Plan): number {
  if (!plan.monthlyPrice || plan.annualPrice === null) return 0;
  return plan.monthlyPrice * 12 - plan.annualPrice;
}

/** Feature comparison matrix for the pricing table. */
export const comparisonGroups: {
  group: string;
  rows: { label: string; values: Record<PlanId, string | boolean> }[];
}[] = [
  {
    group: "Scanning",
    rows: [
      {
        label: "Scans included",
        values: {
          free: "5 / 24 hours",
          starter: "300 / month",
          growth: "3,000 / month",
          professional: "5,000 / month",
          enterprise: "Unlimited",
        },
      },
      {
        label: "Stores",
        values: {
          free: "1",
          starter: "1",
          growth: "3",
          professional: "5",
          enterprise: "Unlimited",
        },
      },
      {
        label: "Team users",
        values: {
          free: "1",
          starter: "1",
          growth: "3",
          professional: "5",
          enterprise: "Unlimited",
        },
      },
      {
        label: "Images per scan",
        values: {
          free: "1",
          starter: "Multi-image",
          growth: "Multi-image",
          professional: "Unlimited",
          enterprise: "Unlimited",
        },
      },
      {
        label: "Faster AI processing",
        values: {
          free: false,
          starter: false,
          growth: false,
          professional: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    group: "Reports & analytics",
    rows: [
      {
        label: "Annotated shelf image",
        values: { free: true, starter: true, growth: true, professional: true, enterprise: true },
      },
      {
        label: "PDF audit report",
        values: { free: true, starter: true, growth: true, professional: true, enterprise: true },
      },
      {
        label: "CSV export",
        values: { free: false, starter: true, growth: true, professional: true, enterprise: true },
      },
      {
        label: "Scan history",
        values: {
          free: "7 days",
          starter: "Unlimited",
          growth: "Unlimited",
          professional: "Unlimited",
          enterprise: "Unlimited",
        },
      },
      {
        label: "Historical trends",
        values: { free: false, starter: false, growth: true, professional: true, enterprise: true },
      },
      {
        label: "Low stock alerts",
        values: { free: false, starter: false, growth: true, professional: true, enterprise: true },
      },
      {
        label: "Multi-location dashboard",
        values: { free: false, starter: false, growth: true, professional: true, enterprise: true },
      },
    ],
  },
  {
    group: "Platform & support",
    rows: [
      {
        label: "Support",
        values: {
          free: "Community",
          starter: "Email",
          growth: "Email",
          professional: "Priority",
          enterprise: "Dedicated AM + SLA",
        },
      },
      {
        label: "REST API access",
        values: { free: false, starter: false, growth: false, professional: true, enterprise: true },
      },
      {
        label: "GST invoices",
        values: { free: false, starter: true, growth: true, professional: true, enterprise: true },
      },
    ],
  },
];

export type AddOn = {
  id: string;
  name: string;
  description: string;
  price: string;
  unit: string;
  available: boolean;
};

export const addOns: AddOn[] = [
  {
    id: "scan-pack-500",
    name: "Extra scan pack",
    description: "Top up 500 additional shelf scans, valid for 12 months.",
    price: "₹749",
    unit: "per pack",
    available: true,
  },
  {
    id: "ai-credits",
    name: "AI credits",
    description: "Additional AI recommendation and re-analysis credits.",
    price: "₹499",
    unit: "per 1,000 credits",
    available: true,
  },
  {
    id: "storage",
    name: "Extra image storage",
    description: "Retain annotated shelf images and reports for longer.",
    price: "₹299",
    unit: "per 100 GB / month",
    available: true,
  },
  {
    id: "seats",
    name: "Additional team members",
    description: "Add auditors and store managers beyond your plan seats.",
    price: "₹199",
    unit: "per seat / month",
    available: true,
  },
];
