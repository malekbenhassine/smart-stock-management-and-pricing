import re
from bs4 import BeautifulSoup


DOMAIN_TEMPLATES = {
    "mytek.tn": {
        "product_card": "div[data-id][data-name][data-url]",
        "product_name": "a[href]",
        "product_link": "a[href]",
        "product_price": "span[itemprop='price']",
        "old_price": ".old-price, .regular-price",
        "availability": "span:last-of-type",
        "sku": "span[itemprop='sku']",
        "next_page": ".pages-item-next a, a[rel='next'], a.next",
    },
    "tunisianet.com.tn": {
        "product_card": ".js-product-miniature, .product-miniature",
        "product_name": "h2 a, h3 a, .product-title a",
        "product_link": "h2 a, h3 a, .product-title a",
        "product_price": ".price",
        "old_price": ".regular-price, .old-price",
        "availability": ".product-availability",
        "sku": ".product-reference",
        "next_page": ".pagination .next a, a[rel='next'], a.next",
    },
    "spacenet.tn": {
        "product_card": ".product-item, .thumbnail-container, .item",
        "product_name": "h2 a, h3 a, .product-title a, .name a",
        "product_link": "h2 a, h3 a, .product-title a, .name a",
        "product_price": ".price, .product-price",
        "old_price": ".old-price, .regular-price",
        "availability": ".availability, .stock",
        "sku": ".product-reference, .sku",
        "next_page": ".pagination .next a, a[rel='next'], a.next",
    },
    "zoom.com.tn": {
        "product_card": ".product-miniature, .product-item, .thumbnail-container, article, .item, .ajax_block_product",
        "product_name": "h1 a, h2 a, h3 a, h4 a, h5 a, .h3 a, .h4 a, .h5 a, .product-title a, a[href]",
        "product_link": "h1 a, h2 a, h3 a, h4 a, h5 a, .h3 a, .h4 a, .h5 a, .product-title a, a[href]",
        "product_price": ".price, .product-price, .our_price_display, [class*='price']",
        "old_price": ".old-price, .regular-price, .price-old, [class*='old']",
        "availability": ".availability, .stock, .product-availability, [class*='stock']",
        "sku": ".sku, .reference, .product-reference",
        "next_page": "a[rel='next'], .pagination .next a, a.next, a[href*='page=']",
    },
    "infotec.tn": {
        "product_card": "li.product, .products .product, .type-product, article.product, .product-small",
        "product_name": ".woocommerce-loop-product__title, .product-title a, h2 a, h3 a, a.woocommerce-LoopProduct-link",
        "product_link": "a.woocommerce-LoopProduct-link, a[href*='/fr/p/'], a[href*='/p/'], .product-title a, h2 a, h3 a",
        "product_price": ".price .woocommerce-Price-amount, .woocommerce-Price-amount, .price, ins .amount",
        "old_price": "del .woocommerce-Price-amount, del .amount, del, .old-price",
        "availability": ".stock, .availability, .ast-stock-detail, [class*='stock']",
        "sku": ".sku, .product_meta .sku",
        "next_page": ".woocommerce-pagination a.next, a.next, a[rel='next'], .pagination a.next",
    },
}

GENERIC_CANDIDATES = {
    "product_card": [
        "div[data-id][data-name][data-url]",
        ".js-product-miniature",
        ".product-miniature",
        ".product-item",
        ".product",
        ".thumbnail-container",
        "article.product-miniature",
        ".ajax_block_product",
        ".item",
        ".card",
        "article",
    ],
    "product_name": [
        ".product-title a",
        ".product-item-link",
        ".name a",
        "h1 a",
        "h2 a",
        "h3 a",
        "h4 a",
        "h5 a",
        "a[href]",
    ],
    "product_link": [
        ".product-title a",
        ".product-item-link",
        ".name a",
        "h1 a",
        "h2 a",
        "h3 a",
        "h4 a",
        "h5 a",
        "a[href]",
    ],
    "product_price": [
        "span[itemprop='price']",
        ".price",
        ".product-price",
        ".current-price",
        ".sale-price",
        ".our_price_display",
        "[class*='price']",
    ],
    "old_price": [
        ".old-price",
        ".regular-price",
        ".was-price",
        ".price-old",
        "[class*='old']",
    ],
    "availability": [
        ".availability",
        ".stock",
        ".product-availability",
        "[class*='stock']",
    ],
    "sku": [
        "span[itemprop='sku']",
        ".sku",
        ".product-reference",
        ".reference",
    ],
    "next_page": [
        "a[rel='next']",
        ".pagination .next a",
        ".pages-item-next a",
        "a.next",
        "a[href*='page=']",
    ],
}


_PRICE_RE = re.compile(
    r"""
    (?:
        \d[\d\s.,]*\s*(?:TND|DT)   # avec symbole monétaire dinar
        |
        \d{3,}[.,]\d{3}             # format  sans symbole : 1299,000 ou 2799.000
        |
        \d[\d\s]{2,}[.,]\d{1,3}    # nombre avec séparateur décimal
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def domain_template_for_host(host: str) -> dict:
    """Retourne les sélecteurs prédéfinis pour un site connu comme Mytek, Tunisianet ou Spacenet."""
    host = (host or "").lower().replace("www.", "")
    return DOMAIN_TEMPLATES.get(host, {})


def _clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _looks_like_price_text(text: str) -> bool:
    """
   détecte les prix tunisiens avec OU sans symbole monétaire.
    Exemples valides : '1299,000', '2 799.000', '1299 TND', '3 499 DT'
    """
    if not text:
        return False
    txt = _clean_text(text)
    return bool(_PRICE_RE.search(txt))


def _score_selector_nodes(key: str, nodes) -> int:
    if not nodes:
        return 0

    sample = nodes[:8]
    score = 0

    for node in sample:
        text = _clean_text(node.get_text(" ", strip=True))

        if key == "product_card":
            if text and len(text) >= 20:
                score += 1
            if _looks_like_price_text(text):
                score += 2
            #bonus si la card contient un lien (indicateur fiable)
            if node.select_one("a[href]"):
                score += 1

        elif key == "product_name":
            if 8 <= len(text) <= 180:
                score += 2
            # tokens élargis aux marques et termes informatique tunisien courants
            if any(tok in text.lower() for tok in [
                "pc", "portable", "laptop", "hp", "dell", "lenovo",
                "asus", "acer", "iphone", "samsung", "écran", "ecran",
                "intel", "amd", "ryzen", "core", "geforce", "rtx",
                "disque", "mémoire", "clavier", "souris", "imprimante",
                "tablette", "processeur", "ram", "ssd", "hdd",
            ]):
                score += 2

        elif key == "product_price":
            if _looks_like_price_text(text):
                score += 3
            # FIX : l'attribut content de span[itemprop='price'] contient le nombre seul
            if node.has_attr("content"):
                try:
                    float(node["content"])
                    score += 5
                except (ValueError, TypeError):
                    pass

        elif key == "next_page":
            if text.lower() in {"suivant", "next"} or "suivant" in text.lower():
                score += 3
            elif node.has_attr("rel") and "next" in node.get("rel", []):
                score += 3
            else:
                score += 1

        else:
            if text:
                score += 1

    return score


def detect_selectors(host: str, html: str) -> dict:
    template = domain_template_for_host(host)
    if template:
        return template

    soup = BeautifulSoup(html, "lxml")
    resolved = {}

    for key, candidates in GENERIC_CANDIDATES.items():
        best_selector = None
        best_score = -1

        for selector in candidates:
            try:
                nodes = soup.select(selector)
                if not nodes:
                    continue

                score = _score_selector_nodes(key, nodes)

                if score > best_score:
                    best_score = score
                    best_selector = selector

            except Exception:
                continue

        if best_selector:
            resolved[key] = best_selector

    return resolved
