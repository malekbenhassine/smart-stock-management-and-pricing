from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SEARCH_INPUT_NAMES = {
    "q", "s", "search", "search_query", "query", "keyword", "keywords",
    "term", "motcle", "mot_cle", "searchword", "find", "text",
}

# Templates fiables pour les sites tunisiens connus.
# Le placeholder {query} sera remplacé par la requête encodée dans scraping_service.py.
KNOWN_SEARCH_TEMPLATES: dict[str, list[str]] = {
    "mytek.tn": [
        "https://www.mytek.tn/myteksearch/index/productsearch/?q={query}",
        "https://www.mytek.tn/catalogsearch/result/?q={query}",
    ],
    "spacenet.tn": [
        "https://spacenet.tn/module/ambjolisearch/jolisearch?orderby=position&orderway=desc&search_query={query}&submit_search=",
        "https://spacenet.tn/recherche?controller=search&s={query}",
    ],
    "tunisianet.com.tn": [
        "https://www.tunisianet.com.tn/recherche?controller=search&s={query}",
    ],
    "zoom.com.tn": [
        "https://zoom.com.tn/recherche?controller=search&s={query}",
    ],
    "scoopgaming.com.tn": [
        "https://www.scoopgaming.com.tn/catalogsearch/result/?q={query}",
    ],
    "informatica.tn": [
        "https://informatica.tn/?s={query}&post_type=product",
        "https://informatica.tn/?s={query}",
    ],
    "infotec.tn": [
        "https://infotec.tn/wp-json/wc/store/v1/products?search={query}&per_page=20",
        "https://infotec.tn/wp-json/wp/v2/search?search={query}&subtype=product&per_page=20",
        "https://infotec.tn/?s={query}&post_type=product",
        "https://infotec.tn/fr/?s={query}&post_type=product",
        "https://infotec.tn/?s={query}",
    ],
    "bestpc.tn": [
        "https://bestpc.tn/?s={query}&post_type=product&type_aws=true",
        "https://bestpc.tn/?s={query}&post_type=product",
        "https://bestpc.tn/?s={query}",
    ],
    "carthagoinformatique.tn": [
        "https://carthagoinformatique.tn/?s={query}&post_type=product",
        "https://carthagoinformatique.tn/?s={query}",
    ],
}


def normalize_root(site_url: str) -> tuple[str, str]:
    raw = str(site_url or "").strip()
    if not raw:
        return "", ""

    parsed = urlparse(raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}")
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or parsed.path).split("/")[0].lower()
    if not host:
        return "", ""

    root = f"{scheme}://{host}".rstrip("/")
    domain = host[4:] if host.startswith("www.") else host
    return root, domain


def normalize_template_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.netloc:
        return url

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def _dedupe(items: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for item in items:
        item = (item or "").strip()
        if not item or "{query}" not in item:
            continue

        normalized = normalize_template_url(item)
        if normalized in seen:
            continue

        seen.add(normalized)
        # On garde l'URL originale pour préserver www si un site connu en a besoin,
        # mais le test de doublon ignore www.
        result.append(item)

        if len(result) >= limit:
            break

    return result


def detect_cms(root: str, domain: str, html: str) -> str:
    h = (html or "").lower()

    if domain in {"infotec.tn", "bestpc.tn", "informatica.tn", "carthagoinformatique.tn"}:
        return "wordpress_woocommerce"

    if domain in {"tunisianet.com.tn", "spacenet.tn", "zoom.com.tn", "sbsinformatique.com"}:
        return "prestashop"

    if domain in {"mytek.tn", "scoopgaming.com.tn"}:
        return "magento"

    if any(x in h for x in ["woocommerce", "wp-content", "wp-json", "post_type=product", "add-to-cart"]):
        return "wordpress_woocommerce"

    if any(x in h for x in ["prestashop", "controller=search", "jolisearch", "ambjolisearch", "search_query"]):
        return "prestashop"

    if any(x in h for x in ["magento", "catalogsearch", "mage/"]):
        return "magento"

    if any(x in h for x in ["shopify", "cdn.shopify.com", "/collections/"]):
        return "shopify"

    return "unknown"


def _looks_like_search_form(form) -> bool:
    txt = " ".join([
        form.get("id") or "",
        " ".join(form.get("class") or []),
        form.get("role") or "",
        form.get("action") or "",
        form.get_text(" ", strip=True)[:180],
    ]).lower()

    return any(x in txt for x in ["search", "recher", "chercher", "jolisearch", "catalogsearch"])


def _candidate_input_names(form) -> list[str]:
    names: list[str] = []

    for inp in form.select("input[name], textarea[name]"):
        name = (inp.get("name") or "").strip()
        if not name:
            continue

        itype = (inp.get("type") or "").lower()
        placeholder = (inp.get("placeholder") or "").lower()
        css = " ".join(inp.get("class") or []).lower()

        if name.lower() in SEARCH_INPUT_NAMES:
            names.append(name)
        elif itype == "search":
            names.append(name)
        elif any(x in placeholder for x in ["search", "recher", "chercher"]):
            names.append(name)
        elif any(x in css for x in ["search", "recher"]):
            names.append(name)

    return list(dict.fromkeys(names))


def _allowed_search_keys(cms: str) -> set[str]:
    if cms == "wordpress_woocommerce":
        return {"s"}
    if cms == "prestashop":
        return {"s", "search_query"}
    if cms == "magento":
        return {"q"}
    if cms == "shopify":
        return {"q"}
    return {"s", "q", "search_query"}


def _allowed_hidden_keys(cms: str) -> set[str]:
    if cms == "wordpress_woocommerce":
        return {"post_type", "type_aws"}
    if cms == "prestashop":
        return {"controller", "submit_search", "orderby", "orderway"}
    return set()


def templates_from_forms(root: str, html: str, cms: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    templates: list[str] = []

    allowed_search = _allowed_search_keys(cms)
    allowed_hidden = _allowed_hidden_keys(cms)

    for form in soup.select("form"):
        names = _candidate_input_names(form)

        if not names and not _looks_like_search_form(form):
            continue

        names = [n for n in names if n.lower() in allowed_search]

        if not names:
            if cms == "wordpress_woocommerce":
                names = ["s"]
            elif cms == "magento":
                names = ["q"]
            elif cms == "prestashop":
                names = ["s"]
            else:
                names = ["s"]

        action = form.get("action") or root
        action_url = urljoin(root + "/", action)
        parsed = urlparse(action_url)
        existing = parse_qs(parsed.query, keep_blank_values=True)

        for name in names:
            params: dict[str, str] = {}

            for k, v in existing.items():
                if k.lower() in allowed_hidden:
                    params[k] = v[0] if isinstance(v, list) and v else ""

            params[name] = "{query}"

            for hidden in form.select("input[type='hidden'][name]"):
                h_name = (hidden.get("name") or "").strip()
                h_value = hidden.get("value") or ""

                if h_name.lower() not in allowed_hidden:
                    continue

                # product_cat=0 donne souvent des doublons inutiles WooCommerce.
                if h_name == "product_cat" and h_value in {"", "0", "all"}:
                    continue

                params[h_name] = h_value

            query = urlencode(params, doseq=False).replace("%7Bquery%7D", "{query}")
            templates.append(
                urlunparse((
                    parsed.scheme or "https",
                    parsed.netloc,
                    parsed.path or "/",
                    "",
                    query,
                    "",
                ))
            )

    return _dedupe(templates, limit=4)


def cms_fallback_templates(root: str, cms: str) -> list[str]:
    if cms == "wordpress_woocommerce":
        return [
            f"{root}/?s={{query}}&post_type=product",
            f"{root}/?s={{query}}",
        ]

    if cms == "prestashop":
        return [
            f"{root}/recherche?controller=search&s={{query}}",
            f"{root}/search?controller=search&s={{query}}",
            f"{root}/module/ambjolisearch/jolisearch?search_query={{query}}&submit_search=",
        ]

    if cms == "magento":
        return [
            f"{root}/catalogsearch/result/?q={{query}}",
        ]

    if cms == "shopify":
        return [
            f"{root}/search?q={{query}}",
            f"{root}/collections/all?q={{query}}",
        ]

    return [
        f"{root}/?s={{query}}",
        f"{root}/search?q={{query}}",
        f"{root}/recherche?controller=search&s={{query}}",
    ]


def discover_search_url_templates(
    site_url: str,
    html: str | None = None,
    session: requests.Session | None = None,
    limit: int = 6,
) -> list[str]:
    root, domain = normalize_root(site_url)

    if not root:
        return []

    if html is None:
        try:
            sess = session or requests.Session()
            sess.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            })
            html = sess.get(root, timeout=(6, 12), allow_redirects=True, verify=False).text
        except Exception:
            html = ""

    cms = detect_cms(root, domain, html or "")
    templates: list[str] = []

    for domain_key, values in KNOWN_SEARCH_TEMPLATES.items():
        if domain == domain_key or domain.endswith("." + domain_key):
            templates.extend(values)
            break

    templates.extend(templates_from_forms(root, html or "", cms))
    templates.extend(cms_fallback_templates(root, cms))

    return _dedupe(templates, limit=limit)
