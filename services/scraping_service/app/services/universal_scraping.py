# universal_scraping_solution.py
# À mettre dans : scraping_service/app/services/universal_scraping_solution.py
#
# Objectif :
# - extraction générique des produits concurrents ;
# - scoring strict pour éviter les faux matchs ;
# - blocage des accessoires quand le produit interne est un vrai produit ;
# - correction iPhone : iPhone 15 Pro Max 256Go ne doit PAS matcher iPhone 14, iPhone 13 ou coque iPhone.

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse, unquote

from bs4 import BeautifulSoup


@dataclass
class UniversalCandidate:
    urlProduit: str | None = None
    nomProduit: str | None = None
    skuConcurrent: str | None = None
    prixConcurrent: float | None = None
    ancien_prix: float | None = None
    disponibilite: str | None = "unknown"
    descriptionConcurrent: str | None = None
    fiable: bool = False
    score: float = 0.0
    reason: str = ""


# Important :
# On ne met PAS "pro" et "max" ici.
# Pour Apple, "iPhone 15 Pro Max" : Pro + Max font partie du modèle.
GENERIC_PRODUCT_WORDS = {
    "avec", "sans", "pour", "de", "du", "des", "la", "le", "les", "en", "et", "ou", "sur",
    "plus", "mini", "pack", "new", "nouveau",
    "noir", "black", "blanc", "white", "gris", "silver", "argent", "bleu", "rouge", "vert", "rose",
    "gold", "dore", "doré", "violet", "titanium", "titane", "naturel", "marron",
    "filaire", "wireless", "sansfil", "fil", "gaming", "gamer", "rgb", "led", "usb", "bluetooth",
    "pc", "ordinateur", "portable", "laptop", "ecran", "écran", "moniteur",
    "clavier", "keyboard", "souris", "mouse", "casque", "headset", "ecouteur", "écouteur",
    "montre", "connectee", "connecte", "connectée", "smartwatch", "smart", "watch",
    "azerty", "qwerty", "full", "hd", "fhd", "uhd", "tft", "ips", "amoled",
    "go", "gb", "to", "tb", "ram", "ssd", "hdd",
}

# Ces mots indiquent souvent un accessoire.
# Si le produit interne n'est pas un accessoire, on bloque ces candidats.
ACCESSORY_WORDS = {
    "coque", "case", "cover", "housse", "etui", "étui", "protection", "protege", "protège",
    "film", "verre", "trempe", "trempé", "tempered", "glass",
    "chargeur", "charger", "cable", "câble", "adaptateur", "adapter",
    "support", "stand", "bracelet", "strap", "dock",
}

BAD_URL_PARTS = {
    "recherche", "search", "catalogsearch", "productsearch", "jolisearch", "controller=search",
    "submit_search", "orderby=", "orderway=", "search_query=", "?s=", "login", "connexion",
    "account", "mon-compte", "cart", "panier", "wishlist", "compare", "checkout", "commande",
    "contact", "about", "a-propos", "conditions", "brand", "marque", "manufacturer", "category",
    "categorie", "product-category", "tag", "page/", "javascript:", "add-to-cart",
    "facebook", "instagram", "youtube", "linkedin", "twitter",
}

CARD_SELECTORS = [
    "article.product-miniature",
    "div.product-miniature",
    "div.js-product-miniature",
    "li.product",
    "li.product-miniature",
    "div.product",
    "div.thumbnail-container",
    "div.product-container",
    "div.product-item",
    "div.product-card",
    "div.product-wrapper",
    "div.product-grid-item",
    "div.wd-product",
    "div.product-small",
    "div.item-product",
    "div.item",
    "div.card",
]

TITLE_SELECTORS = [
    "h1", "h2", "h3",
    ".product-title", ".product-title a",
    ".woocommerce-loop-product__title",
    ".product-name", "a.product-name",
    ".name", ".title", ".wd-entities-title",
    "[itemprop='name']",
]

PRICE_SELECTORS = [
    "[itemprop='price']",
    ".price", ".product-price", ".regular-price", ".current-price", ".price-wrapper",
    ".woocommerce-Price-amount", ".amount", ".prix", ".old-price", ".special-price",
]


def normalize_for_match(value: str | None) -> str:
    if not value:
        return ""

    text = str(value).lower()
    accents = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a",
        "î": "i", "ï": "i",
        "ô": "o",
        "ù": "u", "û": "u",
        "ç": "c",
    }

    for src, dst in accents.items():
        text = text.replace(src, dst)

    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def compact(value: str | None) -> str:
    return normalize_for_match(value).replace(" ", "").replace("-", "").replace("_", "")


def parse_price_any(text: str | None) -> float | None:
    if not text:
        return None

    raw = text.replace("\xa0", " ")

    matches = re.findall(
        r"(\d{1,5}(?:[\s.,]\d{3})*(?:[.,]\d{1,3})?)\s*(?:DT|TND|د\.ت|€|EUR)?",
        raw,
        flags=re.I,
    )

    values: list[float] = []

    for m in matches:
        cleaned = m.replace(" ", "")

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")

        try:
            value = float(cleaned)

            if 1 <= value <= 100000:
                values.append(value)
        except Exception:
            pass

    return values[0] if values else None


def extract_prices_any(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None

    raw = text.replace("\xa0", " ")

    matches = re.findall(
        r"(\d{1,5}(?:[\s.,]\d{3})*(?:[.,]\d{1,3})?)\s*(?:DT|TND|د\.ت|€|EUR)",
        raw,
        flags=re.I,
    )

    prices: list[float] = []

    for match in matches:
        price = parse_price_any(match)

        if price is not None:
            prices.append(price)

    if not prices:
        return None, None

    if len(prices) >= 2:
        current_price = min(prices)
        old_price = max(prices)

        if old_price > current_price:
            return current_price, old_price

        return current_price, None

    return prices[0], None


def clean_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None

    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)

    if not parsed.scheme or not parsed.netloc:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def is_probable_product_url(url: str | None) -> bool:
    if not url:
        return False

    lower = unquote(url.lower()).strip()

    if any(bad in lower for bad in BAD_URL_PARTS):
        return False

    parsed = urlparse(lower)
    path = parsed.path.strip("/")

    if not parsed.netloc or not path:
        return False

    if lower.endswith(".html"):
        slug = path.split("/")[-1].replace(".html", "")
        return len(slug) >= 6

    if "/produit/" in lower or "/product/" in lower:
        slug = path.split("/")[-1]
        return len(slug) >= 4

    last = path.split("/")[-1]
    has_letters = bool(re.search(r"[a-z]", last))
    has_product_shape = len(last) >= 12 and ("-" in last or bool(re.search(r"\d", last)))

    return has_letters and has_product_shape


def is_accessory_text(text: str | None) -> bool:
    """
    Détecte un vrai accessoire.

    Important : on ne doit PAS rejeter une montre juste parce que son URL
    contient "leather-strap" ou parce que le titre indique un bracelet offert.

    On bloque surtout les titres qui commencent par : bracelet, strap, coque,
    chargeur, câble, verre trempé, etc.
    """
    normalized = normalize_for_match(text)

    if not normalized:
        return False

    tokens = normalized.split()
    first_tokens = set(tokens[:4])
    all_tokens = set(tokens)

    accessory_norm = {normalize_for_match(w) for w in ACCESSORY_WORDS}

    main_product_words = {
        "montre", "smartwatch", "watch",
        "telephone", "smartphone", "iphone", "ipad",
        "pc", "ordinateur", "portable", "laptop",
        "casque", "ecouteur", "souris", "clavier", "ecran",
    }

    # Accessoire clair si le titre commence par un mot accessoire.
    if first_tokens.intersection(accessory_norm):
        return True

    # Cas expressions fortes.
    accessory_phrases = [
        "verre trempe", "film protection", "coque", "housse", "etui",
        "strap for", "bracelet", "cable", "chargeur", "adaptateur",
    ]

    if any(phrase in normalized for phrase in accessory_phrases):
        # Si le titre décrit d'abord un produit principal, on ne bloque pas.
        # Exemple : "Montre connectée ... avec écouteurs offerts + strap ..."
        if first_tokens.intersection(main_product_words):
            return False
        return True

    return False

def extract_iphone_signature(text: str | None) -> dict | None:
    """
    Extrait une signature stricte iPhone.
    Exemples :
    - iPhone 15 Pro Max 256Go
      => generation=15, pro=True, max=True, capacity=256go
    - iPhone 14 128Go
      => generation=14, pro=False, max=False, capacity=128go

    Cette fonction est volontairement stricte pour éviter :
    - iPhone 15 Pro Max 256Go -> iPhone 14 128Go
    - iPhone 15 Pro Max 256Go -> coque iPhone 15 Pro Max
    """

    normalized = normalize_for_match(text)

    if "iphone" not in normalized:
        return None

    generation = None
    gen_match = re.search(r"\biphone\s*(\d{1,2}|se)\b", normalized, flags=re.I)

    if gen_match:
        generation = gen_match.group(1).lower()

    has_pro = bool(re.search(r"\bpro\b", normalized))
    has_max = bool(re.search(r"\bmax\b", normalized))

    capacity = None
    cap_match = re.search(r"\b(\d{2,4})\s*(go|gb|to|tb)\b", normalized, flags=re.I)

    if cap_match:
        number, unit = cap_match.groups()
        unit = unit.lower()
        if unit == "gb":
            unit = "go"
        if unit == "tb":
            unit = "to"
        capacity = f"{number}{unit}"

    return {
        "generation": generation,
        "pro": has_pro,
        "max": has_max,
        "capacity": capacity,
    }


def iphone_signature_matches(target: dict, candidate: dict) -> tuple[bool, str]:
    """
    Compare deux signatures iPhone.
    Si le produit interne est iPhone 15 Pro Max 256Go,
    le candidat doit être iPhone 15 Pro Max 256Go.
    """

    if not target or not candidate:
        return True, "not_iphone"

    if target.get("generation") and candidate.get("generation") != target.get("generation"):
        return False, f"iphone_generation_mismatch:{target.get('generation')}!={candidate.get('generation')}"

    # Si le produit cible contient Pro, le candidat doit contenir Pro.
    if target.get("pro") and not candidate.get("pro"):
        return False, "iphone_missing_pro"

    # Si le produit cible contient Max, le candidat doit contenir Max.
    if target.get("max") and not candidate.get("max"):
        return False, "iphone_missing_max"

    # Si le produit cible a une capacité, le candidat doit avoir la même.
    if target.get("capacity") and candidate.get("capacity") != target.get("capacity"):
        return False, f"iphone_capacity_mismatch:{target.get('capacity')}!={candidate.get('capacity')}"

    return True, "iphone_signature_ok"



def extract_color_set(text: str | None) -> set[str]:
    """
    Retourne des couleurs normalisées.
    Exemple : vert, green => green ; gris, gray => gray.
    """
    normalized = normalize_for_match(text)
    tokens = set(normalized.split())
    mapping = {
        "vert": "green", "verte": "green", "green": "green",
        "bleu": "blue", "bleue": "blue", "blue": "blue",
        "noir": "black", "noire": "black", "black": "black", "midnight": "black",
        "blanc": "white", "blanche": "white", "white": "white",
        "gris": "gray", "gray": "gray", "grey": "gray", "silver": "gray", "argent": "gray",
        "rose": "pink", "pink": "pink",
        "gold": "gold", "dore": "gold", "doré": "gold",
        "marron": "brown", "brown": "brown",
        "beige": "beige",
    }
    return {mapping[t] for t in tokens if t in mapping}


def model_guard(product_text: str, candidate_text: str) -> tuple[bool, str]:
    """
    Garde-fou générique sur le modèle/couleur.
    Corrige les cas :
    - Mibro Lite 3 Pro Vert ne doit pas matcher Mibro Lite 3 Noir/Rose sans Pro.
    - iPhone 15 Pro Max 256Go ne doit pas matcher iPhone 14/13/coque.
    """
    p = normalize_for_match(product_text)
    c = normalize_for_match(candidate_text)
    p_tokens = set(p.split())
    c_tokens = set(c.split())

    # Tokens modèle obligatoires.
    # IMPORTANT :
    # "max" ne doit PAS être obligatoire pour tous les produits.
    # Exemple bug corrigé :
    # Produit DELL Pro 16 Ultra 5 225U rejeté avec missing_model_token:max
    # alors que "Max" n'appartient pas au modèle DELL.
    #
    # On garde donc "max" obligatoire seulement pour les familles où c'est un vrai modèle :
    # iPhone 15 Pro Max, MacBook Pro Max, etc.
    strong_required = {"pro", "ultra", "plus", "lite", "air"}

    apple_like = bool({"iphone", "ipad", "macbook", "apple"}.intersection(p_tokens))
    if apple_like or re.search(r"\bpro\s+max\b", p):
        strong_required.add("max")

    for token in sorted(strong_required.intersection(p_tokens)):
        if token not in c_tokens:
            return False, f"missing_model_token:{token}"

    product_numbers = {t for t in p_tokens if re.fullmatch(r"\d{1,2}", t)}
    for number in product_numbers:
        if re.search(rf"\b(lite|iphone|watch|series|pro|max)\s*{number}\b|\b{number}\s*(pro|max|lite)\b", p):
            if number not in c_tokens:
                return False, f"missing_model_number:{number}"

    p_colors = extract_color_set(p)
    c_colors = extract_color_set(c)
    if p_colors and c_colors and not p_colors.intersection(c_colors):
        return False, "color_mismatch:" + ",".join(sorted(p_colors)) + "!=" + ",".join(sorted(c_colors))

    return True, "model_guard_ok"

def important_words_from_product(product: dict) -> list[str]:
    text = normalize_for_match(
        " ".join([
            str(product.get("sku") or ""),
            str(product.get("nom") or product.get("name") or ""),
            str(product.get("marque") or product.get("brand") or ""),
            str(product.get("categorie") or product.get("category") or ""),
            str(product.get("description") or ""),
        ])
    )

    words: list[str] = []

    for word in text.split():
        is_capacity = bool(re.fullmatch(r"\d{2,4}(go|gb|to|tb)", word, flags=re.I))
        is_apple_signature = word in {"iphone", "ipad", "macbook", "pro", "max", "air"}

        if len(word) < 3 and not is_capacity:
            continue

        if word in GENERIC_PRODUCT_WORDS and not is_capacity and not is_apple_signature:
            continue

        if word not in words:
            words.append(word)

    return words[:14]


def extract_refs_from_text(text: str | None) -> list[str]:
    if not text:
        return []

    refs: list[str] = []

    patterns = [
        r"\b[A-Z]{1,4}[-_ ]?\d{2,5}[A-Z0-9]{0,5}\b",
        r"\b\d{1,3}[A-Z]{1,4}\d{2,5}[A-Z0-9]{0,5}\b",
        r"\b[A-Z0-9]{4,}[-_][A-Z0-9]{2,}\b",
        r"\[([A-Z0-9._/-]{4,})\]",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            ref = match if isinstance(match, str) else match[0]
            ref = ref.strip(" []()")

            if len(ref) >= 4 and ref.lower() not in [x.lower() for x in refs]:
                refs.append(ref)

    return refs[:5]


def score_candidate(product: dict, candidate: UniversalCandidate) -> UniversalCandidate:
    product_text = normalize_for_match(
        " ".join([
            str(product.get("sku") or ""),
            str(product.get("nom") or product.get("name") or ""),
            str(product.get("marque") or product.get("brand") or ""),
            str(product.get("categorie") or product.get("category") or ""),
            str(product.get("description") or ""),
        ])
    )

    candidate_text = normalize_for_match(
        " ".join([
            candidate.nomProduit or "",
            candidate.skuConcurrent or "",
            candidate.urlProduit or "",
            candidate.descriptionConcurrent or "",
        ])
    )

    candidate_compact = compact(candidate_text)
    score = 0.0
    reasons: list[str] = []

    # ------------------------------------------------------------
    # 0) Blocage accessoires
    # ------------------------------------------------------------
    product_title_for_accessory = normalize_for_match(
        " ".join([
            str(product.get("nom") or product.get("name") or ""),
            str(product.get("categorie") or product.get("category") or ""),
        ])
    )

    candidate_title_for_accessory = normalize_for_match(candidate.nomProduit or "")

    target_is_accessory = is_accessory_text(product_title_for_accessory)
    candidate_is_accessory = is_accessory_text(candidate_title_for_accessory)

    if candidate_is_accessory and not target_is_accessory:
        candidate.score = 0
        candidate.fiable = False
        candidate.reason = "blocked_accessory_candidate"
        return candidate

    # ------------------------------------------------------------
    # 1) Références
    # ------------------------------------------------------------
    # IMPORTANT :
    # On ne rejette PLUS automatiquement un candidat si sa référence concurrente
    # est différente de la référence interne.
    #
    # Pourquoi ?
    # Un même produit peut avoir :
    # - une référence interne / fournisseur : BU-MIBRO-L3PRO-GREEN
    # - une référence concurrente différente : XPAW..., MU7A..., etc.
    #
    # Avant, cette règle rejetait des vrais produits avant matching.
    # Maintenant :
    # - référence exacte = gros bonus
    # - référence différente = pas un rejet automatique
    # - modèle/couleur/accessoire restent les vrais garde-fous.
    product_refs = []

    if product.get("sku"):
        product_refs.append(str(product.get("sku")))

    product_refs += extract_refs_from_text(product_text)

    # ------------------------------------------------------------
    # 2) Garde-fou modèle/couleur générique
    # ------------------------------------------------------------
    model_ok, model_reason = model_guard(product_text, candidate_text)

    if not model_ok:
        candidate.score = 0
        candidate.fiable = False
        candidate.reason = model_reason
        return candidate

    # ------------------------------------------------------------
    # 3) Règle stricte iPhone
    # ------------------------------------------------------------
    target_iphone = extract_iphone_signature(product_text)
    candidate_iphone = extract_iphone_signature(candidate_text)

    if target_iphone:
        ok, reason = iphone_signature_matches(target_iphone, candidate_iphone)

        if not ok:
            candidate.score = 0
            candidate.fiable = False
            candidate.reason = reason
            return candidate

        if ok and reason == "iphone_signature_ok":
            score += 80
            reasons.append(reason)

    # ------------------------------------------------------------
    # 4) Références / SKU exacts
    # ------------------------------------------------------------
    refs = product_refs

    for ref in refs:
        compact_ref = compact(ref)

        if len(compact_ref) >= 4 and compact_ref in candidate_compact:
            score += 100
            reasons.append(f"ref:{ref}")
            break

    # ------------------------------------------------------------
    # 3) Marque
    # ------------------------------------------------------------
    brand = normalize_for_match(product.get("marque") or product.get("brand") or "")

    if brand and brand in candidate_text:
        score += 35
        reasons.append("brand")

    # ------------------------------------------------------------
    # 4) Capacité : 256Go == 256 Go
    # ------------------------------------------------------------
    capacity_matches = re.findall(
        r"\b(\d{2,4})\s*(go|gb|to|tb)\b",
        product_text,
        flags=re.I,
    )

    for number, unit in capacity_matches:
        unit = unit.lower()
        if unit == "gb":
            unit = "go"
        if unit == "tb":
            unit = "to"

        compact_capacity = f"{number}{unit}"

        if compact_capacity in candidate_compact:
            score += 25
            reasons.append(f"capacity:{compact_capacity}")
            break

    # ------------------------------------------------------------
    # 5) Mots forts
    # ------------------------------------------------------------
    important = important_words_from_product(product)
    common = [word for word in important if word in candidate_text]

    if common:
        score += min(50, len(common) * 18)
        reasons.append("words:" + ",".join(common[:5]))

    if len(common) >= 2:
        score += 25
        reasons.append("2+strong_words")

    # ------------------------------------------------------------
    # 6) Nom complet ou majorité du nom
    # ------------------------------------------------------------
    product_name = normalize_for_match(product.get("nom") or product.get("name") or "")

    if product_name and compact(product_name) in candidate_compact:
        score += 70
        reasons.append("full_name")
    elif product_name:
        name_words = [
            word for word in product_name.split()
            if (
                word not in GENERIC_PRODUCT_WORDS
                or word in {"iphone", "ipad", "macbook", "pro", "max", "air"}
                or bool(re.fullmatch(r"\d{2,4}(go|gb|to|tb)", word, flags=re.I))
            )
            and len(word) >= 3
        ]

        if name_words:
            ratio = len([word for word in name_words if word in candidate_text]) / len(name_words)

            if ratio >= 0.80:
                score += 40
                reasons.append("name_ratio")

    # ------------------------------------------------------------
    # 7) Garde-fou anti faux positifs
    # ------------------------------------------------------------
    has_ref_match = any(reason.startswith("ref:") for reason in reasons)
    has_brand_match = "brand" in reasons
    has_iphone_strict_match = "iphone_signature_ok" in reasons

    if not has_ref_match and not has_iphone_strict_match:
        if brand and not has_brand_match:
            score -= 35
            reasons.append("missing_brand")

        if len(common) == 0:
            score -= 45
            reasons.append("no_strong_word")

    candidate.score = max(0.0, min(100.0, score))
    candidate.fiable = candidate.score >= 75
    candidate.reason = ";".join(reasons)

    return candidate


def extract_title_from_card(card) -> str | None:
    for selector in TITLE_SELECTORS:
        node = card.select_one(selector)

        if node:
            text = node.get_text(" ", strip=True)

            if text and len(text) >= 5:
                return text

    img = card.select_one("img[alt]")

    if img and img.get("alt") and len(img.get("alt").strip()) >= 5:
        return img.get("alt").strip()

    for a in card.select("a[href]"):
        text = a.get_text(" ", strip=True)

        if text and len(text) >= 8 and not any(bad in text.lower() for bad in ["panier", "détails", "details", "voir"]):
            return text

    return None


def extract_url_from_card(card, page_url: str) -> str | None:
    links: list[str] = []

    for a in card.select("a[href]"):
        href = a.get("href") or ""
        url = clean_url(page_url, href)

        if url and is_probable_product_url(url):
            links.append(url)

    if links:
        return links[0]

    raw_html = str(card).replace("\\/", "/")

    for raw_url in re.findall(r"https?://[^\"'\s<>]+", raw_html, flags=re.I):
        url = clean_url(page_url, raw_url)

        if url and is_probable_product_url(url):
            return url

    return None


def detect_availability(text: str | None) -> str:
    value = (text or "").upper()

    if "EN STOCK" in value or "DISPONIBLE" in value:
        return "en_stock"

    if "RUPTURE" in value or "HORS STOCK" in value or "OUT OF STOCK" in value:
        return "rupture"

    if "SUR COMMANDE" in value:
        return "sur_commande"

    return "unknown"


def candidate_from_link_node(a, page_url: str, product: dict) -> UniversalCandidate | None:
    href = a.get("href") or ""
    url = clean_url(page_url, href)

    if not url or not is_probable_product_url(url):
        return None

    title = a.get_text(" ", strip=True)

    if not title or len(title) < 5:
        img = a.select_one("img[alt]")

        if img and img.get("alt"):
            title = img.get("alt").strip()

    if not title or len(title) < 5:
        title = url.rstrip("/").split("/")[-1].replace(".html", "").replace("-", " ").title()

    parent = a

    for _ in range(4):
        if parent.parent:
            parent = parent.parent

    parent_text = parent.get_text(" ", strip=True)
    current_price, old_price = extract_prices_any(parent_text)
    refs = extract_refs_from_text(parent_text)

    candidate = UniversalCandidate(
        urlProduit=url,
        nomProduit=title,
        skuConcurrent=refs[0] if refs else None,
        prixConcurrent=current_price,
        ancien_prix=old_price,
        disponibilite=detect_availability(parent_text),
        descriptionConcurrent=parent_text[:1500],
    )

    return score_candidate(product, candidate)


def extract_universal_candidates_from_search_page(
    soup: BeautifulSoup,
    page_url: str,
    product: dict,
    limit: int = 12,
) -> list[UniversalCandidate]:
    cards = []
    seen_nodes = set()

    for selector in CARD_SELECTORS:
        for node in soup.select(selector):
            ident = id(node)

            if ident not in seen_nodes:
                cards.append(node)
                seen_nodes.add(ident)

    if not cards:
        for a in soup.select("a[href]"):
            url = clean_url(page_url, a.get("href"))

            if not is_probable_product_url(url):
                continue

            parent = a

            for _ in range(5):
                if parent.parent:
                    parent = parent.parent

            ident = id(parent)

            if ident not in seen_nodes:
                cards.append(parent)
                seen_nodes.add(ident)

    results: list[UniversalCandidate] = []
    seen_urls: set[str] = set()

    for card in cards:
        text = card.get_text(" ", strip=True)

        if not text or len(text) < 10:
            continue

        url = extract_url_from_card(card, page_url)

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)

        title = extract_title_from_card(card)

        if not title:
            title = (
                url.rstrip("/")
                .split("/")[-1]
                .replace(".html", "")
                .replace("-", " ")
                .title()
            )

        card_price_text = " ".join(
            [text] + [
                node.get_text(" ", strip=True)
                for node in card.select(",".join(PRICE_SELECTORS))
            ]
        )

        current_price, old_price = extract_prices_any(card_price_text)
        refs = extract_refs_from_text(text)

        candidate = UniversalCandidate(
            urlProduit=url,
            nomProduit=title,
            skuConcurrent=refs[0] if refs else None,
            prixConcurrent=current_price,
            ancien_prix=old_price,
            disponibilite=detect_availability(text),
            descriptionConcurrent=text[:1500],
        )

        candidate = score_candidate(product, candidate)

        # 75+ = fiable / auto-match
        # 55-74 = candidat douteux / validation
        if candidate.score >= 55:
            results.append(candidate)

        if len(results) >= limit:
            break

    # Fallback liens plats
    if len(results) == 0:
        for a in soup.select("a[href]"):
            candidate = candidate_from_link_node(a, page_url, product)

            if not candidate:
                continue

            if not candidate.urlProduit or candidate.urlProduit in seen_urls:
                continue

            seen_urls.add(candidate.urlProduit)

            if candidate.score >= 55:
                results.append(candidate)

            if len(results) >= limit:
                break

    results.sort(key=lambda candidate: candidate.score, reverse=True)
    return results[:limit]
