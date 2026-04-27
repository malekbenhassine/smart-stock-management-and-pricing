from __future__ import annotations

from datetime import datetime
from typing import Optional, Set
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse, quote_plus
import re
import time
import requests
import urllib3

from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.schemas.scraping_schemas import (
    CompetitorModel,
    ProductCompetitorPayload,
    ScrapeSummary,
    CatalogScrapeDetail,
)
from app.services.stock_client import StockServiceClient
from app.services.selector_service import detect_selectors


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
        "dell", "acer", "msi", "macbook", "iphone", "samsung", "écran",
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

    params.pop("p", None)
    params.pop("page", None)

    flat = {k: v[0] for k, v in params.items()}
    new_query = urlencode(flat) if flat else ""

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))


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
            "Accept-Language": "fr,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

    def _absolute_url(self, base_url: str, href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        return urljoin(base_url, href)

    def _get_html(self, url: str) -> str:
        last_exc = None

        for _ in range(3):
            try:
                response = self.session.get(
                    url,
                    timeout=(10, 45),
                    allow_redirects=True,
                    verify=False,
                )
                response.raise_for_status()
                return response.text
            except Exception as exc:
                last_exc = exc
                time.sleep(1)

        raise RuntimeError(f"Echec récupération HTML pour {url}: {last_exc}")

    def _extract_product_from_card(
        self,
        card,
        page_url: str,
        selectors: dict,
        competitor: CompetitorModel,
    ):
        data_name = card.get("data-name")
        data_url = card.get("data-url")
        data_sku = card.get("data-sku")
        data_price = card.get("data-final-price") or card.get("data-price")

        name_node = (
            card.select_one(selectors.get("product_name"))
            if selectors.get("product_name")
            else None
        )

        link_node = (
            card.select_one(selectors.get("product_link"))
            if selectors.get("product_link")
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

        href = data_url

        if not href and link_node and link_node.has_attr("href"):
            href = link_node.get("href")

        url_produit = self._absolute_url(page_url, href)

        prix_concurrent = parse_price(
            data_price or (
                price_node.get_text(" ", strip=True)
                if price_node
                else None
            )
        )

        ancien_prix = (
            parse_price(old_price_node.get_text(" ", strip=True))
            if old_price_node
            else None
        )

        disponibilite = (
            availability_node.get_text(" ", strip=True)
            if availability_node
            else None
        )

        sku_concurrent = data_sku or (
            sku_node.get_text(" ", strip=True)
            if sku_node
            else None
        )

        if not nom_produit or not url_produit or prix_concurrent is None:
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

            if not absolute_url or absolute_url in seen_urls:
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
                    break

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

        saved_rows = int(
            save_result.get("rows")
            or save_result.get("inserted", 0) + save_result.get("updated", 0)
        )

        self.stock_client.update_last_scraping(competitor.id)

        return ScrapeSummary(
            competitor_id=competitor.id,
            competitor_name=competitor.nom,
            pages_parcourues=pages_total,
            produits_bruts=raw_total,
            produits_uniques=len(all_items),
            produits_enregistres=saved_rows,
            errors=all_errors,
            catalog_details=catalog_details,
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
        Génère des variantes uniquement pour comparer dans les textes/URLs.
        La recherche reste basée sur la référence exacte.
        """
        ref = self._normalize_reference_text(reference)

        if not ref:
            return set()

        return {
            ref,
            ref.replace("-", ""),
            ref.replace(" ", ""),
            ref.replace("-", " "),
        }

    def _extract_reference_from_text_fallback(self, text: str) -> list[str]:
        """
        Fallback uniquement si le SKU est absent.
        On exclut les processeurs/connectiques/mots techniques.
        """
        if not text:
            return []

        patterns = [
            r"\b[A-Z0-9]{4,12}[-_][A-Z0-9]{3,16}\b",  # X1502VA-BQ903W, 15-fa1006nk
            r"\b[A-Z]{1,5}\d{3,6}[A-Z]{1,6}\b",      # X1502VA, FA506NFR
            r"\b\d[A-Z0-9]{5,10}\b",                 # 9U1B9EA
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
        Nouvelle règle métier :
        - Le SKU du produit interne est la référence réelle.
        - La recherche se base d'abord et presque uniquement sur ce SKU tel qu'il est.
        - On ne rajoute pas CPU, RAM, DC-in, haut-parleur, etc. comme références.
        """
        sku = (product.get("sku") or "").strip()

        if sku:
            return [sku]

        # Fallback sécurité si un produit n'a pas encore de SKU réel.
        nom = product.get("nom") or ""
        description = product.get("description") or ""
        return self._extract_reference_from_text_fallback(f"{nom} {description}")

    def _build_product_search_queries(self, product: dict) -> list[str]:
        """
        Recherche par référence exacte.
        Si sku = X1502VA-BQ903W, on cherche X1502VA-BQ903W.
        Pas de recherche par CPU/RAM/nom complet pour éviter les faux résultats.
        """
        references = self._extract_references_from_product(product)
        queries: list[str] = []

        for ref in references:
            ref = " ".join(str(ref).split()).strip()
            if ref and ref.lower() not in [q.lower() for q in queries]:
                queries.append(ref)

        return queries[:3]

    def _item_contains_reference(
        self,
        item: ProductCompetitorPayload,
        references: list[str],
    ) -> bool:
        """
        Vérifie que le produit concurrent contient la référence exacte du produit.
        On accepte aussi la version compacte sans tiret, car certaines URLs retirent les tirets.
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
        """
        Vérifie la référence exacte dans la fiche produit.

        Pourquoi ?
        Certains sites n'affichent pas la référence dans la carte produit
        ou dans la liste de recherche. La référence existe parfois seulement
        dans la page détail du produit.
        """
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
                        item.descriptionConcurrent = detail_text[:2500]
                        return True

                    if variant_compact and variant_compact in compact_text:
                        item.descriptionConcurrent = detail_text[:2500]
                        return True

            return False

        except Exception:
            return False

    def _filter_reference_candidates(
        self,
        product: dict,
        items: list[ProductCompetitorPayload],
        max_candidates: int = 8,
    ) -> list[ProductCompetitorPayload]:
        """
        Garde le produit concurrent si la référence du produit interne existe dans :
        - le nom du produit concurrent
        - la description du produit concurrent
        - la référence/SKU concurrent
        - l'URL du produit concurrent
        - ou la page détail du produit concurrent

        Important : on ne garde pas les produits proches sans référence exacte.
        """
        references = self._extract_references_from_product(product)

        if not references:
            return []

        filtered: list[ProductCompetitorPayload] = []

        for item in items:
            if self._item_contains_reference(item, references):
                filtered.append(item)

            elif self._product_detail_contains_reference(item, references):
                filtered.append(item)

            if len(filtered) >= max_candidates:
                break

        return filtered

    def _build_search_urls_for_competitor(
        self,
        competitor: CompetitorModel,
        query: str,
    ) -> list[str]:
        """
        Construit plusieurs URLs de recherche selon le concurrent.

        Important :
        Certains sites Prestashop utilisent plusieurs formats de recherche.
        Spacenet peut ne pas répondre avec un seul format.
        """
        base_url = (competitor.site_url or "").rstrip("/")

        if not base_url:
            return []

        domain = urlparse(base_url).netloc.lower().replace("www.", "")
        q = quote_plus(query)

        urls = []

        if "mytek" in domain:
            urls.append(f"{base_url}/catalogsearch/result/?q={q}")
            urls.append(f"{base_url}/search?query={q}")

        elif "tunisianet" in domain:
            urls.append(f"{base_url}/recherche?controller=search&s={q}")
            urls.append(f"{base_url}/recherche?s={q}")
            urls.append(f"{base_url}/module/iqitsearch/searchiqit?s={q}")

        elif "spacenet" in domain:
            urls.append(f"{base_url}/recherche?search_query={q}")
            urls.append(f"{base_url}/search?query={q}")
            urls.append(f"{base_url}/recherche?s={q}")
            urls.append(f"{base_url}/module/iqitsearch/searchiqit?s={q}")

        elif "scoop" in domain:
            urls.append(f"{base_url}/recherche?controller=search&s={q}")
            urls.append(f"{base_url}/search?query={q}")
            urls.append(f"{base_url}/recherche?s={q}")

        elif "bestpc" in domain:
            urls.append(f"{base_url}/recherche?controller=search&s={q}")
            urls.append(f"{base_url}/search?query={q}")
            urls.append(f"{base_url}/recherche?s={q}")

        elif "carthagoinformatique" in domain:
            urls.append(f"{base_url}/recherche?controller=search&s={q}")
            urls.append(f"{base_url}/search?query={q}")
            urls.append(f"{base_url}/recherche?s={q}")

        else:
            urls.append(f"{base_url}/catalogsearch/result/?q={q}")
            urls.append(f"{base_url}/search?query={q}")
            urls.append(f"{base_url}/recherche?controller=search&s={q}")
            urls.append(f"{base_url}/recherche?s={q}")
            urls.append(f"{base_url}/module/iqitsearch/searchiqit?s={q}")

        # Supprimer doublons
        clean_urls = []
        seen = set()

        for url in urls:
            if url not in seen:
                clean_urls.append(url)
                seen.add(url)

        return clean_urls
    def _quick_normalize(self, value: str | None) -> str:
        if not value:
            return ""

        value = value.lower()
        value = value.replace("è", "e").replace("é", "e").replace("ê", "e")
        value = value.replace("à", "a").replace("ù", "u")
        value = value.replace("go", "gb")
        value = value.replace("g ", "gb ")
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
        Score rapide côté scraping_service.
        Ce n'est PAS le vrai matching.
        Il sert seulement à garder les candidats les plus intéressants.
        """
        product_terms = self._extract_strong_terms_for_product(product)

        item_text = self._quick_normalize(
            " ".join([
                item.nomProduit or "",
                item.descriptionConcurrent or "",
                item.skuConcurrent or "",
                item.urlProduit or "",
            ])
        )

        score = 0

        for term in product_terms:
            clean_term = self._quick_normalize(term)

            if not clean_term:
                continue

            if clean_term in item_text:
                if re.match(r"\b[a-z]{1,4}\d{3,6}[a-z]{0,4}\b", clean_term):
                    score += 100
                elif re.match(r"\b\d{2}-[a-z0-9]{4,12}\b", clean_term):
                    score += 100
                elif clean_term in {"asus", "hp", "dell", "lenovo", "acer", "msi"}:
                    score += 20
                elif "rtx" in clean_term or "gtx" in clean_term:
                    score += 35
                elif clean_term in {"i3", "i5", "i7", "i9"}:
                    score += 30
                elif "gb" in clean_term or "tb" in clean_term:
                    score += 15
                else:
                    score += 10

        return score


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

    def search_product_on_all_competitors(self, product: dict, debug: bool = False) -> dict:
        """
        Recherche ciblée optimisée par SKU/référence réelle.

        Logique finale :
        1. Prendre le SKU tel qu'il est.
        2. Chercher uniquement cette référence chez chaque concurrent.
        3. Garder uniquement les produits concurrents qui contiennent cette référence.
        4. Envoyer ces candidats au stock_service pour MATCHED/IGNORED final.
        """
        competitors = self.stock_client.get_competitors()
        active_competitors = [c for c in competitors if getattr(c, "actif", True)]

        references = self._extract_references_from_product(product)
        queries = self._build_product_search_queries(product)

        total_found = 0
        total_sent_to_matching = 0
        total_saved = 0
        results = []

        for competitor in active_competitors:
            competitor_items: list[ProductCompetitorPayload] = []
            competitor_errors: list[str] = []
            pages_tested = 0
            seen_product_urls: set[str] = set()

            try:
                # Recherche directe par référence uniquement.
                for query in queries[:3]:
                    search_urls = self._build_search_urls_for_competitor(
                        competitor=competitor,
                        query=query,
                    )

                    for search_url in search_urls[:2]:
                        try:
                            html = self._get_html(search_url)

                            items, next_url, page_errors, soup, selectors = (
                                self._extract_products_from_page(
                                    page_url=search_url,
                                    html=html,
                                    competitor=competitor,
                                )
                            )

                            pages_tested += 1
                            competitor_errors.extend(page_errors)

                            for item in items:
                                item.produit_id = product.get("id") or product.get("product_id")

                                if item.urlProduit not in seen_product_urls:
                                    seen_product_urls.add(item.urlProduit)
                                    competitor_items.append(item)

                        except Exception as exc:
                            competitor_errors.append(
                                f"Erreur recherche {search_url}: {str(exc)}"
                            )

                filtered_items = self._filter_reference_candidates(
                    product=product,
                    items=competitor_items,
                    max_candidates=5,
                )

                total_found += len(competitor_items)
                total_sent_to_matching += len(filtered_items)

                save_result = self.stock_client.save_competitor_products(filtered_items)

                saved = int(
                    save_result.get("rows")
                    or save_result.get("inserted", 0) + save_result.get("updated", 0)
                )
                total_saved += saved

                result_item = {
                    "competitor_id": competitor.id,
                    "competitor_name": competitor.nom,
                    "mode": "exact_sku_reference_search",
                    "references": references,
                    "queries": queries,
                    "pages_tested": pages_tested,
                    "products_found": len(competitor_items),
                    "products_sent_to_matching": len(filtered_items),
                    "products_saved": saved,
                    "save_result": save_result,
                }

                if debug:
                    result_item["errors"] = competitor_errors
                    result_item["found_candidates"] = [
                        {
                            "nomProduit": item.nomProduit,
                            "skuConcurrent": item.skuConcurrent,
                            "urlProduit": item.urlProduit,
                            "prixConcurrent": item.prixConcurrent,
                            "containsReference": self._item_contains_reference(item, references),
                        }
                        for item in competitor_items[:30]
                    ]
                    result_item["sent_candidates"] = [
                        {
                            "nomProduit": item.nomProduit,
                            "skuConcurrent": item.skuConcurrent,
                            "urlProduit": item.urlProduit,
                            "prixConcurrent": item.prixConcurrent,
                        }
                        for item in filtered_items
                    ]

                results.append(result_item)

            except Exception as exc:
                error_item = {
                    "competitor_id": competitor.id,
                    "competitor_name": competitor.nom,
                    "mode": "exact_sku_reference_search",
                    "references": references,
                    "queries": queries,
                    "error": str(exc),
                }

                if debug:
                    error_item["errors"] = competitor_errors

                results.append(error_item)

        matched_total = 0
        manual_review_total = 0
        ignored_total = 0

        for result in results:
            save_result = result.get("save_result") or {}
            matched_total += int(save_result.get("matched", 0) or 0)
            manual_review_total += int(save_result.get("manual_review", 0) or 0)
            ignored_total += int(save_result.get("ignored", 0) or 0)

        response = {
            "status": "success",
            "mode": "exact_sku_reference_search",
            "product_id": product.get("id") or product.get("product_id"),
            "references": references,
            "queries": queries,
            "summary": {
                "competitorsProcessed": len(active_competitors),
                "productsFound": total_found,
                "productsSentToMatching": total_sent_to_matching,
                "productsSaved": total_saved,
                "matched": matched_total,
                "manualReview": manual_review_total,
                "ignored": ignored_total,
            },
            "message": "Analyse concurrentielle par référence exacte terminée.",
        }

        if debug:
            response["results"] = results

        return response

    def scrape_one(self, competitor_id: int) -> dict:
        competitor = self.stock_client.get_competitor_by_id(competitor_id)

        if competitor is None:
            raise ValueError(f"Concurrent {competitor_id} introuvable")

        return self.scrape_competitor(competitor).model_dump()

    def scrape_due_or_all(self, competitor_id: int | None = None) -> dict:
        competitors = self.stock_client.get_competitors()

        if competitor_id is not None:
            competitors = [c for c in competitors if c.id == competitor_id]

        if competitor_id is not None and not competitors:
            raise ValueError(f"Concurrent {competitor_id} introuvable")

        results = []
        total_saved = 0

        for competitor in competitors:
            summary = self.scrape_competitor(competitor)
            results.append(summary.model_dump())
            total_saved += summary.produits_enregistres

        return {
            "status": "success",
            "concurrents_traites": len(results),
            "produits_enregistres_total": total_saved,
            "results": results,
        }