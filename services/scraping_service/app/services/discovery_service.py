from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse
import re
import unicodedata
import requests
import urllib3
from bs4 import BeautifulSoup

from app.services.selector_service import detect_selectors
from app.services.keyword_service import generate_keywords

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# Utilitaire : normalise les accents pour la comparaison de tokens
# ---------------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    """Supprime les accents d'une chaîne (é→e, à→a, etc.)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


# ---------------------------------------------------------------------------
# Mots-clés d'inclusion – domaine informatique tunisien
# FIX : ajout des formes plurielles et des variantes accentuées/non-accentuées
# ---------------------------------------------------------------------------
INCLUDE_HINTS = [
    # Catégories produit — singulier ET pluriel
    "ordinateur", "ordinateurs",
    "pc", "pcs",
    "portable", "portables",
    "laptop", "laptops",
    "gaming",
    "smartphone", "smartphones",
    "telephone", "telephones", "telephonie",
    "phone", "phones",
    "imprimante", "imprimantes",
    "monitor", "monitors",
    "moniteur", "moniteurs",
    "informatique",
    "accessoire", "accessoires",
    "composant", "composants",
    "tablette", "tablettes",
    "clavier", "claviers",
    "souris",
    "ecouteur", "ecouteurs",
    "casque", "casques",
    "camera", "cameras",
    "appareil", "appareils",
    "ecran", "ecrans",
    "processeur", "processeurs",
    "memoire",
    "disque", "disques",
    "ram",
    "ssd",
    "hdd",
    "carte", "cartes",
    "reseau",
    "wifi",
    "switch",
    "routeur", "routeurs",
    "onduleur", "onduleurs",
    "batterie", "batteries",
    "chargeur", "chargeurs",
    "cable", "cables",
    "adaptateur", "adaptateurs",
    "peripherique", "peripheriques",
    "stockage",
    # Marques courantes dans les URLs tunisiennes
    "hp", "dell", "lenovo", "asus", "acer", "msi", "apple", "samsung",
    "intel", "amd", "nvidia", "epson", "canon", "brother", "logitech",
    # Termes e-commerce génériques
    "produit", "produits",
    "product", "products",
    "article", "articles",
    "catalogue", "catalog",
    "boutique", "shop",
    "categorie", "categories",
    "category",
    "collection", "collections",
    "nos-produits", "tous-les-produits",
    "bureau", "bureautique",
    "maison", "multimedia",
    "jeux", "jeu",
    "video",
]

EXCLUDE_HINTS = [
    "contact", "about", "a-propos", "login", "signin", "register",
    "cart", "panier", "checkout", "compte", "account", "cgv", "faq",
    "blog", "news", "mentions", "privacy", "sav", "service-client",
    "recrutement", "emploi", "livraison", "retour", "garantie",
]

CATALOG_URL_PATTERNS = [
    r"/\d+-",
    r"/c/", r"/cat/", r"/category", r"/categorie", r"/catalogue",
    r"/shop", r"/collection", r"/produit", r"/product",
    r"/listing", r"/rayon",
]
_CATALOG_URL_RE = re.compile("|".join(CATALOG_URL_PATTERNS), re.IGNORECASE)

_PRICE_RE = re.compile(
    r"(?:\d[\d\s.,]*\s*(?:TND|DT)|\d{3,}[.,]\d{3}|\d[\d\s]{2,}[.,]\d{1,3})",
    re.IGNORECASE,
)

# Sélecteurs de menus de navigation à explorer en priorité
NAV_SELECTORS = [
    "nav a[href]",
    ".nav a[href]",
    ".navbar a[href]",
    ".menu a[href]",
    ".main-menu a[href]",
    "#menu a[href]",
    ".navigation a[href]",
    ".top-menu a[href]",
    "header a[href]",
    ".header-nav a[href]",
    ".category-menu a[href]",
    ".categories a[href]",
    ".sidebar a[href]",
    # FIX : sélecteurs supplémentaires courants (PrestaShop/WooCommerce/custom)
    "#top-menu a[href]",
    ".menu-item a[href]",
    ".nav-item a[href]",
    "ul.menu a[href]",
    "ul.nav a[href]",
    ".dropdown-menu a[href]",
    ".sub-menu a[href]",
    "footer a[href]",  # certains sites listent toutes leurs catégories dans le footer
]


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme or "https", host, path, "", "", ""))


def same_host(url1: str, url2: str) -> bool:
    h1 = urlparse(url1).netloc.lower().replace("www.", "")
    h2 = urlparse(url2).netloc.lower().replace("www.", "")
    return h1 == h2


def score_catalog_candidate(title: str, url: str) -> float:
    # FIX : normalisation des accents avant comparaison des tokens
    raw_haystack = f"{title} {url}".lower()
    haystack = _strip_accents(raw_haystack)
    score = 0.0

    for token in INCLUDE_HINTS:
        token_normalized = _strip_accents(token.lower())
        if token_normalized in haystack:
            score += 2.0

    for token in EXCLUDE_HINTS:
        token_normalized = _strip_accents(token.lower())
        if token_normalized in haystack:
            score -= 5.0

    if _CATALOG_URL_RE.search(url):
        score += 2.0

    # Bonus profondeur faible = catégorie principale (plus intéressante)
    depth = len([p for p in urlparse(url).path.split("/") if p])
    if depth == 1:
        score += 1.5
    elif depth == 2:
        score += 1.0
    elif depth == 3:
        score += 0.5

    return score


def extract_same_domain_links(site_url: str, html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        absolute = urljoin(site_url, href)
        if not same_host(site_url, absolute):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        links.append((title, canonical_url(absolute)))
    return links


def extract_nav_links(site_url: str, html: str) -> list[tuple[str, str]]:
    """Extrait les liens depuis les menus de navigation (priorité haute)."""
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    for sel in NAV_SELECTORS:
        try:
            for a in soup.select(sel):
                href = a.get("href")
                if not href:
                    continue
                absolute = urljoin(site_url, href)
                if not same_host(site_url, absolute):
                    continue
                url = canonical_url(absolute)
                if url in seen:
                    continue
                seen.add(url)
                title = " ".join(a.get_text(" ", strip=True).split())
                links.append((title, url))
        except Exception:
            continue

    return links


def _page_has_enough_products(soup: BeautifulSoup, selectors: dict) -> bool:
    product_card_sel = selectors.get("product_card")
    product_price_sel = selectors.get("product_price")
    product_name_sel = selectors.get("product_name")

    if product_card_sel:
        cards = soup.select(product_card_sel)
        if len(cards) >= 3:
            return True

    if product_price_sel and product_name_sel:
        prices = soup.select(product_price_sel)
        names = soup.select(product_name_sel)
        if len(prices) >= 3 and len(names) >= 3:
            return True

    # Fallback : compter les prix dans le texte brut
    all_text = soup.get_text(" ")
    price_matches = _PRICE_RE.findall(all_text)
    if len(price_matches) >= 3:
        return True

    return False


def _build_candidates(site_url: str, html: str) -> list[dict]:
    """
    Construit la liste de candidats catalogue depuis :
    1. Les liens de navigation (nav, menu, header, footer) — priorité haute
    2. Tous les liens de la page

    FIX (1) : seuil de score abaissé de 0.5 à -1.0 — les URLs neutres
              (score=0) sont désormais visitées pour vérification plutôt
              qu'éliminées silencieusement.
    FIX (2) : déduplication assouplie — seuil de dominance porté à 3 niveaux
              (était 2) pour conserver les sous-catégories légitimes.
    FIX (3) : limite de candidats portée à 60 (était 40).
    """
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    def add_candidate(title: str, url: str, source: str) -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        score = score_catalog_candidate(title, url)
        # FIX : seuil abaissé à -1.0 (était 0.5)
        if score < -1.0:
            return
        depth = max(0, len([p for p in urlparse(url).path.split("/") if p]))
        candidates.append({
            "title": title or url.split("/")[-1].replace("-", " ").strip() or "Catalogue",
            "url": url,
            "parent_url": None,
            "depth": depth,
            "score": score,
            "source": source,
            "is_selected": True,
        })

    # 1. Liens de navigation
    for title, url in extract_nav_links(site_url, html):
        add_candidate(title, url, "nav_discovery")

    # 2. Tous les liens de la page
    for title, url in extract_same_domain_links(site_url, html):
        add_candidate(title, url, "auto_discovery")

    # Trier : score DESC puis depth ASC
    candidates.sort(key=lambda x: (-x["score"], x["depth"], x["url"]))

    # FIX : seuil de dominance porté à 3 (était 2)
    deduped: list[dict] = []
    retained_paths: list[str] = []

    for c in candidates:
        path = urlparse(c["url"]).path.rstrip("/")
        dominated = any(
            path.startswith(p + "/") and (path.count("/") - p.count("/")) >= 3
            for p in retained_paths
        )
        if not dominated:
            retained_paths.append(path)
            deduped.append(c)
        # FIX : limite portée à 60
        if len(deduped) >= 60:
            break

    return deduped


class DiscoveryService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "fr,en;q=0.9,ar;q=0.8",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

    def get_html(self, url: str) -> str:
        response = self.session.get(url, timeout=(10, 45), allow_redirects=True, verify=False)
        response.raise_for_status()
        return response.text

    def discover_site(self, site_url: str) -> dict:
        site_url = canonical_url(site_url)
        host = urlparse(site_url).netloc.lower().replace("www.", "")

        html = self.get_html(site_url)
        selectors = detect_selectors(host, html)

        candidates = _build_candidates(site_url, html)

        verified_catalogs = []
        category_titles = []
        sample_product_titles = []
        visible_brands: list[str] = []

        # FIX : limite portée à 40 (était 20) pour couvrir tous les candidats
        for item in candidates[:40]:
            try:
                page_html = self.get_html(item["url"])
                page_selectors = selectors or detect_selectors(host, page_html)
                soup = BeautifulSoup(page_html, "lxml")

                if _page_has_enough_products(soup, page_selectors):
                    verified_catalogs.append(item)
                    category_titles.append(item["title"])

                    name_sel = page_selectors.get("product_name")
                    if name_sel:
                        for node in soup.select(name_sel)[:10]:
                            txt = " ".join(node.get_text(" ", strip=True).split())
                            if txt and len(txt) >= 5:
                                sample_product_titles.append(txt)

            except Exception:
                continue

        keywords = generate_keywords(category_titles, sample_product_titles, visible_brands)

        return {
            "site_url": site_url,
            "host": host,
            "selectors": selectors,
            "keywords": keywords,
            "catalogs": verified_catalogs,
            "warnings": [] if verified_catalogs else ["Aucun catalogue vérifié automatiquement"],
        }
