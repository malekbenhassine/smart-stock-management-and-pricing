from __future__ import annotations

from datetime import datetime

from typing import Optional, Set
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse, quote_plus
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import requests
import urllib3
import warnings

try:
    import cloudscraper
except Exception:  # cloudscraper est optionnel mais recommandé pour Infotec/WordPress anti-bot
    cloudscraper = None

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from app.schemas.scraping_schemas import (
    CompetitorModel,
    ProductCompetitorPayload,
    ScrapeSummary,
    CatalogScrapeDetail,
)
from app.services.stock_client import StockServiceClient
from app.services.selector_service import detect_selectors
from app.services.search_template_service import discover_search_url_templates


PRICE_RE = re.compile(r"(\d[\d\s.,]*)\s*TND", re.IGNORECASE)

_FULL_PAGE_THRESHOLD = 24


def normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return " ".join(value.split()).strip() or None


def parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None

    text = value.replace("\xa0", " ").strip()
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ",.")

    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price_from_text(text: str) -> Optional[float]:
    if not text:
        return None

    m = PRICE_RE.search(text.replace("\xa0", " "))
    if not m:
        return None

    return parse_price(m.group(1))




def _safe_float(value) -> Optional[float]:
    """Convertit un prix numérique/string en float sans confondre séparateurs FR/TN."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_price(str(value))


def extract_price_from_node(node) -> Optional[float]:
    """
    Extraction robuste du prix depuis un noeud HTML.
    Priorité aux attributs numériques, puis texte visible.
    Corrige les cas itemprop='price' avec content='259.000'.
    """
    if node is None:
        return None

    for attr in (
        "content", "data-price", "data-final-price", "data-product-price",
        "data-price-amount", "value", "aria-label",
    ):
        raw = node.get(attr) if hasattr(node, "get") else None
        price = _safe_float(raw)
        if price is not None:
            return price

    text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)
    return extract_price_from_text(text) or parse_price(text)


def choose_plausible_price(prices: list[Optional[float]]) -> Optional[float]:
    """
    Choisit un prix plausible dans une liste.
    Évite les valeurs parasites très petites ou les vieux prix si plusieurs existent.
    """
    clean = []
    for price in prices:
        if price is None:
            continue
        try:
            p = float(price)
        except Exception:
            continue
        if 0.05 <= p <= 100000:
            clean.append(p)
    if not clean:
        return None
    # Si plusieurs prix sont visibles dans la même carte, le prix courant est souvent le plus petit
    # quand il y a une promo. On garde la plus petite valeur plausible.
    return min(clean)

def looks_like_product_name(text: str) -> bool:
    if not text:
        return False

    t = " ".join(text.split()).strip()
    lower = t.lower()

    banned = [
        "détails", "voir les détails", "ajouter au panier", "acheter",
        "connexion", "create an account", "panier", "menu",
        "retour", "suivant", "précédent", "contact", "accueil",
    ]

    if lower in banned:
        return False

    if len(t) < 8:
        return False

    useful_tokens = [
        "pc", "portable", "laptop", "notebook", "lenovo", "asus", "hp",
        "dell", "acer", "msi", "macbook", "iphone", "samsung", "oppo", "vivo", "realme", "honor", "infinix", "tecno", "xiaomi", "redmi", "écran",
        "ecran", "monitor", "moniteur", "ssd", "ram", "go", "gb", "tb",
        "intel", "amd", "ryzen", "core", "geforce", "rtx", "gtx",
        "processeur", "memoire", "mémoire", "disque", "clavier", "souris",
        "imprimante", "tablette", "smartphone", "telephone", "téléphone",
        "onduleur", "batterie", "chargeur", "casque", "ecouteur", "écouteur",
        "routeur", "switch", "wifi", "carte", "webcam", "scanner",
        "cable", "câble", "hdmi", "usb", "adaptateur", "hub",
    ]

    if len(t) > 20:
        return True

    return any(tok in lower for tok in useful_tokens)


def _detect_page_param(url: str) -> Optional[str]:
    params = parse_qs(urlparse(url).query)

    if "p" in params:
        return "p"

    if "page" in params:
        return "page"

    return None


def _build_page_url(base_url: str, page_num: int, param: str = "p") -> str:
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[param] = [str(page_num)]

    flat_params = {k: v[0] for k, v in params.items()}
    new_query = urlencode(flat_params)

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))


def _strip_page_param(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    for key in ("p", "page", "page_id", "paged"):
        params.pop(key, None)

    flat = {k: v[0] for k, v in params.items()}
    new_query = urlencode(flat) if flat else ""

    # support pagination sous forme /page/2/ ou /p/2/
    clean_path = re.sub(r"/(page|p)/\d+/?$", "", parsed.path.rstrip("/"), flags=re.IGNORECASE)

    return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", new_query, ""))


def _extract_product_ids(soup: BeautifulSoup, product_card_sel: Optional[str]) -> set:
    ids = set()

    if product_card_sel:
        for card in soup.select(product_card_sel):
            pid = card.get("data-id") or card.get("data-url")
            if pid:
                ids.add(pid)

    if not ids:
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href and len(href) > 5:
                ids.add(href)

    return ids


class ScrapingService:
    def __init__(self) -> None:
        self.stock_client = StockServiceClient()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        })

    def _absolute_url(self, base_url: str, href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        return urljoin(base_url, href)
    
    def _is_search_or_listing_url(self, url: str | None) -> bool:
        """
        Retourne True si l'URL est une page de recherche / catalogue,
        donc elle ne doit jamais être enregistrée comme urlProduit (hathi zedeteha khater 3tani des urls ghaltin)
        """
        if not url:
            return True

        parsed = urlparse(url)
        full = f"{parsed.path}?{parsed.query}".lower()

        bad_patterns = [
            "recherche",
            "search",
            "catalogsearch/result",
            "productsearch",
            "jolisearch",
            "controller=search",
            "submit_search",
            "post_type=product",
            "?s=",
            "&s=",
            "orderby=",
            "orderway=",
            "search_query=",
        ]

        return any(pattern in full for pattern in bad_patterns)

    def _clean_product_url(self, url: str | None) -> str | None:
        """
        Nettoie l'URL produit (nahi les # ect.)
        """
        if not url:
            return None

        parsed = urlparse(url)

        allowed_params = {}
        clean_query = urlencode(allowed_params)

        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            clean_query,
            "",
        ))

    def _is_probable_product_url(self, url: str | None) -> bool:
        """
        Vérifie si l'URL ressemble vraiment à une fiche produit.

        """
        if not url:
            return False

        if self._is_search_or_listing_url(url):
            return False

        parsed = urlparse(url)
        path_raw = parsed.path.lower()
        path = path_raw.strip("/")

        if not path:
            return False

        blocked_markers = [
            "/content/", "/brand/", "/marque/", "/manufacturer/",
            "/module/", "/recherche", "/search", "/catalogsearch",
            "/contact", "/a-propos", "/about", "/conditions", "/stores",
        ]
        if any(marker in path_raw for marker in blocked_markers):
            return False

        product_markers = [
            ".html", "/produit/", "/product/", "/products/", "/article/", "/p/",
        ]
        if any(marker in path_raw for marker in product_markers):
            return True

        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            last = parts[-1]
            if "-" in last and any(char.isdigit() for char in last):
                return True

        return False

    def _get_best_product_href_from_node(self, node, page_url: str) -> str | None:
        """
        Cherche le meilleur lien produit dans une carte HTML.
        """
        if node is None:
            return None

        candidates = []

        data_url = node.get("data-url")
        if data_url:
            candidates.append(data_url)

        for a in node.select("a[href]"):
            href = a.get("href")
            if href:
                candidates.append(href)

        for href in candidates:
            absolute = self._absolute_url(page_url, href)
            absolute = self._clean_product_url(absolute)

            if self._is_probable_product_url(absolute):
                return absolute

        return None

    def _get_canonical_product_url(self, soup: BeautifulSoup, current_url: str) -> str:
        """
        Depuis une fiche produit, récupère l'URL canonique réelle.
        """
        candidates = []

        canonical = soup.select_one("link[rel='canonical']")
        if canonical and canonical.get("href"):
            candidates.append(canonical.get("href"))

        og_url = soup.select_one("meta[property='og:url']")
        if og_url and og_url.get("content"):
            candidates.append(og_url.get("content"))

        for candidate in candidates:
            absolute = self._absolute_url(current_url, candidate)
            absolute = self._clean_product_url(absolute)

            if self._is_probable_product_url(absolute):
                return absolute

        return self._clean_product_url(current_url) or current_url
    
    def _get_html(self, url: str, timeout_seconds: int = 10) -> str:
        """Récupère le HTML avec retry adapté aux sites WooCommerce comme Infotec."""
        try:
            response = self._get_response_raw(url, timeout_seconds=timeout_seconds)
            return response.text

        except Exception as exc:
            raise RuntimeError(f"Echec récupération HTML pour {url}: {exc}")

    def _get_response_raw(self, url: str, timeout_seconds: int = 10) -> "requests.Response":
        """
        Retourne la Response brute avec headers navigateur.

        Correction Infotec : ce site WordPress/WooCommerce renvoie souvent 406
        avec requests classique. On tente donc :
        1) requests normal avec headers navigateur complets
        2) retry avec headers renforcés
        3) fallback cloudscraper si installé
        """
        parsed = urlparse(url)
        root = f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else ""

        base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        }
        if root:
            base_headers["Referer"] = root + "/"

        response = self.session.get(
            url,
            headers=base_headers,
            timeout=(5, timeout_seconds),
            allow_redirects=True,
            verify=False,
        )

        if response.status_code in {403, 406, 429}:
            retry_headers = {
                **base_headers,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
            response = self.session.get(
                url,
                headers=retry_headers,
                timeout=(5, timeout_seconds),
                allow_redirects=True,
                verify=False,
            )

        if response.status_code in {403, 406, 429} and cloudscraper is not None:
            try:
                scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "desktop": True}
                )
                response = scraper.get(
                    url,
                    headers=base_headers,
                    timeout=(5, timeout_seconds),
                    allow_redirects=True,
                    verify=False,
                )
            except Exception:
                pass

        response.raise_for_status()
        return response

    def _extract_products_from_mytek_json(
        self,
        raw_json: str,
        competitor: "CompetitorModel",
        product: dict | None = None,
    ) -> list["ProductCompetitorPayload"]:
        """
        Parse la réponse JSON de l'endpoint Mytek productsearch.
        Format typique :
          {"result": [{"url": "https://mytek.tn/xxx.html", "name": "...", "price": "..."}]}
        ou liste directe.
        Retourne des ProductCompetitorPayload prêts à filtrer.
        """
        import json as _json

        items: list[ProductCompetitorPayload] = []

        try:
            data = _json.loads(raw_json)
        except Exception:
            return items

        # Normaliser : peut être dict avec "result" / "items" / "products", ou liste directe
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            for key in ("result", "items", "products", "data", "hits"):
                if isinstance(data.get(key), list):
                    records = data[key]
                    break

        if not records:
            return items

        for rec in records:
            if not isinstance(rec, dict):
                continue

            # URL du produit
            url_produit = (
                rec.get("url") or rec.get("product_url") or
                rec.get("href") or rec.get("link") or ""
            ).strip()

            if not url_produit:
                continue

            if not url_produit.startswith("http"):
                url_produit = f"https://www.mytek.tn{url_produit}"

            url_produit = self._clean_product_url(url_produit)

            if self._is_search_or_listing_url(url_produit):
                continue

            # Nom
            nom_produit = normalize_text(
                rec.get("name") or rec.get("title") or rec.get("nom") or ""
            )
            if not nom_produit:
                continue

            # Prix — peut être string "299.000 TND" ou float
            prix_raw = (
                rec.get("price") or rec.get("final_price") or
                rec.get("prix") or rec.get("special_price") or ""
            )
            prix_concurrent: float | None = None
            if isinstance(prix_raw, (int, float)):
                prix_concurrent = float(prix_raw)
            else:
                prix_concurrent = (
                    extract_price_from_text(str(prix_raw)) or
                    parse_price(str(prix_raw))
                )

            if prix_concurrent is None:
                # Essayer regular_price
                prix_raw2 = rec.get("regular_price") or rec.get("old_price") or ""
                if prix_raw2:
                    prix_concurrent = (
                        extract_price_from_text(str(prix_raw2)) or
                        parse_price(str(prix_raw2))
                    )

            if prix_concurrent is None:
                prix_concurrent = 0.0  # prix inconnu, on garde quand même le produit

            # SKU
            sku_concurrent = normalize_text(
                rec.get("sku") or rec.get("reference") or rec.get("id") or ""
            )

            items.append(ProductCompetitorPayload(
                urlProduit=url_produit,
                skuConcurrent=sku_concurrent,
                nomProduit=nom_produit,
                descriptionConcurrent=nom_produit,
                concurrent_id=competitor.id,
                produit_id=(product or {}).get("id") or (product or {}).get("product_id"),
                prixConcurrent=prix_concurrent,
                ancienPrixConcurrent=None,
                isPromo=False,
                disponibilite=None,
                dateCollecte=datetime.utcnow().isoformat(),
                fiable=True,
            ))

        return items


    def _extract_products_from_generic_json(
        self,
        raw_json: str,
        competitor: "CompetitorModel",
        page_url: str,
    ) -> list["ProductCompetitorPayload"]:
        """
        Parse les réponses JSON génériques WordPress/WooCommerce.
        Exemple Infotec : /wp-json/wp/v2/search?... retourne title + url.
        S'il n'y a pas de prix dans le JSON, on garde quand même l'URL :
        le code ouvrira ensuite la fiche détail pour extraire le prix réel.
        """
        import json as _json

        try:
            data = _json.loads(raw_json)
        except Exception:
            return []

        if isinstance(data, dict):
            records = None
            for key in ("items", "products", "data", "results", "result"):
                if isinstance(data.get(key), list):
                    records = data.get(key)
                    break
            if records is None:
                records = [data]
        elif isinstance(data, list):
            records = data
        else:
            return []

        items: list[ProductCompetitorPayload] = []
        seen: set[str] = set()

        for rec in records:
            if not isinstance(rec, dict):
                continue

            raw_url = (
                rec.get("url")
                or rec.get("link")
                or rec.get("permalink")
                or rec.get("product_url")
                or rec.get("href")
            )
            url_produit = self._clean_product_url(self._absolute_url(page_url, raw_url)) if raw_url else None
            if not url_produit or url_produit in seen:
                continue
            if self._is_search_or_listing_url(url_produit):
                continue
            if not self._is_probable_product_url(url_produit):
                continue

            raw_title = rec.get("title") or rec.get("name") or rec.get("post_title") or ""
            if isinstance(raw_title, dict):
                raw_title = raw_title.get("rendered") or raw_title.get("raw") or ""
            name = normalize_text(str(raw_title))
            if not name:
                name = urlparse(url_produit).path.rstrip("/").split("/")[-1].replace("-", " ").title()

            raw_price = rec.get("price") or rec.get("regular_price") or rec.get("sale_price")
            price = extract_price_from_text(str(raw_price)) if raw_price is not None else None

            seen.add(url_produit)
            items.append(ProductCompetitorPayload(
                urlProduit=url_produit,
                skuConcurrent=normalize_text(str(rec.get("sku") or rec.get("ref") or "")) or None,
                nomProduit=name,
                descriptionConcurrent=normalize_text(str(rec.get("description") or rec.get("excerpt") or name)),
                concurrent_id=competitor.id,
                produit_id=None,
                prixConcurrent=price,
                ancienPrixConcurrent=None,
                isPromo=False,
                disponibilite=None,
                dateCollecte=datetime.utcnow().isoformat(),
                fiable=True,
            ))

        return items

    def _extract_product_from_card(
        self,
        card,
        page_url: str,
        selectors: dict,
        competitor: CompetitorModel,
    ):
        data_name = card.get("data-name")
        data_sku = card.get("data-sku")
        data_price = card.get("data-final-price") or card.get("data-price")

        name_node = (
            card.select_one(selectors.get("product_name"))
            if selectors.get("product_name")
            else None
        )

        price_node = (
            card.select_one(selectors.get("product_price"))
            if selectors.get("product_price")
            else None
        )

        old_price_node = (
            card.select_one(selectors.get("old_price"))
            if selectors.get("old_price")
            else None
        )

        availability_node = (
            card.select_one(selectors.get("availability"))
            if selectors.get("availability")
            else None
        )

        sku_node = (
            card.select_one(selectors.get("sku"))
            if selectors.get("sku")
            else None
        )

        nom_produit = data_name or (
            name_node.get_text(" ", strip=True) if name_node else None
        )

        url_produit = self._get_best_product_href_from_node(card, page_url)

        if not url_produit:
            return None

        price_candidates = [parse_price(data_price), extract_price_from_node(price_node)]

        # Fallback dans la carte : on cherche seulement les noeuds qui ressemblent à des prix,
        # pas tout le texte de la carte pour éviter de capter une référence produit comme prix.
        for price_candidate_node in card.select(
            "[itemprop='price'], meta[property='product:price:amount'], "
            ".price, .product-price, .current-price, .special-price, "
            ".final-price, .price-final_price, .woocommerce-Price-amount, [class*='price']"
        )[:8]:
            # ignorer explicitement les anciens prix pour le prix courant
            classes = " ".join(price_candidate_node.get("class", [])).lower()
            if "old" in classes or "regular" in classes or "was" in classes:
                continue
            price_candidates.append(extract_price_from_node(price_candidate_node))

        prix_concurrent = choose_plausible_price(price_candidates)

        ancien_prix = extract_price_from_node(old_price_node) if old_price_node else None

        disponibilite = (
            availability_node.get_text(" ", strip=True)
            if availability_node
            else None
        )

        sku_raw = data_sku or (
            sku_node.get_text(" ", strip=True)
            if sku_node
            else None
        )
        sku_concurrent = None
        if sku_raw:
            sku_clean = " ".join(sku_raw.split()).strip()
            if (len(sku_clean) <= 40 and
                (any(c.isdigit() for c in sku_clean) or
                 any(c.isupper() for c in sku_clean) or
                 '-' in sku_clean)):
                sku_concurrent = sku_clean

        if not nom_produit or prix_concurrent is None:
            return None

        description_concurrent = card.get_text(" ", strip=True)

        return ProductCompetitorPayload(
            urlProduit=url_produit,
            skuConcurrent=sku_concurrent,
            nomProduit=nom_produit,
            descriptionConcurrent=description_concurrent,

            concurrent_id=competitor.id,
            produit_id=None,

            prixConcurrent=prix_concurrent,
            ancienPrixConcurrent=ancien_prix,
            isPromo=bool(ancien_prix and ancien_prix > prix_concurrent),

            disponibilite=normalize_text(disponibilite),
            dateCollecte=datetime.utcnow().isoformat(),
            fiable=True,
        )

    def _extract_products_without_cards(
        self,
        soup: BeautifulSoup,
        page_url: str,
        competitor: CompetitorModel,
    ):
        items = []
        seen_urls = set()

        for a in soup.select("a[href]"):
            href = a.get("href")
            text = a.get_text(" ", strip=True)

            if not href or not looks_like_product_name(text):
                continue

            absolute_url = self._absolute_url(page_url, href)
            absolute_url = self._clean_product_url(absolute_url)

            if not absolute_url or absolute_url in seen_urls:
                continue

            if not self._is_probable_product_url(absolute_url):
                continue

            if not self._is_real_product_url(absolute_url, competitor.nom):
                # garder uniquement les vraies fiches produit pour éviter les pages catégorie
                continue

            parent = a.parent
            price = None
            availability = None

            probe = parent

            for _ in range(4):
                if probe is None:
                    break

                probe_text = probe.get_text(" ", strip=True)
                price = extract_price_from_text(probe_text) or price

                lower_text = probe_text.lower()

                if "hors stock" in lower_text:
                    availability = "Hors stock"
                elif "en stock" in lower_text:
                    availability = "En stock"
                elif "en arrivage" in lower_text:
                    availability = "En arrivage"

                if price is not None:
                    break

                probe = probe.parent

            if price is None:
                continue

            seen_urls.add(absolute_url)

            items.append(
                ProductCompetitorPayload(
                    urlProduit=absolute_url,
                    skuConcurrent=None,
                    nomProduit=text,
                    descriptionConcurrent=probe.get_text(" ", strip=True) if probe else text,

                    concurrent_id=competitor.id,
                    produit_id=None,

                    prixConcurrent=price,
                    ancienPrixConcurrent=None,
                    isPromo=False,

                    disponibilite=availability,
                    dateCollecte=datetime.utcnow().isoformat(),
                    fiable=False,
                )
            )

        return items
    
    
    

    def _is_real_product_url(self, url: str, competitor_name: str = "") -> bool:
        """
        Vérifie qu'une URL ressemble vraiment à une fiche produit.
        Évite les pages catégories comme /smartphone.html ou /telephone-portable.html.
        """
        if not url:
            return False

        u = url.lower()

        bad_parts = [
            "/content/",
            "/brand/",
            "/marque/",
            "/category/",
            "/categorie/",
            "/contact",
            "/a-propos",
            "/about",
            "/smartphone.html",
            "/telephone-portable.html",
            "/smartphone-mobile-tunisie.html",
        ]

        if any(part in u for part in bad_parts):
            return False

        # PrestaShop / Zoom / Spacenet / Tunisianet : ID numérique dans l'URL
        if re.search(r"/\d{3,8}[-_]", u):
            return True

        if re.search(r"/[a-z0-9\-]+/\d{3,8}[-_a-z0-9]*", u):
            return True

        # WooCommerce / custom shops : /produit/ ou /product/ suivi d'un slug
        if re.search(r"/(produit|product|products|item)/.+", u):
            return True

        # WooCommerce avec SKU dans le slug ex: /produit/ecouteurs-xiaomi-buds-8-bhr08olgl/
        # Le slug contient souvent la référence produit collée à la fin après un tiret
        if re.search(r"/produit[s]?/[a-z0-9\-]{8,}/", u):
            return True

        # Magento / Mytek : URL produit .html
        # FIX: seuil abaissé — un slug produit valide a au moins 3 tirets
        # ou 10+ chars avec au moins 1 tiret. Exclut /souris.html (0 tiret, 6 chars).
        if u.endswith(".html"):
            slug = u.split("/")[-1].replace(".html", "")
            dash_count = slug.count("-")
            if dash_count >= 3 or (len(slug) >= 10 and dash_count >= 1):
                return True

        # Fallback : dernier segment de path avec tirets (WooCommerce sans extension)
        parsed_path = urlparse(u).path.rstrip("/")
        last_segment = parsed_path.split("/")[-1] if parsed_path else ""
        generic_categories = {
            "smartphones", "ordinateurs", "ordinateurs-portables", "pc-portables",
            "pc-gamer", "ecrans", "imprimantes", "claviers", "souris-gamer",
            "accessoires", "composants", "stockage", "reseaux", "tablettes",
            "casques", "ecouteurs", "cameras", "chargeurs", "cables",
            "informatique", "telephonie", "multimedia",
        }
        if last_segment and "-" in last_segment and len(last_segment) >= 8:
            if last_segment not in generic_categories:
                return True

        return False

    def _extract_product_links_from_search_page(
        self,
        soup: BeautifulSoup,
        page_url: str,
        query: str,
        product: dict | None = None,
        limit: int = 20,
    ) -> list[str]:
        """
        Récupère les URLs produit depuis une page de recherche.

        Stratégie :
        1. Extraire les URLs depuis les balises <script> JSON (Mytek/Magento catalogsearch).
        2. Chercher les liens <a> forts (référence / marque / nom).
        3. Fallback : tous les liens produit probables.
        """
        import json as _json

        product = product or {}

        query_norm = self._quick_normalize(query)
        query_compact = query_norm.replace("-", "").replace(" ", "")

        sku_norm = self._quick_normalize(product.get("sku"))
        sku_compact = sku_norm.replace("-", "").replace(" ", "")

        marque_norm = self._quick_normalize(product.get("marque"))
        nom_norm = self._quick_normalize(product.get("nom"))

        strong_urls: list[str] = []
        fallback_urls: list[str] = []
        seen: set[str] = set()

        blocked_words = [
            "login", "connexion", "account", "cart", "panier", "wishlist",
            "compare", "contact", "javascript:", "add-to-cart", "customer",
            "checkout", "mon-compte", "authentication", "password", "register",
            "facebook", "instagram", "linkedin", "youtube", "twitter",
        ]

        # ---------------------------------------------------------------
        # FIX : extraire les URLs depuis les données JSON embarquées dans <script>
        # Mytek catalogsearch injecte les résultats en JSON dans la page HTML
        # ---------------------------------------------------------------
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if not script_text or len(script_text) < 30:
                continue

            # Pattern 1 : "url":"https://..." ou "product_url":"..."
            for raw_url in re.findall(
                r'"(?:url|product_url|href|link|productUrl)"\s*:\s*"([^"]+)"',
                script_text, re.IGNORECASE
            ):
                if not raw_url or raw_url.startswith("http") is False and not raw_url.startswith("/"):
                    continue
                absolute_url = self._absolute_url(page_url, raw_url)
                absolute_url = self._clean_product_url(absolute_url)
                if not absolute_url or absolute_url in seen:
                    continue
                if self._is_search_or_listing_url(absolute_url):
                    continue
                if not self._is_real_product_url(absolute_url):
                    continue
                seen.add(absolute_url)
                strong_urls.append(absolute_url)

            # Pattern 2 : blocs JSON inline Magento {"items":[{"url":"..."}]}
            # On tente un parse JSON sur les fragments qui ressemblent à des listes de produits
            for json_match in re.finditer(r'\{[^{}]*"(?:url|product_url)"[^{}]*\}', script_text):
                try:
                    obj = _json.loads(json_match.group())
                    raw_url = obj.get("url") or obj.get("product_url") or ""
                    if raw_url:
                        absolute_url = self._absolute_url(page_url, raw_url)
                        absolute_url = self._clean_product_url(absolute_url)
                        if absolute_url and absolute_url not in seen:
                            if not self._is_search_or_listing_url(absolute_url):
                                if self._is_real_product_url(absolute_url):
                                    seen.add(absolute_url)
                                    strong_urls.append(absolute_url)
                except Exception:
                    pass

        # ---------------------------------------------------------------
        # Parcours HTML classique des liens <a>
        # ---------------------------------------------------------------
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            link_text = a.get_text(" ", strip=True) or ""

            if not href:
                continue

            href_lower = href.lower()

            if any(word in href_lower for word in blocked_words):
                continue

            absolute_url = self._absolute_url(page_url, href)
            absolute_url = self._clean_product_url(absolute_url)

            if not absolute_url:
                continue

            if self._is_search_or_listing_url(absolute_url):
                continue

            if not self._is_probable_product_url(absolute_url):
                continue

            if not self._is_real_product_url(absolute_url, product.get("nom", "") or product.get("name", "") or ""):
                continue

            if absolute_url in seen:
                continue

            seen.add(absolute_url)

            parent_text = ""
            parent = a.parent

            for _ in range(4):
                if parent is None:
                    break

                parent_text += " " + parent.get_text(" ", strip=True)
                parent = parent.parent

            combined = self._quick_normalize(
                f"{link_text} {parent_text} {href} {absolute_url}"
            )
            combined_compact = combined.replace("-", "").replace(" ", "")

            contains_reference = False

            if query_norm and query_norm in combined:
                contains_reference = True

            if query_compact and query_compact in combined_compact:
                contains_reference = True

            if sku_norm and sku_norm in combined:
                contains_reference = True

            if sku_compact and sku_compact in combined_compact:
                contains_reference = True

            contains_brand = bool(marque_norm and marque_norm in combined)

            contains_name_word = False
            if nom_norm:
                important_words = [
                    word for word in nom_norm.split()
                    if len(word) >= 4
                    and word not in {
                        "avec", "noir", "blanc", "gris",
                        "azerty", "qwerty",
                    }
                ]

                common_words = [
                    word for word in important_words
                    if word in combined
                ]

                contains_name_word = len(common_words) >= 1

            if contains_reference or contains_brand or contains_name_word:
                strong_urls.append(absolute_url)
            else:
                fallback_urls.append(absolute_url)

            if len(strong_urls) >= limit:
                break

        if strong_urls:
            return strong_urls[:limit]

        return fallback_urls[:limit]

    def _extract_product_from_detail_page(
        self,
        url_produit: str,
        competitor: CompetitorModel,
    ) -> ProductCompetitorPayload | None:
        """
        Ouvre une fiche produit et extrait nom + prix + référence.
        Ce fallback corrige les pages de recherche dont les cartes sont mal parsées.
        """
        try:
            html = self._get_html(url_produit)
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(" ", strip=True)
            if self._is_search_or_listing_url(url_produit):
                return None

            final_url = self._get_canonical_product_url(soup, url_produit)

            if not self._is_probable_product_url(final_url):
                return None

            if not self._is_real_product_url(final_url, competitor.nom):
                return None
            
            name = None
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)

            if not name:
                meta_title = soup.select_one("meta[property='og:title']")
                if meta_title and meta_title.get("content"):
                    name = meta_title.get("content").strip()

            if not name:
                meta_name = soup.select_one("meta[name='title']")
                if meta_name and meta_name.get("content"):
                    name = meta_name.get("content").strip()

            if not name and soup.title:
                name = soup.title.get_text(" ", strip=True)

            name = normalize_text(name)
            if not name:
                return None

            price = None
            price_selectors = [
                "[itemprop='price']",
                "meta[property='product:price:amount']",
                "meta[property='og:price:amount']",
                "meta[itemprop='price']",
                ".price",
                ".product-price",
                ".current-price",
                ".regular-price",
                ".special-price",
                ".price-box",
                ".price-wrapper",
                ".woocommerce-Price-amount",
                ".product-prices",
                ".our_price_display",
                ".price-container",
                ".final-price",
                ".price-final_price",
                ".amount",
            ]

            for selector in price_selectors:
                node = soup.select_one(selector)
                if not node:
                    continue

                classes = " ".join(node.get("class", [])).lower() if hasattr(node, "get") else ""
                if "old" in classes or "was" in classes:
                    continue

                price = extract_price_from_node(node)

                if price is not None:
                    break

            if price is None:
                price = extract_price_from_text(text)

            if price is None:
                return None

            old_price = None
            old_price_selectors = [
                ".old-price", ".regular-price .price", ".price-old",
                ".was-price", "del",
            ]
            for selector in old_price_selectors:
                node = soup.select_one(selector)
                if not node:
                    continue
                old_price = extract_price_from_node(node)
                if old_price:
                    break

            availability = None
            lower_text = text.lower()
            if "hors stock" in lower_text or "rupture" in lower_text or "épuisé" in lower_text or "epuise" in lower_text:
                availability = "Hors stock"
            elif "en stock" in lower_text or "disponible" in lower_text:
                availability = "En stock"
            elif "en arrivage" in lower_text:
                availability = "En arrivage"

            sku_concurrent = None
            sku_patterns = [
                r"(référence|reference|ref|sku)\s*[:\-]?\s*([A-Z0-9\-_]{3,40})",
                r"\b([A-Z]{1,8}[-\s]?\d{3,8}[A-Z0-9]*)\b",
                r"\b([A-Z0-9]{3,12}[-_][A-Z0-9]{2,16})\b",
            ]

            for pattern in sku_patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    sku_concurrent = match.group(2) if len(match.groups()) >= 2 else match.group(1)
                    sku_concurrent = sku_concurrent.strip()
                    break

            return ProductCompetitorPayload(
                urlProduit=final_url,
                skuConcurrent=sku_concurrent,
                nomProduit=name,
                descriptionConcurrent=text[:3000],
                concurrent_id=competitor.id,
                produit_id=None,
                prixConcurrent=price,
                ancienPrixConcurrent=old_price,
                isPromo=bool(old_price and old_price > price),
                disponibilite=availability,
                dateCollecte=datetime.utcnow().isoformat(),
                fiable=True,
            )

        except Exception:
            return None

    def _extract_products_from_search_by_detail(
        self,
        page_url: str,
        html: str,
        competitor: CompetitorModel,
        query: str,
        product: dict | None = None,
        limit: int = 5,
        budget_seconds: float = 8.0,
    ) -> list[ProductCompetitorPayload]:
        """
        Ouvre quelques fiches détail avec un vrai budget temps.
        Correction importante :
        - pas de "with ThreadPoolExecutor", car il peut attendre les tâches lentes à la sortie.
        - shutdown(wait=False) pour ne pas bloquer tout le scraping.
        """
        if budget_seconds <= 1:
            return []

        soup = BeautifulSoup(html, "lxml")
        urls = self._extract_product_links_from_search_page(
            soup=soup,
            page_url=page_url,
            query=query,
            product=product,
            limit=limit,
        )

        unique_urls = [
            url for url in dict.fromkeys(urls)
            if self._is_real_product_url(url, competitor.nom)
            and not self._is_search_or_listing_url(url)
        ]

        if not unique_urls:
            return []

        items: list[ProductCompetitorPayload] = []
        executor = ThreadPoolExecutor(max_workers=2)
        futures = {}

        try:
            futures = {
                executor.submit(self._extract_product_from_detail_page, url, competitor): url
                for url in unique_urls[:limit]
            }

            deadline = time.monotonic() + budget_seconds

            for future in as_completed(futures, timeout=max(1, budget_seconds)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                try:
                    item = future.result(timeout=min(1, remaining))
                    if item:
                        items.append(item)
                except Exception:
                    pass

        except FuturesTimeoutError:
            for future in list(futures.keys()):
                if future.done():
                    try:
                        item = future.result(timeout=0)
                        if item:
                            items.append(item)
                    except Exception:
                        pass

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return items

    def _extract_magento_product_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        """
        Extrait les URLs produit depuis les scripts Magento (x-magento-init, data-mage-init).
        Mytek et autres sites Magento chargent les produits via JSON dans des <script type="text/x-magento-init">.
        """
        import json as _json
        urls = []
        seen = set()

        for script in soup.find_all("script"):
            stype = script.get("type", "")
            text = script.string or ""
            if not text:
                continue

            # Scripts Magento type="text/x-magento-init"
            if "x-magento-init" in stype or "magento" in text.lower():
                # Chercher toutes les URLs .html dans le script
                for raw_url in re.findall(r'"(https?://[^"]+\.html)"', text):
                    if raw_url not in seen:
                        clean = self._clean_product_url(raw_url)
                        if clean and self._is_real_product_url(clean) and not self._is_search_or_listing_url(clean):
                            seen.add(raw_url)
                            urls.append(clean)

            # Scripts contenant des listes de produits JSON (pattern général)
            if '"url"' in text or '"product_url"' in text:
                for raw_url in re.findall(r'"(?:url|product_url|href)"\s*:\s*"(https?://[^"]+)"', text, re.IGNORECASE):
                    if raw_url not in seen:
                        clean = self._clean_product_url(raw_url)
                        if clean and self._is_real_product_url(clean) and not self._is_search_or_listing_url(clean):
                            seen.add(raw_url)
                            urls.append(clean)

        return urls[:20]

    def _extract_products_from_json_ld_page(
        self,
        soup: BeautifulSoup,
        page_url: str,
        competitor: CompetitorModel,
    ) -> list[ProductCompetitorPayload]:
        """
        Extrait les produits depuis JSON-LD (Product / ItemList).
        Beaucoup de sites e-commerce mettent nom, url, sku et prix dans les scripts JSON-LD.
        """
        import json as _json

        items: list[ProductCompetitorPayload] = []
        seen: set[str] = set()

        def _iter_objects(obj):
            if isinstance(obj, dict):
                yield obj
                graph = obj.get("@graph")
                if isinstance(graph, list):
                    for child in graph:
                        yield from _iter_objects(child)
                item_list = obj.get("itemListElement")
                if isinstance(item_list, list):
                    for child in item_list:
                        yield from _iter_objects(child)
                offers = obj.get("offers")
                if isinstance(offers, list):
                    for child in offers:
                        yield from _iter_objects(child)
                elif isinstance(offers, dict):
                    yield offers
            elif isinstance(obj, list):
                for child in obj:
                    yield from _iter_objects(child)

        def _product_from_obj(obj: dict) -> ProductCompetitorPayload | None:
            obj_type = obj.get("@type") or obj.get("type") or ""
            if isinstance(obj_type, list):
                obj_type = " ".join(map(str, obj_type))
            obj_type = str(obj_type).lower()

            # ItemList peut contenir l'URL seulement; le détail sera extrait par fallback détail.
            if "product" not in obj_type and not (obj.get("name") and (obj.get("offers") or obj.get("price"))):
                return None

            raw_url = obj.get("url") or obj.get("productUrl") or obj.get("link")
            url_produit = self._clean_product_url(self._absolute_url(page_url, raw_url)) if raw_url else None
            if not url_produit or self._is_search_or_listing_url(url_produit):
                return None
            if not self._is_probable_product_url(url_produit):
                return None

            name = normalize_text(obj.get("name") or obj.get("title"))
            if not name:
                return None

            offers = obj.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = (
                _safe_float(obj.get("price"))
                or _safe_float(offers.get("price") if isinstance(offers, dict) else None)
                or parse_price(str(offers.get("priceSpecification", "")) if isinstance(offers, dict) else "")
            )
            if price is None:
                return None

            availability = None
            if isinstance(offers, dict):
                av = str(offers.get("availability") or "").lower()
                if "instock" in av or "in_stock" in av:
                    availability = "En stock"
                elif "outofstock" in av or "rupture" in av:
                    availability = "Hors stock"

            return ProductCompetitorPayload(
                urlProduit=url_produit,
                skuConcurrent=normalize_text(obj.get("sku") or obj.get("mpn") or obj.get("gtin13")),
                nomProduit=name,
                descriptionConcurrent=normalize_text(obj.get("description") or name),
                concurrent_id=competitor.id,
                produit_id=None,
                prixConcurrent=price,
                ancienPrixConcurrent=None,
                isPromo=False,
                disponibilite=availability,
                dateCollecte=datetime.utcnow().isoformat(),
                fiable=True,
            )

        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = _json.loads(raw)
            except Exception:
                continue
            for obj in _iter_objects(data):
                item = _product_from_obj(obj)
                if item and item.urlProduit not in seen:
                    seen.add(item.urlProduit)
                    items.append(item)

        return items

    def _extract_products_from_page(
        self,
        page_url: str,
        html: str,
        competitor: CompetitorModel,
    ):
        soup = BeautifulSoup(html, "lxml")

        host = competitor.site_host_normalized or ""
        selectors = dict(competitor.selectors_override or {})

        if not selectors.get("product_card"):
            selectors.update(detect_selectors(host, html))

        errors = []
        items = []

        # 1) JSON-LD d'abord : souvent plus propre que les classes CSS.
        try:
            items.extend(self._extract_products_from_json_ld_page(soup, page_url, competitor))
        except Exception as exc:
            errors.append(f"Erreur JSON-LD sur {page_url}: {str(exc)}")

        product_card_sel = selectors.get("product_card")
        cards = []

        if product_card_sel:
            try:
                cards = soup.select(product_card_sel)
            except Exception as exc:
                errors.append(f"Sélecteur product_card invalide: {exc}")

        if cards:
            for card in cards:
                try:
                    item = self._extract_product_from_card(
                        card,
                        page_url,
                        selectors,
                        competitor,
                    )

                    if item:
                        items.append(item)

                except Exception as exc:
                    errors.append(f"Erreur parsing carte sur {page_url}: {str(exc)}")

        if not items:
            fallback_items = self._extract_products_without_cards(
                soup,
                page_url,
                competitor,
            )
            items.extend(fallback_items)

        # Dédoublonnage interne de la page en gardant l'item le plus fiable.
        deduped = {}
        for item in items:
            key = (item.urlProduit or item.nomProduit or "").strip().lower()
            if not key:
                continue
            if key not in deduped or (item.fiable and not deduped[key].fiable):
                deduped[key] = item
        items = list(deduped.values())

        next_page_url = None
        next_selector = selectors.get("next_page")

        if next_selector:
            try:
                next_node = soup.select_one(next_selector)

                if next_node and next_node.has_attr("href"):
                    candidate = self._absolute_url(page_url, next_node.get("href"))

                    if candidate and candidate != page_url:
                        next_page_url = candidate

            except Exception:
                pass

        if not next_page_url:
            for a in soup.select("a[href]"):
                txt = a.get_text(" ", strip=True).lower()

                if txt in {"suivant", "next"} or "navigate_next" in txt:
                    candidate = self._absolute_url(page_url, a.get("href"))

                    if candidate and candidate != page_url:
                        next_page_url = candidate
                        break

        if not next_page_url and len(items) >= _FULL_PAGE_THRESHOLD:
            param = _detect_page_param(page_url) or "p"
            current_params = parse_qs(urlparse(page_url).query)
            current_page_num = int(current_params.get(param, ["1"])[0])
            next_page_url = _build_page_url(page_url, current_page_num + 1, param)

        return items, next_page_url, errors, soup, selectors

    def _scrape_catalog(
        self,
        catalog: dict,
        competitor: CompetitorModel,
        seen_product_urls: Set[str],
        all_items: list,
        all_errors: list,
        max_pages: int = 30,
    ) -> tuple[int, int, int, list]:
        current_url = catalog["url"]
        base_url_stripped = _strip_page_param(current_url)

        seen_pages: Set[str] = set()
        prev_product_ids: set = set()

        page_count = 0
        catalog_raw = 0
        catalog_unique = 0
        catalog_errors = []
        consecutive_empty_pages = 0

        while current_url and page_count < max_pages:
            normalized = current_url

            if normalized in seen_pages:
                break

            seen_pages.add(normalized)

            try:
                html = self._get_html(current_url)

                page_items, next_page_url, page_errors, soup, selectors = (
                    self._extract_products_from_page(
                        current_url,
                        html,
                        competitor,
                    )
                )

                if not page_items:
                    catalog_errors.extend(page_errors)
                    all_errors.extend(page_errors)
                    consecutive_empty_pages += 1
                    page_count += 1

                    # Ne pas arrêter dès la première page vide : certains catalogues
                    # renvoient une page intermédiaire vide ou un HTML partiellement chargé.
                    if next_page_url and consecutive_empty_pages < 2:
                        current_url = next_page_url
                        time.sleep(0.5)
                        continue

                    # Fallback pagination si la page ressemble à une page catalogue.
                    if consecutive_empty_pages < 2:
                        param = _detect_page_param(current_url) or "p"
                        current_params = parse_qs(urlparse(current_url).query)
                        try:
                            current_page_num = int(current_params.get(param, ["1"])[0])
                        except Exception:
                            current_page_num = page_count + 1
                        current_url = _build_page_url(current_url, current_page_num + 1, param)
                        time.sleep(0.5)
                        continue

                    break

                consecutive_empty_pages = 0

                product_card_sel = selectors.get("product_card")
                current_ids = _extract_product_ids(soup, product_card_sel)

                if prev_product_ids and current_ids and current_ids == prev_product_ids:
                    break

                prev_product_ids = current_ids

                if next_page_url:
                    next_stripped = _strip_page_param(next_page_url)

                    if next_stripped != base_url_stripped:
                        next_page_url = None

                catalog_raw += len(page_items)

                for item in page_items:
                    if item.urlProduit not in seen_product_urls:
                        seen_product_urls.add(item.urlProduit)
                        all_items.append(item)
                        catalog_unique += 1

                all_errors.extend(page_errors)
                catalog_errors.extend(page_errors)

                page_count += 1
                current_url = next_page_url
                time.sleep(0.5)

            except Exception as exc:
                msg = f"Erreur scraping page {current_url}: {str(exc)}"
                all_errors.append(msg)
                catalog_errors.append(msg)
                break

        return page_count, catalog_raw, catalog_unique, catalog_errors

    def scrape_competitor(self, competitor: CompetitorModel) -> ScrapeSummary:
        if not competitor.actif:
            return ScrapeSummary(
                competitor_id=competitor.id,
                competitor_name=competitor.nom,
                pages_parcourues=0,
                produits_bruts=0,
                produits_uniques=0,
                produits_enregistres=0,
                produits_matches=0,
                produits_a_valider=0,
                produits_ignores=0,
                produits_invalides=0,
                inserted=0,
                updated=0,
                errors=["Concurrent inactif"],
                catalog_details=[],
            )

        catalogs = [
            c for c in (competitor.catalogs or [])
            if c.get("is_selected", True)
            and c.get("is_active", True)
            and c.get("url")
        ]

        if not catalogs:
            return ScrapeSummary(
                competitor_id=competitor.id,
                competitor_name=competitor.nom,
                pages_parcourues=0,
                produits_bruts=0,
                produits_uniques=0,
                produits_enregistres=0,
                produits_matches=0,
                produits_a_valider=0,
                produits_ignores=0,
                produits_invalides=0,
                inserted=0,
                updated=0,
                errors=["Aucun catalogue actif sélectionné"],
                catalog_details=[],
            )

        all_items: list[ProductCompetitorPayload] = []
        all_errors: list[str] = []
        catalog_details = []
        seen_product_urls: Set[str] = set()

        pages_total = 0
        raw_total = 0

        for catalog in catalogs:
            page_count, catalog_raw, catalog_unique, catalog_errors = self._scrape_catalog(
                catalog=catalog,
                competitor=competitor,
                seen_product_urls=seen_product_urls,
                all_items=all_items,
                all_errors=all_errors,
                max_pages=15,
            )

            pages_total += page_count
            raw_total += catalog_raw

            catalog_details.append(
                CatalogScrapeDetail(
                    catalog_url=catalog["url"],
                    catalog_title=catalog.get("title"),
                    pages_parcourues=page_count,
                    produits_bruts=catalog_raw,
                    produits_uniques=catalog_unique,
                    errors=catalog_errors,
                )
            )

        save_result = self.stock_client.save_competitor_products(all_items)

        inserted = int(save_result.get("inserted", 0) or 0)
        updated = int(save_result.get("updated", 0) or 0)
        matched = int(save_result.get("matched", 0) or 0)
        manual_review = int(save_result.get("manual_review", 0) or 0)
        ignored = int(save_result.get("ignored", 0) or 0)
        invalid = int(save_result.get("invalid", 0) or 0)

        saved_rows = int(save_result.get("rows") or inserted + updated)

        self.stock_client.update_last_scraping(competitor.id)

        saved_items = save_result.get("saved_items", []) or save_result.get("scraped_products", []) or []
        invalid_items = save_result.get("invalid_items", []) or []
        if invalid_items:
            all_errors.extend([
                f"Produit catalogue ignoré: {x.get('reason')}"
                for x in invalid_items[:20]
                if isinstance(x, dict)
            ])

        return ScrapeSummary(
            competitor_id=competitor.id,
            competitor_name=competitor.nom,
            pages_parcourues=pages_total,
            produits_bruts=raw_total,
            produits_uniques=len(all_items),
            produits_enregistres=saved_rows,
            produits_matches=matched,
            produits_a_valider=manual_review,
            produits_ignores=ignored,
            produits_invalides=invalid,
            inserted=inserted,
            updated=updated,
            errors=all_errors,
            catalog_details=catalog_details,
            scraped_products=saved_items,
            saved_items=saved_items,
        )

    # -------------------------------------------------------------------------
    # Recherche ciblée par catalogues pertinents
    # -------------------------------------------------------------------------

    def _extract_keywords_from_product(self, product: dict) -> set[str]:
        text = " ".join([
            product.get("nom") or "",
            product.get("categorie") or "",
            product.get("description") or "",
            product.get("marque") or "",
            product.get("sku") or "",
        ]).lower()

        keyword_map = {
            "pc_gamer": [
                "pc gamer", "gamer", "gaming", "victus", "rog", "tuf",
                "nitro", "predator", "rtx", "gtx", "geforce"
            ],
            "pc_portable": [
                "pc portable", "portable", "laptop", "notebook",
                "ordinateur portable", "vivobook", "ideapad", "thinkpad",
                "pavilion", "inspiron", "latitude", "victus"
            ],
            "ordinateur_bureau": [
                "ordinateur bureau", "pc bureau", "desktop", "all in one",
                "mini pc", "unite centrale", "unité centrale"
            ],
            "souris": [
                "souris", "mouse", "wireless mouse", "gaming mouse",
                "souris gamer", "souris sans fil"
            ],
            "clavier": [
                "clavier", "keyboard", "clavier gamer", "clavier mécanique",
                "clavier mecanique", "azerty", "qwerty"
            ],
            "pack_clavier_souris": [
                "clavier souris", "pack clavier", "combo clavier",
                "desktop set", "keyboard mouse"
            ],
            "tapis_souris": [
                "tapis souris", "tapis de souris", "mouse pad", "mousepad"
            ],
            "casque": [
                "casque", "headset", "ecouteur", "écouteur", "earbuds",
                "micro casque", "casque gamer", "casque bluetooth"
            ],
            "microphone": [
                "microphone", "micro", "micro gamer", "micro streaming"
            ],
            "webcam": [
                "webcam", "camera web", "caméra web"
            ],
            "cable": [
                "cable", "câble", "usb-c", "type-c", "type c", "hdmi",
                "vga", "displayport", "dp", "ethernet", "rj45",
                "jack", "sata", "cable réseau", "câble réseau"
            ],
            "adaptateur": [
                "adaptateur", "adapter", "convertisseur", "hub",
                "dongle", "usb hub", "hub usb"
            ],
            "chargeur": [
                "chargeur", "charger", "alimentation", "adaptateur secteur",
                "power adapter", "bloc secteur"
            ],
            "batterie": [
                "batterie", "battery", "power bank", "batterie pc portable",
                "batterie smartphone"
            ],
            "ecran": [
                "ecran", "écran", "moniteur", "monitor", "display",
                "full hd", "fhd", "ips", "144hz", "165hz", "240hz"
            ],
            "projecteur": [
                "projecteur", "videoprojecteur", "vidéoprojecteur",
                "projector"
            ],
            "haut_parleur": [
                "haut parleur", "haut-parleur", "speaker", "enceinte",
                "soundbar", "barre de son"
            ],
            "imprimante": [
                "imprimante", "printer", "canon", "epson", "brother",
                "hp laser", "laserjet", "jet d'encre", "multifonction"
            ],
            "scanner": [
                "scanner", "scan"
            ],
            "toner": [
                "toner", "cartouche", "encre", "drum", "tambour"
            ],
            "stockage": [
                "ssd", "hdd", "disque dur", "disque externe", "flash",
                "clé usb", "cle usb", "usb flash", "carte mémoire",
                "carte memoire", "microsd", "sd card", "sandisk", "kingston"
            ],
            "ram": [
                "ram", "barrette mémoire", "barrette memoire", "ddr3",
                "ddr4", "ddr5", "mémoire pc", "memoire pc"
            ],
            "carte_graphique": [
                "carte graphique", "gpu", "rtx", "gtx", "geforce",
                "radeon"
            ],
            "processeur": [
                "processeur", "cpu", "intel core", "core i3", "core i5",
                "core i7", "core i9", "ryzen"
            ],
            "carte_mere": [
                "carte mère", "carte mere", "motherboard"
            ],
            "boitier": [
                "boitier", "boîtier", "case", "tour pc"
            ],
            "ventilation": [
                "ventilateur", "refroidisseur", "cooler", "watercooling",
                "cooling"
            ],
            "reseau": [
                "routeur", "router", "switch", "wifi", "wi-fi",
                "modem", "point d'accès", "access point", "répéteur",
                "repeteur", "réseau", "reseau"
            ],
            "camera_surveillance": [
                "camera ip", "caméra ip", "camera surveillance",
                "caméra surveillance", "dvr", "nvr"
            ],
            "onduleur": [
                "onduleur", "ups"
            ],
            "smartphone": [
                "smartphone", "telephone", "téléphone", "iphone",
                "galaxy", "redmi", "xiaomi", "oppo", "honor",
                "infinix", "tecno"
            ],
            "tablette": [
                "tablette", "tablet", "ipad", "galaxy tab"
            ],
            "accessoire_telephone": [
                "coque", "protection écran", "protection ecran",
                "film verre trempé", "verre trempe", "chargeur smartphone",
                "cable iphone", "câble iphone", "lightning", "magsafe"
            ],
            "console": [
                "console", "playstation", "ps5", "ps4", "xbox", "nintendo",
                "switch oled"
            ],
            "manette": [
                "manette", "controller", "joystick", "gamepad"
            ],
            "chaise_gamer": [
                "chaise gamer", "fauteuil gamer", "gaming chair"
            ],
            "bureau_gamer": [
                "bureau gamer", "desk gamer", "gaming desk"
            ],
        }

        detected = set()

        for business_key, words in keyword_map.items():
            for word in words:
                if word in text:
                    detected.add(business_key)
                    detected.add(word)

        specs_patterns = [
            r"\brtx\s*\d{3,4}\b",
            r"\bgtx\s*\d{3,4}\b",
            r"\bmx\s*\d{3,4}\b",
            r"\bi[3579]\b",
            r"\bcore\s*i[3579]\b",
            r"\bryzen\s*[3579]\b",
            r"\b(4|8|16|32|64|128)\s*(go|gb)\b",
            r"\b(128|256|512)\s*(go|gb)\b",
            r"\b(1|2|4|8)\s*(to|tb)\b",
            r"\b\d{2,3}\s*w\b",
            r"\b\d{4,6}\s*mah\b",
            r"\b\d{2,3}\s*hz\b",
        ]

        for pattern in specs_patterns:
            for match in re.findall(pattern, text):
                if isinstance(match, tuple):
                    detected.add(" ".join([x for x in match if x]).strip())
                else:
                    detected.add(match.strip())

        return detected

    def _catalog_score_for_product(self, catalog: dict, keywords: set[str]) -> int:
        url = (catalog.get("url") or "").lower()
        title = (catalog.get("title") or "").lower()
        text = f"{url} {title}"

        score = 0

        for keyword in keywords:
            keyword = keyword.lower().strip()
            if keyword and keyword in text:
                score += 10

        rules = {
            "pc_gamer": [
                "gamer", "gaming", "pc-gamer", "pc_gamer",
                "ordinateur-gamer", "pc-portable-gamer"
            ],
            "pc_portable": [
                "pc-portable", "ordinateur-portable", "ordinateurs-portables",
                "laptop", "notebook", "portable"
            ],
            "ordinateur_bureau": [
                "ordinateur-bureau", "pc-bureau", "desktop",
                "all-in-one", "mini-pc", "unite-centrale", "unité-centrale"
            ],
            "souris": [
                "souris", "mouse"
            ],
            "clavier": [
                "clavier", "keyboard"
            ],
            "pack_clavier_souris": [
                "clavier-souris", "clavier-souris-tapis", "combo"
            ],
            "tapis_souris": [
                "tapis", "tapis-de-souris", "mousepad", "mouse-pad"
            ],
            "casque": [
                "casque", "ecouteur", "écouteur", "micro-casque",
                "headset", "earbuds"
            ],
            "microphone": [
                "microphone", "micro"
            ],
            "webcam": [
                "webcam", "camera-web", "caméra-web"
            ],
            "cable": [
                "cable", "câble", "cables", "câbles", "adaptateur",
                "cables-adaptateurs", "câbles-adaptateurs", "connectique"
            ],
            "adaptateur": [
                "adaptateur", "adapter", "convertisseur", "hub",
                "cables-adaptateurs", "câbles-adaptateurs"
            ],
            "chargeur": [
                "chargeur", "charger", "alimentation", "adaptateur-secteur"
            ],
            "batterie": [
                "batterie", "battery", "power-bank"
            ],
            "ecran": [
                "ecran", "écran", "moniteur", "monitor"
            ],
            "projecteur": [
                "projecteur", "videoprojecteur", "vidéoprojecteur", "projector"
            ],
            "haut_parleur": [
                "haut-parleur", "haut parleur", "speaker", "enceinte", "son"
            ],
            "imprimante": [
                "imprimante", "printer", "impression", "multifonction"
            ],
            "scanner": [
                "scanner"
            ],
            "toner": [
                "toner", "cartouche", "encre", "tambour", "drum"
            ],
            "stockage": [
                "stockage", "ssd", "hdd", "disque-dur", "disque dur",
                "flash", "cle-usb", "clé-usb", "carte-memoire", "carte-mémoire"
            ],
            "ram": [
                "ram", "memoire", "mémoire", "barrette", "ddr3", "ddr4", "ddr5"
            ],
            "carte_graphique": [
                "carte-graphique", "gpu", "rtx", "gtx", "geforce", "radeon"
            ],
            "processeur": [
                "processeur", "cpu", "intel", "amd", "ryzen"
            ],
            "carte_mere": [
                "carte-mere", "carte-mère", "motherboard"
            ],
            "boitier": [
                "boitier", "boîtier", "case", "tour"
            ],
            "ventilation": [
                "ventilateur", "refroidisseur", "cooler", "watercooling"
            ],
            "reseau": [
                "reseau", "réseau", "routeur", "router", "switch",
                "wifi", "modem", "access-point", "point-acces"
            ],
            "camera_surveillance": [
                "camera", "caméra", "surveillance", "dvr", "nvr"
            ],
            "onduleur": [
                "onduleur", "ups"
            ],
            "smartphone": [
                "smartphone", "telephone", "téléphone", "mobile", "iphone"
            ],
            "tablette": [
                "tablette", "tablet", "ipad"
            ],
            "accessoire_telephone": [
                "accessoire-telephone", "accessoires-telephonie",
                "coque", "protection", "verre-trempe", "lightning"
            ],
            "console": [
                "console", "playstation", "xbox", "nintendo"
            ],
            "manette": [
                "manette", "controller", "joystick", "gamepad"
            ],
            "chaise_gamer": [
                "chaise-gamer", "fauteuil-gamer"
            ],
            "bureau_gamer": [
                "bureau-gamer", "desk-gamer"
            ],
        }

        for key, catalog_terms in rules.items():
            if key in keywords:
                for term in catalog_terms:
                    if term in text:
                        score += 50
                        break

        peripheral_keys = {
            "souris", "clavier", "pack_clavier_souris", "tapis_souris",
            "casque", "microphone", "webcam", "cable", "adaptateur",
            "chargeur", "batterie"
        }

        if keywords.intersection(peripheral_keys):
            if any(x in text for x in ["accessoire", "accessoires", "peripherique", "périphérique"]):
                score += 25

        return score

    def _select_relevant_catalogs_for_product(
        self,
        competitor: CompetitorModel,
        product: dict,
        max_catalogs: int = 5,
    ) -> list[dict]:
        catalogs = [
            c for c in (competitor.catalogs or [])
            if c.get("is_selected", True)
            and c.get("is_active", True)
            and c.get("url")
        ]

        if not catalogs:
            return []

        keywords = self._extract_keywords_from_product(product)

        scored_catalogs = []

        for catalog in catalogs:
            score = self._catalog_score_for_product(catalog, keywords)

            if score > 0:
                scored_catalogs.append((score, catalog))

        scored_catalogs.sort(key=lambda x: x[0], reverse=True)

        return [catalog for score, catalog in scored_catalogs[:max_catalogs]]
    
    
    
    def _normalize_reference_text(self, value: str | None) -> str:
        """
        Normalise une référence sans changer son sens.
        Exemple : X1502VA-BQ903W -> x1502va-bq903w
        """
        if not value:
            return ""

        value = str(value).lower().strip()
        value = value.replace("é", "e").replace("è", "e").replace("ê", "e")
        value = value.replace("à", "a").replace("ù", "u")
        value = re.sub(r"[^a-z0-9\-]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _reference_variants(self, reference: str) -> set[str]:
        """
        Génère les variantes d'une référence.
        Corrige les références Apple avec slash :
        MRXQ3FN/A -> mrxq3fn/a, mrxq3fn a, mrxq3fna, mrxq3fn-a
        """
        raw = str(reference or "").strip()
        ref = self._normalize_reference_text(raw)
        if not ref:
            return set()

        # Version qui garde le slash pour les références Apple constructeur.
        slash_ref = raw.lower().strip()
        slash_ref = slash_ref.replace("é", "e").replace("è", "e").replace("ê", "e")
        slash_ref = slash_ref.replace("à", "a").replace("ù", "u")
        slash_ref = re.sub(r"[^a-z0-9\-/]+", " ", slash_ref)
        slash_ref = re.sub(r"\s+", " ", slash_ref).strip()

        variants = {
            ref,
            ref.replace("-", ""),
            ref.replace(" ", ""),
            ref.replace("-", " "),
        }

        if slash_ref:
            variants.update({
                slash_ref,
                slash_ref.replace("/", " "),
                slash_ref.replace("/", ""),
                slash_ref.replace("/", "-"),
                slash_ref.replace("/", "%2f"),
                slash_ref.replace("/", "%2F"),
            })

        compact = ref.replace("-", "").replace(" ", "")
        match = re.match(r"^([a-z]+)(\d+)$", compact)
        if match:
            prefix, number = match.groups()
            variants.add(f"{prefix}-{number}")
            variants.add(f"{prefix} {number}")
            variants.add(f"{prefix}{number}")

        return {v for v in variants if v}

    def _extract_reference_from_text_fallback(self, text: str) -> list[str]:
        """
        Fallback uniquement si le SKU est absent.
        On exclut les processeurs/connectiques/mots techniques.
        """
        if not text:
            return []

        patterns = [
            r"\b[A-Z0-9]{4,12}[-_][A-Z0-9]{3,16}\b",
            r"\b[A-Z]{1,8}\d{3,8}[A-Z0-9]{0,8}\b",
            r"\b\d[A-Z0-9]{5,12}\b",
        ]

        excluded = [
            r"^i[3579][- ]?\d", r"^core$", r"^intel$", r"^ryzen$",
            r"^dc[- ]?in$", r"^usb", r"^hdmi$", r"^rj45$",
            r"haut", r"parleur", r"speaker", r"bluetooth", r"wifi",
            r"windows", r"full", r"ecran", r"ips",
        ]

        found: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                ref = str(match).strip()
                ref_lower = ref.lower()
                if len(ref) < 4:
                    continue
                if any(re.search(p, ref_lower) for p in excluded):
                    continue
                if ref_lower not in [x.lower() for x in found]:
                    found.append(ref)

        found.sort(key=len, reverse=True)
        return found[:3]

    def _extract_references_from_product(self, product: dict) -> list[str]:
        """
        Retourne plusieurs vraies références au lieu de garder un SKU composé.
        Exemple : "MRXQ3FN/A - APPLE176" doit donner :
        ["MRXQ3FN/A", "APPLE176"]
        Sinon le matching cherche la chaîne complète et rate les concurrents.
        """
        raw_values = [
            product.get("sku") or "",
            product.get("reference") or "",
            product.get("ref") or "",
        ]

        nom = product.get("nom") or product.get("name") or ""
        description = product.get("description") or ""

        refs: list[str] = []

        def add_ref(value: str):
            value = " ".join(str(value or "").split()).strip(" -_|,;()[]")
            if not value:
                return
            low = value.lower()
            if re.match(r"^pc\d+$", low):
                return
            if len(value) < 4 or len(value) > 40:
                return
            if low not in [x.lower() for x in refs]:
                refs.append(value)

        for raw in raw_values:
            raw = str(raw or "").strip()
            if not raw:
                continue

            # 1) garder la référence Apple avec slash
            for m in re.findall(r"\b[A-Z0-9]{4,12}/[A-Z0-9]{1,6}\b", raw, flags=re.IGNORECASE):
                add_ref(m)

            # 2) séparer les SKU composés : MRXQ3FN/A - APPLE176
            for part in re.split(r"\s*(?:-|–|—|\||,|;)\s*", raw):
                add_ref(part)

            # 3) codes alphanumériques classiques : APPLE176, X1502VA...
            for m in re.findall(r"\b[A-Z]{2,12}\d{2,8}[A-Z0-9]*\b", raw, flags=re.IGNORECASE):
                add_ref(m)

        if not refs:
            refs.extend(self._extract_reference_from_text_fallback(f"{nom} {description}"))

        return refs[:6]

    def _dedupe_queries(self, queries: list[str], max_len: int = 20) -> list[str]:
        """
        Déduplique les requêtes en gardant l'ordre.
        """
        final: list[str] = []
        seen: set[str] = set()

        for query in queries:
            query = " ".join(str(query or "").split()).strip()
            if len(query) < 2:
                continue

            # éviter les requêtes énormes qui ralentissent les sites
            parts = query.split()
            if len(parts) > 9:
                query = " ".join(parts[:9])

            key = self._quick_normalize(query)
            if key in seen:
                continue

            seen.add(key)
            final.append(query)

            if len(final) >= max_len:
                break

        return final

    def _build_product_search_query_stages(self, product: dict) -> dict[str, list[str]]:
        """
        Construit les requêtes par niveau de fallback :

        1) reference       : SKU / référence exacte / variantes compactes
        2) name            : nom complet + nom simplifié + modèles spécifiques
        3) category_brand  : catégorie + marque + mots forts

        La recherche utilise ces niveaux dans l'ordre. On ne passe au niveau suivant
        que si aucun candidat fiable n'a été trouvé au niveau précédent.
        """
        sku = (product.get("sku") or "").strip()
        marque = (product.get("marque") or product.get("brand") or "").strip()
        nom = (product.get("nom") or product.get("name") or "").strip()
        description = (product.get("description") or "").strip()
        categorie = (product.get("categorie") or product.get("category") or "").strip()

        reference_queries: list[str] = []
        name_queries: list[str] = []
        category_brand_queries: list[str] = []

        sku_norm = self._quick_normalize(sku)
        has_real_sku = bool(sku_norm and not re.match(r"^pc\d+$", sku_norm))

        # =========================================================
        # Niveau 1 : référence / SKU
        # =========================================================
        references = self._extract_references_from_product(product)
        for ref in references:
            ref = " ".join(str(ref or "").split()).strip()
            if not ref:
                continue
            if re.match(r"^pc\d+$", ref.lower()):
                continue

            reference_queries.append(ref)

            for variant in self._reference_variants(ref):
                reference_queries.append(variant)
                if marque:
                    reference_queries.append(f"{marque} {variant}")

        if has_real_sku and marque:
            reference_queries.append(f"{marque} {sku}")

        # =========================================================
        # Niveau 2 : nom produit exact / nom simplifié
        # =========================================================
        if nom:
            name_queries.append(nom)

            nom_norm = self._quick_normalize(nom)
            marque_norm = self._quick_normalize(marque)
            compact_nom = nom_norm.replace("-", "").replace(" ", "")

            stop_words = {
                "avec", "pour", "sans", "de", "du", "des", "la", "le", "les",
                "noir", "black", "blanc", "white", "gris", "silver", "argent",
                "bleu", "rouge", "vert", "rose", "violet", "orange",
                "azerty", "qwerty",
            }

            useful_words = [
                w for w in nom_norm.split()
                if len(w) >= 2
                and w not in stop_words
                and w != marque_norm
            ]

            if useful_words:
                name_queries.append(" ".join(useful_words[:7]))

            if marque and useful_words:
                name_queries.append(f"{marque} {' '.join(useful_words[:6])}")

            # Cas smartphones : Samsung Galaxy A17 4G 6/128, 12/128, 128Go, Gris...
            # Important : les concurrents n'utilisent pas toujours le SKU Mytek.
            phone_model_match = re.search(
                r"\b(galaxy\s+)?([a-z]{1,4}\s?\d{1,3}[a-z]{0,3})\b",
                nom_norm,
                flags=re.IGNORECASE,
            )
            if phone_model_match and any(x in nom_norm for x in ["smartphone", "galaxy", "samsung", "iphone", "redmi","vivo", "honor", "oppo", "xiaomi", "tecno", "infinix"]):
                model = phone_model_match.group(2).replace(" ", "").upper()
                brand = marque or ("Samsung" if "samsung" in nom_norm or "galaxy" in nom_norm else "")

                storage_matches = re.findall(r"\b(64|128|256|512)\s*(gb|go)\b", nom_norm)
                ram_matches = re.findall(r"\b(2|3|4|6|8|12|16)\s*(gb|go)\b", nom_norm)
                storages = [m[0] for m in storage_matches]
                rams = [m[0] for m in ram_matches if m[0] not in storages]

                network = "4G" if "4g" in nom_norm else ("5G" if "5g" in nom_norm else "")
                colors = []
                for color in ["gris", "noir", "bleu", "blanc", "silver", "black", "blue", "white", "gold", "rose"]:
                    if color in nom_norm:
                        colors.append(color)

                bases = []

                # Génération des requêtes smartphone sans forcer "Galaxy" pour toutes les marques.
                # Exemple : VIVO Y29 doit générer "VIVO Y29", pas "VIVO Galaxy Y29".
                if brand:
                    bases.append(f"{brand} {model}")

                if "galaxy" in nom_norm or "samsung" in nom_norm:
                    if brand:
                        bases.append(f"{brand} Galaxy {model}")
                    bases.append(f"Galaxy {model}")

                bases.append(model)

                for b in bases:
                    name_queries.append(b)
                    if network:
                        name_queries.append(f"{b} {network}")
                    for storage in storages[:2]:
                        name_queries.append(f"{b} {storage}Go")
                        name_queries.append(f"{b} {storage}GB")
                        if network:
                            name_queries.append(f"{b} {network} {storage}Go")
                        for color in colors[:1]:
                            name_queries.append(f"{b} {storage}Go {color}")
                    for ram in rams[:2]:
                        for storage in storages[:2]:
                            name_queries.append(f"{b} {ram}Go {storage}Go")
                            name_queries.append(f"{b} {ram}/{storage}")

            # Cas spécial T800 / Ultra / Ultra 2.
            # Beaucoup de sites n'indexent pas le SKU T800-ULT2-OR mais indexent le nom.
            if "t800" in compact_nom:
                has_ultra = "ultra" in nom_norm or "ult" in nom_norm or "ult2" in compact_nom
                has_two = "ultra 2" in nom_norm or "ult2" in compact_nom or "ultra2" in compact_nom or " 2 " in f" {nom_norm} "
                has_orange = "orange" in nom_norm or compact_nom.endswith("or")

                if has_ultra and has_two:
                    base_t800 = [
                        "T800 Ultra 2",
                        "Montre T800 Ultra 2",
                        "Montre Connectée T800 Ultra 2",
                    ]
                    if has_orange:
                        base_t800.extend([
                            "T800 Ultra 2 Orange",
                            "Montre T800 Ultra 2 Orange",
                            "Montre Connectée T800 Ultra 2 Orange",
                        ])
                    name_queries.extend(base_t800)
                elif has_ultra:
                    name_queries.extend([
                        "T800 Ultra",
                        "Montre T800 Ultra",
                        "Montre Connectée T800 Ultra",
                    ])

            # Cas spécial Redmi Buds : ne pas dépendre seulement du SKU BHR...
            if "redmi" in nom_norm and "buds" in nom_norm:
                tokens = []
                for token in ["redmi", "buds", "8", "lite", "active", "play", "pro"]:
                    if token in nom_norm.split() or token in compact_nom:
                        tokens.append(token)
                if tokens:
                    base = " ".join(tokens)
                    name_queries.extend([
                        base,
                        f"Xiaomi {base}",
                        f"Écouteurs Xiaomi {base}",
                    ])

            # Cas spécial Apple MacBook : certains sites indexent surtout le modèle commercial,
            # pas la référence interne complète "MRXQ3FN/A - APPLE176".
            if "apple" in nom_norm or self._quick_normalize(marque) == "apple":
                refs = self._extract_references_from_product(product)
                for ref in refs:
                    if "/" in ref:
                        name_queries.append(ref)
                        name_queries.append(ref.replace("/", ""))
                        name_queries.append(ref.replace("/", "-"))
                        name_queries.append(f"Apple {ref}")
                if "macbook" in nom_norm or "m3" in nom_norm:
                    apple_base = "Apple MacBook Air M3"
                    name_queries.extend([
                        apple_base,
                        "MacBook Air M3 13",
                        "MacBook Air M3 13 8Go 256Go",
                        "MacBook Air M3 13 8GB 256GB",
                        "Apple MacBook Air 13 pouces M3",
                    ])
                    if "silver" in nom_norm or "argent" in nom_norm:
                        name_queries.extend([
                            "MacBook Air M3 13 Silver",
                            "MacBook Air M3 13 Argent",
                            "Apple MacBook Air M3 8Go 256Go Silver",
                            "Apple MacBook Air M3 8Go 256Go Argent",
                        ])

            # Cas générique : marque + 3/6 mots distinctifs du nom
            if useful_words:
                name_queries.append(" ".join(useful_words[:4]))
                if marque:
                    name_queries.append(f"{marque} {' '.join(useful_words[:4])}")

        # =========================================================
        # Niveau 3 : catégorie + marque + mots importants
        # Ce niveau sert à TROUVER plus de candidats, pas à tout accepter.
        # Le filtre strict garde ensuite seulement le même modèle.
        # =========================================================
        base_text = self._quick_normalize(f"{nom} {description}")
        generic_stop_words = {
            "avec", "pour", "sans", "de", "du", "des", "la", "le", "les",
            "noir", "black", "blanc", "white", "gris", "silver", "argent",
            "bleu", "rouge", "vert", "rose", "violet", "orange",
            "connectee", "connecte", "smart", "watch", "montre",
            "pc", "ordinateur", "portable",
        }
        important_words = [
            w for w in base_text.split()
            if len(w) >= 2 and w not in generic_stop_words
        ]

        if categorie and marque:
            category_brand_queries.append(f"{categorie} {marque}")
            if important_words:
                category_brand_queries.append(f"{categorie} {marque} {' '.join(important_words[:4])}")
        elif marque and important_words:
            category_brand_queries.append(f"{marque} {' '.join(important_words[:4])}")
        elif categorie and important_words:
            category_brand_queries.append(f"{categorie} {' '.join(important_words[:4])}")

        return {
            "reference": self._dedupe_queries(reference_queries, max_len=12),
            "name": self._dedupe_queries(name_queries, max_len=18),
            "category_brand": self._dedupe_queries(category_brand_queries, max_len=8),
        }

    def _build_product_search_queries(self, product: dict) -> list[str]:
        """
        Version plate pour le debug et la réponse API.
        La recherche réelle utilise _build_product_search_query_stages().
        """
        stages = self._build_product_search_query_stages(product)
        return self._dedupe_queries(
            stages["reference"] + stages["name"] + stages["category_brand"],
            max_len=24,
        )

    def _item_contains_reference(
        self,
        item: ProductCompetitorPayload,
        references: list[str],
    ) -> bool:
        """
        Garde le produit si la référence existe dans :
        nomProduit / descriptionConcurrent / skuConcurrent / urlProduit.
        """
        if not references:
            return True

        item_text = self._normalize_reference_text(
            " ".join([
                item.nomProduit or "",
                item.descriptionConcurrent or "",
                item.skuConcurrent or "",
                item.urlProduit or "",
            ])
        )
        item_compact = item_text.replace("-", "").replace(" ", "")

        for ref in references:
            for variant in self._reference_variants(ref):
                variant_compact = variant.replace("-", "").replace(" ", "")
                if variant and variant in item_text:
                    return True
                if variant_compact and variant_compact in item_compact:
                    return True

        return False

    def _product_detail_contains_reference(
        self,
        item: ProductCompetitorPayload,
        references: list[str],
    ) -> bool:
        if not references or not item.urlProduit:
            return False

        try:
            html = self._get_html(item.urlProduit)
            soup = BeautifulSoup(html, "lxml")
            detail_text = soup.get_text(" ", strip=True)
            normalized_text = self._normalize_reference_text(detail_text)
            compact_text = normalized_text.replace("-", "").replace(" ", "")

            for reference in references:
                for variant in self._reference_variants(reference):
                    variant_compact = variant.replace("-", "").replace(" ", "")
                    if variant and variant in normalized_text:
                        item.descriptionConcurrent = detail_text[:3000]
                        return True
                    if variant_compact and variant_compact in compact_text:
                        item.descriptionConcurrent = detail_text[:3000]
                        return True
            return False
        except Exception:
            return False


    # =========================================================
    # PATCH FIABILITE MATCHING - anti faux positifs
    # =========================================================
    def _detect_product_family_strict(self, text: str | None) -> str | None:
        """
        Détecte la famille métier du produit.
        Objectif : empêcher qu'un smartphone soit matché avec une carte mère,
        un ventilateur, une protection écran, etc.
        """
        t = self._quick_normalize(text or "")
        if not t:
            return None

        # Les accessoires téléphone doivent être testés AVANT smartphone,
        # sinon "protection Samsung Galaxy Note10" serait vu comme smartphone.
        if any(x in t for x in [
            "protection ecran", "protection d ecran", "verre trempe",
            "screenforce", "invisiglass", "coque", "etui", "film",
            "case iphone", "chargeur iphone", "cable iphone",
        ]):
            return "accessoire_telephone"

        if any(x in t for x in [
            "carte mere", "motherboard", "lga", "socket",
            "z690", "z790", "b550", "b650", "b760", "x670",
            "ddr4", "ddr5",
        ]):
            return "carte_mere"

        if any(x in t for x in [
            "ventilateur", "refroidisseur", "cooler", "watercooling",
            "ventilo", "hyper 212", "processeur cooler",
        ]):
            return "ventilation"

        if any(x in t for x in [
            "smartphone", "telephone", "mobile", "iphone", "galaxy",
            "redmi", "xiaomi", "oppo", "honor","vivo", "realme",
            "infinix", "tecno", "itel", "samsung a", "samsung s",
        ]):
            return "smartphone"

        if any(x in t for x in ["pc portable", "ordinateur portable", "laptop", "notebook"]):
            return "pc_portable"

        if any(x in t for x in ["ecran", "moniteur", "monitor"]):
            return "ecran"

        return None

    def _extract_phone_signature(self, text: str | None) -> dict:
        """
        Signature smartphone robuste.
        Pour Samsung Galaxy A17 : modèle = a17, stockage = 128, réseau = 4g.
        On n'impose pas toujours la RAM, car les sites peuvent écrire 6Go, 12Go,
        ou inverser RAM/stockage.
        """
        t = self._quick_normalize(text or "")
        compact = t.replace("-", " ")
        sig = {
            "brand": None,
            "model": None,
            "storage": None,
            "network": None,
        }

        brands = [
            "samsung", "apple", "xiaomi", "redmi", "oppo", "vivo", "honor",
            "realme", "infinix", "tecno", "itel", "huawei",
        ]
        for b in brands:
            if b in compact:
                sig["brand"] = "xiaomi" if b == "redmi" else b
                break

        model_patterns = [
            # Samsung Galaxy : A17, S24, A56...
            r"\bgalaxy\s+([asmz]\s?\d{1,3}[a-z]{0,3})\b",
            r"\bsamsung\s+galaxy\s+([asmz]\s?\d{1,3}[a-z]{0,3})\b",
            r"\bsamsung\s+([asmz]\s?\d{1,3}[a-z]{0,3})\b",

            # iPhone
            r"\biphone\s+(\d{1,2}(?:\s?pro|\s?plus|\s?promax|\s?pro max)?)\b",

            # Redmi / Xiaomi
            r"\bredmi\s+([a-z]*\s?\d{1,3}[a-z]{0,3})\b",
            r"\bxiaomi\s+([a-z]*\s?\d{1,3}[a-z]{0,3})\b",

            # OPPO Reno / A series
            r"\boppo\s+reno\s+(\d{1,2}[a-z]{0,2})\b",
            r"\breno\s+(\d{1,2}[a-z]{0,2})\b",
            r"\boppo\s+([a-z]\s?\d{1,3}[a-z]{0,3})\b",

            # VIVO : VIVO Y29, VIVO V50, VIVO Y21D...
            # On exige le mot vivo pour éviter de confondre des codes génériques avec un modèle.
            r"\bvivo\s+([vy]\s?\d{1,3}[a-z]{0,3})\b",

            # Realme / Honor / Infinix / Tecno
            r"\brealme\s+([a-z]\s?\d{1,3}[a-z]{0,3})\b",
            r"\bhonor\s+([a-z]\s?\d{1,3}[a-z]{0,3})\b",
            r"\binfinix\s+([a-z]*\s?\d{1,3}[a-z]{0,3})\b",
            r"\btecno\s+([a-z]*\s?\d{1,3}[a-z]{0,3})\b",

            # Samsung générique A17, S24... uniquement en dernier
            r"\b([asmz]\s?\d{1,3}[a-z]{0,3})\b",
        ]
        for pattern in model_patterns:
            m = re.search(pattern, compact, flags=re.IGNORECASE)
            if m:
                model = re.sub(r"\s+", "", m.group(1).lower())
                # éviter de prendre des specs comme ddr4 / 4g comme modèle
                if model not in {"4g", "5g", "12g", "128g", "256g", "512g"}:
                    sig["model"] = model
                    break

        storage_values = []
        for m in re.findall(r"\b(64|128|256|512)\s*(?:gb|go)\b", compact):
            storage_values.append(m)
        if storage_values:
            sig["storage"] = storage_values[-1]

        if re.search(r"\b4\s*g\b|\b4g\b", compact):
            sig["network"] = "4g"
        elif re.search(r"\b5\s*g\b|\b5g\b", compact):
            sig["network"] = "5g"

        return sig

    def _is_candidate_compatible_with_product(self, product: dict, item: ProductCompetitorPayload) -> bool:
        """
        Garde seulement les candidats métier compatibles avec le produit source.
        C'est le garde-fou principal contre :
        - smartphone A17 -> carte mère Z690
        - smartphone A17 -> ventilateur Cooler Master
        - smartphone A17 -> protection Note10
        """
        product_text = " ".join([
            str(product.get("nom") or product.get("name") or ""),
            str(product.get("description") or ""),
            str(product.get("sku") or ""),
            str(product.get("marque") or product.get("brand") or ""),
            str(product.get("categorie") or product.get("category") or ""),
        ])
        item_text = " ".join([
            item.nomProduit or "",
            item.descriptionConcurrent or "",
            item.skuConcurrent or "",
            item.urlProduit or "",
        ])

        product_family = self._detect_product_family_strict(product_text)
        item_family = self._detect_product_family_strict(item_text)

        if product_family and item_family and product_family != item_family:
            return False

        if product_family == "smartphone":
            p_sig = self._extract_phone_signature(product_text)
            i_sig = self._extract_phone_signature(item_text)

            # Un accessoire téléphone n'est jamais le smartphone lui-même.
            if item_family == "accessoire_telephone":
                return False

            # Modèle obligatoire : A17 doit matcher A17.
            if p_sig.get("model"):
                if not i_sig.get("model"):
                    return False
                if p_sig["model"] != i_sig["model"]:
                    return False

            # Si on connaît la marque source et que le candidat expose une marque différente : rejet.
            if p_sig.get("brand") and i_sig.get("brand") and p_sig["brand"] != i_sig["brand"]:
                return False

            # Stockage : si les deux l'indiquent, il doit être cohérent.
            if p_sig.get("storage") and i_sig.get("storage") and p_sig["storage"] != i_sig["storage"]:
                return False

            # Réseau : si les deux l'indiquent, il doit être cohérent.
            if p_sig.get("network") and i_sig.get("network") and p_sig["network"] != i_sig["network"]:
                return False

        return True

    def _is_bad_candidate_for_product(
        self,
        product: dict,
        item: ProductCompetitorPayload,
    ) -> bool:
        """
        Rejette les faux candidats évidents avant l'envoi au stock_service.
        """

        product_text = self._quick_normalize(
            " ".join([
                str(product.get("nom") or product.get("name") or ""),
                str(product.get("marque") or product.get("brand") or ""),
                str(product.get("sku") or ""),
                str(product.get("description") or ""),
            ])
        )

        item_text = self._quick_normalize(
            " ".join([
                item.nomProduit or "",
                item.skuConcurrent or "",
                item.urlProduit or "",
                item.descriptionConcurrent or "",
            ])
        )

        if not item_text:
            return True

        if not self._is_candidate_compatible_with_product(product, item):
            return True

        references = self._extract_references_from_product(product)
        compact_item_text = item_text.replace("-", "").replace(" ", "")

        for ref in references:
            compact_ref = self._quick_normalize(ref).replace("-", "").replace(" ", "")
            if compact_ref and compact_ref in compact_item_text:
                return False

        if "mibro" in product_text:
            if "mibro" not in item_text and "xpaw021" not in compact_item_text:
                return True
            if "c4" in product_text and "c4" not in item_text and "xpaw021" not in compact_item_text:
                return True

        bad_words = [
            "pack back to school",
            "pc portable",
            "ordinateur portable",
            "support ecran",
            "support écran",
            "chargeur",
            "clavier",
            "souris",
            "tapis gamer",
            "ecran msi",
            "écran msi",
        ]

        for bad_word in bad_words:
            if bad_word in item_text:
                if "mibro" not in item_text and "xpaw021" not in compact_item_text:
                    return True

        bad_url_parts = [
            "/content/",
            "/brand/",
            "/marque/",
            "/page/",
            "/contact",
            "/a-propos",
            "/about",
        ]
        url = (item.urlProduit or "").lower()
        return any(part in url for part in bad_url_parts)


    def _clean_token_for_matching(self, value: str | None) -> str:
        """Normalisation stable pour comparer les modèles produits."""
        text = self._quick_normalize(value or "")
        text = text.replace("/", " ").replace("_", "-")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _product_matching_tokens(self, product: dict) -> set[str]:
        """
        Extrait les tokens qui définissent le MODELE, pas seulement la famille.
        Exemple : "Xiaomi Redmi Buds 8 Lite" => {redmi, buds, 8, lite}
        Cela évite d'accepter Buds 6 Play ou Buds 8 Active.
        """
        name = self._clean_token_for_matching(product.get("nom") or product.get("name") or "")
        description = self._clean_token_for_matching(product.get("description") or "")
        brand = self._clean_token_for_matching(product.get("marque") or product.get("brand") or "")
        sku = self._clean_token_for_matching(product.get("sku") or "")

        source_text_for_family = f"{name} {description} {brand} {sku}".strip()
        if self._detect_product_family_strict(source_text_for_family) == "smartphone":
            sig = self._extract_phone_signature(source_text_for_family)
            phone_tokens: set[str] = set()

            if sig.get("model"):
                phone_tokens.add(sig["model"])

            if "galaxy" in source_text_for_family:
                phone_tokens.add("galaxy")

            if sig.get("storage"):
                phone_tokens.add(f"{sig['storage']}gb")

            # IMPORTANT :
            # Pour les smartphones, on ne met PAS le SKU interne dans les tokens obligatoires.
            # Les concurrents utilisent souvent des références différentes.
            # Exemple :
            # - produit interne : VIVO Y29 16Go 256Go Blanc
            # - Mytek : VIVO-Y29-8/256-EWHITE
            # Si on impose le SKU, un vrai produit peut être rejeté avant l'enregistrement.
            return {t for t in phone_tokens if t}

        text = f"{name} {description}".strip()
        words = text.split()

        generic_words = {
            # mots de famille trop larges
            "ecouteur", "ecouteurs", "casque", "audio", "sans", "fil", "wireless",
            "bluetooth", "true", "stereo", "tws", "intra", "auriculaire",
            "montre", "connectee", "connecte", "smartwatch", "smart", "watch",
            "pc", "ordinateur", "portable", "laptop", "notebook", "bureau",
            "ecran", "moniteur", "monitor", "imprimante", "printer",
            "chargeur", "cable", "câble", "adaptateur", "souris", "clavier",
            "smartphone", "telephone", "tablette", "camera", "webcam",
            # couleurs / marketing
            "noir", "black", "blanc", "white", "gris", "silver", "argent",
            "bleu", "blue", "rouge", "red", "vert", "green", "rose", "pink",
            "violet", "purple", "gold", "jaune", "yellow",
            "avec", "pour", "et", "de", "des", "du", "la", "le", "les", "un", "une",
            "promo", "pack", "new", "original", "officiel",
        }

        brand_words = set(brand.split()) if brand else set()
        tokens: set[str] = set()

        known_model_words = {
            "redmi", "buds", "lite", "active", "play", "pro", "plus", "max", "ultra",
            "mibro", "amazfit", "haylou", "kieslect", "galaxy", "iphone",
            "vivobook", "zenbook", "ideapad", "thinkpad", "probook", "elitebook",
            "victus", "pavilion", "inspiron", "latitude", "tuf", "rog", "nitro",
            "predator", "aspire", "macbook",
        }

        # FIX : les mots de la marque ne doivent PAS être retirés des tokens
        # si la marque ressemble à un nom de modèle (contient des chiffres ou est courte).
        # Ex : marque="T800 Ultra" → les mots 't800' et 'ultra' sont des identifiants
        # du modèle et doivent rester dans les tokens.
        # On retire uniquement les grandes marques connues (XIAOMI, SAMSUNG...) qui
        # n'apportent pas de distinction de modèle.
        known_generic_brands = {
            "xiaomi", "samsung", "apple", "huawei", "honor", "oppo", "vivo", "realme",
            "infinix", "tecno", "itel", "lenovo", "hp", "dell", "asus", "acer",
            "msi", "lg", "sony", "philips", "toshiba", "logitech", "tp-link",
            "canon", "epson", "brother", "xerox", "kyocera",
        }
        # Ne retirer les brand_words que si la marque est une marque générique connue
        brand_is_generic = brand and all(w in known_generic_brands for w in brand.split())
        effective_brand_words = brand_words if brand_is_generic else set()

        for word in words:
            w = word.strip("- ")
            if not w or len(w) < 2:
                continue
            if w in generic_words or w in effective_brand_words:
                continue

            # garder chiffres courts utiles : Buds 8, iPhone 15, S4, etc.
            if re.fullmatch(r"\d{1,4}", w):
                tokens.add(w)
                continue

            # garder codes modèles : x1502va, bhr08olgl, g1ir, 15-fa1006nk, etc.
            if re.search(r"[a-z]", w) and re.search(r"\d", w):
                tokens.add(w)
                tokens.add(w.replace("-", ""))
                continue

            # garder les mots modèle connus ou distinctifs
            if w in known_model_words or len(w) >= 4:
                tokens.add(w)

        # Si le SKU est réel, on l'ajoute comme token fort, mais on ne l'impose pas toujours
        # car certains concurrents affichent une référence interne différente.
        if sku and not re.match(r"^pc\d+$", sku):
            tokens.add(sku)
            tokens.add(sku.replace("-", ""))

        return {t for t in tokens if t}

    def _item_matching_text(self, item: ProductCompetitorPayload) -> tuple[str, str]:
        """Retourne texte normalisé + version compacte pour un produit concurrent."""
        text = self._clean_token_for_matching(" ".join([
            item.nomProduit or "",
            item.descriptionConcurrent or "",
            item.skuConcurrent or "",
            item.urlProduit or "",
        ]))
        compact = text.replace("-", "").replace(" ", "")
        return text, compact

    def _has_exact_reference_match(
        self,
        product: dict,
        item: ProductCompetitorPayload,
        references: list[str] | None = None,
    ) -> bool:
        """True uniquement si une vraie référence produit est visible dans le candidat."""
        refs = references if references is not None else self._extract_references_from_product(product)
        if not refs:
            return False

        item_text, item_compact = self._item_matching_text(item)
        for ref in refs:
            if not ref or re.match(r"^pc\d+$", str(ref).lower().strip()):
                continue
            for variant in self._reference_variants(ref):
                variant_norm = self._clean_token_for_matching(variant)
                variant_compact = variant_norm.replace("-", "").replace(" ", "")
                if variant_norm and variant_norm in item_text:
                    return True
                if variant_compact and variant_compact in item_compact:
                    return True
        return False

    def _is_same_model_candidate(
        self,
        product: dict,
        item: ProductCompetitorPayload,
        references: list[str] | None = None,
    ) -> bool:
        """
        Contrôle générique du même modèle.
        Accepte : même référence exacte, ou même tokens modèle.
        Refuse : produits proches mais différents (Buds 8 Active, Buds 6 Play, Watch + Buds...).
        """
        refs = references if references is not None else self._extract_references_from_product(product)

        if not self._is_candidate_compatible_with_product(product, item):
            return False

        if self._has_exact_reference_match(product, item, refs):
            return True

        item_text, item_compact = self._item_matching_text(item)
        model_tokens = self._product_matching_tokens(product)

        # Retirer les tokens SKU exacts de l'obligation si le concurrent utilise une ref interne.
        for ref in refs or []:
            ref_norm = self._clean_token_for_matching(ref)
            if ref_norm:
                model_tokens.discard(ref_norm)
                model_tokens.discard(ref_norm.replace("-", ""))

        if not model_tokens:
            return True

        present = set()
        missing = set()
        for token in model_tokens:
            token_compact = token.replace("-", "").replace(" ", "")
            found = token in item_text or (token_compact and token_compact in item_compact)
            if found:
                present.add(token)
            else:
                missing.add(token)

        # Cas très strict : si le produit a une signature courte mais très spécifique,
        # il faut tous les tokens. Ex : redmi + buds + 8 + lite.
        strict_tokens = {"redmi", "buds", "lite", "active", "play", "pro", "plus", "max", "ultra"}
        product_specific = model_tokens.intersection(strict_tokens) | {t for t in model_tokens if re.fullmatch(r"\d{1,3}", t)}

        if len(product_specific) >= 3:
            return product_specific.issubset(present)

        # Match parfait si tous les tokens sont présents
        if len(model_tokens) >= 2 and len(present) == len(model_tokens):
            return True

        # Pour les autres produits : on exige au moins 70% des tokens modèle,
        # et toujours les codes alphanumériques forts s'ils existent.
        strong_codes = {
            t for t in model_tokens
            if re.search(r"[a-z]", t) and re.search(r"\d", t) and len(t) >= 4
        }
        if strong_codes and not strong_codes.intersection(present):
            return False

        required_ratio = 0.70 if len(model_tokens) >= 4 else 1.0
        return (len(present) / max(1, len(model_tokens))) >= required_ratio


    def _filter_reference_candidates(
        self,
        product: dict,
        items: list[ProductCompetitorPayload],
        max_candidates: int = 15,
    ) -> list[ProductCompetitorPayload]:
        """
        Filtrage final avant envoi au stock_service.
        Cette version envoie seulement les vrais candidats du même modèle.
        """
        references = self._extract_references_from_product(product)

        exact_items: list[ProductCompetitorPayload] = []
        scored_items: list[tuple[int, ProductCompetitorPayload]] = []
        seen_urls: set[str] = set()

        detail_checks_done = 0
        max_detail_checks = 2

        for item in items:
            url_key = (item.urlProduit or "").strip().lower()
            if url_key and url_key in seen_urls:
                continue
            if url_key:
                seen_urls.add(url_key)

            if self._is_bad_candidate_for_product(product, item):
                continue

            if self._has_exact_reference_match(product, item, references):
                exact_items.append(item)
                continue

            # Vérifier la fiche détail uniquement si le nom est déjà cohérent.
            score_before_detail = self._quick_candidate_score(product, item)
            if references and detail_checks_done < max_detail_checks and score_before_detail >= 65:
                detail_checks_done += 1
                if self._product_detail_contains_reference(item, references):
                    exact_items.append(item)
                    continue

            # Sans référence exacte, on accepte seulement le même modèle.
            if not self._is_same_model_candidate(product, item, references):
                continue

            score = self._quick_candidate_score(product, item)
            if score >= 75:
                scored_items.append((score, item))

        ranked: list[tuple[int, ProductCompetitorPayload]] = []

        for item in exact_items:
            ranked.append((100, item))

        ranked.extend(scored_items)
        ranked.sort(key=lambda x: x[0], reverse=True)

        final_items: list[ProductCompetitorPayload] = []
        final_seen: set[str] = set()

        for score, item in ranked:
            key = (item.urlProduit or item.nomProduit or "").strip().lower()
            if not key or key in final_seen:
                continue
            final_seen.add(key)
            final_items.append(item)

        return final_items[:max_candidates]

    def _discover_search_url_templates(self, competitor: CompetitorModel) -> list[str]:
        """
        Retourne les templates de recherche d'un concurrent.

        Priorité :
        1) templates enregistrés en base dans concurrents.url_recherche ;
        2) détection automatique live si l'ancien concurrent n'a pas encore url_recherche.

        Important : pour les nouveaux concurrents, la détection est faite pendant la discovery
        puis sauvegardée dans stock_service. Ici on ne refait la détection qu'en fallback.
        """
        saved_templates = getattr(competitor, "url_recherche", None) or []
        if isinstance(saved_templates, list):
            cleaned = []
            seen = set()
            for template in saved_templates:
                template = str(template or "").strip()
                if not template or "{query}" not in template:
                    continue
                if template in seen:
                    continue
                seen.add(template)
                cleaned.append(template)
            if cleaned:
                return cleaned[:8]

        site_url = (competitor.site_url or "").strip()
        if not site_url:
            return []

        cache_key = (competitor.site_host_normalized or site_url).lower().replace("www.", "")
        if not hasattr(self, "_search_template_cache"):
            self._search_template_cache = {}

        if cache_key in self._search_template_cache:
            return list(self._search_template_cache[cache_key])

        try:
            templates = discover_search_url_templates(site_url, session=self.session, limit=8)
        except Exception:
            templates = []

        self._search_template_cache[cache_key] = templates
        return templates

    def _build_search_urls_for_competitor(
        self,
        competitor: CompetitorModel,
        query: str,
    ) -> list[str]:
        """
        Construit les URLs finales à tester pour un produit spécifique.

        Exemple :
        template = https://www.mytek.tn/myteksearch/index/productsearch/?q={query}
        query    = OPPO-A6X-4/128-PURPLE
        résultat = https://www.mytek.tn/myteksearch/index/productsearch/?q=OPPO-A6X-4%2F128-PURPLE
        """
        raw_query = " ".join(str(query or "").split()).strip()
        if not raw_query:
            return []

        encoded_query = quote_plus(raw_query, safe="")

        urls: list[str] = []
        seen: set[str] = set()

        for template in self._discover_search_url_templates(competitor):
            template = str(template or "").strip()
            if not template or "{query}" not in template:
                continue

            url = template.replace("{query}", encoded_query)
            if url and url not in seen:
                urls.append(url)
                seen.add(url)

        return urls

    def _quick_normalize(self, value: str | None) -> str:
        if not value:
            return ""

        value = value.lower()
        value = value.replace("è", "e").replace("é", "e").replace("ê", "e")
        value = value.replace("à", "a").replace("ù", "u")
        # FIX : remplacer "go"/"to" uniquement quand ce sont des unités de stockage
        # (précédées d'un chiffre) pour ne pas corrompre des références comme "LOGO123" ou "CONGO".
        value = re.sub(r"(\d+)\s*go\b", r"\1gb", value)
        value = re.sub(r"(\d+)\s*to\b", r"\1tb", value)
        value = re.sub(r"[^a-z0-9\- ]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()

        return value


    def _extract_strong_terms_for_product(self, product: dict) -> set[str]:
        """
        Extrait les termes importants du produit.
        Sert à pré-filtrer les résultats scrapés avant de les envoyer au stock_service.
        """
        text = self._quick_normalize(
            " ".join([
                product.get("nom") or "",
                product.get("description") or "",
                product.get("sku") or "",
                product.get("marque") or "",
            ])
        )

        terms = set()

        sku = self._quick_normalize(product.get("sku"))
        marque = self._quick_normalize(product.get("marque"))

        # Ne pas utiliser les SKU internes type pc25895
        if sku and not re.match(r"^pc\d+$", sku):
            terms.add(sku)

        if marque:
            terms.add(marque)

        patterns = [
            r"\b\d{2}-[a-z0-9]{4,12}\b",          # 15-fa1006nk
            r"\b[a-z]{1,4}\d{3,6}[a-z]{0,4}\b",   # x1502va, fa1006nk
            r"\brtx\s*\d{3,4}\b",
            r"\bgtx\s*\d{3,4}\b",
            r"\bi3\b|\bi5\b|\bi7\b|\bi9\b",
            r"\bryzen\s*[3579]\b",
            r"\b(4|8|16|24|32|64)\s*gb\b",
            r"\b(128|256|512)\s*gb\b",
            r"\b(1|2|4)\s*tb\b",
            r"\bvivobook\b|\bvictus\b|\btuf\b|\brog\b|\bnitro\b|\bideapad\b|\bthinkpad\b|\bpavilion\b|\binspiron\b",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text):
                if isinstance(match, tuple):
                    term = " ".join([x for x in match if x]).strip()
                else:
                    term = match.strip()

                if term:
                    terms.add(term)

        return terms



    def _quick_candidate_score(
        self,
        product: dict,
        item: ProductCompetitorPayload,
    ) -> int:
        """
        Score strict et générique avant matching.
        - référence exacte => 100
        - même modèle obligatoire
        - marque seule / famille seule ne suffit jamais
        """
        from difflib import SequenceMatcher

        references = self._extract_references_from_product(product)
        product_name = self._quick_normalize(product.get("nom") or product.get("name") or "")
        product_brand = self._quick_normalize(product.get("marque") or product.get("brand") or "")
        item_name = self._quick_normalize(item.nomProduit or "")
        item_text, _ = self._item_matching_text(item)

        if not item_text:
            return 0

        if self._has_exact_reference_match(product, item, references):
            return 100

        # Marque obligatoire si connue et non générique.
        if product_brand and len(product_brand) >= 3 and product_brand not in item_text:
            return 0

        # Même modèle obligatoire.
        if not self._is_same_model_candidate(product, item, references):
            return 0

        # Score minimum garanti quand sameModel=True
        score = 35

        if product_brand and product_brand in item_text:
            score += 20

        if product_name and item_name:
            similarity = SequenceMatcher(None, product_name, item_name).ratio()
            if similarity >= 0.88:
                score += 55
            elif similarity >= 0.75:
                score += 42
            elif similarity >= 0.62:
                score += 25

        model_tokens = self._product_matching_tokens(product)
        matched_model_tokens = 0
        for token in model_tokens:
            token_compact = token.replace("-", "").replace(" ", "")
            if token in item_text or (token_compact and token_compact in item_text.replace("-", "").replace(" ", "")):
                matched_model_tokens += 1
                if re.search(r"\d", token):
                    score += 16
                elif token in {"redmi", "buds", "lite", "active", "play", "pro", "plus", "max", "ultra"}:
                    score += 14
                else:
                    score += 8

        if model_tokens:
            score += int((matched_model_tokens / max(1, len(model_tokens))) * 20)

        return min(score, 100)

    def _filter_best_candidates_before_matching(
        self,
        product: dict,
        items: list[ProductCompetitorPayload],
        max_candidates: int = 15,
    ) -> list[ProductCompetitorPayload]:
        """
        Garde les meilleurs candidats avant envoi au stock_service.
        Très important pour éviter d'envoyer 200 ou 300 produits.
        """
        scored = []

        for item in items:
            score = self._quick_candidate_score(product, item)

            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [item for score, item in scored[:max_candidates]]


    def _search_one_competitor(
        self,
        competitor: "CompetitorModel",
        product: dict,
        queries: list[str],
        references: list[str],
        max_queries: int,
        max_search_urls: int,
        detail_limit: int,
        max_candidates: int,
        per_competitor_budget: float,
        debug: bool,
    ) -> dict:
        """
        Recherche ciblée sur UN concurrent avec fallback contrôlé :
        1) recherche par référence
        2) si aucun candidat fiable : recherche par nom
        3) si encore rien : recherche catégorie + marque

        Le fallback élargit seulement les requêtes. Le filtrage final reste strict :
        on n'envoie au stock_service que les candidats du même modèle.
        """
        competitor_items: list[ProductCompetitorPayload] = []
        competitor_errors: list[str] = []
        pages_tested = 0
        seen_product_urls: set[str] = set()
        tested_search_urls: list[str] = []
        detail_urls_found: list[str] = []
        selected_catalogs: list = []
        stages_debug: dict[str, list[str]] = {}

        competitor_name = (competitor.nom or "").lower()
        competitor_site = (competitor.site_url or "").lower()
        # Budget uniforme pour tous les concurrents
        deadline = time.monotonic() + per_competitor_budget

        def _time_left() -> float:
            return deadline - time.monotonic()

        def _merge_items(items: list[ProductCompetitorPayload]) -> None:
            for item in items:
                item.produit_id = product.get("id") or product.get("product_id")
                if not item.urlProduit:
                    continue
                if not self._is_probable_product_url(item.urlProduit):
                    continue
                if item.urlProduit in seen_product_urls:
                    continue
                seen_product_urls.add(item.urlProduit)
                competitor_items.append(item)

        def _has_reliable_candidate(items: list[ProductCompetitorPayload], stage_name: str) -> bool:
            filtered = self._filter_reference_candidates(
                product=product,
                items=items,
                max_candidates=max_candidates,
            )
            if not filtered:
                return False

            # Référence exacte : un seul candidat suffit.
            if any(self._has_exact_reference_match(product, item, references) for item in filtered):
                return True

            # Nom : un candidat cohérent suffit (score>=35 garanti si sameModel=True).
            if stage_name == "name":
                return max(self._quick_candidate_score(product, item) for item in filtered) >= 35

            # Catégorie/marque : fallback large, on reste prudent.
            if stage_name == "category_brand":
                return max(self._quick_candidate_score(product, item) for item in filtered) >= 50

            return False

        try:
            query_stages = self._build_product_search_query_stages(product)
            stages_order = [
                ("reference", query_stages.get("reference", [])),
                ("name", query_stages.get("name", [])),
                ("category_brand", query_stages.get("category_brand", [])),
            ]
            stages_debug = {name: qs for name, qs in stages_order}

            for stage_name, stage_queries in stages_order:
                if _time_left() <= 1:
                    competitor_errors.append(f"Budget temps dépassé avant fallback {stage_name}.")
                    break

                # Si le niveau précédent a déjà trouvé un vrai candidat, on ne va pas plus large.
                if _has_reliable_candidate(competitor_items, stage_name):
                    break

                if not stage_queries:
                    continue

                if stage_name == "reference":
                    current_max_queries = min(max_queries, 6)
                    stage_timeout_cap = 8
                elif stage_name == "name":
                    current_max_queries = min(max_queries, 7)
                    stage_timeout_cap = 7
                else:
                    current_max_queries = min(max_queries, 4)
                    stage_timeout_cap = 6

                for query in stage_queries[:current_max_queries]:
                    if _time_left() <= 1:
                        competitor_errors.append(f"Budget temps dépassé pendant {stage_name}.")
                        break

                    search_urls = self._build_search_urls_for_competitor(
                        competitor=competitor,
                        query=query,
                    )

                    for search_url in search_urls[:max_search_urls]:
                        if _time_left() <= 1:
                            break

                        tested_search_urls.append(search_url)

                        try:
                            http_timeout = max(2, min(stage_timeout_cap, int(_time_left() - 1)))
                            response = self._get_response_raw(search_url, timeout_seconds=http_timeout)
                            content_type = response.headers.get("Content-Type", "").lower()
                            raw_text = response.text

                            json_items: list[ProductCompetitorPayload] = []
                            if "application/json" in content_type or raw_text.lstrip().startswith(("{", "[")):
                                json_items = self._extract_products_from_mytek_json(
                                    raw_json=raw_text,
                                    competitor=competitor,
                                    product=product,
                                )
                                if not json_items:
                                    json_items = self._extract_products_from_generic_json(
                                        raw_json=raw_text,
                                        competitor=competitor,
                                        page_url=search_url,
                                    )

                                # Si le JSON donne seulement les URLs (cas WordPress Infotec),
                                # on ouvre les fiches pour récupérer le prix + stock.
                                detailed_from_json = []
                                for ji in json_items[:min(4, detail_limit)]:
                                    if ji.urlProduit and (ji.prixConcurrent is None) and _time_left() > 2:
                                        detail_item = self._extract_product_from_detail_page(ji.urlProduit, competitor)
                                        detailed_from_json.append(detail_item or ji)
                                    else:
                                        detailed_from_json.append(ji)
                                json_items = [x for x in detailed_from_json if x]
                                html = "<html><body></body></html>"
                            else:
                                html = raw_text

                            items, _, page_errors, soup, selectors = self._extract_products_from_page(
                                page_url=search_url,
                                html=html,
                                competitor=competitor,
                            )
                            pages_tested += 1
                            competitor_errors.extend(page_errors)

                            if json_items:
                                existing_urls = {i.urlProduit for i in items if i.urlProduit}
                                for ji in json_items:
                                    if ji.urlProduit and ji.urlProduit not in existing_urls:
                                        items.append(ji)
                                        existing_urls.add(ji.urlProduit)

                            # Mytek/Magento : URLs cachées dans scripts JS.
                            if not items and "mytek" in search_url.lower() and _time_left() > 4:
                                magento_urls = self._extract_magento_product_urls(
                                    BeautifulSoup(html, "lxml"), search_url
                                )
                                if magento_urls:
                                    magento_items = []
                                    for product_url in magento_urls[:min(4, detail_limit)]:
                                        if _time_left() <= 2:
                                            break
                                        detail_item = self._extract_product_from_detail_page(product_url, competitor)
                                        if detail_item:
                                            magento_items.append(detail_item)
                                    items.extend(magento_items)

                            # Ouvrir les fiches détail seulement si la page ne donne pas encore un candidat fiable.
                            current_preview = self._filter_reference_candidates(
                                product=product,
                                items=items,
                                max_candidates=max_candidates,
                            )

                            if not current_preview and _time_left() > 4:
                                detail_budget = max(2, min(4, _time_left() - 1))
                                detail_items = self._extract_products_from_search_by_detail(
                                    page_url=search_url,
                                    html=html,
                                    competitor=competitor,
                                    query=query,
                                    product=product,
                                    limit=min(detail_limit, 3),
                                    budget_seconds=detail_budget,
                                )
                                if detail_items:
                                    existing_urls = {i.urlProduit for i in items if i.urlProduit}
                                    for di in detail_items:
                                        if di.urlProduit and di.urlProduit not in existing_urls:
                                            items.append(di)
                                            existing_urls.add(di.urlProduit)
                                    detail_urls_found.extend([i.urlProduit for i in detail_items if i.urlProduit])

                            _merge_items(items)

                            if _has_reliable_candidate(competitor_items, stage_name):
                                break

                        except Exception as exc:
                            competitor_errors.append(f"Erreur {search_url}: {str(exc)}")

                    if _has_reliable_candidate(competitor_items, stage_name):
                        break

                if _has_reliable_candidate(competitor_items, stage_name):
                    break

            filtered_items = self._filter_reference_candidates(
                product=product,
                items=competitor_items,
                max_candidates=max_candidates,
            )

            # Dernier fallback catalogue : uniquement si aucun candidat sérieux.
            if not filtered_items and _time_left() > 8:
                selected_catalogs = self._select_relevant_catalogs_for_product(
                    competitor=competitor,
                    product=product,
                    max_catalogs=1,
                )

                for catalog in selected_catalogs:
                    if _time_left() <= 3:
                        break

                    catalog_items: list[ProductCompetitorPayload] = []
                    catalog_errors: list[str] = []
                    catalog_seen: set[str] = set()

                    page_count, _, _, errors = self._scrape_catalog(
                        catalog=catalog,
                        competitor=competitor,
                        seen_product_urls=catalog_seen,
                        all_items=catalog_items,
                        all_errors=catalog_errors,
                        max_pages=1,
                    )

                    pages_tested += page_count
                    competitor_errors.extend(errors)
                    _merge_items(catalog_items)

                filtered_items = self._filter_reference_candidates(
                    product=product,
                    items=competitor_items,
                    max_candidates=max_candidates,
                )

            # On force les champs indispensables avant l'envoi au stock_service.
            # Objectif : un résultat visible dans le scheduler doit être sauvegardable en base.
            payload_items = []
            for candidate in filtered_items:
                if hasattr(candidate, "model_dump"):
                    payload = candidate.model_dump()
                else:
                    payload = dict(candidate)

                payload["produit_id"] = payload.get("produit_id") or product.get("id") or product.get("product_id")
                payload["product_id"] = payload.get("product_id") or payload.get("produit_id")
                payload["concurrent_id"] = payload.get("concurrent_id") or getattr(competitor, "id", None)
                payload["concurrentId"] = payload.get("concurrentId") or payload.get("concurrent_id")
                payload["competitor_name"] = payload.get("competitor_name") or getattr(competitor, "nom", None)
                payload["concurrent"] = payload.get("concurrent") or getattr(competitor, "nom", None)
                payload["nomConcurrent"] = payload.get("nomConcurrent") or getattr(competitor, "nom", None)

                payload_items.append(payload)

            save_result = self.stock_client.save_competitor_products(payload_items)

            saved_items = save_result.get("saved_items", []) or save_result.get("scraped_products", []) or []
            invalid_items = save_result.get("invalid_items", []) or []
            products_saved_count = int(
                save_result.get("rows")
                or (int(save_result.get("inserted", 0) or 0) + int(save_result.get("updated", 0) or 0))
            )

            result = {
                "competitor_id": competitor.id,
                "competitor_name": competitor.nom,
                "pages_tested": pages_tested,
                "products_found": len(competitor_items),
                "products_sent_to_matching": len(payload_items),
                "products_saved": products_saved_count,
                "products_invalid": int(save_result.get("invalid", 0) or 0),
                "save_result": save_result,
                # Très important : le scheduler affiche les lignes réellement sauvegardées.
                "scraped_products": saved_items,
                "saved_items": saved_items,
                "invalid_items": invalid_items,
                "time_remaining": round(_time_left(), 1),
            }

            if debug:
                result["query_stages"] = stages_debug
                result["tested_search_urls"] = tested_search_urls
                result["detail_urls_found"] = detail_urls_found
                result["catalogs_selected"] = len(selected_catalogs)
                result["errors"] = competitor_errors
                result["found_candidates"] = [
                    {
                        "nomProduit": i.nomProduit,
                        "skuConcurrent": i.skuConcurrent,
                        "urlProduit": i.urlProduit,
                        "prixConcurrent": i.prixConcurrent,
                        "quickScore": self._quick_candidate_score(product, i),
                        "sameModel": self._is_same_model_candidate(product, i, references),
                    }
                    for i in competitor_items[:20]
                ]
                result["filtered_candidates"] = [
                    {
                        "nomProduit": i.nomProduit,
                        "skuConcurrent": i.skuConcurrent,
                        "urlProduit": i.urlProduit,
                        "prixConcurrent": i.prixConcurrent,
                        "quickScore": self._quick_candidate_score(product, i),
                    }
                    for i in filtered_items[:20]
                ]

            return result

        except Exception as exc:
            return {
                "competitor_id": competitor.id,
                "competitor_name": competitor.nom,
                "error": str(exc),
                "products_found": len(competitor_items),
                "products_sent_to_matching": 0,
                "products_saved": 0,
                "errors": competitor_errors if debug else [],
            }

    def search_product_on_all_competitors(
        self,
        product: dict,
        debug: bool = False,
        fast: bool = True,
    ) -> dict:
        """
        Recherche ciblée parallèle fiable.
        """

        competitors = self.stock_client.get_competitors()
        active_competitors = [c for c in competitors if getattr(c, "actif", True)]

        references = self._extract_references_from_product(product)
        queries = self._build_product_search_queries(product)

        max_queries = 24 if fast else 34
        max_search_urls = 6 if fast else 10
        detail_limit = 8 if fast else 14
        max_candidates = 8 if fast else 12
        per_competitor_budget = 70.0 if fast else 110.0
        pool_timeout = 240.0 if fast else 360.0

        results: list[dict] = []
        processed_competitor_ids: set[int] = set()

        total_found = 0
        total_sent = 0
        total_saved = 0
        matched_total = 0
        manual_review_total = 0
        ignored_total = 0
        combined_products: list[dict] = []

        def _collect_result(res: dict) -> None:
            nonlocal total_found, total_sent, total_saved
            nonlocal matched_total, manual_review_total, ignored_total

            competitor_id = res.get("competitor_id")
            if competitor_id in processed_competitor_ids:
                return
            if competitor_id is not None:
                processed_competitor_ids.add(competitor_id)

            res["mode"] = "parallel_fast_reliable" if fast else "parallel_full_reliable"
            res["references"] = references
            res["queries"] = queries[:max_queries]
            results.append(res)

            save_result = res.get("save_result", {}) or {}
            total_found += int(res.get("products_found", 0) or 0)
            total_sent += int(res.get("products_sent_to_matching", 0) or 0)
            total_saved += int(
                res.get("products_saved", 0)
                or save_result.get("inserted", 0)
                or save_result.get("updated", 0)
                or 0
            )
            matched_total += int(save_result.get("matched", 0) or 0)
            manual_review_total += int(save_result.get("manual_review", 0) or 0)
            ignored_total += int(save_result.get("ignored", 0) or 0)
            combined_products.extend(res.get("scraped_products", []) or save_result.get("saved_items", []) or [])

        if not active_competitors:
            return {
                "status": "success",
                "mode": "no_active_competitor",
                "product_id": product.get("id") or product.get("product_id"),
                "references": references,
                "queries": queries[:max_queries],
                "summary": {
                    "competitorsProcessed": 0,
                    "productsFound": 0,
                    "productsSentToMatching": 0,
                    "productsSaved": 0,
                    "matched": 0,
                    "manualReview": 0,
                    "ignored": 0,
                },
                "message": "Aucun concurrent actif.",
            }

        pool = ThreadPoolExecutor(max_workers=min(len(active_competitors), 5))
        future_to_comp = {}
        processed_futures: set[int] = set()

        try:
            for competitor in active_competitors:
                future = pool.submit(
                    self._search_one_competitor,
                    competitor,
                    product,
                    queries,
                    references,
                    max_queries,
                    max_search_urls,
                    detail_limit,
                    max_candidates,
                    per_competitor_budget,
                    debug,
                )
                future_to_comp[future] = competitor

            try:
                for future in as_completed(future_to_comp.keys(), timeout=pool_timeout):
                    processed_futures.add(id(future))
                    competitor = future_to_comp[future]
                    try:
                        res = future.result(timeout=1)
                    except Exception as exc:
                        res = {
                            "competitor_id": competitor.id,
                            "competitor_name": competitor.nom,
                            "error": str(exc),
                            "products_found": 0,
                            "products_sent_to_matching": 0,
                            "products_saved": 0,
                        }
                    _collect_result(res)
            except FuturesTimeoutError:
                pass

            for future, competitor in future_to_comp.items():
                if id(future) in processed_futures:
                    continue
                if future.done():
                    try:
                        res = future.result(timeout=0)
                    except Exception as exc:
                        res = {
                            "competitor_id": competitor.id,
                            "competitor_name": competitor.nom,
                            "error": str(exc),
                            "products_found": 0,
                            "products_sent_to_matching": 0,
                            "products_saved": 0,
                        }
                    _collect_result(res)
                else:
                    future.cancel()
                    _collect_result({
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.nom,
                        "error": "Timeout — concurrent ignoré",
                        "products_found": 0,
                        "products_sent_to_matching": 0,
                        "products_saved": 0,
                    })
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        response = {
            "status": "success",
            "mode": "parallel_fast_reliable" if fast else "parallel_full_reliable",
            "product_id": product.get("id") or product.get("product_id"),
            "references": references,
            "queries": queries[:max_queries],
            "scraped_products": combined_products,
            "saved_items": combined_products,
            "summary": {
                "competitorsProcessed": len(active_competitors),
                "productsFound": total_found,
                "productsSentToMatching": total_sent,
                "productsSaved": total_saved,
                "matched": matched_total,
                "manualReview": manual_review_total,
                "ignored": ignored_total,
            },
            "message": "Recherche concurrentielle parallèle terminée.",
        }

        if debug:
            response["results"] = results

        return response

    def scrape_one(self, competitor_id: int) -> dict:
        competitor = self.stock_client.get_competitor_by_id(competitor_id)

        if competitor is None:
            raise ValueError(f"Concurrent {competitor_id} introuvable")

        return self.scrape_competitor(competitor).model_dump()

    def scrape_due_or_all(self, competitor_id: int | None = None, force_all: bool = False) -> dict:
        """
        Scraping catalogue automatique.

        La fréquence n'est plus globale. Elle est définie dans chaque concurrent
        avec uniquement trois choix : 6h, 12h ou 24h.

        Règle :
        - lancement manuel avec competitor_id : on scrape ce concurrent tout de suite ;
        - lancement manuel sans competitor_id avec force_all=True : on scrape tous les concurrents actifs ;
        - lancement automatique sans competitor_id : on scrape seulement les concurrents échus
          selon concurrents.frequenceScrapingHeures et dernierScraping.
        """
        if competitor_id is not None:
            competitors = self.stock_client.get_competitors()
            competitors = [c for c in competitors if c.id == competitor_id]

            if not competitors:
                raise ValueError(f"Concurrent {competitor_id} introuvable")
        else:
            if force_all:
                competitors = [
                    c for c in self.stock_client.get_competitors()
                    if getattr(c, "actif", True) is not False
                ]
            else:
                # Sécurité : en automatique, on ne traite qu'un concurrent par run.
                # Le scheduler rappelle ensuite cette méthode pour le concurrent suivant
                # lorsque son heure est atteinte.
                competitors = self.stock_client.get_due_competitors()[:1]

        results = []
        total_saved = 0
        total_matched = 0
        total_manual_review = 0
        total_ignored = 0
        total_invalid = 0
        scraped_products: list[dict] = []

        for competitor in competitors:
            summary = self.scrape_competitor(competitor)
            row = summary.model_dump()
            results.append(row)
            total_saved += summary.produits_enregistres
            total_matched += summary.produits_matches
            total_manual_review += summary.produits_a_valider
            total_ignored += summary.produits_ignores
            total_invalid += summary.produits_invalides
            scraped_products.extend(row.get("scraped_products", []) or row.get("saved_items", []) or [])

            try:
                self.stock_client.update_last_scraping(competitor.id)
            except Exception as exc:
                print(
                    f"[SCRAPING] Impossible de mettre à jour dernier_scraping "
                    f"pour concurrent {competitor.id}: {exc}",
                    flush=True,
                )

        return {
            "status": "success",
            "mode": "single_competitor" if competitor_id is not None else ("all_active_competitors" if force_all else "due_competitors"),
            "concurrents_traites": len(results),
            "produits_enregistres_total": total_saved,
            "produits_matches_total": total_matched,
            "produits_a_valider_total": total_manual_review,
            "produits_ignores_total": total_ignored,
            "produits_invalides_total": total_invalid,
            "scraped_products": scraped_products,
            "saved_items": scraped_products,
            "results": results,
        }
