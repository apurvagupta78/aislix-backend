"""Brand and product lookup built from the FAISS catalog for OCR text matching."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.catalog import infer_category, load_catalog

_brands: list[str] | None = None
_brand_products: dict[str, list[dict]] | None = None
_brand_aliases: dict[str, str] | None = None

# OCR text often uses multi-word names; map to catalog brand keys (longest checked first).
TEXT_ALIASES: dict[str, str] = {
    "tata tea agni": "Tata",
    "tata tea gold": "Tata",
    "tata tea premium": "Tata",
    "del monte": "Del",
    "tata tea": "Tata",
    "brooke bond": "Brooke",
    "red label": "Brooke",
    "yellow label": "Brooke",
    "taj mahal": "Taj",
    "tata gold": "Tata",
    "tata premium": "Tata",
    "tea agni": "Tata",
    "head & shoulders": "Head",
    "head and shoulders": "Head",
    "head shoulders": "Head",
    "clinic plus": "Clinic",
    "l'oreal": "Loreal",
    "l oreal": "Loreal",
    "mama earth": "Mamaearth",
    "oral-b": "Oral",
    "oral b": "Oral",
    "tresemmé": "Tresemme",
    "tresemm": "Tresemme",
    "tresenme": "Tresemme",
    "tresemrn": "Tresemme",
    "blue bird": "Blue",
    "pear": "Pears",
    "parle-g": "Parle",
    "parle g": "Parle",
    "haldiram's": "Haldiram",
    "surf excel": "Surf",
    "lay's": "Lays",
    "lays": "Lays",
    "bingo!": "Bingo",
    "crax": "Crax",
    "kurkure": "Kurkure",
    "tedhe medhe": "Bingo",
    "mad angles": "Bingo",
    "pringles": "Pringles",
    "baskin robbins": "Baskin",
    "brooklyn creamery": "Brooklyn",
    "mother dairy": "Mother",
    "head and shoulders": "Head",
    "park avenue": "Park",
    "paper boat": "Paper",
    "too yumm": "Too",
    "cream bell": "Cream",
    "masala munch": "Kurkure",
}

# Short OCR fragments → catalog product (checked when full hints miss).
PARTIAL_FRAGMENT_RULES: list[tuple[str, str, str]] = [
    (r"\brings\b", "Crax", "Rings"),
    (r"\bcurls\b", "Crax", "Curls"),
    (r"\bmasala\s+munch\b", "Kurkure", "Masala Munch"),
    (r"\btedhe\s+medhe\b", "Bingo", "Tedhe Medhe"),
    (r"\bmad\s+angles\b", "Bingo", "Mad Angles"),
    (r"\bmagic\s+masala\b", "Lays", "Indias Magic Masala Potato Chips"),
    (r"\btomato\s+tango\b", "Lays", "Tomato Tango Potato Chips"),
    (r"\bcream\s*(?:&|and)\s*onion\b", "Lays", "American Style Cream and Onion Potato Chips"),
    (r"\bclassic\s+salted\b", "Lays", "Classic Salted Potato Chips"),
    (r"\banti[\s-]?dandruff\b", "Head", "Classic Clean Anti Dandruff Shampoo"),
    (r"\bhair\s+fall\b", "Pantene", "Hairfall Control Shampoo"),
    (r"\bsmooth\s*(?:&|and)\s*shine\b", "Tresemme", "Smooth Shine Shampoo"),
    (r"\btotal\s+repair\b", "Loreal", "Total Repair 5 Shampoo"),
]

PERSONAL_CARE_FOOD_TOKENS = (
    "hajmola",
    "digestive",
    "tablet",
    "namkeen",
    "biscuit",
    "chocolate",
    "potato chips",
    "noodles",
    "maggi",
)

# Single-token catalog brands that are usually variant words, not manufacturers.
VARIANT_BRAND_BLOCKLIST = frozenset({
    "clean", "classic", "plus", "repair", "smooth", "nourish", "control", "long",
    "fresh", "total", "intense", "active", "original", "natural", "herbal",
    "anti", "pro", "extra", "super", "deep", "mild", "soft", "strong", "blue",
})

# Distinctive pack text → brand + preferred catalog product (checked before generic brand match).
PRODUCT_HINTS: list[tuple[str, str, str]] = [
    (r"\btata\s+tea\s+agni\b", "Tata", "Tea Agni"),
    (r"\btea\s+agni\b", "Tata", "Tea Agni"),
    (r"\bagni\b", "Tata", "Tea Agni"),
    (r"\btata\s+tea\s+gold\b", "Tata", "Tea Gold"),
    (r"\btata\s+tea\s+premium\b", "Tata", "Tea Premium"),
    (r"\btata\s+premium\b", "Tata", "Tea Premium"),
    (r"\bdesh\s+ki\s+chai\b", "Tata", "Tea Premium"),
    (r"\blipton\b", "Lipton", ""),
    (r"\btetley\b", "Tetley", ""),
    (r"\bgreen\s+tea\b", "Tetley", "Green Tea Regular"),
    (r"\bbrooke\s+bond\b", "Brooke", ""),
    (r"\bred\s+label\b", "Brooke", "Red Label"),
    (r"\byellow\s+label\b", "Lipton", "Yellow Label Tea"),
    (r"\bvahdam\b", "Vahdam", "Darjeeling Tea"),
    (r"\borganic\s+india\b", "Organic India", "Tulsi Masala Chai"),
    (r"\btulsi\s+masala\b", "Organic India", "Tulsi Masala Chai"),
    (r"\btaj\s+maharaja\b", "Taj", "Maharaja Breakfast Tea"),
    (r"\bmaharaja\s+breakfast\b", "Taj", "Maharaja Breakfast Tea"),
    (r"\btwinings\b", "Twinings", ""),
    (r"\breal\b.*\bmango\b", "Real", "Mango Juice"),
    (r"\bmango\s+juice\b", "Real", "Mango Juice"),
    (r"\bcoca[\-\s]?cola\b", "Coca", "Coke"),
    (r"\bpepsi\b", "Pepsi", ""),
    (r"\bfanta\b", "Fanta", ""),
    (r"\bsimple\b", "Simple", "Kind To Skin Refreshing Facial Wash"),
    (r"\bdettol\b.*\bhand\s*wash\b", "Dettol", "Original Hand Wash"),
    (r"\bhand\s*wash\b.*\bdettol\b", "Dettol", "Original Hand Wash"),
    (r"\bhandwash\b.*\bdettol\b", "Dettol", "Original Hand Wash"),
    (r"\bdettol\b", "Dettol", ""),
    (r"\bindulekha\b", "Indulekha", ""),
    (r"\bhimalaya\b", "Himalaya", ""),
    (r"\btresemme\b", "Tresemme", ""),
    (r"\btresemm[eé]\b", "Tresemme", ""),
    (r"\btresenme\b", "Tresemme", ""),
    (r"\bkeratin\s+smooth\b", "Tresemme", "Keratin Smooth Shampoo"),
    (r"\bsmooth\s*(?:&|and\s+)?\s*shine\b", "Tresemme", "Smooth Shine Shampoo"),
    (r"\bvatika\b", "Dabur", "Vatika Health Shine Shampoo"),
    (r"\bdabur\s+vatika\b", "Dabur", "Vatika Health Shine Shampoo"),
    (r"\bhyaluron\s+moisture\b", "Loreal", "Paris Hyaluron Moisture Shampoo"),
    (r"\banti[\-\s]?hair\s*fall\b", "Himalaya", "Anti Hair Fall Shampoo"),
    (r"\bhead\s*(?:&|and)\s*shoulders\b", "Head", ""),
    (r"\bhead\s+shoulders\b", "Head", ""),
    (r"\bcool\s+menthol\b", "Head", "Cool Menthol Shampoo"),
    (r"\bclinic\s+plus\b", "Clinic", "Plus Strong And Long Health Shampoo"),
    (r"\bl[\s']?oreal\b", "Loreal", ""),
    (r"\btotal\s+repair\s*5?\b", "Loreal", "Paris Total Repair 5 Shampoo"),
    (r"\bdove\b", "Dove", ""),
    (r"\bintense\s+repair\b", "Dove", "Intense Repair Shampoo"),
    (r"\bclassic\s+clean\b", "Head", "Classic Clean Shampoo"),
    (r"\bstrong\s*(?:&|and)\s*long\b", "Clinic", "Plus Strong And Long Health Shampoo"),
    (r"\bpantene\b", "Pantene", ""),
    (r"\bsunsilk\b", "Sunsilk", ""),
    (r"\bdabur\b", "Dabur", ""),
    (r"\bcolgate\b", "Colgate", ""),
    (r"\bcloseup\b", "Closeup", ""),
    (r"\bnivea\s+men\b.*\bshampoo\b|\bshampoo\b.*\bnivea\s+men\b", "Nivea", "Men Strong Power Shampoo"),
    (r"\bnivea\s+men\b|\bstrong\s+power\b", "Nivea", "Men Strong Power Shampoo"),
    (r"\bmedimix\b", "Medimix", "Ayurvedic Soap"),
    (r"\bgillette\b", "Gillette", ""),
    (r"\bponds\b|\bpond'?s\b", "Ponds", ""),
    (r"\bvaseline\b", "Vaseline", ""),
    (r"\bnivea\b", "Nivea", ""),
    (r"\baxe\b", "Axe", "Deodorant Body Spray"),
    (r"\bfogg\b", "Fogg", "Deodorant Body Spray"),
    (r"\bwild\s+stone\b", "Wild Stone", "Deodorant Body Spray"),
    (r"\bpark\s+avenue\b", "Park Avenue", "Deodorant Body Spray"),
    (r"\blux\b", "Lux", ""),
    (r"\blifebuoy\b", "Lifebuoy", ""),
    (r"\bmamaearth\b", "Mamaearth", ""),
    (r"\bmeera\b", "Meera", ""),
    (r"\bpears\b", "Pears", ""),
    (r"\bpear\b", "Pears", ""),
    (r"\bjoy\b", "Joy", ""),
    (r"\bhaldiram(?:\'s)?\b", "Haldiram", ""),
    (r"\bbritannia\b", "Britannia", ""),
    (r"\bparle(?:\s+-?\s*g)?\b", "Parle", ""),
    (r"\bmaggi\b", "Maggi", ""),
    (r"\bcrax\b.*\brings\b|\brings\b.*\bcrax\b", "Crax", "Rings"),
    (r"\bcrax\b.*\bcurls\b|\bcurls\b.*\bcrax\b", "Crax", "Curls"),
    (r"\bcrax\b", "Crax", ""),
    (r"\bbingo\b.*\btedhe\s+medhe\b|\btedhe\s+medhe\b", "Bingo", "Tedhe Medhe"),
    (r"\bmad\s+angles\b", "Bingo", "Mad Angles"),
    (r"\bbingo\b", "Bingo", ""),
    (r"\bkurkure\b.*\bmasala\s+munch\b", "Kurkure", "Masala Munch"),
    (r"\bkurkure\b", "Kurkure", ""),
    (r"\brings\b", "Crax", "Rings"),
    (r"\bcurls\b", "Crax", "Curls"),
    (r"\btedhe\s+medhe\b", "Bingo", "Tedhe Medhe"),
    (r"\bmad\s+angles\b", "Bingo", "Mad Angles"),
    (r"\blay(?:\'|s)?s\b.*\bmagic\s+masala\b|\bmagic\s+masala\b.*\blay(?:\'|s)?s\b", "Lays", "Indias Magic Masala Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\btomato\s+tango\b|\btomato\s+tango\b.*\blay(?:\'|s)?s\b", "Lays", "Tomato Tango Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bcream\s*(?:&|and)\s*onion\b|\bcream\s*(?:&|and)\s*onion\b.*\blay(?:\'|s)?s\b", "Lays", "American Style Cream and Onion Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bpotato\s+chips\b", "Lays", "Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bclassic\b", "Lays", "Classic Salted Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bmasala\b", "Lays", "Indias Magic Masala Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\btomato\b", "Lays", "Tomato Tango Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\btango\b", "Lays", "Tomato Tango Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bcream\b", "Lays", "American Style Cream and Onion Potato Chips"),
    (r"\blay(?:\'|s)?s\b.*\bonion\b", "Lays", "American Style Cream and Onion Potato Chips"),
    (r"\blay(?:\'|s)?s\b", "Lays", ""),
    (r"\bpringles\b", "Pringles", ""),
    (r"\bnescafe\b", "Nescafe", ""),
    (r"\bbru\b", "Bru", ""),
    (r"\bsprite\b", "Sprite", ""),
    (r"\bmountain\s+dew\b", "Mountain", ""),
    (r"\bsurf\s+excel\b", "Surf", ""),
    (r"\bharpic\b", "Harpic", ""),
    (r"\bvim\b", "Vim", ""),
    (r"\baashirvaad\b", "Aashirvaad", ""),
    (r"\bfortune\b", "Fortune", ""),
    (r"\bindia\s+gate\b", "India", ""),
    (r"\bamul\b.*\bkulfi\b|\bkulfi\b.*\bamul\b", "Amul", "Rabdi Kulfi Ice Cream Stick"),
    (r"\brajbhog\b|\brajbog\b", "Amul", "Rabdi Kulfi Ice Cream Stick"),
    (r"\brajwadi\b", "Amul", "Rajwadi Kulfi Ice Cream"),
    (r"\bamul\b.*\bice cream sandwich\b|\bice cream sandwich\b.*\bamul\b", "Amul", ""),
    (r"\bice cream sandwich\b", "Amul", "Ice Cream Sandwich"),
    (r"\bsandwich\b", "Amul", "Ice Cream Sandwich"),
    (r"\bkulfi\b", "Amul", "Rabdi Kulfi Ice Cream Stick"),
    (r"\bbrooklyn\b", "Brooklyn", "Ice Cream"),
    (r"\bbaskin\b.*\bfunwich\b|\bfunwich\b|\bfunwith\b", "Baskin Robbins", "Funwich"),
    (r"\bamul\b", "Amul", ""),
]

TEA_OCR_MARKERS = (
    "lipton", "tetley", "tata tea", "tea agni", "agni", "green tea", "red label",
    "yellow label", "brooke bond", "taj mahal", "tea bags", "tea bag", "tea premix",
    "taj mahal tea", "brooke bond taj",
)
NON_TEA_BEVERAGE_BRANDS = {
    "sofit", "coca cola", "coca-cola", "pepsi", "fanta", "sprite", "tropicana", "maaza",
}


def pack_text_indicates_tea(text: str) -> bool:
    text_l = _normalize(text)
    return any(marker in text_l for marker in TEA_OCR_MARKERS)


def label_conflicts_with_tea_pack(label: dict, text: str) -> bool:
    if not text or not pack_text_indicates_tea(text):
        return False
    brand_l = (label.get("brand") or "").strip().lower()
    return brand_l in NON_TEA_BEVERAGE_BRANDS


def label_conflicts_with_pack_text(label: dict, text: str) -> bool:
    """True when OCR clearly names a different brand than the proposed label."""
    if not text or len(text.strip()) < 3:
        return False
    label_brand = (label.get("brand") or "").strip().lower()
    text_l = _normalize(text)

    # Fast partial-text checks (Paddle/EasyOCR often read fragments, not full SKUs).
    ocr_brand_hints: list[tuple[str, str]] = [
        (r"shoulder|head\s*&?\s*shoulder|head\s+shoulder", "head"),
        (r"\bhimalaya\b", "himalaya"),
        (r"\bsunsilk\b", "sunsilk"),
        (r"\bvatika\b|\bdabur\s+vatika\b", "dabur"),
        (r"\bhyaluron\b", "loreal"),
        (r"\bclinic\s*plus\b|\bclinic\b", "clinic"),
        (r"\btresemme\b|\btresemm", "tresemme"),
        (r"\bl[\s']?oreal\b|\btotal\s+repair", "loreal"),
        (r"\bdove\b", "dove"),
        (r"\bpantene\b", "pantene"),
        (r"\bmeera\b", "meera"),
        (r"\bjoy\b", "joy"),
        (r"\bcolgate\b", "colgate"),
        (r"\bdabur\b", "dabur"),
        (r"\bintense\s+repair\b", "dove"),
        (r"\bstrong\s*(?:&|and)\s*long\b", "clinic"),
        (r"\blay(?:\'|s)?s\b", "lays"),
        (r"\bbingo\b|\btedhe\s+medhe\b|\bmad\s+angles\b", "bingo"),
        (r"\bcrax\b", "crax"),
        (r"\bkurkure\b", "kurkure"),
        (r"\bpringles\b", "pringles"),
        (r"\bvahdam\b", "vahdam"),
        (r"\borganic\s+india\b", "organic india"),
        (r"\btata\s+tea\b|\btata\s+premium\b|\bdesh\s+ki\s+chai\b", "tata"),
        (r"\btwinings\b", "twinings"),
        (r"\byellow\s+label\b", "lipton"),
        (r"\btatva\b|\btandoori\s+masala\b", "organic"),
        (r"\bwhole\s+truth\b|\bprotein\s+bar\b", "the"),
        (r"\bamul\b", "amul"),
        (r"\bbrooklyn\b", "brooklyn"),
        (r"\bbaskin\b|\bfunwich\b|\bfunwith\b", "baskin"),
        (r"\bhavmor\b", "havmor"),
        (r"\bkulfi\b|\brajbhog\b|\brajbog\b|\brajwadi\b", "amul"),
        (r"\bsandwich\b", "amul"),
        (r"\btricone\b", "amul"),
        (r"\baxe\b", "axe"),
        (r"\bfogg\b", "fogg"),
        (r"\bwild\s+stone\b", "wild stone"),
        (r"\bpark\s+avenue\b", "park avenue"),
    ]
    for pattern, hinted_brand in ocr_brand_hints:
        if re.search(pattern, text_l, flags=re.IGNORECASE):
            if label_brand and label_brand != hinted_brand:
                if label_brand not in hinted_brand and hinted_brand not in label_brand:
                    if not any(token in text_l for token in _brand_tokens(label.get("brand") or "")):
                        return True
            break

    if "himalaya" in text_l and label_brand == "dabur":
        return True
    if "dabur" in text_l and label_brand == "himalaya":
        return True
    if ("clinic" in text_l or "clinic plus" in text_l) and label_brand == "dove":
        return True
    if "dove" in text_l and label_brand in {"clinic", "dabur"}:
        return True
    product_l = (label.get("product_name") or "").lower()
    if "pantene" in text_l and label_brand == "dove" and "conditioner" in product_l:
        return True
    if ("hair fall" in text_l or "hairfall" in text_l) and label_brand == "dove" and "conditioner" in product_l:
        return True
    if re.search(r"\blay(?:\'|s)?s\b", text_l) and label_brand in {
        "del",
        "haldiram",
        "britannia",
        "bingo",
        "pringles",
        "tooyumm",
        "too yumm",
        "balaji",
    }:
        return True
    if re.search(r"\bbingo\b|\btedhe\s+medhe\b|\bmad\s+angles\b", text_l) and label_brand == "pringles":
        return True
    if re.search(r"\bcrax\b", text_l) and label_brand not in {"", "crax", "unknown"}:
        return True
    if re.search(r"\bkurkure\b", text_l) and label_brand not in {"", "kurkure", "unknown"}:
        return True
    if re.search(r"\bbingo\b|\btedhe\s+medhe\b|\bmad\s+angles\b", text_l) and label_brand not in {
        "",
        "bingo",
        "unknown",
    }:
        return True
    if label_brand == "lays" and any(
        marker in text_l for marker in ("kurkure", "bingo", "crax", "pringles", "tedhe medhe", "mad angles")
    ):
        return True
    if re.search(r"\blay(?:'|s)?s\b", text_l) and label_brand == "bingo":
        return True
    if re.search(r"\bclassic\b", text_l) and re.search(r"\bsalt", text_l) and label_brand == "bingo":
        return True
    if "vatika" in text_l and ("hajmola" in product_l or "digestive" in product_l):
        return True
    if ("hajmola" in product_l or "digestive" in product_l or "tablet" in product_l) and any(
        token in text_l for token in ("vatika", "shampoo", "conditioner", "hair", "naturals")
    ):
        return True
    if "dabur" in text_l and ("hajmola" in product_l or "digestive" in product_l):
        if not any(token in text_l for token in ("hajmola", "imli", "digestive", "tablet")):
            return True
    if re.search(r"\baxe\b", text_l) and ("kesh" in product_l or label_brand == "patanjali"):
        return True
    if re.search(r"\bdeodorant\b|\bbody\s+spray\b", text_l) and "shampoo" in product_l:
        return True
    if re.search(r"\bvatika\b", text_l) and label_brand == "sunsilk":
        return True
    if re.search(r"yellow\s+label", text_l) and "darjeeling" in product_l:
        return True
    if re.search(r"\bdarjeeling\b", text_l) and "yellow label" in product_l:
        return True
    if re.search(r"\bhyaluron\b", text_l) and "total repair" in product_l:
        return True
    if re.search(r"\btotal\s+repair\b", text_l) and "hyaluron" in product_l:
        return True

    if "amul" in text_l and label_brand == "havmor":
        return True
    if any(token in text_l for token in ("kulfi", "rajbhog", "rajbog", "rajwadi", "rabdi")):
        if label_brand == "havmor" or "sandwich" in product_l:
            return True
    if "sandwich" in text_l and ("tricone" in product_l or "cone" in product_l or "kulfi" in product_l):
        return True
    if any(token in text_l for token in ("tricone", " cone")) and "sandwich" in product_l:
        return True

    label_text = " ".join(
        [
            label.get("brand") or "",
            label.get("product_name") or "",
            label.get("variant") or "",
            label.get("sku") or "",
        ]
    )
    from app.scan_context import compatible_product_types, infer_product_type

    label_type = infer_product_type(label_text)
    ocr_type = infer_product_type(text)
    if label_type and ocr_type and not compatible_product_types(label_type, ocr_type):
        return True

    corrected = match_from_text(text)
    if not corrected:
        return False
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not label_brand or not text_brand or label_brand == text_brand:
        return False
    if "dettol" in text_l and label_brand == "himalaya":
        return True
    if "himalaya" in text_l and label_brand == "dettol":
        return True
    if any(token in text_l for token in _brand_tokens(label.get("brand") or "")):
        return False
    return True


def _brand_tokens(brand: str) -> set[str]:
    brand_l = brand.lower().strip()
    tokens = {brand_l, brand_l.replace("-", " ")}
    if brand_l == "coca":
        tokens.add("coca cola")
        tokens.add("coca-cola")
    if brand_l == "head":
        tokens.update({"head & shoulders", "head and shoulders", "head shoulders", "shoulders"})
    if brand_l == "clinic":
        tokens.add("clinic plus")
    if brand_l == "loreal":
        tokens.update({"l'oreal", "l oreal"})
    if brand_l == "blue":
        tokens.add("blue bird")
    return tokens


def _blue_brand_allowed(normalized: str) -> bool:
    """Blue catalog brand is baking (Blue Bird); block color-only OCR matches."""
    return "bird" in normalized or "caster sugar" in normalized or "demerara" in normalized


def _tea_brand_blocked_on_pack(text: str, brand: str) -> bool:
    """Reject tea brands when pack text indicates shampoo/personal care."""
    brand_l = brand.lower().strip()
    if brand_l not in {"taj", "brooke", "tata", "lipton", "tetley"}:
        return False
    text_l = _normalize(text)
    pc_markers = ("shampoo", "conditioner", "soap", "hand wash", "handwash", "toothpaste")
    return any(marker in text_l for marker in pc_markers)


def _tea_brand_blocked_on_pc_pack(text: str, brand: str) -> bool:
    """Reject tea brands when pack text indicates personal care (price-tag bleed)."""
    brand_l = brand.lower().strip()
    if brand_l not in {"taj", "brooke", "tata", "lipton", "tetley"}:
        return False
    text_l = _normalize(text)
    if any(token in text_l for token in ("tea", "chai", "green tea", "tea bags", "tea bag")):
        return False
    pc_markers = ("shampoo", "conditioner", "soap", "hand wash", "handwash", "toothpaste", "dandruff")
    return any(marker in text_l for marker in pc_markers) or len(text_l) < 40


def _hint_matched_in_text(normalized: str) -> bool:
    for pattern, _, _ in PRODUCT_HINTS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return True
    return False


def _variant_brand_blocked(brand_norm: str, normalized: str, has_hint: bool) -> bool:
    if brand_norm not in VARIANT_BRAND_BLOCKLIST:
        return False
    if has_hint:
        return True
    if brand_norm == "clean" and ("head" in normalized or "shoulders" in normalized):
        return True
    if brand_norm == "plus" and "clinic" in normalized:
        return True
    if brand_norm == "blue" and not _blue_brand_allowed(normalized):
        return True
    if brand_norm == "rite":
        return True
    return False


def display_brand_name(brand: str, product_name: str = "") -> str:
    """Human-readable brand for UI/annotations."""
    brand = (brand or "").strip()
    product_l = (product_name or "").lower()
    if brand.lower() == "head" and "shoulder" in product_l:
        return "Head & Shoulders"
    if brand.lower() == "head" and ("head" in product_l or "shoulder" in product_l):
        return "Head & Shoulders"
    if brand.lower() == "clinic" and "plus" in product_l:
        return "Clinic Plus"
    return brand


def ocr_agrees_with_label(
    label: dict,
    text: str,
    *,
    strict: bool = False,
    scan_context: dict | None = None,
) -> bool:
    """Return True when OCR text supports the proposed brand/product label."""
    if not text or len(text.strip()) < 3:
        return not strict
    label_brand = (label.get("brand") or "").strip().lower()
    if label_brand == "blue" and not _blue_brand_allowed(_normalize(text)):
        return False
    corrected = match_from_text(text, scan_context=scan_context)
    if not corrected:
        return False
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not label_brand or not text_brand:
        return False
    if label_brand == text_brand:
        return True
    if label_brand in text_brand or text_brand in label_brand:
        return True
    text_l = _normalize(text)
    tokens = _brand_tokens(label.get("brand") or "")
    if label_brand == "blue":
        return "bird" in text_l
    return any(token in text_l for token in tokens if len(token) >= 4)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


_OCR_CHAR_FIXES = (
    (re.compile(r"\b0(?=[a-z])", re.I), "O"),
    (re.compile(r"(?<=[a-z])0(?=\s|$)", re.I), "o"),
    (re.compile(r"\bl\s*(?:'|')?\s*s\b", re.I), "lays"),
    (re.compile(r"\b1(?=[a-z])"), "l"),
)


def normalize_ocr_text(text: str) -> str:
    """Clean common OCR noise before catalog matching."""
    cleaned = _normalize(text)
    if not cleaned:
        return ""
    for pattern, repl in _OCR_CHAR_FIXES:
        cleaned = pattern.sub(repl, cleaned)
    cleaned = re.sub(r"(.)\1{2,}", r"\1\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _load() -> None:
    global _brands, _brand_products, _brand_aliases
    if _brands is not None:
        return
    products = load_catalog()
    brand_map: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for entry in products:
        brand = (entry.get("brand") or "").strip()
        if not brand or brand.lower() in {"unknown", "7"}:
            continue
        key = brand.lower()
        brand_map.setdefault(key, []).append(entry)
        seen.add(brand)
    _brand_products = brand_map
    _brands = sorted(seen, key=len, reverse=True)
    _brand_aliases = {k: v for k, v in TEXT_ALIASES.items()}
    for brand in seen:
        alias = _normalize(brand)
        if len(alias) >= 5 and (" " in alias or "&" in brand):
            _brand_aliases.setdefault(alias, brand)
        compact = alias.replace(" ", "")
        if len(compact) >= 6 and compact != alias:
            _brand_aliases.setdefault(compact, brand)


def all_brands() -> list[str]:
    _load()
    return _brands or []


def products_for_brand(brand: str) -> list[dict]:
    _load()
    return (_brand_products or {}).get(brand.lower(), [])


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _word_in_text(word: str, normalized: str) -> bool:
    if not word:
        return False
    return re.search(rf"\b{re.escape(word)}\b", normalized) is not None


def match_brand_in_text(text: str) -> tuple[str, float] | None:
    """Return (brand, confidence) if a catalog brand appears in OCR text."""
    _load()
    if not text or not _brands:
        return None
    normalized = _normalize(text)
    candidates: list[tuple[str, float, int]] = []
    has_hint = _hint_matched_in_text(normalized)

    for pattern, brand, _product in PRODUCT_HINTS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            span_len = len(re.search(pattern, normalized, flags=re.IGNORECASE).group(0))  # type: ignore[union-attr]
            candidates.append((brand, 0.94, span_len + 1000))

    for alias, brand in sorted((_brand_aliases or {}).items(), key=lambda item: -len(item[0])):
        if alias in normalized:
            candidates.append((brand, 0.91, len(alias) + 500))

    for brand in _brands:
        brand_norm = _normalize(brand)
        if len(brand_norm) < 3:
            continue
        if _variant_brand_blocked(brand_norm, normalized, has_hint):
            continue
        if _word_in_text(brand_norm, normalized):
            candidates.append((brand, min(0.99, 0.84 + len(brand_norm) / 100), len(brand_norm)))

    if candidates:
        candidates.sort(key=lambda item: (-item[2], -item[1]))
        return candidates[0][0], round(candidates[0][1], 4)

    best_brand = ""
    best_score = 0.0
    for brand in _brands:
        brand_norm = _normalize(brand)
        if len(brand_norm) < 5:
            continue
        ratio = _similarity(brand, text)
        if ratio >= 0.9 and ratio > best_score:
            best_score = ratio
            best_brand = brand
    if best_brand:
        return best_brand, round(best_score, 4)
    return None


def _catalog_entry(brand: str, product_name: str) -> dict | None:
    for entry in products_for_brand(brand):
        if (entry.get("product_name") or "").strip().lower() == product_name.lower():
            return entry
    return None


def _label_from_brand_product(
    brand: str,
    product_name: str,
    text: str,
    *,
    confidence: float = 0.9,
    scan_context: dict | None = None,
    allow_brand_fallback: bool = True,
) -> dict:
    entry = _catalog_entry(brand, product_name)
    if entry:
        product_name = entry.get("product_name") or product_name
        return {
            "brand": display_brand_name(brand, product_name),
            "product_name": product_name,
            "variant": entry.get("variant") or "",
            "sku": entry.get("sku") or "",
            "category": entry.get("category") or infer_category(entry.get("sku") or ""),
            "confidence": confidence,
            "recognition_source": "ocr",
            "visible_text": text[:240],
        }
    if not allow_brand_fallback:
        return {
            "brand": display_brand_name(brand, product_name),
            "product_name": product_name,
            "variant": "",
            "sku": "",
            "category": "General",
            "confidence": confidence,
            "recognition_source": "ocr",
            "visible_text": text[:240],
        }
    product = match_product_for_brand(brand, text, scan_context=scan_context)
    if product:
        product["visible_text"] = text[:240]
        product["confidence"] = max(float(product.get("confidence") or 0), confidence)
        product["recognition_source"] = "ocr"
        return product
    return {
        "brand": display_brand_name(brand, product_name),
        "product_name": product_name,
        "variant": "",
        "sku": "",
        "category": "General",
        "confidence": confidence,
        "recognition_source": "ocr",
        "visible_text": text[:240],
    }


def _is_ambiguous_lays_tomato_fragment(text_l: str) -> bool:
    """Tomato/tango tokens must not map to Tomato Tango without Lay's brand on pack text."""
    blob = re.sub(r"\s+", " ", (text_l or "").lower().strip())
    if not blob:
        return True
    if re.search(r"\blay(?:'|s)?s\b", blob):
        return False
    if "tomato" in blob or "tango" in blob:
        return True
    ambiguous = {"spanish tomato", "spanish", "tom", "tomat", "tomato ta", "tomato to"}
    return blob in ambiguous


def _is_ambiguous_lays_cream_fragment(text_l: str) -> bool:
    """Short OCR fragments like 'Cream' must not map to Cream & Onion without row consensus."""
    blob = re.sub(r"\s+", " ", (text_l or "").lower().strip())
    if not blob or len(blob) > 18:
        return False
    if any(token in blob for token in ("magic", "masala", "tomato", "tango", "india")):
        return False
    if "onion" in blob:
        return False
    ambiguous = {
        "cream", "crear", "crea", "cre", "c", "cream &", "cream & o", "cream & on", "eam & o", "eam & on",
    }
    return blob in ambiguous or blob.startswith("cream")


def _lays_flavor_fragment_allowed(text_l: str, sub: str) -> bool:
    """Allow Lay's flavor fragments on chip aisles when brand or masala tokens are present."""
    if sub not in {"chips", "potato_chips"}:
        return False
    if re.search(r"\blay(?:'|s)?s\b", text_l):
        return True
    if "potato" in text_l and "chips" in text_l:
        return False
    if re.search(r"\bmagic\b", text_l) or re.search(r"\bmasala\b", text_l):
        return True
    if "cream" in text_l and "onion" in text_l:
        return True
    return False


def _flavor_token_bonus(normalized: str, product_l: str) -> float:
    """Prefer SKUs whose flavor tokens appear in OCR when scores tie."""
    bonus = 0.0
    groups = (
        ("magic", "masala"),
        ("tomato", "tango"),
        ("cream", "onion"),
        ("classic", "salted"),
    )
    for tokens in groups:
        if all(token in normalized for token in tokens) and all(token in product_l for token in tokens):
            bonus += 0.25
    return bonus


def _match_partial_fragments(normalized: str, scan_context: dict | None = None) -> dict | None:
    """Map short OCR fragments (rings, magic, tango) to catalog SKUs."""
    if not normalized or len(normalized.strip()) < 3:
        return None
    text_l = normalized.lower()
    sub = ((scan_context or {}).get("sub_category") or "").lower()

    for pattern, brand, product_name in PARTIAL_FRAGMENT_RULES:
        if not re.search(pattern, text_l, flags=re.IGNORECASE):
            continue
        if brand.lower() == "lays":
            if not _lays_flavor_fragment_allowed(text_l, sub):
                continue
        if brand.lower() == "bingo" and re.search(r"\blay(?:'|s)?s\b", text_l):
            continue
        return _label_from_brand_product(
            brand, product_name, normalized, confidence=0.88, scan_context=scan_context
        )

    if re.search(r"\bmagic\b", text_l) and _lays_flavor_fragment_allowed(text_l, sub):
        return _label_from_brand_product(
            "Lays", "Indias Magic Masala Potato Chips", normalized, confidence=0.82, scan_context=scan_context
        )
    if re.search(r"\btango\b", text_l) and not _is_ambiguous_lays_tomato_fragment(text_l):
        if _lays_flavor_fragment_allowed(text_l, sub):
            return _label_from_brand_product(
                "Lays", "Tomato Tango Potato Chips", normalized, confidence=0.82, scan_context=scan_context
            )
    if re.search(r"\btomato\b", text_l) and not _is_ambiguous_lays_tomato_fragment(text_l):
        if _lays_flavor_fragment_allowed(text_l, sub):
            return _label_from_brand_product(
                "Lays", "Tomato Tango Potato Chips", normalized, confidence=0.82, scan_context=scan_context
            )
    if re.search(r"\bcream\b", text_l) and _is_ambiguous_lays_cream_fragment(text_l):
        return None
    if (
        re.search(r"\bcream\b", text_l)
        and "onion" in text_l
        and _lays_flavor_fragment_allowed(text_l, sub)
    ):
        return _label_from_brand_product(
            "Lays",
            "American Style Cream and Onion Potato Chips",
            normalized,
            confidence=0.82,
            scan_context=scan_context,
        )
    return None


def personal_care_food_mismatch(label: dict, scan_context: dict | None) -> bool:
    """Block food/digestive SKUs on personal-care shelf scans."""
    if not scan_context:
        return False
    from app.scan_context import NARROW_PC_SUBCATEGORIES, _normalize_key

    cat = _normalize_key(scan_context.get("aislix_category") or "")
    sub = (scan_context.get("sub_category") or "").strip().lower()
    if cat != "personal care" and sub not in NARROW_PC_SUBCATEGORIES:
        return False
    blob = " ".join(
        [
            label.get("brand") or "",
            label.get("product_name") or "",
            label.get("sku") or "",
        ]
    ).lower()
    return any(token in blob for token in PERSONAL_CARE_FOOD_TOKENS)


def expand_partial_ocr_text(text: str, scan_context: dict | None = None) -> str:
    """Normalize common OCR truncations before catalog matching."""
    if not text:
        return text
    t = text.lower()
    sub = ((scan_context or {}).get("sub_category") or "").lower()
    if re.search(r"\bmagic\b", t) and "masala" not in t and sub in {"chips", "potato_chips"}:
        t = re.sub(r"\bmagic\b", "magic masala", t, count=1)
    if re.search(r"\btango\b", t) and "tomato" not in t and re.search(r"\blay(?:'|s)?s\b", t) and sub in {"chips", "potato_chips"}:
        t = re.sub(r"\btango\b", "tomato tango", t, count=1)
    if re.search(r"\bmasala\b", t) and "munch" not in t and "kurkure" in t:
        t = t.replace("masala", "masala munch")
    return t


def match_from_text(text: str, scan_context: dict | None = None) -> dict | None:
    """Best catalog match from OCR text: product hints → brand → SKU."""
    text = normalize_ocr_text(text)
    if not text or len(text.strip()) < 3:
        return None
    text = expand_partial_ocr_text(text, scan_context)
    normalized = _normalize(text)

    for pattern, brand, product_name in PRODUCT_HINTS:
        if not re.search(pattern, normalized, flags=re.IGNORECASE):
            continue
        if brand.lower() == "bingo" and re.search(r"\blay(?:'|s)?s\b", normalized):
            continue
        if brand.lower() == "lays" and re.search(
            r"\bbingo\b|\bmad\s+angles\b|\btedhe\s+medhe\b", normalized
        ):
            continue
        if product_name:
            entry = _catalog_entry(brand, product_name)
            if entry:
                product_name = entry.get("product_name") or product_name
                return {
                    "brand": display_brand_name(brand, product_name),
                    "product_name": product_name,
                    "variant": entry.get("variant") or "",
                    "sku": entry.get("sku") or "",
                    "category": entry.get("category") or infer_category(entry.get("sku") or ""),
                    "confidence": 0.94,
                    "recognition_source": "ocr",
                    "visible_text": text[:240],
                }
            return _label_from_brand_product(
                brand,
                product_name,
                text,
                confidence=0.9,
                scan_context=scan_context,
                allow_brand_fallback=False,
            )
        product = match_product_for_brand(brand, text, scan_context=scan_context)
        if product:
            product["visible_text"] = text[:240]
            product["confidence"] = max(float(product.get("confidence") or 0), 0.9)
            return product
        return {
            "brand": display_brand_name(brand, product_name),
            "product_name": product_name or brand,
            "variant": "",
            "sku": "",
            "category": "General",
            "confidence": 0.88,
            "recognition_source": "ocr",
            "visible_text": text[:240],
        }

    brand_match = match_brand_in_text(text)
    if not brand_match:
        partial = _match_partial_fragments(normalized, scan_context)
        if partial:
            return partial
        return None
    brand, brand_conf = brand_match
    if _tea_brand_blocked_on_pack(text, brand):
        return None
    if _tea_brand_blocked_on_pc_pack(text, brand):
        return None
    product = match_product_for_brand(brand, text, scan_context=scan_context)
    if not product:
        return None
    product["visible_text"] = text[:240]
    product["confidence"] = max(float(product.get("confidence") or 0), brand_conf)
    return product


def reconcile_label_with_text(label: dict, text: str) -> dict:
    """Override GPT/FAISS labels when pack text clearly names a different brand or SKU."""
    if not text or len(text.strip()) < 3:
        return label
    if label_conflicts_with_tea_pack(label, text):
        corrected = match_from_text(text)
        if corrected:
            merged = {**label, **corrected}
            merged["recognition_source"] = (label.get("recognition_source") or "faiss") + "+ocr_fix"
            merged["confidence"] = float(corrected.get("confidence") or 0.88)
            return merged
        return {
            **label,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "recognition_source": "ocr_reject",
        }
    corrected = match_from_text(text)
    if not corrected:
        return label

    current_brand = (label.get("brand") or "").strip().lower()
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not text_brand or text_brand == current_brand:
        if corrected.get("product_name") and corrected.get("product_name") != label.get("product_name"):
            merged = {**label, **corrected}
            merged["recognition_source"] = label.get("recognition_source", "gpt") + "+ocr"
            merged["confidence"] = max(float(label.get("confidence") or 0), float(corrected.get("confidence") or 0))
            return merged
        return label

    # Pack text explicitly names a different brand (e.g. Lipton misread as Tata).
    merged = {**label, **corrected}
    merged["recognition_source"] = (label.get("recognition_source") or "gpt") + "+ocr_fix"
    merged["confidence"] = float(corrected.get("confidence") or 0.88)
    return merged


def _volume_tokens(text: str) -> set[str]:
    return {match.group(0).replace(" ", "").lower() for match in re.finditer(r"\b\d+\s*ml\b", text.lower())}


def _hair_product_type_adjustment(normalized: str, entry: dict) -> float:
    """Prefer shampoo vs conditioner SKUs when pack text indicates product type."""
    sku_l = (entry.get("sku") or "").lower()
    product_l = (entry.get("product_name") or "").lower()
    is_shampoo = "shampoo" in sku_l or "shampoo" in product_l
    is_conditioner = "conditioner" in sku_l or "conditioner" in product_l
    if not is_shampoo and not is_conditioner:
        return 0.0
    if "shampoo" in normalized:
        if is_shampoo:
            return 0.18
        if is_conditioner:
            return -0.28
        if "lotion" in product_l or "roll on" in product_l or "deodorant" in product_l:
            return -0.45
    if re.search(r"\bnivea\s+men\b|\bstrong\s+power\b|\bsea\s+mineral", normalized):
        if is_shampoo:
            return 0.35
        if "lotion" in product_l:
            return -0.5
    if "conditioner" in normalized or "color protect" in normalized:
        if is_conditioner:
            return 0.18
        if is_shampoo:
            return -0.28
    if any(token in normalized for token in ("total repair", "repair 5", "hair fall", "anti dandruff")):
        if is_shampoo:
            return 0.12
        if is_conditioner:
            return -0.18
    return 0.0


def _ocr_specific_sku_adjustment(
    normalized: str,
    entry: dict,
    scan_context: dict | None = None,
) -> float:
    """Align catalog SKU pick with distinctive OCR tokens; penalize cross-aisle SKUs."""
    sku_l = (entry.get("sku") or "").lower()
    product_l = (entry.get("product_name") or "").lower()
    blob = f"{sku_l} {product_l}"
    score = 0.0

    if scan_context:
        from app.scan_context import NARROW_PC_SUBCATEGORIES, _normalize_key

        cat = _normalize_key(scan_context.get("aislix_category") or "")
        sub = (scan_context.get("sub_category") or "").strip().lower()
        if cat == "personal care" or sub in NARROW_PC_SUBCATEGORIES:
            if any(token in blob for token in PERSONAL_CARE_FOOD_TOKENS):
                score -= 0.55
            if sub == "shampoo" and any(token in blob for token in ("shampoo", "conditioner", "vatika", "hair")):
                score += 0.2
            if sub == "deodorant" and "deodorant" in blob:
                score += 0.25

    token_pairs = (
        ("vatika", "vatika"),
        ("hajmola", "hajmola"),
        ("imli", "hajmola"),
        ("axe", "axe"),
        ("kesh", "kesh"),
        ("bingo", "bingo"),
        ("angles", "angles"),
        ("lays", "lays"),
        ("magic", "magic"),
        ("tango", "tango"),
    )
    for ocr_token, sku_token in token_pairs:
        if ocr_token in normalized:
            if sku_token in blob:
                score += 0.35
            elif sku_token in {"hajmola", "bingo", "kesh"}:
                score -= 0.4

    if "lays" in normalized and "bingo" in blob:
        score -= 0.45
    if "vatika" in normalized and "hajmola" in blob:
        score -= 0.5
    if re.search(r"\baxe\b", normalized) and "shampoo" in blob:
        score -= 0.35
    return score


def _subcategory_product_adjustment(
    normalized: str,
    entry: dict,
    scan_context: dict | None = None,
) -> float:
    """Boost SKUs that fit the scan sub-category; penalize obvious mismatches."""
    score = _hair_product_type_adjustment(normalized, entry)
    if not scan_context:
        return score

    sub = (scan_context.get("sub_category") or "").strip()
    if not sub or sub == "others":
        return score

    from app.scan_context import SUB_CATEGORY_PRODUCT_KEYWORDS, infer_product_type

    keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(sub) or []
    if not keywords:
        return score

    sku_l = (entry.get("sku") or "").lower()
    product_l = (entry.get("product_name") or "").lower()
    entry_blob = f"{sku_l} {product_l}"
    entry_type = infer_product_type(entry_blob)
    text_type = infer_product_type(normalized)

    entry_hits = sum(1 for kw in keywords if kw in entry_blob or kw in normalized)
    if entry_hits > 0:
        score += 0.12 * entry_hits

    if text_type and entry_type:
        if text_type == entry_type:
            score += 0.15
        elif text_type == sub and entry_type != sub:
            score -= 0.2

    if sub == "ice_cream":
        if any(token in entry_blob for token in ("kulfi", "ice cream", "funwich", "sorbet", "gelato", "frozen")):
            score += 0.35
        if any(token in entry_blob for token in ("chocolate", "biscuit", "milk", "butter", "ghee", "paneer", "cheese")):
            score -= 0.45
        if "sandwich" in normalized:
            if "sandwich" in entry_blob:
                score += 0.5
            if any(token in entry_blob for token in ("tricone", "cone", "kulfi")):
                score -= 0.6
        if any(token in normalized for token in ("kulfi", "rajbhog", "rajbog", "rajwadi", "rabdi")):
            if "kulfi" in entry_blob:
                score += 0.5
            if "sandwich" in entry_blob:
                score -= 0.6
        if "tricone" in normalized or re.search(r"\bcone\b", normalized):
            if "tricone" in entry_blob or "cone" in entry_blob:
                score += 0.45
            if "sandwich" in entry_blob or "kulfi" in entry_blob:
                score -= 0.55

    conflicting = {
        "ice_cream": ("shampoo", "soap", "tea", "detergent", "biscuit"),
        "shampoo": ("lotion", "skincare", "tea", "biscuit"),
        "tea": ("shampoo", "soap", "chips"),
        "chips": ("tea", "shampoo", "detergent"),
    }
    for conflict in conflicting.get(sub, ()):
        if conflict in entry_blob and not any(kw in entry_blob for kw in keywords):
            score -= 0.25
    return score


def _entries_for_scan_subcategory(
    entries: list[dict],
    scan_context: dict | None,
    normalized: str,
) -> list[dict]:
    """Filter brand catalog rows to the scan sub-category; avoid lotion on shampoo shelves."""
    if not scan_context or not entries:
        return entries
    from app.scan_context import NARROW_PC_SUBCATEGORIES, effective_sub_category

    sub = effective_sub_category(scan_context)
    if sub not in NARROW_PC_SUBCATEGORIES:
        return entries

    def _blob(entry: dict) -> str:
        return " ".join(
            filter(
                None,
                [
                    entry.get("product_name") or "",
                    entry.get("sku") or "",
                    entry.get("variant") or "",
                ],
            )
        ).lower()

    if sub == "shampoo":
        shampoo_rows = [e for e in entries if "shampoo" in _blob(e)]
        if shampoo_rows:
            return shampoo_rows
        if re.search(r"\bnivea\b|\bstrong\s+power\b|\bmen\b", normalized):
            return []
        non_lotion = [e for e in entries if "lotion" not in _blob(e) and "roll on" not in _blob(e)]
        return non_lotion or entries
    if sub == "deodorant":
        deo_rows = [e for e in entries if "deodorant" in _blob(e) or "body spray" in _blob(e)]
        return deo_rows or entries
    if sub == "soap":
        soap_rows = [e for e in entries if "soap" in _blob(e)]
        return soap_rows or entries
    return entries


def _synthetic_brand_product(
    brand: str,
    normalized: str,
    scan_context: dict | None,
) -> dict | None:
    """Catalog gaps: return a typed label when OCR + aisle clearly indicate product kind."""
    if not scan_context:
        return None
    from app.scan_context import effective_sub_category

    sub = effective_sub_category(scan_context)
    brand_l = brand.strip().lower()
    if sub == "shampoo" and brand_l == "nivea":
        if re.search(r"\bmen\b|\bstrong\s+power\b|\bshampoo\b", normalized) or len(normalized) < 24:
            return _label_from_brand_product(
                "Nivea",
                "Men Strong Power Shampoo",
                normalized,
                confidence=0.86,
                scan_context=scan_context,
            )
    return None


def match_product_for_brand(
    brand: str,
    text: str,
    scan_context: dict | None = None,
) -> dict | None:
    """Pick the best catalog SKU for a brand given OCR text."""
    entries = products_for_brand(brand)
    if not entries:
        return None
    normalized = _normalize(text)
    volume_tokens = _volume_tokens(text)
    seen_skus: set[str] = set()
    unique_entries: list[dict] = []
    for entry in entries:
        sku = (entry.get("sku") or "").lower()
        if sku in seen_skus:
            continue
        seen_skus.add(sku)
        unique_entries.append(entry)

    best: dict | None = None
    best_score = 0.0
    for entry in unique_entries:
        product = (entry.get("product_name") or "").strip()
        product_l = product.lower()
        variant = (entry.get("variant") or "").strip()
        sku = (entry.get("sku") or "").strip()
        haystack = " ".join(filter(None, [product, variant, sku.replace("_", " ")]))
        if not haystack:
            continue
        hay_norm = _normalize(haystack)
        if hay_norm in normalized or _normalize(product) in normalized:
            score = 0.92
        else:
            score = _similarity(haystack, text)
            for token in re.split(r"[\s\-]+", _normalize(product)):
                if len(token) >= 4 and _word_in_text(token, normalized):
                    score = max(score, 0.95)
        if volume_tokens:
            entry_vol = _volume_tokens(haystack)
            if entry_vol & volume_tokens:
                score += 0.08
            elif entry_vol and not (entry_vol & volume_tokens):
                score -= 0.05
        score += _subcategory_product_adjustment(normalized, entry, scan_context)
        score += _flavor_token_bonus(normalized, product_l)
        score += _ocr_specific_sku_adjustment(normalized, entry, scan_context)
        if score > best_score or (score == best_score and best and len(product_l) < len((best.get("product_name") or ""))):
            best_score = score
            best = entry
    if best and best_score >= 0.55:
        product_name = best.get("product_name") or brand
        return {
            "brand": display_brand_name(brand, product_name),
            "product_name": product_name,
            "variant": best.get("variant") or "",
            "sku": best.get("sku") or "",
            "category": best.get("category") or infer_category(best.get("sku") or ""),
            "confidence": round(min(0.98, best_score), 4),
            "recognition_source": "ocr",
        }
    fallback_pool = _entries_for_scan_subcategory(unique_entries, scan_context, normalized)
    if not fallback_pool:
        synthetic = _synthetic_brand_product(brand, normalized, scan_context)
        if synthetic:
            return synthetic
        return None
    fallback = fallback_pool[0]
    product_name = fallback.get("product_name") or brand
    return {
        "brand": display_brand_name(brand, product_name),
        "product_name": product_name if product_name != brand else display_brand_name(brand, product_name),
        "variant": "",
        "sku": fallback.get("sku") or "",
        "category": fallback.get("category") or "General",
        "confidence": 0.78,
        "recognition_source": "ocr",
    }


def recover_label_from_context(
    label: dict,
    scan_context: dict | None,
    pack_text: str = "",
) -> dict | None:
    """Fill missing brand or product using OCR, aisle hints, and catalog context."""
    if not scan_context:
        return None

    from app.scan_context import SUB_CATEGORY_BRAND_HINTS, effective_sub_category, label_fits_scan_context

    brand = (label.get("brand") or "").strip()
    product = (label.get("product_name") or "").strip()
    unknown = {"", "unknown", "n/a", "unidentified sku", "unknown product"}

    brand_missing = brand.lower() in unknown
    product_missing = product.lower() in unknown
    if not brand_missing and not product_missing:
        return None

    if pack_text and len(pack_text.strip()) >= 3:
        ocr = match_from_text(pack_text, scan_context=scan_context)
        if ocr and label_fits_scan_context(ocr, scan_context, pack_text):
            brand_ok = (ocr.get("brand") or "").lower() not in unknown
            product_ok = (ocr.get("product_name") or "").lower() not in unknown
            if brand_ok and product_ok:
                ocr["recognition_source"] = (label.get("recognition_source") or "ocr") + "+context"
                return ocr

    aislix_key = (scan_context.get("aislix_category") or "").strip().lower()
    sub = effective_sub_category(scan_context)
    hints: set[str] = set()
    if sub:
        hints.update((SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}).get(sub) or set())
    hints.update(scan_context.get("brand_hints") or set())

    combined = " ".join(filter(None, [product, pack_text, brand])).strip()

    if brand_missing and not product_missing:
        for hint_brand in sorted(hints, key=len, reverse=True):
            candidate = match_product_for_brand(hint_brand, combined, scan_context=scan_context)
            if not candidate:
                continue
            cand_product = (candidate.get("product_name") or "").lower()
            if product.lower() in cand_product or cand_product in product.lower():
                candidate["recognition_source"] = (label.get("recognition_source") or "ocr") + "+context"
                return candidate
        if sub == "ice_cream" or "ice cream" in product.lower() or "kulfi" in product.lower():
            for hint_brand in ("Amul", "Baskin Robbins", "Brooklyn", "Kwality", "Mother Dairy"):
                if hint_brand.lower() not in {h.lower() for h in hints}:
                    continue
                candidate = match_product_for_brand(hint_brand, combined, scan_context=scan_context)
                if candidate and label_fits_scan_context(candidate, scan_context, pack_text):
                    candidate["recognition_source"] = (label.get("recognition_source") or "ocr") + "+context"
                    return candidate

    if not brand_missing and product_missing:
        candidate = match_product_for_brand(brand, combined or product, scan_context=scan_context)
        if candidate and label_fits_scan_context(candidate, scan_context, pack_text):
            candidate["recognition_source"] = (label.get("recognition_source") or "ocr") + "+context"
            return candidate

    if brand_missing and product_missing and hints and combined.strip():
        best: dict | None = None
        best_score = 0.0
        for hint_brand in hints:
            candidate = match_product_for_brand(hint_brand, combined, scan_context=scan_context)
            if not candidate or not label_fits_scan_context(candidate, scan_context, pack_text):
                continue
            score = float(candidate.get("confidence") or 0)
            if score > best_score:
                best_score = score
                best = candidate
        if best:
            best["recognition_source"] = (label.get("recognition_source") or "ocr") + "+context"
            return best

    return None


def category_allows_brand(
    scan_category: str | None,
    brand: str,
    sku: str = "",
    entry_category: str = "",
    scan_context: dict | None = None,
) -> bool:
    """Reject obvious cross-aisle FAISS false positives when scan category is set."""
    from app.scan_context import resolve_scan_context, sku_allowed_in_context

    if scan_context:
        return sku_allowed_in_context(brand, sku=sku, entry_category=entry_category, context=scan_context)

    if not scan_category or not brand:
        return True

    ctx = resolve_scan_context({"category": scan_category})
    if ctx.get("aislix_category"):
        return sku_allowed_in_context(brand, sku=sku, entry_category=entry_category, context=ctx)

    cat = scan_category.lower()
    brand_l = brand.lower()
    sku_cat = infer_category(sku or brand_l).lower()

    tea_keys = ("tea", "beverage", "drink", "coffee")
    snack_keys = ("snack", "chip", "biscuit", "namkeen")
    if any(k in cat for k in tea_keys):
        snack_brands = {
            "mars", "lays", "lay's", "haldiram", "haldiram's", "britannia", "parle",
            "biscoff", "bisk farm", "mtr", "maggi", "maggie", "sunfeast",
        }
        if brand_l in snack_brands:
            return False
        if any(k in cat for k in tea_keys) and sku_cat == "beverages":
            return True
        if any(k in cat for k in tea_keys):
            tea_brands = {
                "lipton", "tetley", "tata", "tata tea", "brooke bond", "taj mahal",
                "tajmahal", "tata gold", "red label", "yellow label", "tazo",
            }
            if any(tb in brand_l for tb in tea_brands):
                return True
            if "tea" in brand_l or "tea" in (sku or "").lower():
                return True
    if any(k in cat for k in snack_keys):
        if brand_l in {"lipton", "tetley", "tropicana", "sofit"}:
            return False
    return True
