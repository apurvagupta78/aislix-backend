"""Scan location and aisle context for category-aware product recognition."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.catalog import infer_category

BASE_DIR = Path(__file__).resolve().parent.parent
CATEGORIES_PATH = BASE_DIR / "data" / "categories.json"

# Aislix retail aisle → catalog.json category values (lowercase).
AISLIX_TO_CATALOG: dict[str, list[str]] = {
    "beverages": ["beverages"],
    "fresh food": ["general"],
    "dairy & chilled": ["dairy"],
    "grocery & staples": ["staples"],
    "packaged food & snacks": ["snacks", "bakery & biscuits"],
    "frozen foods & ice cream": ["dairy", "general"],
    "personal care": ["personal care"],
    "home care": ["household"],
    "health & wellness": ["personal care", "general"],
    "baby & pet care": ["general", "dairy"],
    "others": ["general"],
}

# Typical brands per aisle — used to reject obvious cross-aisle false positives.
AISLE_BRAND_HINTS: dict[str, set[str]] = {
    "beverages": {
        "lipton", "tetley", "tata", "brooke bond", "taj mahal", "red label", "yellow label",
        "nescafe", "bru", "coca cola", "pepsi", "frooti", "maaza", "real", "tropicana",
        "boost", "horlicks", "complan", "bournvita", "sprite", "fanta", "paper boat", "tang",
        "minute maid", "mirinda", "7up", "mountain dew",
    },
    "packaged food & snacks": {
        "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "sunfeast", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "too yumm", "act ii",
        "cadbury", "nestle", "amul", "itc", "priya gold", "snickers", "mars", "figaro",
    },
    "personal care": {
        "dove", "lux", "lifebuoy", "himalaya", "colgate", "pepsodent", "closeup",
        "head & shoulders", "pantene", "sunsilk", "gillette", "nivea", "ponds", "pond's",
        "dettol", "pears", "tresemme", "tresemmé", "sensodyne", "loreal", "l'oreal",
        "lakme", "lakmé", "clinic plus", "indulekha", "mamaearth", "garnier", "joy",
        "simple", "clear", "meera", "oral-b", "oral b", "tressemme",
    },
    "home care": {
        "surf excel", "ariel", "rin", "tide", "vim", "harpic", "lizol", "domex",
        "good knight", "all out", "odonil", "airwick",
    },
    "dairy & chilled": {
        "amul", "mother dairy", "nestle", "britannia", "go", "epigamia", "yakult", "sofit",
    },
    "frozen foods & ice cream": {
        "amul", "baskin robbins", "brooklyn", "kwality", "walls", "havmor", "vadilal",
        "cream bell", "go", "mother dairy",
    },
    "grocery & staples": {
        "india gate", "fortune", "saffola", "aashirvaad", "pillsbury", "mdh", "everest",
        "tata sampann", "patanjali", "24 mantra",
    },
}

# Food / snack brands that must not appear on personal care, home care, etc.
FOOD_SNACK_BRANDS: set[str] = {
    "snickers", "mars", "cadbury", "kitkat", "munch", "perk", "galaxy", "twix", "bounty",
    "figaro", "haldiram", "haldiram's", "britannia", "parle", "lays", "lay's", "kurkure",
    "bingo", "maggi", "maggie", "nutella", "american garden", "jabsons", "nutrela",
    "blue bird", "shan", "homelite", "knorr", "kellogg's", "kelloggs", "quaker", "rite",
}

# SKU/product tokens that indicate snacks — reject outside snack aisle audits.
CROSS_AISLE_SNACK_TOKENS = (
    "choco_berry", "protein_bar", "caster_sugar", "namkeen", "biscuit",
    "cheese_slices", "peanut", "jalapeno", "trident", "snack", "bhujia", "wafer",
)

# Beverage SKU tokens — reject outside beverage aisle audits.
CROSS_AISLE_BEVERAGE_TOKENS = (
    "soft_drink", "soft drink", "nescafe", "green_tea", "tea_bags", "tea_bag",
    "instant_coffee", "filter_coffee", "mineral_water", "fruit_drink", "mango_drink",
)

# Personal care SKU tokens — reject outside PC / health & wellness audits.
CROSS_AISLE_PC_TOKENS = (
    "shampoo", "conditioner", "toothpaste", "toothbrush", "hand_wash", "handwash",
    "bathing_bar", "face_wash", "facewash",
)

# Aisle keys where snack / beverage / PC product tokens are expected (not cross-aisle).
SNACK_AISLE_KEYS = frozenset({"packaged food & snacks"})
BEVERAGE_AISLE_KEYS = frozenset({"beverages"})
PC_AISLE_KEYS = frozenset({"personal care", "health & wellness"})
GROCERY_AISLE_KEYS = frozenset({"grocery & staples"})
BLUE_BRAND_ALLOWED_AISLES = GROCERY_AISLE_KEYS | SNACK_AISLE_KEYS

# Backward-compatible alias used in tests/docs.
PC_SNACK_SKU_TOKENS = CROSS_AISLE_SNACK_TOKENS

# Brands that must never appear when a specific aisle category is selected.
AISLE_BRAND_BLOCKLIST: dict[str, set[str]] = {
    "beverages": {
        "mars", "cadbury", "snickers", "kitkat", "munch", "perk", "galaxy", "twix",
        "bounty", "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "sunfeast",
        "dove", "lux", "colgate", "pepsodent", "harpic", "vim", "surf excel", "sofit",
        "figaro",
    },
    "packaged food & snacks": {
        "lipton", "tetley", "coca cola", "pepsi", "sprite", "fanta", "tropicana", "mirinda",
    },
    "personal care": FOOD_SNACK_BRANDS
    | {
        "lipton", "tetley", "coca cola", "pepsi", "sprite", "fanta", "mirinda", "real",
        "surf excel", "ariel", "rin", "tide", "vim", "harpic",
        "ragu", "davidoff", "twinings", "twinning", "schweppes", "girnar", "ritebite",
        "rite bite", "trident", "american garden", "blue bird", "blue", "shan", "knorr", "rite",
        "taj", "taj mahal", "brooke", "brooke bond", "tata", "nescafe", "bru",
    },
    "home care": FOOD_SNACK_BRANDS | {"lipton", "tetley", "coca cola", "pepsi", "dove", "colgate"},
    "health & wellness": FOOD_SNACK_BRANDS | {"lipton", "coca cola", "pepsi", "lays"},
    "dairy & chilled": {"dove", "lux", "colgate", "harpic", "surf excel", "lipton", "lays"},
}

# Sub-category blocklists (cross-type within aisle). Keys are normalized sub_category ids.
SUB_CATEGORY_BLOCKLIST: dict[str, set[str]] = {
    "tea": {
        "coca", "coca cola", "coca-cola", "pepsi", "fanta", "sprite", "real", "tropicana",
        "maaza", "frooti", "paper boat", "minute maid", "sofit", "mirinda", "7up",
    },
    "juices": {"lipton", "tetley", "tata", "brooke", "brooke bond"},
    "soft_drinks": {"lipton", "tetley", "tata", "brooke bond", "brooke"},
    "coffee": {"coca cola", "pepsi", "sprite", "fanta", "mirinda", "lipton", "tetley"},
    "water": {"lipton", "tetley", "coca cola", "pepsi", "snickers", "cadbury"},
    "shampoo": {
        "taj", "taj mahal", "lipton", "tetley", "tata", "brooke", "brooke bond",
        "coca", "pepsi", "sprite", "fanta", "mirinda", "nescafe", "bru",
        "colgate", "pepsodent", "sensodyne", "closeup", "oral-b", "oral b",
        "haldiram", "haldiram's", "britannia", "parle", "maggi", "lays", "rite",
    },
    "chips": {
        "bagrrys", "hersheys", "del", "knorr", "oetker", "dr oetker", "dr",
        "lipton", "tetley", "tata", "brooke", "brooke bond", "taj", "taj mahal",
        "nescafe", "bru", "coca", "pepsi", "sprite", "fanta", "dove", "pantene",
        "colgate", "harpic", "surf", "ariel", "vim", "dettol",
    },
    "namkeen": {
        "bagrrys", "hersheys", "del", "knorr", "oetker", "lipton", "tetley", "tata",
        "dove", "pantene", "colgate", "harpic", "nescafe", "bru",
    },
    "biscuits": {
        "lipton", "tetley", "tata", "dove", "pantene", "colgate", "harpic", "knorr",
        "del", "bagrrys", "nescafe", "bru", "coca", "pepsi",
    },
    "noodles": {
        "lipton", "tetley", "tata", "dove", "pantene", "colgate", "harpic", "hersheys",
        "bagrrys", "del", "oetker", "nescafe", "bru",
    },
}

NARROW_PC_SUBCATEGORIES = frozenset({"shampoo", "soap", "toothpaste", "deodorant", "skincare"})

SHAMPOO_REJECT_TEXT = (
    "roll on", "roll-on", "deodorant", "toothpaste", "tooth brush", "toothbrush",
    "tea bags", "tea bag", "taj mahal", "red label", "yellow label", "green tea",
    "antiseptic liquid", "soap bar", "bathing bar", "namkeen", "biscuit",
)

# Product-text tokens that should not appear on a focused sub-category audit.
SUB_CATEGORY_REJECT_TEXT: dict[str, tuple[str, ...]] = {
    "shampoo": SHAMPOO_REJECT_TEXT,
    "chips": (
        "muesli", "olive", "mayonnaise", "mayo", "kisses", "cup soup", "cup_soup",
        "funfoods", "oetker", "shampoo", "conditioner", "toothpaste", "tea bag",
        "green tea", "detergent", "harpic", "namkeen", "bhujia",
    ),
    "namkeen": (
        "muesli", "olive", "mayonnaise", "kisses", "shampoo", "conditioner",
        "toothpaste", "tea bag", "green tea", "detergent", "potato chips",
    ),
    "biscuits": (
        "shampoo", "conditioner", "toothpaste", "olive", "muesli", "detergent",
        "tea bag", "green tea", "namkeen", "bhujia",
    ),
    "noodles": (
        "shampoo", "olive", "muesli", "kisses", "detergent", "toothpaste", "tea bag",
    ),
    "tea": (
        "shampoo", "conditioner", "toothpaste", "namkeen", "bhujia", "detergent",
        "harpic", "potato chips", "mayonnaise",
    ),
}

# Expected brands when a narrow sub-category is selected (OCR can override).
SUB_CATEGORY_BRAND_HINTS: dict[str, dict[str, set[str]]] = {
    "personal care": {
        "shampoo": {
            "dove", "pantene", "sunsilk", "head & shoulders", "tresemme", "tresemmé",
            "clinic plus", "loreal", "l'oreal", "garnier", "indulekha", "himalaya",
            "clear", "meera", "sunsilk", "schwarzkopf", "dabur", "vatika",
        },
        "soap": {
            "lux", "dove", "dettol", "pears", "lifebuoy", "santoor", "hamam", "cinthol",
            "medimix", "margo", "fiama", "yardley",
        },
        "toothpaste": {
            "colgate", "pepsodent", "sensodyne", "closeup", "dabur", "himalaya", "oral-b",
            "oral b", "meswak",
        },
        "deodorant": {"axe", "denim", "park avenue", "fogg", "nivea", "dove", "rexona"},
        "skincare": {"nivea", "ponds", "pond's", "mamaearth", "garnier", "himalaya", "joy", "simple"},
        "cosmetics": {"lakme", "lakmé", "maybelline", "loreal", "l'oreal", "colorbar"},
        "shaving": {"gillette", "dorco", "bombay shaving", "park avenue"},
    },
    "beverages": {
        "tea": {"lipton", "tetley", "tata", "brooke bond", "taj mahal", "red label", "yellow label"},
        "coffee": {"nescafe", "bru", "davidoff", "continental"},
        "soft_drinks": {"coca cola", "pepsi", "sprite", "fanta", "mirinda", "7up", "mountain dew"},
        "juices": {"real", "tropicana", "paper boat", "b natural", "minute maid", "frooti", "maaza"},
    },
    "frozen foods & ice cream": {
        "ice_cream": {
            "amul", "baskin robbins", "brooklyn", "kwality", "walls", "havmor", "vadilal",
            "cream bell", "go", "mother dairy",
        },
    },
}

# Product-type keywords for sub-category inference (compliance / mismatch detection).
SUB_CATEGORY_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "shampoo": ["shampoo", "conditioner", "hair fall", "anti dandruff", "hair care", "keratin", "hyaluron", "vatika"],
    "soap": ["soap", "handwash", "hand wash", "bathing bar", "bath bar", "antiseptic liquid"],
    "hand_care": ["hand wash", "handwash", "hand-wash", "hand sanitizer", "sanitizer"],
    "toothpaste": ["toothpaste", "toothbrush", "tooth brush", "dental", "oral care", "mouthwash"],
    "deodorant": ["deodorant", "deo", "body spray", "antiperspirant"],
    "skincare": ["face wash", "facewash", "moistur", "lotion", "cream", "serum", "sunscreen", "spf"],
    "cosmetics": ["lipstick", "kajal", "mascara", "foundation", "compact", "nail polish"],
    "shaving": ["razor", "shaving", "aftershave", "shave gel", "shave foam"],
    "tea": ["tea", "chai", "green tea", "tea bags", "tea bag", "premix", "tulsi", "masala chai", "organic india", "darjeeling"],
    "coffee": ["coffee", "nescafe", "instant coffee", "filter coffee"],
    "soft_drinks": ["cola", "coke", "pepsi", "sprite", "fanta", "mirinda", "soft drink", "soda"],
    "juices": ["juice", "mango drink", "fruit drink", "nectar"],
    "water": ["mineral water", "packaged water", "drinking water"],
    "ice_cream": ["ice cream", "kulfi", "funwich", "frozen dessert", "sorbet", "gelato", "cone", "sandwich"],
    "energy_drinks": ["energy drink", "red bull", "monster"],
    "sports_drinks": ["sports drink", "electrolyte", "isotonic"],
    "detergent": ["detergent", "washing powder", "laundry"],
    "dishwash": ["dishwash", "dish wash", "utensil cleaner"],
    "floor_cleaner": ["floor cleaner", "floor mop"],
    "toilet_cleaner": ["toilet cleaner", "harpic"],
    "disinfectants": ["disinfect", "sanitizer", "antiseptic"],
    "air_fresheners": ["air freshener", "room freshener", "odonil"],
    "insecticides": ["mosquito", "insecticide", "repellent", "good knight", "all out"],
    "biscuits": ["biscuit", "cookie", "cracker", "marie"],
    "chips": ["chips", "crisps", "wafers"],
    "namkeen": ["namkeen", "bhujia", "mixture"],
    "noodles": ["noodles", "maggi", "instant noodles"],
    "chocolates": ["chocolate", "cocoa"],
    "milk": ["milk", "toned milk", "full cream milk"],
    "curd": ["curd", "yogurt", "dahi"],
    "paneer": ["paneer"],
    "rice": ["rice", "basmati"],
    "atta": ["atta", "flour", "whole wheat"],
    "dal": ["dal", "lentil", "pulse"],
    "oil": ["cooking oil", "mustard oil", "sunflower oil", "refined oil"],
}

# Product types used to block wrong label propagation across all aisles.
PROPAGATION_PRODUCT_TYPES = (
    "shampoo", "soap", "toothpaste", "hand_care",
    "tea", "coffee", "soft_drinks", "juices", "water",
    "biscuits", "chips", "namkeen", "noodles", "chocolates",
    "detergent", "dishwash", "floor_cleaner", "toilet_cleaner",
    "milk", "atta", "rice", "oil",
)

def _cross_aisle_sku_conflict(aislix_key: str, brand_l: str, sku_l: str) -> bool:
    """True when SKU/brand tokens belong to a different aisle than the audit selection."""
    haystack = f"{sku_l} {brand_l}"

    if aislix_key not in SNACK_AISLE_KEYS and aislix_key not in GROCERY_AISLE_KEYS:
        if brand_l == "rite":
            return True
        if any(token in haystack for token in CROSS_AISLE_SNACK_TOKENS):
            return True

    if aislix_key not in BEVERAGE_AISLE_KEYS:
        if any(token in sku_l for token in CROSS_AISLE_BEVERAGE_TOKENS):
            return True
        if brand_l in {"coca", "pepsi", "lipton", "tetley", "fanta", "sprite", "mirinda", "nescafe", "bru"}:
            if brand_l not in (AISLE_BRAND_HINTS.get(aislix_key) or set()):
                return True

    if aislix_key not in PC_AISLE_KEYS:
        if any(token in sku_l for token in CROSS_AISLE_PC_TOKENS):
            return True

    if aislix_key not in BLUE_BRAND_ALLOWED_AISLES and brand_l == "blue":
        return True

    if aislix_key in PC_AISLE_KEYS:
        if brand_l in {"taj", "lipton", "tetley", "brooke", "tata", "nescafe", "bru", "coca", "pepsi"}:
            return True

    return False


HAND_SANITIZER_KEYWORDS = ("hand sanitizer", "sanitizer", "hand sanitiser")
HANDWASH_KEYWORDS = ("hand wash", "handwash", "hand-wash")


def _infer_product_type(text: str) -> str | None:
    text_l = _normalize_key(text)
    if len(text_l) < 3:
        return None
    if any(kw in text_l for kw in HAND_SANITIZER_KEYWORDS):
        return "hand_sanitizer"
    if any(kw in text_l for kw in HANDWASH_KEYWORDS):
        return "hand_care"
    best_score = 0
    best_type: str | None = None
    for ptype in PROPAGATION_PRODUCT_TYPES:
        keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(ptype) or []
        score = sum(1 for kw in keywords if kw in text_l)
        if score > best_score:
            best_score = score
            best_type = ptype
    return best_type if best_score > 0 else None


SNACK_PRODUCT_TYPES = frozenset({"chips", "namkeen", "biscuits", "noodles", "chocolates"})


def compatible_product_types(left: str, right: str) -> bool:
    """True when two inferred product types can coexist on the same snack-facing audit."""
    if left == right:
        return True
    if left in SNACK_PRODUCT_TYPES and right in SNACK_PRODUCT_TYPES:
        return True
    return False


def infer_product_type(text: str) -> str | None:
    """Public wrapper for product-type inference from label or OCR text."""
    return _infer_product_type(text)


def product_type_matches_sub_category(
    sub_category: str,
    label: dict,
    ocr_text: str = "",
) -> bool:
    """Return True when a proposed label fits the scan sub-category."""
    sub = _slug_key(sub_category)
    if not sub or sub == "others":
        return True

    label_text = " ".join(
        [
            label.get("brand") or "",
            label.get("product_name") or "",
            label.get("variant") or "",
            label.get("sku") or "",
        ]
    )
    label_type = _infer_product_type(label_text)
    ocr_type = _infer_product_type(ocr_text) if ocr_text and len(ocr_text.strip()) >= 3 else None

    if ocr_type and label_type and not compatible_product_types(ocr_type, label_type):
        return False

    if label_type and label_type != sub and not compatible_product_types(label_type, sub):
        return False

    if ocr_type and ocr_type != sub and not compatible_product_types(ocr_type, sub):
        if label_type not in {None, sub} and not compatible_product_types(label_type, sub):
            return False

    return True


def strict_subcategory_gates_enabled() -> bool:
    return os.getenv("STRICT_SUBCATEGORY_GATES", "true").lower() in {"1", "true", "yes"}


def propagation_type_conflict(ref_label: dict, probe_text: str) -> bool:
    """True when reference label and probe OCR text indicate different product types."""
    ref_parts = [
        ref_label.get("brand") or "",
        ref_label.get("product_name") or "",
        ref_label.get("variant") or "",
    ]
    ref_type = _infer_product_type(" ".join(ref_parts))
    probe_type = _infer_product_type(probe_text)
    if not ref_type or not probe_type:
        return False
    if {ref_type, probe_type} == {"hand_sanitizer", "hand_care"}:
        return True
    return ref_type != probe_type

# Cross-aisle product keywords for compliance (wrong putaway on a focused audit).
AISLE_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "beverages": [
        "coffee", "espresso", "tea", "camomile", "chamomile", "cola", "coke", "pepsi",
        "juice", "soda water", "schweppes", "kahwa", "nescafe", "soft drink", "energy drink",
        "mineral water", "green tea",
    ],
    "packaged food & snacks": [
        "pizza sauce", "pasta sauce", "tomato sauce", "namkeen", "biscuit", "cookie",
        "protein bar", "choco berry", "chocolate", "jalapeno", "trident", "gum",
        "caster sugar", "peanut", "olive", "snack", "chips", "maggi", "noodles",
    ],
    "grocery & staples": [
        "caster sugar", "sugar", "atta", "flour", "rice", "dal", "lentil", "masala", "spice",
    ],
    "dairy & chilled": ["milk", "curd", "paneer", "cheese", "butter", "yogurt", "dahi"],
    "home care": [
        "detergent", "dishwash", "floor cleaner", "toilet cleaner", "harpic", "surf excel",
        "lizol", "mosquito repellent",
    ],
}

AISLE_DISPLAY_NAMES: dict[str, str] = {
    "beverages": "Beverages",
    "packaged food & snacks": "Packaged Food & Snacks",
    "grocery & staples": "Grocery & Staples",
    "dairy & chilled": "Dairy & Chilled",
    "home care": "Home Care",
    "personal care": "Personal Care",
}

# Primary compliance messaging (dashboard, PDF, API).
COMPLIANCE_ALERT_TITLE = "Category Mismatch Detected"
COMPLIANCE_ALERT_INTERPRETATION = "Likely Putaway / Shelf Placement Violation"

_categories: list[dict] | None = None
_name_index: dict[str, dict] | None = None
_subcategory_index: dict[str, str] | None = None


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _slug_key(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower().strip())).strip("_")


def _index_subcategories() -> dict[str, str]:
    """Map sub-category ids, labels, and slug variants → canonical subcategory id."""
    index: dict[str, str] = {}
    for cat in _categories or []:
        for sub in cat.get("subcategories") or []:
            sid = str(sub.get("id") or "").strip()
            if not sid:
                continue
            label = str(sub.get("label") or "").strip()
            for alias in (sid, label, sid.replace("_", " "), label.replace(" ", "_")):
                if alias:
                    index[_slug_key(alias)] = sid
                    index[_normalize_key(alias)] = sid
    return index


def normalize_sub_category_id(raw: str | None, category_name: str | None = None) -> str:
    """
    Canonical sub-category id from API id, label, or planogram CSV text.
    Examples: 'Ice cream' → ice_cream, 'ice_cream' → ice_cream, 'Soft drinks' → soft_drinks.
    """
    if not raw or not str(raw).strip():
        return ""
    load_aislix_categories()
    key = _slug_key(str(raw))
    idx = _subcategory_index or {}
    if key in idx:
        return idx[key]
    if category_name:
        cat = resolve_aislix_category(category_name)
        if cat:
            for sub in cat.get("subcategories") or []:
                sid = str(sub.get("id") or "")
                label = str(sub.get("label") or "")
                if key in {_slug_key(sid), _slug_key(label)}:
                    return sid
    return key


def sub_categories_match(a: str | None, b: str | None, category_name: str | None = None) -> bool:
    """True when two sub-category values refer to the same subcategory (id or label)."""
    left = normalize_sub_category_id(a, category_name)
    right = normalize_sub_category_id(b, category_name)
    if not left or not right:
        return not left and not right
    return left == right


def aisle_category_matches(item_category: str | None, aislix_category: str | None) -> bool:
    """True when recognizer/planogram category label matches the scan aisle category."""
    if not item_category or not aislix_category:
        return False
    item_key = _normalize_key(item_category)
    aisle_key = _normalize_key(aislix_category)
    if item_key == aisle_key:
        return True
    resolved = resolve_aislix_category(aislix_category)
    if resolved:
        names = {
            _normalize_key(resolved.get("name") or ""),
            _normalize_key(resolved.get("id") or ""),
        }
        return item_key in names
    return False


def load_aislix_categories() -> list[dict]:
    global _categories, _name_index, _subcategory_index
    if _categories is not None:
        return _categories
    if not CATEGORIES_PATH.exists():
        _categories = []
        _name_index = {}
        _subcategory_index = {}
        return _categories
    with open(CATEGORIES_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    _categories = data if isinstance(data, list) else []
    _name_index = {_normalize_key(item.get("name") or ""): item for item in _categories}
    _name_index.update({_normalize_key(item.get("id") or ""): item for item in _categories})
    _subcategory_index = _index_subcategories()
    return _categories


def resolve_aislix_category(raw: str | None) -> dict | None:
    if not raw or not str(raw).strip():
        return None
    load_aislix_categories()
    return (_name_index or {}).get(_normalize_key(str(raw)))


def resolve_subcategory_label(category: dict | None, sub_id: str | None) -> str | None:
    if not category or not sub_id:
        return None
    sub_key = _slug_key(sub_id)
    for sub in category.get("subcategories") or []:
        if _slug_key(sub.get("id") or "") == sub_key:
            return sub.get("label") or sub_id
    return sub_id.replace("_", " ").title()


def build_shelf_label(
    *,
    shelf_label: str | None = None,
    location: str | None = None,
    aisle: str | None = None,
    rack: str | None = None,
    bin_label: str | None = None,
) -> str:
    if shelf_label and shelf_label.strip():
        return shelf_label.strip()
    if location and location.strip():
        return location.strip()
    parts: list[str] = []
    if aisle and aisle.strip():
        parts.append(f"Aisle {aisle.strip()}" if not aisle.strip().lower().startswith("aisle") else aisle.strip())
    if rack and rack.strip():
        parts.append(f"Rack {rack.strip()}" if not rack.strip().lower().startswith("rack") else rack.strip())
    if bin_label and bin_label.strip():
        parts.append(f"Bin {bin_label.strip()}" if not bin_label.strip().lower().startswith("bin") else bin_label.strip())
    return " · ".join(parts)


def _split_combined_category(metadata: dict) -> dict:
    """Lovable often sends 'Beverages · Tea' as category without a separate sub_category."""
    meta = dict(metadata)
    raw = meta.get("category") or meta.get("aislix_category") or ""
    raw_str = str(raw).strip()
    if "·" not in raw_str:
        return meta
    parts = [p.strip() for p in raw_str.replace("\u00b7", "·").split("·") if p.strip()]
    if len(parts) < 2:
        return meta
    meta["category"] = parts[0]
    if not meta.get("sub_category"):
        meta["sub_category"] = normalize_sub_category_id(parts[1], parts[0])
    if not meta.get("sub_category_label"):
        meta["sub_category_label"] = parts[1]
    return meta


def resolve_scan_context(metadata: dict | None) -> dict:
    """Normalize scan metadata from API / Lovable into a recognition context dict."""
    metadata = _split_combined_category(metadata or {})
    category_raw = metadata.get("category") or metadata.get("aislix_category")
    resolved = resolve_aislix_category(category_raw)
    aislix_name = (resolved or {}).get("name") or (str(category_raw).strip() if category_raw else "")
    aislix_id = (resolved or {}).get("id") or ""

    shelf_label = build_shelf_label(
        shelf_label=metadata.get("shelf_label"),
        location=metadata.get("location"),
        aisle=metadata.get("aisle"),
        rack=metadata.get("rack"),
        bin_label=metadata.get("bin"),
    )

    catalog_cats = AISLIX_TO_CATALOG.get(_normalize_key(aislix_name), [])
    brand_hints = AISLE_BRAND_HINTS.get(_normalize_key(aislix_name), set())
    sub_category, sub_category_label, sub_category_custom = _resolve_sub_category(metadata, resolved)

    return {
        "store_id": (metadata.get("store_id") or "").strip() or None,
        "aislix_category": aislix_name or None,
        "aislix_category_id": aislix_id or None,
        "aislix_examples": (resolved or {}).get("examples") or "",
        "shelf_label": shelf_label or None,
        "location": (metadata.get("location") or shelf_label or "").strip() or None,
        "notes": (metadata.get("notes") or "").strip() or None,
        "sub_category": sub_category,
        "sub_category_label": sub_category_label,
        "sub_category_custom": sub_category_custom,
        "catalog_categories": catalog_cats,
        "brand_hints": brand_hints,
    }


def _resolve_sub_category(metadata: dict, category: dict | None) -> tuple[str | None, str | None, str | None]:
    raw = metadata.get("sub_category") or metadata.get("beverage_type") or metadata.get("product_type")
    custom = (metadata.get("sub_category_custom") or "").strip() or None
    label = (metadata.get("sub_category_label") or "").strip() or None

    if raw and str(raw).strip():
        sub_id = normalize_sub_category_id(str(raw), (category or {}).get("name"))
        if not label:
            label = resolve_subcategory_label(category, sub_id)
        return sub_id, label, custom

    notes = (metadata.get("notes") or "").lower()
    if "tea shelf" in notes or "tea aisle" in notes or notes.strip() == "tea":
        return "tea", "Tea", custom
    if "juice" in notes:
        return "juices", "Juices", custom
    if "soft drink" in notes or "cola" in notes:
        return "soft_drinks", "Soft drinks", custom

    if custom and category and _normalize_key(category.get("name") or "") == "others":
        return "others", custom, custom

    return None, None, custom


def _ocr_confirms_brand(brand_l: str, ocr_text: str) -> bool:
    if not ocr_text:
        return False
    text_l = ocr_text.lower()
    if brand_l in text_l or brand_l.replace("-", " ") in text_l:
        return True
    if brand_l == "coca" and ("coca cola" in text_l or "coca-cola" in text_l):
        return True
    return False


def sub_category_blocks_brand(
    context: dict | None,
    brand: str,
    ocr_text: str = "",
    *,
    product_name: str = "",
) -> bool:
    """Return True when brand should be rejected for this scan sub_category."""
    if not context or not brand:
        return False
    sub = context.get("sub_category")
    if not sub:
        return False

    brand_l = brand.lower().strip()
    if _ocr_confirms_brand(brand_l, ocr_text):
        return False

    blocklist = SUB_CATEGORY_BLOCKLIST.get(sub, set())
    if brand_l in blocklist:
        return True

    reject_tokens = SUB_CATEGORY_REJECT_TEXT.get(sub, ())
    if reject_tokens:
        haystack = f"{ocr_text} {product_name} {brand}".lower()
        if any(token in haystack for token in reject_tokens):
            return True

    aislix_key = _normalize_key(context.get("aislix_category") or "")
    sub_hints = (SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}).get(sub)
    general_hints = context.get("brand_hints") or set()
    if sub_hints and sub != "others":
        if aislix_key == "beverages":
            if brand_l not in sub_hints and brand_l not in general_hints:
                return True
        elif aislix_key == "personal care" and sub in NARROW_PC_SUBCATEGORIES:
            if brand_l not in sub_hints and brand_l not in general_hints:
                return True

    return False


def gpt_context_prompt(context: dict | None) -> str:
    if not context or not context.get("aislix_category"):
        return ""
    name = context["aislix_category"]
    examples = context.get("aislix_examples") or ""
    shelf = context.get("shelf_label") or ""
    sub_label = context.get("sub_category_label") or ""
    sub_custom = context.get("sub_category_custom") or ""

    if sub_custom:
        sub_label = sub_custom
    elif not sub_label and context.get("sub_category"):
        sub_label = str(context["sub_category"]).replace("_", " ").title()

    lines = [
        f"\nScan context: this shelf photo is from the **{name}** aisle.",
        f"Sub-section: **{sub_label}**." if sub_label else "",
        f"Expected product types: {examples}." if examples else "",
        f"Location: {shelf}." if shelf else "",
    ]

    if _normalize_key(name) == "beverages":
        lines.append(
            "Only label beverages. Never label chocolate, biscuits, snacks, soap, or shampoo."
        )
    elif _normalize_key(name) == "personal care":
        lines.append(
            "Only label personal care products (shampoo, soap, toothpaste, skincare, etc.). "
            "Never label food, snacks, beverages, olives, peanuts, or chocolate."
        )
        lines.append(
            "Common shampoo brands: Dove, Pantene, Sunsilk, Head & Shoulders, Tresemme, "
            "Clinic Plus, L'Oreal, Himalaya, Indulekha, Garnier, Meera, Mamaearth, Dabur. "
            "Toothpaste/toothbrush: Colgate, Oral-B, Sensodyne, Closeup, Pepsodent. "
            "Soap/handwash: Dettol, Lux, Lifebuoy, Pears, Santoor. "
            "Read the brand LOGO on THIS pack — never copy a neighbor's label. "
            "A toothbrush must never be labeled as shampoo."
        )
    elif _normalize_key(name) == "home care":
        lines.append(
            "Only label home care / cleaning products (detergent, dishwash, floor cleaner, "
            "toilet cleaner, repellent). Never label food, beverages, or shampoo."
        )
        lines.append(
            "Common brands: Surf Excel, Ariel, Rin, Tide, Vim, Harpic, Lizol, Domex, "
            "Good Knight, All Out, Odonil."
        )
    elif _normalize_key(name) == "packaged food & snacks":
        lines.append(
            "Only label packaged food and snacks (biscuits, chips, namkeen, noodles, "
            "chocolates, protein bars). Never label beverages, shampoo, or detergent."
        )
        lines.append(
            "Common brands: Haldiram, Britannia, Parle, Lay's, Kurkure, Maggi, Cadbury, "
            "Snickers, MTR, Sunfeast."
        )
    elif _normalize_key(name) == "grocery & staples":
        lines.append(
            "Only label grocery and staples (atta, rice, dal, oil, spices, sugar). "
            "Never label shampoo, beverages, or biscuits unless they are clearly in this aisle."
        )
        lines.append(
            "Common brands: Aashirvaad, Fortune, India Gate, Tata Sampann, MDH, Everest, "
            "Patanjali, Blue Bird (sugar/baking)."
        )
    else:
        lines.append(
            f"Only label products that belong in {name}"
            + (f" — {sub_label}" if sub_label else "")
            + ". Reject obvious cross-aisle guesses."
        )

    return "\n".join(line for line in lines if line)


def sku_allowed_in_context(
    brand: str,
    sku: str = "",
    entry_category: str = "",
    context: dict | None = None,
) -> bool:
    """Return False for obvious cross-aisle FAISS / GPT false positives."""
    if not context or not context.get("aislix_category"):
        return True
    if not brand:
        return True

    brand_l = brand.lower().strip()
    aislix_key = _normalize_key(context["aislix_category"])
    allowed_catalog = context.get("catalog_categories") or []
    hints = context.get("brand_hints") or set()
    blocklist = AISLE_BRAND_BLOCKLIST.get(aislix_key, set())
    sku_l = (sku or "").lower()

    if brand_l in blocklist:
        return False

    if _cross_aisle_sku_conflict(aislix_key, brand_l, sku_l):
        return False

    from app.category_scope import effective_entry_ids

    pseudo = {
        "brand": brand,
        "product_name": "",
        "variant": "",
        "sku": sku,
        "category": entry_category or "",
    }
    inferred_cat, _ = effective_entry_ids(pseudo)
    scan_cat_id = context.get("aislix_category_id")
    if scan_cat_id and inferred_cat and inferred_cat not in {"", "others"}:
        if inferred_cat != scan_cat_id:
            return False

    entry_cat_norm = _normalize_key(entry_category or "")
    if entry_cat_norm and aisle_category_matches(entry_category, context.get("aislix_category")):
        if scan_cat_id and inferred_cat and inferred_cat not in {"", "others"}:
            return inferred_cat == scan_cat_id
        return True

    sku_cat = (entry_category or infer_category(sku or brand_l)).lower()

    if allowed_catalog and sku_cat not in {"", "general"}:
        if sku_cat in allowed_catalog:
            return True
        if sku_cat == "general":
            pass
        else:
            if brand_l in hints and sku_cat.lower() not in {"dairy", "snacks", "personal care", "household"}:
                return True
            if aislix_key == "personal care" and brand_l in hints:
                return True
            return False

    other_aisle_brands: set[str] = set()
    for aisle_key, brands in AISLE_BRAND_HINTS.items():
        if aisle_key != aislix_key:
            other_aisle_brands.update(brands)

    if brand_l in other_aisle_brands and brand_l not in hints:
        return False

    return True


def validate_scan_metadata(metadata: dict | None) -> list[str]:
    """Return list of validation errors. Empty = ok."""
    required = os.getenv("SCAN_CONTEXT_REQUIRED", "false").lower() in {"1", "true", "yes"}
    metadata = metadata or {}
    errors: list[str] = []

    category = metadata.get("category") or metadata.get("aislix_category")
    resolved = resolve_aislix_category(str(category)) if category else None
    if required and not category:
        errors.append("category is required.")
    elif category and not resolved:
        errors.append(f"Unknown category: {category}")

    if required and not metadata.get("store_id"):
        errors.append("store_id is required.")

    shelf_label = build_shelf_label(
        shelf_label=metadata.get("shelf_label"),
        location=metadata.get("location"),
        aisle=metadata.get("aisle"),
        rack=metadata.get("rack"),
        bin_label=metadata.get("bin"),
    )
    if required and not shelf_label:
        errors.append("location is required.")

    sub = metadata.get("sub_category") or metadata.get("product_type")
    if required and resolved and (resolved.get("subcategories") or []) and not sub:
        if _normalize_key(resolved.get("name") or "") != "others":
            errors.append("sub_category is required.")

    if sub and _slug_key(str(sub)) == "others":
        custom = (metadata.get("sub_category_custom") or metadata.get("notes") or "").strip()
        if not custom:
            errors.append("sub_category_custom is required when sub_category is Others.")

    return errors


def categories_for_api() -> list[dict]:
    """Return category list with subcategories for GET /categories."""
    return load_aislix_categories()
