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

    # FIX: Remplacement go/to uniquement quand ce sont des unités (avec word boundaries)
    value = re.sub(r"\b(\d+)\s*go\b", r"\1gb", value)
    value = re.sub(r"\b(\d+)\s*to\b", r"\1tb", value)

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
                " 4gb", " 8gb", " 16gb", " 24gb", " 32gb",
                " 128gb", " 256gb", " 512gb", " 1tb",
                " rtx", " gtx", " windows",
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
    on ne considère pas que c'est le même produit.
    """
    critical_keys = [
        "modele",
        "processeur",
        "ram",
        "stockage",
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

    # FIX: Si match_type absent ou NO_MATCH, on se rabat sur le score numérique
    if match_type in {None, "NO_MATCH"}:
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
    """
    Matching corrigé.

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
    # 0. Correction importante :
    # chercher la référence interne dans tout le texte concurrent.
    # Exemple :
    # internal_ref = xpaw021
    # competitor_name = Montre Connectée MIBRO Watch C4 Silver XPAW021
    # competitor_desc = urlProduit + skuConcurrent + description
    # ============================================================

    competitor_full_ref_text = normalize_ref(
        " ".join([
            competitor_name,
            competitor_desc,
        ])
    )

    if internal_ref and competitor_full_ref_text:
        if internal_ref == competitor_full_ref_text or internal_ref in competitor_full_ref_text:
            reasons.append(
                "Référence interne trouvée dans le nom, la description, le SKU ou l'URL du produit concurrent."
            )

            if internal_brand and competitor_brand and internal_brand != competitor_brand:
                reasons.append(
                    f"Attention : référence trouvée mais marques différentes : {internal_brand} ≠ {competitor_brand}."
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
                    "criticalMismatches": ["marque"],
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