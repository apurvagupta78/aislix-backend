"""Centralized role → five primary KPI configuration."""

from __future__ import annotations

from typing import TypedDict


class RoleKpiDefinition(TypedDict):
    kpi_id: str
    label: str
    tooltip: str


class RoleProfile(TypedDict):
    role_id: str
    label: str
    introduction: str
    primary_kpis: list[RoleKpiDefinition]


ROLE_PROFILES: dict[str, RoleProfile] = {
    "supermarket": {
        "role_id": "supermarket",
        "label": "Supermarket",
        "introduction": (
            "Evaluates on-shelf availability, planogram layout, mandatory assortment, "
            "shelf price labels, and active promotional execution for the selected store fixture."
        ),
        "primary_kpis": [
            {
                "kpi_id": "osa",
                "label": "On-Shelf Availability (OSA)",
                "tooltip": "Listed SKUs visibly available / listed SKUs assessed. Multiple facings count once per SKU.",
            },
            {
                "kpi_id": "planogram_compliance",
                "label": "Planogram Compliance",
                "tooltip": "Required positions passing all configured layout checks / required positions assessed.",
            },
            {
                "kpi_id": "assortment_compliance",
                "label": "Assortment Compliance",
                "tooltip": "Mandatory assortment SKUs visibly present / mandatory assortment SKUs assessed.",
            },
            {
                "kpi_id": "price_compliance",
                "label": "Price Compliance",
                "tooltip": "Required price-label positions meeting approved price requirements / positions assessed.",
            },
            {
                "kpi_id": "promotional_compliance",
                "label": "Promotional Compliance",
                "tooltip": "Active promotions passing all required visual checks / active promotions assessed.",
            },
        ],
    },
    "darkstore": {
        "role_id": "darkstore",
        "label": "Dark Store",
        "introduction": (
            "Evaluates pick-location accuracy, planogram adherence, assortment breadth, "
            "on-shelf availability, and facing counts for rapid fulfillment shelves."
        ),
        "primary_kpis": [
            {
                "kpi_id": "osa",
                "label": "On-Shelf Availability (OSA)",
                "tooltip": "Listed SKUs visibly available / listed SKUs assessed within the audited pick scope.",
            },
            {
                "kpi_id": "location_accuracy",
                "label": "Location Accuracy",
                "tooltip": "Occupied locations containing only approved SKUs / occupied locations assessed.",
            },
            {
                "kpi_id": "planogram_compliance",
                "label": "Planogram Compliance",
                "tooltip": "Required positions passing all configured layout checks / required positions assessed.",
            },
            {
                "kpi_id": "assortment_compliance",
                "label": "Assortment Compliance",
                "tooltip": "Mandatory assortment SKUs visibly present / mandatory assortment SKUs assessed.",
            },
            {
                "kpi_id": "facing_count",
                "label": "Facing Count",
                "tooltip": "Sum of visible front facings for assessed SKUs — partial count when coverage is incomplete.",
            },
        ],
    },
    "fmcg": {
        "role_id": "fmcg",
        "label": "FMCG Brand",
        "introduction": (
            "Evaluates brand share of shelf, on-shelf availability for listed SKUs, facing counts, "
            "planogram compliance, and promotional execution within the selected category scope."
        ),
        "primary_kpis": [
            {
                "kpi_id": "share_of_shelf",
                "label": "Share of Shelf (SOS)",
                "tooltip": "Brand occupied linear shelf space / total occupied linear space in the category.",
            },
            {
                "kpi_id": "osa",
                "label": "On-Shelf Availability (OSA)",
                "tooltip": "Listed SKUs visibly available / listed SKUs assessed for the brand scope.",
            },
            {
                "kpi_id": "facing_count",
                "label": "Facing Count",
                "tooltip": "Visible front facings for the selected brand across assessed positions.",
            },
            {
                "kpi_id": "planogram_compliance",
                "label": "Planogram Compliance",
                "tooltip": "Required positions passing all configured layout checks / required positions assessed.",
            },
            {
                "kpi_id": "promotional_compliance",
                "label": "Promotional Compliance",
                "tooltip": "Active promotions passing all required visual checks / active promotions assessed.",
            },
        ],
    },
    "distributor": {
        "role_id": "distributor",
        "label": "Distributor",
        "introduction": (
            "Evaluates outlet must-stock presence, on-shelf availability, planogram execution, "
            "price label compliance, and promotional visibility for the distributor portfolio."
        ),
        "primary_kpis": [
            {
                "kpi_id": "osa",
                "label": "On-Shelf Availability (OSA)",
                "tooltip": "Listed SKUs visibly available / listed SKUs assessed within the outlet scope.",
            },
            {
                "kpi_id": "msl_compliance",
                "label": "Must-Stock List (MSL) Compliance",
                "tooltip": "Required MSL SKUs visibly present / required MSL SKUs assessed for this outlet.",
            },
            {
                "kpi_id": "planogram_compliance",
                "label": "Planogram Compliance",
                "tooltip": "Required positions passing all configured layout checks / required positions assessed.",
            },
            {
                "kpi_id": "price_compliance",
                "label": "Price Compliance",
                "tooltip": "Required price-label positions meeting approved price requirements / positions assessed.",
            },
            {
                "kpi_id": "promotional_compliance",
                "label": "Promotional Compliance",
                "tooltip": "Active promotions passing all required visual checks / active promotions assessed.",
            },
        ],
    },
    "local": {
        "role_id": "local",
        "label": "Local Store",
        "introduction": (
            "Evaluates basic on-shelf availability, mandatory assortment, facing counts, "
            "price label accuracy, and promotional visibility for kirana-scale audits."
        ),
        "primary_kpis": [
            {
                "kpi_id": "osa",
                "label": "On-Shelf Availability (OSA)",
                "tooltip": "Listed SKUs visibly available / listed SKUs assessed.",
            },
            {
                "kpi_id": "assortment_compliance",
                "label": "Assortment Compliance",
                "tooltip": "Mandatory assortment SKUs visibly present / mandatory assortment SKUs assessed.",
            },
            {
                "kpi_id": "facing_count",
                "label": "Facing Count",
                "tooltip": "Sum of visible front facings for assessed SKUs.",
            },
            {
                "kpi_id": "price_compliance",
                "label": "Price Compliance",
                "tooltip": "Required price-label positions meeting approved price requirements / positions assessed.",
            },
            {
                "kpi_id": "promotional_compliance",
                "label": "Promotional Compliance",
                "tooltip": "Active promotions passing all required visual checks / active promotions assessed.",
            },
        ],
    },
}


def normalize_role_id(customer_type: str | None) -> str:
    ct = (customer_type or "supermarket").lower().strip()
    aliases = {
        "fmcg_brand": "fmcg",
        "brand": "fmcg",
        "dark_store": "darkstore",
        "kirana": "local",
        "local_store": "local",
        "audit_agency": "supermarket",
        "warehouse": "darkstore",
    }
    return aliases.get(ct, ct if ct in ROLE_PROFILES else "supermarket")


def get_role_profile(customer_type: str | None) -> RoleProfile:
    return ROLE_PROFILES[normalize_role_id(customer_type)]
