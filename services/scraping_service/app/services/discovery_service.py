from __future__ import annotations

import html
from urllib.parse import urljoin, urlparse, urlunparse
import re
import unicodedata
import requests
import urllib3
from bs4 import BeautifulSoup
import time
from app.services.selector_service import detect_selectors
from app.services.keyword_service import generate_keywords
import time
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
    """
    Vérifie qu'une page contient suffisamment de produits.
    Critères assouplis : 1 seul suffisamment fiable, ou 2 signaux faibles.
    """
    product_card_sel = selectors.get("product_card")
    product_price_sel = selectors.get("product_price")
    product_name_sel = selectors.get("product_name")

    # Signal fort : sélecteur product_card connu (1 carte suffit)
    if product_card_sel:
        cards = soup.select(product_card_sel)
        if len(cards) >= 1:
            return True

    # Signal fort : prix + noms détectés (seuil abaissé à 1)
    if product_price_sel and product_name_sel:
        prices = soup.select(product_price_sel)
        names = soup.select(product_name_sel)
        if len(prices) >= 1 and len(names) >= 1:
            return True

    # Signal moyen : regex prix dans le texte brut (seuil abaissé à 1)
    all_text = soup.get_text(" ")
    price_matches = _PRICE_RE.findall(all_text)
    if len(price_matches) >= 1:
        return True

    # Signal faible : la page contient des liens qui ressemblent à des produits
    product_links = [
        a for a in soup.select("a[href]")
        if _CATALOG_URL_RE.search(a.get("href", ""))
    ]
    if len(product_links) >= 3:
        return True

    return False

def _build_candidates(site_url: str, html: str) -> list[dict]:
    """
    Construit la liste de candidats catalogue depuis :
    1. Les liens de navigation (nav, menu, header, footer)
    2. Tous les liens du body

    Stratégie : inclure large, laisser la vérification filtrer.
    """
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    # URLs à exclure absolument (pages non-produit)
    HARD_EXCLUDE = re.compile(
        r"/(login|signin|register|cart|panier|checkout|compte|account|"
        r"cgv|faq|blog|news|mentions|privacy|sav|contact|about|"
        r"recrutement|emploi|livraison|retour|garantie|wishlist|"
        r"compare|search|recherche|404|sitemap|feed|rss)(/|$)",
        re.IGNORECASE,
    )

    def add_candidate(title: str, url: str, source: str) -> None:
        if url in seen_urls:
            return
        # Exclure les extensions non-HTML
        if re.search(r"\.(jpg|jpeg|png|gif|pdf|zip|xml|css|js)$", url, re.IGNORECASE):
            return
        # Exclure les pages non-produit
        if HARD_EXCLUDE.search(urlparse(url).path):
            return
        # Exclure les ancres pures et les pages de même host racine sans path
        parsed = urlparse(url)
        if not parsed.path or parsed.path == "/":
            return

        seen_urls.add(url)
        score = score_catalog_candidate(title, url)
        depth = max(0, len([p for p in parsed.path.split("/") if p]))
        candidates.append({
            "title": title or url.split("/")[-1].replace("-", " ").strip() or "Catalogue",
            "url": url,
            "parent_url": None,
            "depth": depth,
            "score": score,
            "source": source,
            "is_selected": True,
        })

    # 1. Liens de navigation (priorité haute)
    for title, url in extract_nav_links(site_url, html):
        add_candidate(title, url, "nav_discovery")

    # 2. Tous les liens du body
    for title, url in extract_same_domain_links(site_url, html):
        add_candidate(title, url, "auto_discovery")

    # Trier : score DESC, puis depth ASC
    candidates.sort(key=lambda x: (-x["score"], x["depth"], x["url"]))

    # Déduplication par dominance de path — seuil conservateur (4 niveaux)
    # Ex : /cat/laptops/asus/gaming ne bloque PAS /cat/laptops/asus
    deduped: list[dict] = []
    retained_paths: list[str] = []

    for c in candidates:
        path = urlparse(c["url"]).path.rstrip("/")
        dominated = any(
            path.startswith(p + "/") and (path.count("/") - p.count("/")) >= 4
            for p in retained_paths
        )
        if not dominated:
            retained_paths.append(path)
            deduped.append(c)
        if len(deduped) >= 150:
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

    # ── 1. Charger la homepage ───────────────────────────────────────────
        try:
            html = self.get_html(site_url)
        except Exception as exc:
            return {
                "site_url": site_url,
                "host": host,
                "selectors": {},
                "keywords": [],
                "catalogs": [],
                "warnings": [f"Impossible de charger la page d'accueil : {exc}"],
            }

        selectors = detect_selectors(host, html)
        candidates = _build_candidates(site_url, html)

    # ── 2. Crawler 1 niveau supplémentaire (menus JS / pages intermédiaires) ──
    # Certains sites cachent leurs catégories derrière des pages de section
        extra_candidates: list[dict] = []
        top_nav = [c for c in candidates if c["source"] == "nav_discovery" and c["depth"] == 1]

        for nav_item in top_nav[:8]:
            try:
                sub_html = self.session.get(
                    nav_item["url"], timeout=(5, 10), allow_redirects=True, verify=False
                ).text
                for title, url in extract_nav_links(nav_item["url"], sub_html):
                    if url not in {c["url"] for c in candidates}:
                        score = score_catalog_candidate(title, url)
                        depth = max(0, len([p for p in urlparse(url).path.split("/") if p]))
                        extra_candidates.append({
                            "title": title or url.split("/")[-1].replace("-", " ") or "Catalogue",
                            "url": url,
                            "parent_url": nav_item["url"],
                            "depth": depth,
                            "score": score,
                            "source": "sub_nav_discovery",
                            "is_selected": True,
                        })
            except Exception:
                continue

    # Fusionner et re-trier
        all_candidates = candidates + extra_candidates
        all_candidates.sort(key=lambda x: (-x["score"], x["depth"], x["url"]))

    # Déduplication finale
        seen = set()
        merged: list[dict] = []
        for c in all_candidates:
            if c["url"] not in seen:
                seen.add(c["url"])
                merged.append(c)

    # ── 3. Vérification avec budget temps ────────────────────────────────
        MAX_TO_CHECK    = 60   # candidats max à vérifier
        MAX_TOTAL_SECS  = 90   # budget total
        PER_PAGE_SECS   = 10   # timeout par page

        verified_catalogs     = []
        unverified_fallback   = []
        category_titles       = []
        sample_product_titles = []
        visible_brands: list[str] = []

        deadline = time.monotonic() + MAX_TOTAL_SECS

        for item in merged[:MAX_TO_CHECK]:
            unverified_fallback.append(item)

            if time.monotonic() >= deadline:
                break

            try:
                resp = self.session.get(
                    item["url"],
                    timeout=(5, PER_PAGE_SECS),
                    allow_redirects=True,
                    verify=False,
                )
                resp.raise_for_status()
                page_html = resp.text
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

    # ── 4. Fallback si 0 catalogue vérifié ───────────────────────────────
        warnings = []
        final_catalogs = verified_catalogs

        if not verified_catalogs:
            fallback = [c for c in unverified_fallback if c["score"] > 0]
            if not fallback:
                fallback = unverified_fallback

            for c in fallback:
                c["source"] = "auto_discovery_unverified"
                c["is_selected"] = False

            final_catalogs = fallback
            category_titles = [c["title"] for c in fallback]
            warnings.append(
                "Aucun catalogue vérifié automatiquement — candidats non-confirmés retournés (is_selected=False)."
            )

        keywords = generate_keywords(category_titles, sample_product_titles, visible_brands)

        return {
            "site_url": site_url,
            "host": host,
            "selectors": selectors,
            "keywords": keywords,
            "catalogs": final_catalogs,
            "warnings": warnings,
    }