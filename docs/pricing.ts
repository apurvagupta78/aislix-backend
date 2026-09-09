// Aislix plan catalogue. This is product configuration (not scan data), so it
// is defined statically here and consumed by both /pricing and /billing.
// Prices are in INR. Annual pricing = 10 months (≈17% saving).
//
// ICP labels (2026-09): aligned to buyers most likely to convert — FMCG field
// teams and audit agencies first; kirana/warehouse de-emphasized on paid tiers.

export type PlanId = "free" | "starter" | "growth" | "professional" | "enterprise";
export type BillingCycle = "monthly" | "annual";

export type Plan = {
  id: PlanId;
  name: string;
  tagline: string;
  /** Short audience label shown on pricing cards (badge under plan name). */
  audience?: string;
  /** 2–3 bullets: who this plan is honestly best for. */
  bestFor?: string[];
  /** Optional honest caveat — shown as muted text, not hidden. */
  notIdealFor?: string;
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

/** Primary ICP strip for /pricing hero — honest, conversion-focused. */
export const primaryIcpStrip =
  "Built for FMCG field teams, retail audit agencies, and multi-store ops — not generic image recognition.";

/** Who Aislix helps most (pricing page “Who it’s for” section). */
export const icpSegments: {
  title: string;
  description: string;
  recommendedPlan: PlanId;
  priority: "primary" | "secondary";
}[] = [
  {
    title: "FMCG brand field teams",
    description:
      "Reps photograph shelves in modern trade and general trade. Get SKU counts, brand share, and planogram gaps in minutes — export to CSV for your sales head.",
    recommendedPlan: "growth",
    priority: "primary",
  },
  {
    title: "Retail audit agencies",
    description:
      "Cut manual counting time per store visit. AI first pass + your auditor review. Scale audits without scaling headcount linearly.",
    recommendedPlan: "growth",
    priority: "primary",
  },
  {
    title: "Distributors & sales teams",
    description:
      "Spot-check outlet availability and shelf execution across your beat. One photo per visit, structured report back to HQ.",
    recommendedPlan: "starter",
    priority: "secondary",
  },
  {
    title: "Dark stores & small retail chains",
    description:
      "Daily or weekly category audits across a handful of locations. Multi-store dashboard and historical trends.",
    recommendedPlan: "professional",
    priority: "secondary",
  },
  {
    title: "National retail & enterprise FMCG",
    description:
      "Category onboarding, custom models, integrations, SLA, and unlimited scale. Pilot on your SKUs first.",
    recommendedPlan: "enterprise",
    priority: "primary",
  },
];

export const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "Pilot Aislix on real shelf photos",
    audience: "Evaluation & pilots",
    bestFor: [
      "Try before you buy on your own shelf images",
      "Demo to your team or client",
      "Single store, single user",
    ],
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
    tagline: "One rep, one store, recurring audits",
    audience: "Solo auditors & outlet checks",
    bestFor: [
      "Single distributor rep checking outlets",
      "Independent auditor or small consultancy",
      "One location with weekly shelf audits",
    ],
    notIdealFor: "Not built for large field teams — see Growth.",
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
    tagline: "Field teams auditing multiple stores",
    audience: "FMCG teams & audit agencies",
    bestFor: [
      "Regional FMCG brands (5–20 field reps)",
      "Audit agencies running 3+ stores per week",
      "Planogram compliance + CSV export to HQ",
    ],
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
    tagline: "Multi-store ops at higher volume",
    audience: "Dark stores & multi-location ops",
    bestFor: [
      "Dark store / q-commerce ops (3–5 locations)",
      "Larger audit firms with dedicated audit teams",
      "FMCG teams needing API + priority support",
    ],
    notIdealFor: "Enterprise chains should start with a pilot — contact sales.",
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
    tagline: "National scale with your categories onboarded",
    audience: "Large FMCG & retail chains",
    bestFor: [
      "National brands with custom SKU libraries",
      "Retail chains needing integrations & SLA",
      "Category packs tuned to your packaging",
    ],
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
        label: "Financial impact estimates",
        values: { free: false, starter: false, growth: true, professional: true, enterprise: true },
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

/** FAQ entries for /pricing — honest positioning. */
export const pricingFaqs: { q: string; a: string }[] = [
  {
    q: "Who is Aislix best for?",
    a: "FMCG field teams, retail audit agencies, and multi-store retail ops who need faster shelf audits — SKU counts, brand share, and planogram compliance from a phone photo. We are not a warehouse or inventory WMS.",
  },
  {
    q: "Will it work on every product category?",
    a: "Aislix works across FMCG categories (snacks, beverages, personal care, tea, etc.). Accuracy is strongest on categories you audit repeatedly. Enterprise customers can onboard custom SKU libraries for their brands.",
  },
  {
    q: "Do I need a planogram?",
    a: "No. You can run shelf audits without a planogram. Planogram mode is optional and compares expected vs actual shelf layout when you upload a planogram CSV.",
  },
  {
    q: "Can kirana stores use Aislix?",
    a: "Yes — the Free plan lets any store try shelf digitization. Paid plans are designed for teams doing recurring audits across stores, which is why Growth is our most popular plan for FMCG and agencies.",
  },
  {
    q: "How accurate is the AI?",
    a: "Treat Aislix as audit acceleration: AI produces a structured first pass in 1–3 minutes. Verify critical counts before acting. Accuracy improves with category focus and human corrections over time.",
  },
  {
    q: "Can we pilot before paying?",
    a: "Yes. Start on Free (5 scans / 24 hours), run your own shelf photos, then upgrade to Growth when your team is ready. Enterprise buyers should contact sales for a category pilot.",
  },
];
