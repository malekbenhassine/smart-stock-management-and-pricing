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
    "redragon", "mibro", "xiaomi", "amazfit", "haylou", "kieslect", "hoco", "joyroom",
    "oppo", "realme", "honor", "infinix", "tecno", "vivo",
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
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "mi watch": "xiaomi",
    "mibro": "mibro",
}


STOP_WORDS = {
    "pc", "portable", "ordinateur", "laptop", "avec", "sans",
    "full", "hd", "ips", "windows", "garantie", "ecran", "écran",
    "memoire", "mémoire", "disque", "ssd", "hdd", "go", "gb",
    "to", "tb", "gris", "noir", "blanc", "gaming", "gamer",
    "gen", "generation", "génération", "produit",
    "montre", "connectee", "connecte", "smartwatch", "smart", "watch",
}


# ============================================================
# Normalisation
# ============================================================

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
        # FIX: "go" et "to" comme unités de stockage remplacés avec word-boundary
        # pour éviter de corrompre des mots (ex: "logo" → "lgb")
        "m.2": "m2",
        "wi-fi": "wifi",
        "thugga ii": "thugga 2",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    # Normaliser les formats smartphones fréquents : 12+512G, 8G/256G, 12/512G
    # Attention : on ne convertit pas 5G en 5gb, car 5G = réseau mobile.
    value = re.sub(
        r"\b(4|6|8|12|16|24|32)\s*\+\s*(128|256|512)\s*g\b",
        r"\1gb \2gb",
        value,
    )
    value = re.sub(
        r"\b(4|6|8|12|16|24|32)\s*g\s*/\s*(128|256|512)\s*g\b",
        r"\1gb \2gb",
        value,
    )
    value = re.sub(
        r"\b(4|6|8|12|16|24|32)\s*/\s*(128|256|512)\s*g\b",
        r"\1gb \2gb",
        value,
    )

    # FIX: Remplacement go/to uniquement quand ce sont des unités (avec word boundaries)
    value = re.sub(r"\b(\d+)\s*go\b", r"\1gb", value)
    value = re.sub(r"\b(\d+)\s*to\b", r"\1tb", value)
    value = re.sub(r"\b(4|6|8|12|16|24|32|64|128|256|512)\s*g\b", r"\1gb", value)

    value = re.sub(r"[/\\|_–]", " ", value)
    value = re.sub(r"[^a-z0-9.+#\- ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def normalize_ref(value: Optional[str]) -> Optional[str]:
    """
    Normalise une référence/SKU pour comparer correctement :

    XPAW021
    Réf : XPAW021
    xpaw-021
    /montre-connectee-mibro-watch-c4-silver-xpaw021.html

    deviennent comparables.
    """
    if not value:
        return None

    value = str(value).lower().strip()

    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))

    # Nettoyer les mots parasites fréquents
    value = value.replace("référence", " ")
    value = value.replace("reference", " ")
    value = value.replace("réf", " ")
    value = value.replace("ref", " ")
    value = value.replace("sku", " ")
    value = value.replace(":", " ")
    value = value.replace("_", " ")
    value = value.replace("-", " ")

    # Garder uniquement lettres/chiffres
    value = re.sub(r"[^a-z0-9]+", "", value)

    return value or None


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


# ============================================================
# Extraction des caractéristiques
# ============================================================

def extract_brand(text: str) -> Optional[str]:
    normalized = normalize_text(text)

    for brand in BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", normalized):
            return brand

    for alias, brand in BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return brand

    return None


def extract_reference(text: str) -> Optional[str]:
    """
    Extrait une vraie référence produit.

    Correction importante :
    - supporte XPAW021, XPAW021-S, BU-MIBRO-L3PRO-GREEN
    - supporte les références compactes lettres+chiffres
    - évite de prendre les CPU, tailles mémoire, ports, etc.
    """
    normalized = normalize_text(text or "")

    patterns = [
        # Références type BU-MIBRO-L3PRO-GREEN, X1502VA-BQ903W
        r"\b[a-z0-9]{2,15}(?:-[a-z0-9]{2,20})+\b",

        # Références type XPAW021, ABC123, MIBROC4, G2412F
        r"\b[a-z]{2,8}\d{2,8}[a-z0-9]{0,8}\b",

        # Références type 82LX00ECFG, 9U1B9EA
        r"\b\d[a-z0-9]{5,14}\b",

        # Références type C4 uniquement si contexte marque/montre
        r"\b[a-z]\d{1,3}\b",
    ]

    excluded_patterns = [
        r"^i[3579]-?[a-z0-9]*$",
        r"^n\d{2,4}$",
        r"^ryzen.*$",
        r"^celeron.*$",
        r"^core.*$",
        r"^intel.*$",
        r"^amd.*$",
        r"^usb.*$",
        r"^hdmi$",
        r"^vga$",
        r"^rj45$",
        r"^wifi$",
        r"^bluetooth$",
        r"^windows.*$",
        r"^full.*$",
        r"^fhd$",
        r"^ips$",
        r"^\d+(gb|tb|go|to)$",
        r"^\d+\.?\d*$",
        r"^\d+hz$",
        r"^\d+w$",
    ]

    candidates: list[str] = []

    for pattern in patterns:
        for match in re.findall(pattern, normalized):
            ref = str(match).strip().replace(" ", "").lower()

            if len(ref) < 3:
                continue

            if any(re.match(excluded, ref) for excluded in excluded_patterns):
                continue

            # Sécurité : rejeter les CPU qui passent quand même
            if re.match(r"^i[3579]-?\d+", ref):
                continue

            if re.match(r"^n\d{2,4}$", ref):
                continue

            # C4 seul est accepté seulement si contexte Mibro / smartwatch
            if re.match(r"^[a-z]\d{1,3}$", ref):
                if not any(word in normalized for word in ["mibro", "watch", "montre", "smartwatch"]):
                    continue

            if ref not in candidates:
                candidates.append(ref)

    if not candidates:
        return None

    # Priorité aux références longues et spécifiques, puis celles avec tiret.
    candidates.sort(key=lambda x: (len(x), "-" in x), reverse=True)

    return candidates[0]


def extract_model(text: str) -> Optional[str]:
    normalized = normalize_text(text)

    patterns = [
        # Smartphones Samsung Galaxy : Galaxy A17 5G, Galaxy A56, Galaxy S24 Ultra...
        r"\b(galaxy\s*[asmz]?\s*\d{1,3}\s*(?:fe|ultra|plus|pro|max)?\s*(?:5g)?)\b",
        # iPhone : iPhone 15 Pro Max, iPhone 14, etc.
        r"\b(iphone\s*\d{1,2}\s*(?:pro|max|plus|mini)?(?:\s*max)?)\b",
        # Xiaomi / Redmi / Poco
        r"\b(redmi\s*note\s*\d{1,2}\s*(?:pro|plus)?(?:\s*5g)?)\b",
        r"\b(redmi\s*\d{1,2}[a-z]?\s*(?:pro|plus)?(?:\s*5g)?)\b",
        r"\b(poco\s*[a-z]\d{1,2}\s*(?:pro)?(?:\s*5g)?)\b",
        # OPPO / Realme / Vivo / Honor / Infinix / Tecno
        # Exemples : Reno 15F 5G, OPPO Reno15 F 5G, A3, Note 40 Pro
        r"\b(?:oppo\s*)?(reno\s*\d{1,2}\s*[a-z]?\s*(?:5g)?)\b",
        r"\b(?:oppo\s*)?(a\s*\d{1,3}\s*(?:5g)?)\b",
        r"\b(?:realme\s*)?(c\s*\d{1,3}\s*(?:5g)?)\b",
        r"\b(?:honor\s*)?(x\s*\d{1,3}\s*(?:5g)?)\b",
        r"\b(?:infinix\s*)?(note\s*\d{1,2}\s*(?:pro)?\s*(?:5g)?)\b",
        r"\b(?:tecno\s*)?(spark\s*\d{1,2}\s*(?:pro)?\s*(?:5g)?)\b",
        r"\b(victus\s*\d{2}-[a-z0-9]{4,12})\b",
        r"\b(victus\s*\d{2})\b",
        r"\b(maxbook\s*x\d+\s*pro)\b",
        r"\b(vivobook\s*[a-z0-9\- ]{1,18})\b",
        r"\b(ideapad\s*[a-z0-9\- ]{1,18})\b",
        r"\b(thinkpad\s*[a-z0-9\- ]{1,18})\b",
        r"\b(pavilion\s*[a-z0-9\- ]{1,18})\b",
        r"\b(inspiron\s*[a-z0-9\- ]{1,18})\b",
        r"\b(latitude\s*[a-z0-9\- ]{1,18})\b",
        r"\b(tuf\s*[a-z0-9\- ]{1,18})\b",
        r"\b(rog\s*[a-z0-9\- ]{1,18})\b",
        r"\b(nitro\s*[a-z0-9\- ]{1,18})\b",
        r"\b(mibro\s*c\d+[a-z0-9\- ]{0,10})\b",
        r"\b(mibro\s*lite\s*\d+\s*pro)\b",
        r"\b(lite\s*\d+\s*pro)\b",
        r"\b(c\d+)\b",
        r"\b(thugga\s*2)\b",
        r"\b(thugga\s*ii)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            model = re.sub(r"\s+", " ", match.group(1)).strip()

            # Nettoyage pour éviter que le modèle capture trop de specs
            stop_tokens = [
                " i3", " i5", " i7", " i9", " ryzen",
                " 4gb", " 6gb", " 8gb", " 12gb", " 16gb", " 24gb", " 32gb",
                " 128gb", " 256gb", " 512gb", " 1tb",
                " rtx", " gtx", " windows", " noir", " gris", " black", " gray", " grey",
            ]

            for token in stop_tokens:
                if token in model:
                    model = model.split(token)[0].strip()
                    break

            return model or None

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
        r"\b(intel\s*)?(n95|n100|n200|n305|n4500)\b",
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
        r"\b(13|14|15|15\.6|16|17|17\.3|19|21\.5|22|24|27|32)\s*(\"|\"|pouces|inch)?\b",
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

    capacity_match = re.search(r"\b(\d+)\s*(mah|w|watt|va|hz)\b", normalized)
    if capacity_match:
        features["capacite"] = capacity_match.group(0).replace(" ", "")

    color_aliases = {
        "noir": "noir",
        "black": "noir",
        "blanc": "blanc",
        "white": "blanc",
        "gris": "gris",
        "gris fonce": "gris",
        "gray": "gris",
        "grey": "gris",
        "argent": "silver",
        "silver": "silver",
        "bleu": "bleu",
        "blue": "bleu",
        "rouge": "rouge",
        "red": "rouge",
        "vert": "vert",
        "green": "vert",
        "rose": "rose",
        "pink": "rose",
        "violet": "violet",
    }

    for raw_color, normalized_color in color_aliases.items():
        if re.search(rf"\b{re.escape(raw_color)}\b", normalized):
            features["couleur"] = normalized_color
            break

    return features


# ============================================================
# Matching logique
# ============================================================

def _same(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b and normalize_text(str(a)) == normalize_text(str(b)))


def _similar(a: Optional[str], b: Optional[str], threshold: float = 85) -> bool:
    if not a or not b:
        return False

    return text_similarity(str(a), str(b)) >= threshold


def _critical_mismatches(internal: dict, competitor: dict) -> list[str]:
    """
    Si deux valeurs critiques existent et sont différentes,
    on rejette le produit.
    Exemple :
    - RTX 3050 ≠ RTX 5060
    - 6GB ≠ 16GB
    - 912-V812-056 ≠ 912-V812-077
    """
    critical_keys = [
        "modele",
        "processeur",
        "ram",
        "stockage",
        "gpu",
    ]

    mismatches = []

    for key in critical_keys:
        a = internal.get(key)
        b = competitor.get(key)

        if not a or not b:
            continue

        if key == "modele":
            if not (_same(a, b) or _similar(a, b, threshold=88)):
                mismatches.append(key)
        else:
            if not _same(a, b):
                mismatches.append(key)

    return mismatches

def _feature_points(internal: dict, competitor: dict) -> tuple[int, dict]:
    """
    Score basé sur les caractéristiques principales.
    """
    weights = {
        "marque": 15,
        "modele": 25,
        "processeur": 20,
        "ram": 15,
        "stockage": 15,
        "ecran": 5,
        "couleur": 3,
        "gpu": 10,
    }

    score = 0
    details = {}

    for key, weight in weights.items():
        a = internal.get(key)
        b = competitor.get(key)

        if not a and not b:
            details[key] = {
                "internal": a,
                "competitor": b,
                "match": None,
                "reason": "ABSENT_BOTH",
            }
            continue

        if a and b:
            if _same(a, b):
                score += weight
                details[key] = {
                    "internal": a,
                    "competitor": b,
                    "match": True,
                    "reason": "EXACT",
                    "points": weight,
                }
            elif key in {"modele"} and _similar(a, b, threshold=88):
                partial = int(weight * 0.8)
                score += partial
                details[key] = {
                    "internal": a,
                    "competitor": b,
                    "match": True,
                    "reason": "SIMILAR",
                    "points": partial,
                }
            else:
                details[key] = {
                    "internal": a,
                    "competitor": b,
                    "match": False,
                    "reason": "DIFFERENT",
                    "points": 0,
                }
        else:
            details[key] = {
                "internal": a,
                "competitor": b,
                "match": None,
                "reason": "MISSING_ONE_SIDE",
                "points": 0,
            }

    return score, details


def match_status(score: float, details: dict | None = None) -> str:
    """
    FIX: Logique corrigée pour tenir compte du score numérique en plus du match_type.
    - MATCHED       : score >= SCORE_AUTO  ou match_type EXACT_REFERENCE/HIGH_CONFIDENCE
    - MANUAL_REVIEW : score >= SCORE_MANUAL ou match_type MEDIUM_CONFIDENCE
    - IGNORED       : score < SCORE_MANUAL
    """
    details = details or {}

    match_type = details.get("match_type") or details.get("matchType")

    if match_type in {"EXACT_REFERENCE", "EXACT_REFERENCE_DIRECT", "HIGH_CONFIDENCE"}:
        return "MATCHED"

    if match_type == "MEDIUM_CONFIDENCE":
        return "MANUAL_REVIEW"

    # Sécurité anti-faux match :
    # si le moteur dit NO_MATCH/absence de preuve, on ne transforme plus
    # automatiquement un score numérique 75 en MATCHED.
    # Le score seul peut être trompé par des mots génériques.
    if match_type in {None, "NO_MATCH"}:
        if score >= SCORE_MANUAL:
            return "MANUAL_REVIEW"
        return "IGNORED"

    return "IGNORED"

def _is_real_reference_candidate(value: Optional[str]) -> bool:
    """
    Vérifie qu'un token ressemble vraiment à une référence produit.
    Évite les faux candidats comme : carte, graphique, geforce, ventus, gaming...
    """
    if not value:
        return False

    raw = str(value).strip().lower()
    ref = normalize_ref(raw)

    if not ref:
        return False

    if len(ref) < 5:
        return False

    if not re.search(r"\d", ref):
        return False

    generic_words = {
        "carte", "graphique", "gaming", "gamer", "geforce", "rtx", "gtx",
        "ventus", "nvidia", "radeon", "msi", "asus", "gigabyte", "aorus",
        "disque", "interne", "externe", "ssd", "hdd", "ordinateur",
        "portable", "ecran", "moniteur", "memoire", "ram", "gddr6",
        "gddr7", "oc", "ti", "go", "gb",
    }

    if ref in generic_words:
        return False

    # Éviter de considérer RTX3050 comme une référence exacte.
    if re.fullmatch(r"(rtx|gtx|rx)\d{3,4}(ti)?", ref):
        return False

    # Éviter les capacités comme 6Go, 16Go, 250Go...
    if re.fullmatch(r"\d+(gb|go|tb|to)", ref):
        return False

    return True


def _extract_reference_candidates_strict(text: Optional[str]) -> set[str]:
    """
    Extrait seulement les vraies références.
    Exemple :
    - 912-V812-056 -> 912v812056
    - 912-V812-077 -> 912v812077
    - XPAW021 -> xpaw021

    Important :
    912-V812 ne doit PAS matcher 912-V812-056.
    """
    if not text:
        return set()

    raw = str(text)
    normalized = normalize_text(raw)

    patterns = [
        # Référence avec plusieurs blocs : 912-V812-056, X1502VA-BQ903W
        r"\b[a-z0-9]{2,15}(?:[-/][a-z0-9]{2,15}){1,4}\b",

        # Référence lettres + chiffres : XPAW021, APPLE176, SSD7CS900
        r"\b[a-z]{2,12}\d{2,8}[a-z0-9]{0,8}\b",

        # Référence chiffres + lettres/chiffres : 9S6-3...
        r"\b\d[a-z0-9]{5,15}\b",
    ]

    refs: set[str] = set()

    for pattern in patterns:
        for match in re.findall(pattern, normalized, flags=re.IGNORECASE):
            if _is_real_reference_candidate(match):
                ref = normalize_ref(match)
                if ref:
                    refs.add(ref)

    return refs

def compute_match_score(
    internal_name: str,
    internal_desc: Optional[str],
    competitor_name: str,
    competitor_desc: Optional[str] = None,
) -> tuple[float, dict]:
    """
    Matching 

    Objectif :
    - Accepter le produit si la référence interne existe dans :
      nom concurrent + description concurrente + sku concurrent + URL.
    - Ne pas dépendre uniquement de skuConcurrent, car parfois le scraper extrait
      un mauvais SKU comme "roidisseur".
    - Garder une logique de score pour les cas sans référence exacte.
    """

    internal_name = internal_name or ""
    internal_desc = internal_desc or ""
    competitor_name = competitor_name or ""
    competitor_desc = competitor_desc or ""

    name_score = text_similarity(internal_name, competitor_name)
    description_score = text_similarity(internal_desc, competitor_desc)

    internal_features = extract_features(internal_name, internal_desc)
    competitor_features = extract_features(competitor_name, competitor_desc)

    internal_ref = normalize_ref(internal_features.get("reference"))
    competitor_ref = normalize_ref(competitor_features.get("reference"))

    internal_brand = internal_features.get("marque")
    competitor_brand = competitor_features.get("marque")

    reasons = []

    feature_score, feature_details = _feature_points(
        internal_features,
        competitor_features,
    )

    # ============================================================
    # 0. Matching strict par vraie référence produit
    # ============================================================

    internal_ref_candidates = _extract_reference_candidates_strict(
        " ".join([
            internal_name,
            internal_desc,
        ])
    )

    competitor_ref_candidates = _extract_reference_candidates_strict(
        " ".join([
            competitor_name,
            competitor_desc,
        ])
    )

    if internal_ref:
        internal_ref_candidates.add(internal_ref)

    if competitor_ref:
        competitor_ref_candidates.add(competitor_ref)

    exact_refs = internal_ref_candidates.intersection(competitor_ref_candidates)

    early_internal_text = normalize_text(f"{internal_name} {internal_desc}")
    early_competitor_text = normalize_text(f"{competitor_name} {competitor_desc}")
    early_smartphone_keywords = [
        "smartphone", "galaxy", "iphone", "redmi", "poco", "xiaomi",
        "oppo", "reno", "realme", "honor", "huawei", "infinix", "tecno", "vivo",
    ]
    early_is_smartphone = any(
        keyword in early_internal_text or keyword in early_competitor_text
        for keyword in early_smartphone_keywords
    )

    early_same_model = (
        _same(internal_features.get("modele"), competitor_features.get("modele"))
        or _similar(internal_features.get("modele"), competitor_features.get("modele"), 88)
    )

    # Si les deux côtés ont des références mais aucune référence identique :
    # on rejette directement.
    # Exemple :
    # 912-V812-056 ≠ 912-V812-015
    # 912-V812-056 ≠ 912-V812-077
    if internal_ref_candidates and competitor_ref_candidates and not exact_refs:
        # Cas important pour les smartphones : les sites mettent souvent dans le SKU
        # la couleur, la variante commerciale ou le code réseau.
        # Exemple : OPPO-RENO15F-12/512-TBLUE ≠ OPPO-RENO15F-5G-BL
        # On ne doit pas rejeter avant d'avoir comparé modèle/RAM/stockage.
        if early_is_smartphone and early_same_model:
            reasons.append(
                "Références/SKU différents, mais smartphone avec même modèle détecté. "
                "Comparaison poursuivie sur RAM, stockage et couleur."
            )
        else:
            reasons.append(
                "Références différentes : "
                + ", ".join(sorted(internal_ref_candidates))
                + " ≠ "
                + ", ".join(sorted(competitor_ref_candidates))
                + "."
            )

            details = {
                "same_product": False,
                "sameProduct": False,
                "score": 0,
                "match_type": "NO_MATCH",
                "matchType": "NO_MATCH",
                "status": "IGNORED",
                "reasons": reasons,
                "nameScore": name_score,
                "descriptionScore": description_score,
                "featuresScore": feature_score,
                "internalFeatures": internal_features,
                "competitorFeatures": competitor_features,
                "featuresDetails": feature_details,
                "criticalMismatches": ["reference"],
            }

            return 0.0, details

    ref_found = bool(exact_refs)

    if ref_found:
        reasons.append(
            "Référence exacte identique trouvée : "
            + ", ".join(sorted(exact_refs))
            + "."
        )

        if internal_brand and competitor_brand and internal_brand != competitor_brand:
            reasons.append(
                f"Référence identique mais marques différentes : {internal_brand} ≠ {competitor_brand}."
            )

            details = {
                "same_product": False,
                "sameProduct": False,
                "score": 0,
                "match_type": "NO_MATCH",
                "matchType": "NO_MATCH",
                "status": "IGNORED",
                "reasons": reasons,
                "nameScore": name_score,
                "descriptionScore": description_score,
                "featuresScore": feature_score,
                "internalFeatures": internal_features,
                "competitorFeatures": competitor_features,
                "featuresDetails": feature_details,
                "criticalMismatches": ["marque"],
            }

            return 0.0, details

        mismatches = _critical_mismatches(internal_features, competitor_features)

        if mismatches:
            reasons.append(
                "Référence identique, mais caractéristique critique différente : "
                + ", ".join(mismatches)
                + "."
            )

            details = {
                "same_product": False,
                "sameProduct": False,
                "score": 55,
                "match_type": "NO_MATCH",
                "matchType": "NO_MATCH",
                "status": "IGNORED",
                "reasons": reasons,
                "nameScore": name_score,
                "descriptionScore": description_score,
                "featuresScore": feature_score,
                "internalFeatures": internal_features,
                "competitorFeatures": competitor_features,
                "featuresDetails": feature_details,
                "criticalMismatches": mismatches,
            }

            return 55.0, details

        details = {
            "same_product": True,
            "sameProduct": True,
            "score": 100,
            "match_type": "EXACT_REFERENCE",
            "matchType": "EXACT_REFERENCE",
            "status": "MATCHED",
            "reasons": reasons,
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": 100,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": feature_details,
            "criticalMismatches": [],
        }

        return 100.0, details

    # ============================================================
    # 1. Marque différente = rejet direct
    # ============================================================

    if internal_brand and competitor_brand and internal_brand != competitor_brand:
        reasons.append(
            f"Marques différentes : {internal_brand} ≠ {competitor_brand}. "
            "Le produit concurrent ne peut pas être le même produit."
        )

        details = {
            "same_product": False,
            "sameProduct": False,
            "score": 0,
            "match_type": "NO_MATCH",
            "matchType": "NO_MATCH",
            "status": "IGNORED",
            "reasons": reasons,
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": feature_score,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": feature_details,
            "criticalMismatches": ["marque"],
        }

        return 0.0, details

    # ============================================================
    # 2. Même référence extraite = match certain
    # ============================================================

    if internal_ref and competitor_ref and internal_ref == competitor_ref:
        reasons.append(
            "Référence/SKU identique entre le produit interne et le produit concurrent."
        )

        if internal_brand and competitor_brand and internal_brand == competitor_brand:
            reasons.append("Marque identique.")

        details = {
            "same_product": True,
            "sameProduct": True,
            "score": 100,
            "match_type": "EXACT_REFERENCE",
            "matchType": "EXACT_REFERENCE",
            "status": "MATCHED",
            "reasons": reasons,
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": 100,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": feature_details,
            "criticalMismatches": [],
        }

        return 100.0, details

    # ============================================================
    # 3. Références différentes : comparer les caractéristiques
    # ============================================================

    if internal_ref and competitor_ref and internal_ref != competitor_ref:
        ref_similarity = text_similarity(internal_ref, competitor_ref)
        reasons.append(
            f"Références différentes : {internal_ref} ≠ {competitor_ref} "
            f"(similarité {ref_similarity}%)."
        )
    else:
        ref_similarity = 0
        reasons.append("Référence absente ou non comparable.")

    mismatches = _critical_mismatches(internal_features, competitor_features)

    if mismatches:
        reasons.append(
            "Produit rejeté car caractéristique critique différente : "
            + ", ".join(mismatches)
            + "."
        )

        details = {
            "same_product": False,
            "sameProduct": False,
            "score": min(feature_score, 59),
            "match_type": "NO_MATCH",
            "matchType": "NO_MATCH",
            "status": "IGNORED",
            "reasons": reasons,
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": feature_score,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": feature_details,
            "criticalMismatches": mismatches,
        }

        return float(min(feature_score, 59)), details

    # ============================================================
    # 4. Vérification des specs principales
    # ============================================================

    same_brand = _same(
        internal_features.get("marque"),
        competitor_features.get("marque"),
    )

    same_model = (
        _same(internal_features.get("modele"), competitor_features.get("modele"))
        or _similar(
            internal_features.get("modele"),
            competitor_features.get("modele"),
            88,
        )
    )

    same_cpu = _same(
        internal_features.get("processeur"),
        competitor_features.get("processeur"),
    )

    same_ram = _same(
        internal_features.get("ram"),
        competitor_features.get("ram"),
    )

    same_storage = _same(
        internal_features.get("stockage"),
        competitor_features.get("stockage"),
    )

    same_screen = _same(
        internal_features.get("ecran"),
        competitor_features.get("ecran"),
    )

    if ref_similarity >= 75:
        feature_score += 5
        reasons.append("Les références sont différentes mais proches.")

    if same_brand:
        reasons.append("Marque identique.")

    if same_model:
        reasons.append("Modèle/gamme identique ou très proche.")

    if same_cpu:
        reasons.append("Processeur identique.")

    if same_ram:
        reasons.append("RAM identique.")

    if same_storage:
        reasons.append("Stockage identique.")

    if same_screen:
        reasons.append("Taille écran identique.")

    # ============================================================
    # 5. Cas spécial montres connectées / Mibro
    # ============================================================

    internal_text = normalize_text(f"{internal_name} {internal_desc}")
    competitor_text = normalize_text(f"{competitor_name} {competitor_desc}")

    if "mibro" in internal_text and "mibro" in competitor_text:
        if "c4" in internal_text and "c4" in competitor_text:
            final_score = 88
            match_type = "HIGH_CONFIDENCE"
            same_product = True
            status = "MATCHED"

            reasons.append(
                "Cas montre connectée : marque Mibro et modèle C4 détectés dans les deux produits."
            )

            details = {
                "same_product": same_product,
                "sameProduct": same_product,
                "score": final_score,
                "match_type": match_type,
                "matchType": match_type,
                "status": status,
                "reasons": reasons,
                "nameScore": name_score,
                "descriptionScore": description_score,
                "featuresScore": feature_score,
                "internalFeatures": internal_features,
                "competitorFeatures": competitor_features,
                "featuresDetails": feature_details,
                "criticalMismatches": [],
            }

            return float(final_score), details

    # ============================================================
    # 5.bis Cas spécial smartphones
    # ============================================================
    # Important : ce bloc doit rester EN DEHORS du bloc Mibro.
    # Sinon il ne s'exécute jamais pour Samsung, iPhone, Xiaomi, etc.
    #
    # Pour les smartphones, on ne doit pas exiger CPU comme pour les PC.
    # Si marque + modèle + RAM + stockage sont identiques :
    # - même couleur ou couleur absente => MATCHED
    # - couleur différente => MANUAL_REVIEW
    # ============================================================

    smartphone_keywords = [
        "smartphone",
        "galaxy",
        "iphone",
        "redmi",
        "poco",
        "xiaomi",
        "oppo",
        "honor",
        "huawei",
        "infinix",
        "tecno",
        "realme",
        "vivo",
    ]

    is_smartphone = any(
        keyword in internal_text or keyword in competitor_text
        for keyword in smartphone_keywords
    )

    same_color = _same(
        internal_features.get("couleur"),
        competitor_features.get("couleur"),
    )

    internal_color = internal_features.get("couleur")
    competitor_color = competitor_features.get("couleur")

    if is_smartphone and same_brand and same_model and same_ram and same_storage:
        if internal_color and competitor_color and not same_color:
            final_score = max(78, feature_score)
            match_type = "MEDIUM_CONFIDENCE"
            same_product = False
            status = "MANUAL_REVIEW"

            reasons.append(
                "Smartphone proche : marque, modèle, RAM et stockage identiques, "
                "mais couleur différente. Vérification manuelle requise."
            )

        else:
            final_score = max(92, feature_score)
            match_type = "HIGH_CONFIDENCE"
            same_product = True
            status = "MATCHED"

            reasons.append(
                "Smartphone confirmé : marque, modèle, RAM et stockage identiques."
            )

        details = {
            "same_product": same_product,
            "sameProduct": same_product,
            "score": round(float(final_score), 2),
            "match_type": match_type,
            "matchType": match_type,
            "status": status,
            "reasons": reasons,
            "nameScore": name_score,
            "descriptionScore": description_score,
            "featuresScore": feature_score,
            "internalFeatures": internal_features,
            "competitorFeatures": competitor_features,
            "featuresDetails": feature_details,
            "criticalMismatches": [],
        }

        return round(float(final_score), 2), details

    # ============================================================
    # 6. Décision finale générale
    # ============================================================

    if same_brand and same_model and same_cpu and same_ram and same_storage:
        final_score = max(90, feature_score)
        match_type = "HIGH_CONFIDENCE"
        same_product = True
        status = "MATCHED"

        reasons.append(
            "Référence différente, mais marque/modèle/processeur/RAM/stockage sont identiques."
        )

    elif same_brand and same_model and same_ram and same_storage:
        final_score = max(72, feature_score)
        match_type = "MEDIUM_CONFIDENCE"
        same_product = False
        status = "MANUAL_REVIEW"

        reasons.append(
            "Produit proche, mais une caractéristique critique manque ou reste à confirmer."
        )

    else:
        internal_filled = sum(
            1 for k in ["marque", "modele", "processeur", "ram", "stockage"]
            if internal_features.get(k)
        )

        competitor_filled = sum(
            1 for k in ["marque", "modele", "processeur", "ram", "stockage"]
            if competitor_features.get(k)
        )

        if internal_filled <= 2 or competitor_filled <= 2:
            text_score = max(name_score, description_score * 0.7)

            if text_score >= SCORE_AUTO:
                final_score = round(text_score, 2)
                match_type = "HIGH_CONFIDENCE"
                same_product = True
                status = "MATCHED"

                reasons.append(
                    f"Peu de caractéristiques extraites — décision basée sur similarité textuelle "
                    f"(nom: {name_score}%, description: {description_score}%)."
                )

            elif text_score >= SCORE_MANUAL:
                final_score = round(text_score, 2)
                match_type = "MEDIUM_CONFIDENCE"
                same_product = False
                status = "MANUAL_REVIEW"

                reasons.append(
                    f"Peu de caractéristiques extraites — produit à vérifier manuellement "
                    f"(nom: {name_score}%, description: {description_score}%)."
                )

            else:
                final_score = min(feature_score, 59)
                match_type = "NO_MATCH"
                same_product = False
                status = "IGNORED"

                reasons.append(
                    "Les caractéristiques et la similarité textuelle sont insuffisantes."
                )

        else:
            final_score = min(feature_score, 59)
            match_type = "NO_MATCH"
            same_product = False
            status = "IGNORED"

            reasons.append(
                "Les caractéristiques disponibles ne suffisent pas pour confirmer que c'est le même produit."
            )

    details = {
        "same_product": same_product,
        "sameProduct": same_product,
        "score": round(float(final_score), 2),
        "match_type": match_type,
        "matchType": match_type,
        "status": status,
        "reasons": reasons,
        "nameScore": name_score,
        "descriptionScore": description_score,
        "featuresScore": feature_score,
        "internalFeatures": internal_features,
        "competitorFeatures": competitor_features,
        "featuresDetails": feature_details,
        "criticalMismatches": mismatches,
    }

    return round(float(final_score), 2), details