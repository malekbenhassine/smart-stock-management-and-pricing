from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional


SCORE_AUTO = 75
SCORE_MANUAL = 60


BRANDS = [
    "hp", "dell", "lenovo", "asus", "acer", "msi", "apple", "bmax",
    "samsung", "huawei", "toshiba", "epson", "canon", "brother",
    "logitech", "razer", "kingston", "sandisk", "western digital",
    "gigabyte", "aorus", "xigmatek", "cooler master", "advance",
]


BRAND_ALIASES = {
    "iphone": "apple",
    "macbook": "apple",
    "galaxy": "samsung",
    "thinkpad": "lenovo",
    "ideapad": "lenovo",
    "pavilion": "hp",
    "envy": "hp",
    "inspiron": "dell",
    "xps": "dell",
    "vivobook": "asus",
    "rog": "asus",
    "tuf": "asus",
    "victus": "hp",
    "maxbook": "bmax",
}


STOP_WORDS = {
    "pc", "portable", "ordinateur", "laptop", "avec", "sans",
    "full", "hd", "ips", "windows", "garantie", "ecran", "écran",
    "memoire", "mémoire", "disque", "ssd", "hdd", "go", "gb",
    "to", "tb", "gris", "noir", "blanc", "gaming", "gamer",
    "gen", "generation", "génération",
}


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""

    value = value.lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))

    replacements = {
        "génération": "gen",
        "generation": "gen",
        "gén": "gen",
        "è": "e",
        "intel core": "core",
        "go": "gb",
        "to": "tb",
        "m.2": "m2",
        "wi-fi": "wifi",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"[/\\|_–]", " ", value)
    value = re.sub(r"[^a-z0-9.+#\- ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def text_similarity(a: Optional[str], b: Optional[str]) -> float:
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)

    if not a_norm or not b_norm:
        return 0.0

    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

    a_tokens = set(w for w in a_norm.split() if len(w) >= 2) - STOP_WORDS
    b_tokens = set(w for w in b_norm.split() if len(w) >= 2) - STOP_WORDS

    if not a_tokens or not b_tokens:
        return round(ratio * 100, 2)

    intersection = a_tokens.intersection(b_tokens)
    union = a_tokens.union(b_tokens)

    jaccard = len(intersection) / len(union)
    coverage = len(intersection) / min(len(a_tokens), len(b_tokens))

    score = max(ratio, (jaccard * 0.45) + (coverage * 0.55))

    return round(score * 100, 2)


def extract_brand(text: str) -> Optional[str]:
    normalized = normalize_text(text)

    for brand in BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", normalized):
            return brand

    for alias, brand in BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return brand

    return None


def normalize_reference_for_match(value: Optional[str]) -> Optional[str]:
    """
    Normalise deux références pour une comparaison exacte.
    X1502VA-BQ903W et x1502va bq903w deviennent x1502vabq903w.
    """
    if not value:
        return None

    value = normalize_text(value)
    value = re.sub(r"[^a-z0-9]+", "", value)

    return value or None


def extract_reference(text: str) -> Optional[str]:
    """
    Extrait une vraie référence produit.
    Priorité aux références complètes avec tiret, puis références compactes.
    On exclut les CPU/connectiques/mots techniques.
    """
    raw = text or ""
    normalized = normalize_text(raw)

    patterns = [
        r"\b[a-z0-9]{4,12}-[a-z0-9]{3,16}\b",  # x1502va-bq903w, 15-fa1006nk
        r"\b[a-z]{1,5}\d{3,6}[a-z]{1,6}\b",    # x1502va, fa506nfr
        r"\b\d[a-z0-9]{5,10}\b",               # 9u1b9ea
    ]

    excluded = [
        r"^i[3579]-?\d", r"^core$", r"^intel$", r"^ryzen$",
        r"^dc-?in$", r"^usb", r"^hdmi$", r"^rj45$",
        r"haut", r"parleur", r"speaker", r"bluetooth", r"wifi",
        r"windows", r"full", r"ecran", r"ips",
    ]

    candidates = []

    for pattern in patterns:
        for match in re.findall(pattern, normalized):
            ref = match.strip().lower()

            if len(ref) < 4:
                continue

            if any(re.search(p, ref) for p in excluded):
                continue

            if ref not in candidates:
                candidates.append(ref)

    if not candidates:
        return None

    candidates.sort(key=len, reverse=True)

    return candidates[0]


def extract_model(text: str) -> Optional[str]:
    normalized = normalize_text(text)

    patterns = [
        r"\b(victus\s*\d{2}-[a-z0-9]{4,12})\b",
        r"\b(victus\s*\d{2})\b",
        r"\b(maxbook\s*x\d+\s*pro)\b",
        r"\b(vivobook\s*[a-z0-9\- ]{1,20})\b",
        r"\b(ideapad\s*[a-z0-9\- ]{1,20})\b",
        r"\b(thinkpad\s*[a-z0-9\- ]{1,20})\b",
        r"\b(pavilion\s*[a-z0-9\- ]{1,20})\b",
        r"\b(inspiron\s*[a-z0-9\- ]{1,20})\b",
        r"\b(latitude\s*[a-z0-9\- ]{1,20})\b",
        r"\b(tuf\s*[a-z0-9\- ]{1,20})\b",
        r"\b(rog\s*[a-z0-9\- ]{1,20})\b",
        r"\b(nitro\s*[a-z0-9\- ]{1,20})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()

    return None


def extract_features(name: str, description: Optional[str] = None) -> dict:
    text = " ".join(filter(None, [name or "", description or ""]))
    normalized = normalize_text(text)

    features = {
        "marque": extract_brand(text),
        "modele": extract_model(text),
        "reference": extract_reference(text),
        "processeur": None,
        "ram": None,
        "stockage": None,
        "ecran": None,
        "gpu": None,
        "os": None,
        "capacite": None,
        "couleur": None,
    }

    cpu_patterns = [
        r"\b(core\s*)?(i3|i5|i7|i9)\s*[- ]?\d{3,5}[a-z0-9]*\b",
        r"\b(i3|i5|i7|i9)\b",
        r"\b(intel\s*)?(n95|n100|n200|n305)\b",
        r"\b(ryzen\s*[3579])\s*[- ]?\d{3,5}[a-z0-9]*\b",
        r"\b(ryzen\s*[3579])\b",
        r"\b(celeron\s+[a-z0-9]+)\b",
    ]

    for pattern in cpu_patterns:
        match = re.search(pattern, normalized)
        if match:
            value = match.group(0)
            value = value.replace("core", "")
            value = re.sub(r"\s+", "", value)
            features["processeur"] = value
            break

    ram_match = re.search(
        r"\b(4|6|8|12|16|24|32|64|128)\s*gb\s*(ddr3|ddr4|ddr5|lpddr4|lpddr5)?\b",
        normalized,
    )
    if ram_match:
        features["ram"] = re.sub(r"\s+", "", ram_match.group(0))

    storage_matches = re.findall(
        r"\b(128|256|512)\s*gb\b|\b(1|2|4|8)\s*tb\b",
        normalized,
    )

    if storage_matches:
        values = []
        for gb, tb in storage_matches:
            if gb:
                values.append(f"{gb}gb")
            if tb:
                values.append(f"{tb}tb")

        if values:
            features["stockage"] = values[-1]

    screen_match = re.search(
        r"\b(13|14|15|15.6|16|17|17.3)\s*(\"|pouces|inch)?",
        normalized,
    )
    if screen_match:
        features["ecran"] = screen_match.group(1)

    gpu_patterns = [
        r"\brtx\s*\d{3,4}\b",
        r"\bgtx\s*\d{3,4}\b",
        r"\bmx\s*\d{3,4}\b",
        r"\bintel\s*uhd\b",
        r"\biris\s*xe\b",
    ]

    for pattern in gpu_patterns:
        match = re.search(pattern, normalized)
        if match:
            features["gpu"] = re.sub(r"\s+", "", match.group(0))
            break

    if "windows 11" in normalized:
        features["os"] = "windows11"
    elif "windows 10" in normalized:
        features["os"] = "windows10"
    elif "freedos" in normalized or "free dos" in normalized:
        features["os"] = "freedos"
    elif "ubuntu" in normalized:
        features["os"] = "ubuntu"

    capacity_match = re.search(r"\b(\d+)\s*(mah|w|watt|va)\b", normalized)
    if capacity_match:
        features["capacite"] = capacity_match.group(0).replace(" ", "")

    for color in [
        "noir", "blanc", "bleu", "rouge", "vert", "gris",
        "argent", "silver", "or", "rose", "violet",
    ]:
        if re.search(rf"\b{color}\b", normalized):
            features["couleur"] = color
            break

    return features


def feature_similarity(internal_features: dict, competitor_features: dict) -> tuple[float, dict]:
    weights = {
        "marque": 20,
        "modele": 25,
        "reference": 30,
        "processeur": 15,
        "ram": 15,
        "stockage": 15,
        "ecran": 5,
        "gpu": 15,
        "os": 3,
        "capacite": 8,
        "couleur": 2,
    }

    possible = 0.0
    obtained = 0.0
    details = {}

    for key, weight in weights.items():
        internal_value = internal_features.get(key)
        competitor_value = competitor_features.get(key)

        if not internal_value and not competitor_value:
            continue

        possible += weight

        matched = False
        partial_score = 0.0

        if internal_value and competitor_value:
            if internal_value == competitor_value:
                matched = True
                partial_score = weight
            else:
                sim = text_similarity(str(internal_value), str(competitor_value))

                if key in {"modele", "reference"} and sim >= 80:
                    matched = True
                    partial_score = weight * 0.8

        obtained += partial_score

        details[key] = {
            "internal": internal_value,
            "competitor": competitor_value,
            "match": matched,
        }

    if possible == 0:
        return 50.0, details

    return round((obtained / possible) * 100, 2), details


def match_status(score: float, details: dict | None = None) -> str:
    details = details or {}

    internal_features = details.get("internalFeatures", {})
    competitor_features = details.get("competitorFeatures", {})

    same_reference = (
        internal_features.get("reference")
        and competitor_features.get("reference")
        and internal_features.get("reference") == competitor_features.get("reference")
    )

    same_model = (
        internal_features.get("modele")
        and competitor_features.get("modele")
        and internal_features.get("modele") == competitor_features.get("modele")
    )

    same_brand = (
        internal_features.get("marque")
        and competitor_features.get("marque")
        and internal_features.get("marque") == competitor_features.get("marque")
    )

    same_gpu = (
        internal_features.get("gpu")
        and competitor_features.get("gpu")
        and internal_features.get("gpu") == competitor_features.get("gpu")
    )

    same_ram = (
        internal_features.get("ram")
        and competitor_features.get("ram")
        and internal_features.get("ram") == competitor_features.get("ram")
    )

    same_cpu = (
        internal_features.get("processeur")
        and competitor_features.get("processeur")
        and internal_features.get("processeur") == competitor_features.get("processeur")
    )

    # Règle métier forte :
    # même marque + même référence/modèle + au moins une caractéristique forte identique
    if score >= 65 and same_brand and (same_reference or same_model) and (same_gpu or same_ram or same_cpu):
        return "MATCHED"

    # Règle métier moyenne :
    # score très proche du seuil + référence/modèle identique
    if score >= 70 and (same_reference or same_model) and (same_gpu or same_ram or same_cpu):
        return "MATCHED"

    if score >= SCORE_AUTO:
        return "MATCHED"

    if score >= SCORE_MANUAL:
        return "MANUAL_REVIEW"

    return "IGNORED"


def compute_match_score(
    internal_name: str,
    internal_desc: Optional[str],
    competitor_name: str,
    competitor_desc: Optional[str] = None,
) -> tuple[float, dict]:
    name_score = text_similarity(internal_name, competitor_name)
    description_score = text_similarity(internal_desc, competitor_desc)

    internal_features = extract_features(internal_name, internal_desc)
    competitor_features = extract_features(competitor_name, competitor_desc)

    internal_reference = internal_features.get("reference")
    competitor_reference = competitor_features.get("reference")

    internal_ref_norm = normalize_reference_for_match(internal_reference)
    competitor_ref_norm = normalize_reference_for_match(competitor_reference)

    # ============================================================
    # RÈGLE PRINCIPALE : même référence = même produit
    # ============================================================
    if internal_ref_norm and competitor_ref_norm:
        if internal_ref_norm == competitor_ref_norm:
            details = {
                "nameScore": name_score,
                "descriptionScore": description_score,
                "featuresScore": 100,
                "internalFeatures": internal_features,
                "competitorFeatures": competitor_features,
                "featuresDetails": {
                    "reference": {
                        "internal": internal_reference,
                        "competitor": competitor_reference,
                        "match": True,
                        "reason": "REFERENCE_EXACT_MATCH",
                    }
                },
                "status": "MATCHED",
                "reason": "REFERENCE_EXACT_MATCH",
            }

            return 95.0, details

        details = {
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": 0,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": {
                "reference": {
                    "internal": internal_reference,
                    "competitor": competitor_reference,
                    "match": False,
                    "reason": "REFERENCE_MISMATCH",
                }
            },
            "status": "IGNORED",
            "reason": "REFERENCE_MISMATCH",
        }

        return 0.0, details

    # ============================================================
    # Fallback si une référence manque : ancien scoring contrôlé
    # ============================================================
    features_score, features_details = feature_similarity(
        internal_features,
        competitor_features,
    )

    final_score = round(
        (name_score * 0.35)
        + (description_score * 0.15)
        + (features_score * 0.50),
        2,
    )

    details = {
        "nameScore": name_score,
        "descriptionScore": description_score,
        "featuresScore": features_score,
        "internalFeatures": internal_features,
        "competitorFeatures": competitor_features,
        "featuresDetails": features_details,
    }

    status = match_status(final_score, details)

    details["status"] = status

    return final_score, details
