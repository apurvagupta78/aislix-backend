"""Map Grocer-Help / SKU class names to Aislix category · sub-category labels."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CATEGORIES_PATH = BASE_DIR / "data" / "categories.json"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@lru_cache(maxsize=1)
def _categories_index() -> dict[str, dict]:
    raw = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for cat in raw:
        out[cat["id"]] = cat
    return out


def _label(category_id: str, sub_category_id: str) -> str:
    cats = _categories_index()
    cat = cats.get(category_id) or {}
    cat_name = cat.get("name") or category_id.replace("_", " ").title()
    sub_name = sub_category_id.replace("_", " ").title()
    for sub in cat.get("subcategories") or []:
        if sub.get("id") == sub_category_id:
            sub_name = sub.get("label") or sub_name
            break
    return f"{cat_name} · {sub_name}"


# (category_id, sub_category_id) — first match wins; order matters (specific before broad).
_RULES: list[tuple[tuple[str, ...], str, str]] = [
    # Beverages
    (("tea", "chai", "tajmahal", "taj_mahal", "lipton", "tetley", "brookebond", "brooke", "redlabel", "taaza", "wagh", "tata_tea", "tata_premium", "tata_premium", "tata gold", "tata_gold", "tata_agni", "greenfields_tea", "organicindia", "organic india", "organicindia_tea", "tulsi", "vahdam", "teatime", "teavalley", "marveltea", "twinings", "tez"), "beverages", "tea"),
    (("coffee", "nescafe", "bru", "davidoff", "lecafe", "wagh bakri"), "beverages", "coffee"),
    (("pepsi", "coca", "sprite", "fanta", "thumps", "mirinda", "maaza", "frooti", "limca", "kinley", "soda", "softdrink", "redbull", "sting", "monster", "energy", "schweppes", "7up", "appy", "paperboat", "juice", "tropicana", "real", "minute", "coconut water", "coconutwater"), "beverages", "others"),
    (("water", "kinley"), "beverages", "water"),
    # Frozen & ice cream (product-type tokens before bare brand names)
    (
        (
            "icecream", "ice cream", "ice_cream", "kulfi", "funwich",
            "frozen dessert", "sorbet", "gelato", "cornetto", "sandwich",
            "brooklyn", "baskin", "baskin robbins", "topntown", "havmor",
            "vadilal", "kwality", "walls", "cream bell", "creamery",
            "amul_cool", "amulcool", "stick", "popsicle",
        ),
        "frozen_ice_cream",
        "ice_cream",
    ),
    (("frozen vegetable", "frozen veg", "frozen peas", "frozen corn"), "frozen_ice_cream", "frozen_vegetables"),
    (("frozen snack", "frozen paratha", "frozen samosa"), "frozen_ice_cream", "frozen_snacks"),
    (("frozen meal", "frozen pizza"), "frozen_ice_cream", "frozen_meals"),
    (("frozen",), "frozen_ice_cream", "frozen_snacks"),
    # Dairy (no bare "amul" — milk/curd SKUs still match via milk, dahi, etc.)
    (
        (
            "milk", "dahi", "curd", "yogurt", "lassi", "paneer", "cheese",
            "butter", "ghee", "mother dairy", "motherdairy", "nandini", "milky",
            "epigamia", "danone", "milkmaid", "toned milk", "full cream milk",
        ),
        "dairy_chilled",
        "others",
    ),
    # Personal care
    (("shampoo", "tresemme", "head", "shoulders", "pantene", "sunsilk", "clinic plus", "clinicplus", "himalaya", "dove", "loreal", "fiama", "herbal", "vatika", "dabur", "hyaluron"), "personal_care", "shampoo"),
    (("soap", "dettol", "lifebuoy", "santoor", "pears", "lux", "cinthol", "medimix"), "personal_care", "soap"),
    (("toothpaste", "tooth brush", "toothbrush", "colgate", "pepsodent", "sensodyne", "dabur red"), "personal_care", "toothpaste"),
    (("deodorant", "deodrant", "axe", "park avenue", "nivea", "fa "), "personal_care", "deodorant"),
    (("lotion", "skincare", "face wash", "facewash", "vaseline", "ponds", "garnier", "mamaearth", "cetaphil", "boroplus"), "personal_care", "skincare"),
    (("shaving", "gillette", "veet"), "personal_care", "shaving"),
    # Home care
    (("detergent", "surf", "ariel", "tide", "rin", "wheel", "mr white"), "home_care", "detergent"),
    (("dishwash", "dish wash", "vim", "prill"), "home_care", "dishwash"),
    (("harpic", "toilet", "lizol", "domex", "floor", "phenyl", "odonil", "air freshener", "airfreshener", "baygon", "allout", "mosquito", "harpic"), "home_care", "others"),
    # Grocery staples
    (("rice", "daawat", "indiagate", "fortune", "basmati", "poha", "atta", "flour", "aashirvaad", "pillsbury"), "grocery_staples", "rice"),
    (("dal", "pulse", "rajma", "moong", "toor"), "grocery_staples", "dal"),
    (("oil", "refined", "mustard", "sunflower", "saffola", "fortune oil", "cooking"), "grocery_staples", "oil"),
    (("sugar", "salt", "tata salt", "rocksalt", "jaggery"), "grocery_staples", "sugar"),
    (("spice", "masala", "mdh", "everest", "catch", "suhana", "mtr", "tandoori", "pickle", "ketchup", "maggi masala"), "grocery_staples", "spices"),
    # Packaged food & snacks
    (("biscuit", "cookie", "parle", "britannia", "oreo", "marie", "goodday", "bourbon", "digestive", "unibic", "mcvities"), "packaged_food_snacks", "biscuits"),
    (("chip", "lays", "kurkure", "bingo", "namkeen", "haldiram", "bikaji", "too yumm", "tooyumm", "cornitos", "protein", "protein bar", "protein_bar", "whole truth", "whole_truth"), "packaged_food_snacks", "chips"),
    (("noodle", "maggi", "yippee", "top ramen", "knorr", "nissin", "ching", "mtr ready"), "packaged_food_snacks", "noodles"),
    (("chocolate", "cadbury", "nestle", "kitkat", "munch", "perk", "dairy milk", "bournville", "ferrero", "toblerone", "amul_choco"), "packaged_food_snacks", "chocolates"),
    (("cereal", "muesli", "oats", "cornflake", "baggrys", "quaker", "kellog"), "packaged_food_snacks", "cereals"),
    (("sauce", "ketchup", "mayo", "mayonnaise", "veeba", "kissan"), "packaged_food_snacks", "sauces"),
    # Health & baby
    (("horlicks", "bournvita", "complan", "protinex", "pediasure", "ensure", "vitamin", "supplement"), "health_wellness", "health_foods"),
    (("baby", "pampers", "huggies", "johnson", "chicco", "mee mee", "diaper", "wipe"), "baby_pet_care", "others"),
    (("pedigree", "dog food", "cat food"), "baby_pet_care", "pet_food"),
]


def _key_in_text(key: str, text: str) -> bool:
    """Match rule tokens without substring false positives (e.g. real in loreal)."""
    key = key.strip()
    if not key:
        return False
    if " " in key:
        return key in text
    if len(key) <= 4:
        return bool(re.search(rf"\b{re.escape(key)}\b", text))
    return key in text


def map_class_to_aislix_category(class_name: str) -> dict[str, str]:
    """Return category label plus ids for a Grocer-Help YOLO class name."""
    text = _norm(class_name.replace("_", " "))
    for keys, category_id, sub_id in _RULES:
        if any(_key_in_text(k, text) for k in keys):
            return {
                "category_id": category_id,
                "sub_category_id": sub_id,
                "category": _label(category_id, sub_id),
            }
    return {
        "category_id": "others",
        "sub_category_id": "others",
        "category": _label("others", "others"),
    }
