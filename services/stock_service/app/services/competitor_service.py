from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from app.models.tables import Competitor, CompetitorCatalog
from app.schemas.competitor_schemas import (
    CompetitorAdvancedConfigUpdate,
    CompetitorCreate,
    CompetitorUpdate,
)
from app.services.alert_event_client import emit_alert_event
from app.services.scraping_client import ScrapingServiceClient


def normalize_site_url(raw_url: str) -> tuple[str, str]:
    value = str(raw_url).strip()
    parsed = urlparse(value)

    scheme = parsed.scheme or "https"
    host = (parsed.netloc or parsed.path).lower().strip()

    # Si l'utilisateur écrit mytek.tn/path, urlparse met tout dans path.
    # On garde seulement le domaine.
    host = host.split("/")[0]

    if host.startswith("www."):
        host = host[4:]

    normalized = urlunparse((scheme, host, "/", "", "", ""))
    return normalized, host


def normalize_catalog_url(raw_url: str) -> str:
    parsed = urlparse(str(raw_url).strip())
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or "").lower().strip()

    # Si l'URL est relative, on la laisse telle quelle pour éviter de créer une URL vide.
    # Normalement le discovery_service doit retourner des URLs absolues.
    if not host:
        return str(raw_url).strip()

    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, host, path, "", "", ""))


ALLOWED_SCRAPING_FREQUENCY_HOURS = {6, 12, 24}
DEFAULT_SCRAPING_FREQUENCY_HOURS = 24


def _normalize_frequency_hours(value: Any, default: int = DEFAULT_SCRAPING_FREQUENCY_HOURS) -> int:
    try:
        number = int(value)
    except Exception:
        number = default

    if number not in ALLOWED_SCRAPING_FREQUENCY_HOURS:
        raise ValueError("La fréquence de scraping doit être 6h, 12h ou 24h.")

    return number


def _dt(value: Any) -> str | None:
    """
    Sérialise les dates concurrent stockées en UTC.

    Les colonnes de ce service utilisent datetime.utcnow() et SQLAlchemy
    retourne des datetimes naïfs. Sans timezone dans la réponse API, le
    navigateur les interprète comme des heures locales, ce qui affiche une
    heure de moins en Tunisie. On ajoute donc le suffixe Z pour indiquer au
    front que ces valeurs sont en UTC.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    return str(value)


def _next_scraping_datetime(obj: Competitor) -> datetime | None:
    """
    Calcule l'heure de prochain scraping du concurrent.

    Règle métier :
    - si le concurrent a déjà été scrapé : dernierScraping + fréquence ;
    - si le concurrent vient d'être créé et n'a jamais été scrapé : createdAt + fréquence.

    Ainsi, l'ajout d'un concurrent ne déclenche plus automatiquement
    un scraping immédiat.
    """
    if not obj.actif:
        return None

    frequency = _normalize_frequency_hours(obj.frequence_scraping_heures)
    base_datetime = obj.dernier_scraping or obj.date_creation or datetime.utcnow()
    return base_datetime + timedelta(hours=frequency)


def _next_scraping_at(obj: Competitor) -> str | None:
    next_datetime = _next_scraping_datetime(obj)
    return _dt(next_datetime) if next_datetime else None


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _first_list(data: dict[str, Any], *keys: str) -> list:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_value(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _make_catalog_title(item: dict[str, Any], url: str) -> str:
    title = _first_value(item, "titre", "title", "name", "label", default=None)
    if title:
        return str(title).strip()[:255]

    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("-", " ").replace("_", " ")
    return (path or "Catalogue détecté")[:255]


def _make_catalog_key(url: str) -> str:
    return normalize_catalog_url(url)


def _catalog_is_active(item: dict[str, Any]) -> bool:
    """
    Compatibilité avec l'ancienne logique :
    - avant : is_selected indiquait si le catalogue devait être utilisé ;
    - maintenant : actif remplace cette notion ;
    - on accepte quand même is_selected/is_active pour comprendre l'ancien retour discovery.
    """
    return bool(
        _first_value(
            item,
            "actif",
            "is_active",
            "isActive",
            "is_selected",
            "isSelected",
            default=True,
        )
    )


def _normalize_discovered_catalog_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    url = _first_value(item, "url", "href", "link", "catalog_url", "catalogUrl")
    if not url:
        return None

    normalized_url = normalize_catalog_url(str(url))
    if not normalized_url:
        return None

    parent_url = _first_value(
        item,
        "url_parent",
        "parent_url",
        "parentUrl",
        "parent",
        default=None,
    )

    try:
        profondeur = int(_first_value(item, "profondeur", "depth", default=0) or 0)
    except Exception:
        profondeur = 0

    try:
        score = float(_first_value(item, "score", default=0) or 0)
    except Exception:
        score = 0.0

    return {
        # Format français
        "titre": _make_catalog_title(item, normalized_url),
        "url": normalized_url,
        "cle_url": _first_value(item, "cle_url", "url_key", "urlKey", default=normalized_url),
        "url_parent": parent_url,
        "profondeur": profondeur,
        "score": score,
        "source": _first_value(item, "source", default="auto_discovery"),
        "actif": _catalog_is_active(item),

        # Format ancien conservé
        "title": _make_catalog_title(item, normalized_url),
        "url_key": _first_value(item, "cle_url", "url_key", "urlKey", default=normalized_url),
        "parent_url": parent_url,
        "depth": profondeur,
        "is_selected": _catalog_is_active(item),
        "is_active": _catalog_is_active(item),
    }


def _extract_discovered_catalogs(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Accepte l'ancienne logique et plusieurs formats possibles renvoyés par scraping_service :
    - catalogs
    - catalogues
    - catalog_urls
    - candidates
    - final_catalogs
    - discovered_catalogs

    Cette fonction évite que le stock_service vide les catalogues juste à cause d'un changement de nom.
    """
    if not isinstance(discovery, dict):
        return []

    raw_items = _first_list(
        discovery,
        "catalogs",
        "catalogues",
        "catalog_urls",
        "catalogUrls",
        "candidates",
        "final_catalogs",
        "discovered_catalogs",
        "items",
        "results",
    )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in raw_items:
        # Cas où le service retourne directement une liste d'URLs.
        if isinstance(item, str):
            item = {
                "url": item,
                "title": "Catalogue détecté",
                "source": "auto_discovery",
                "is_selected": True,
                "is_active": True,
            }

        catalog = _normalize_discovered_catalog_item(item)
        if not catalog:
            continue

        key = catalog["cle_url"]
        if key in seen:
            continue

        seen.add(key)
        normalized.append(catalog)

    return normalized


def _extract_keywords(discovery: dict[str, Any]) -> list[str]:
    values = _first_list(
        discovery,
        "keywords",
        "auto_keywords",
        "mots_cles_auto",
        "autoKeywords",
        "autoKeywordsJson",
    )
    return [str(v).strip() for v in values if str(v).strip()]


def _extract_search_urls(discovery: dict[str, Any]) -> list[str]:
    values = _first_list(
        discovery,
        "url_recherche",
        "urls_recherche",
        "search_urls",
        "searchUrls",
        "search_url",
    )
    return [str(v).strip() for v in values if str(v).strip()]


def _serialize_catalog(c: CompetitorCatalog) -> dict:
    """
    Sérialisation compatible :
    - français pour le diagramme/code ;
    - ancien format pour le frontend et scraping_service.
    """
    selected = bool(getattr(c, "_is_selected_legacy", True))
    active = bool(c.actif)

    return {
        "id": c.id,

        # Ancien format attendu par le front/scraping
        "title": c.titre,
        "url": c.url,
        "url_key": c.cle_url,
        "parent_url": c.url_parent,
        "depth": c.profondeur,
        "score": c.score,
        "source": c.source,
        "is_selected": selected,
        "is_active": active,
        "discovered_at": _dt(c.date_decouverte),

        # Nouveau format français
        "titre": c.titre,
        "cle_url": c.cle_url,
        "url_parent": c.url_parent,
        "profondeur": c.profondeur,
        "actif": active,
        "date_decouverte": _dt(c.date_decouverte),
    }


def _serialize_competitor(obj: Competitor) -> dict:
    catalogues = [_serialize_catalog(c) for c in obj.catalogues if c.actif]

    return {
        "id": obj.id,
        "nom": obj.nom,

        # Ancien format attendu par le front/scraping
        "site_url": obj.url_site,
        "site_host_normalized": obj.hote_site_normalise,
        "actif": obj.actif,
        "frequence_scraping_heures": obj.frequence_scraping_heures,
        "frequence_scraping_label": f"Toutes les {obj.frequence_scraping_heures} h",
        "dernier_scraping": _dt(obj.dernier_scraping),
        "prochain_scraping": _next_scraping_at(obj),
        "next_scraping_at": _next_scraping_at(obj),
        "discovery_status": obj.statut_decouverte,
        "last_discovery_at": _dt(obj.date_derniere_decouverte),
        "last_discovery_error": obj.erreur_derniere_decouverte,
        "auto_keywords": obj.mots_cles_auto_json or [],
        "selectors_override": obj.selecteurs_override_json or {},
        "catalogs": catalogues,
        "url_recherche": obj.urls_recherche or [],
        "created_at": _dt(obj.date_creation),
        "updated_at": _dt(obj.date_modification),

        # Nouveau format français
        "url_site": obj.url_site,
        "hote_site_normalise": obj.hote_site_normalise,
        "statut_decouverte": obj.statut_decouverte,
        "date_derniere_decouverte": _dt(obj.date_derniere_decouverte),
        "erreur_derniere_decouverte": obj.erreur_derniere_decouverte,
        "mots_cles_auto": obj.mots_cles_auto_json or [],
        "selecteurs_override": obj.selecteurs_override_json or {},
        "catalogues": catalogues,
        "urls_recherche": obj.urls_recherche or [],
        "date_creation": _dt(obj.date_creation),
        "date_modification": _dt(obj.date_modification),
    }


def _replace_catalogs(competitor: Competitor, discovered_catalogs: list[dict], db: Session) -> int:
    """
    Remplace les catalogues du concurrent.

    Important :
    - on comprend title/titre, depth/profondeur, parent_url/url_parent ;
    - on utilise actif comme nouvelle logique ;
    - on conserve _is_selected_legacy uniquement pour éviter une erreur DB si la colonne isSelected existe.
    """
    db.query(CompetitorCatalog).filter(
        CompetitorCatalog.concurrent_id == competitor.id
    ).delete(synchronize_session=False)

    count = 0

    for item in discovered_catalogs or []:
        catalog = _normalize_discovered_catalog_item(item)
        if not catalog:
            continue

        url = catalog["url"]
        actif = bool(catalog.get("actif", True))

        row = CompetitorCatalog(
            concurrent_id=competitor.id,
            titre=catalog["titre"],
            url=url,
            cle_url=catalog.get("cle_url") or _make_catalog_key(url),
            url_parent=catalog.get("url_parent"),
            profondeur=int(catalog.get("profondeur", 0) or 0),
            score=float(catalog.get("score", 0) or 0),
            source=catalog.get("source") or "auto_discovery",
            _is_selected_legacy=actif,
            actif=actif,
        )
        db.add(row)
        count += 1

    return count


def create_competitor_service(payload: CompetitorCreate, db: Session):
    """
    Création rapide du concurrent.

    La discovery reste en arrière-plan depuis la route.
    """
    normalized_site_url, site_host = normalize_site_url(str(payload.url_site))

    existing = db.query(Competitor).filter(
        Competitor.hote_site_normalise == site_host
    ).first()
    if existing:
        raise ValueError("Un concurrent existe déjà pour ce site")

    obj = Competitor(
        nom=payload.nom.strip(),
        url_site=normalized_site_url,
        hote_site_normalise=site_host,
        actif=payload.actif,
        frequence_scraping_heures=_normalize_frequency_hours(payload.frequence_scraping_heures),
        statut_decouverte="running",
        date_derniere_decouverte=None,
        erreur_derniere_decouverte=None,
        mots_cles_auto_json=[],
        selecteurs_override_json={},
        urls_recherche=[],
    )

    db.add(obj)
    db.commit()
    db.refresh(obj)

    emit_alert_event(
        event_type="COMPETITOR_CREATED",
        target_role="STOCK",
        metadata={
            "competitor_id": obj.id,
            "competitor_name": obj.nom,
            "site_url": obj.url_site,
            "message": f"Le concurrent {obj.nom} a été ajouté avec succès.",
        },
    )

    return _serialize_competitor(obj)


def run_competitor_discovery_service(competitor_id: int, db: Session):
    """
    Discovery longue lancée en arrière-plan.
    Elle remplit les catalogues, mots-clés et URLs de recherche.
    """
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()

    if not obj:
        return {
            "status": "error",
            "competitor_id": competitor_id,
            "error": "Concurrent introuvable",
        }

    obj.statut_decouverte = "running"
    obj.erreur_derniere_decouverte = None
    db.commit()
    db.refresh(obj)

    scraper = ScrapingServiceClient()

    try:
        discovery = scraper.discover_site(
            competitor_name=obj.nom,
            site_url=obj.url_site,
        )

        if not isinstance(discovery, dict):
            discovery = {}

        catalogs = _extract_discovered_catalogs(discovery)
        keywords = _extract_keywords(discovery)
        search_urls = _extract_search_urls(discovery)

        status = str(discovery.get("status") or "").lower()
        error = discovery.get("error")

        catalogs_count = _replace_catalogs(obj, catalogs, db)

        obj.mots_cles_auto_json = keywords
        obj.urls_recherche = search_urls
        obj.date_derniere_decouverte = datetime.utcnow()

        if status in ("timeout", "error"):
            obj.statut_decouverte = "partial"
            obj.erreur_derniere_decouverte = error or (
                "La découverte du site n'a pas pu se terminer correctement."
            )
        elif catalogs_count > 0:
            obj.statut_decouverte = "ready"
            obj.erreur_derniere_decouverte = None
        else:
            obj.statut_decouverte = "partial"
            obj.erreur_derniere_decouverte = "Aucun catalogue détecté automatiquement."

        db.commit()
        db.refresh(obj)

        if obj.statut_decouverte == "ready":
            emit_alert_event(
                event_type="COMPETITOR_CATALOGS_READY",
                target_role="STOCK",
                value=catalogs_count,
                metadata={
                    "competitor_id": obj.id,
                    "competitor_name": obj.nom,
                    "site_url": obj.url_site,
                    "catalogs_count": catalogs_count,
                    "status": obj.statut_decouverte,
                    "message": (
                        f"Les catalogues du concurrent {obj.nom} sont prêts : "
                        f"{catalogs_count} catalogue(s) détecté(s)."
                    ),
                },
            )
        else:
            emit_alert_event(
                event_type="COMPETITOR_CATALOGS_PARTIAL",
                target_role="STOCK",
                value=catalogs_count,
                metadata={
                    "competitor_id": obj.id,
                    "competitor_name": obj.nom,
                    "site_url": obj.url_site,
                    "catalogs_count": catalogs_count,
                    "status": obj.statut_decouverte,
                    "error": obj.erreur_derniere_decouverte,
                    "message": (
                        f"Découverte partielle pour {obj.nom} : "
                        f"{catalogs_count} catalogue(s) détecté(s). "
                        f"Détail : {obj.erreur_derniere_decouverte or 'information non précisée'}."
                    ),
                },
            )

        return {
            "status": obj.statut_decouverte,
            "competitor_id": obj.id,
            "catalogs_count": catalogs_count,
            "error": obj.erreur_derniere_decouverte,
        }

    except Exception as exc:
        obj.statut_decouverte = "failed"
        obj.date_derniere_decouverte = datetime.utcnow()
        obj.erreur_derniere_decouverte = str(exc)
        db.commit()
        db.refresh(obj)

        emit_alert_event(
            event_type="COMPETITOR_CATALOGS_FAILED",
            target_role="STOCK",
            value=0,
            metadata={
                "competitor_id": obj.id,
                "competitor_name": obj.nom,
                "site_url": obj.url_site,
                "catalogs_count": 0,
                "status": obj.statut_decouverte,
                "error": str(exc),
                "message": (
                    f"La découverte des catalogues du concurrent {obj.nom} a échoué. "
                    f"Erreur : {str(exc)}"
                ),
            },
        )

        return {
            "status": "failed",
            "competitor_id": obj.id,
            "error": str(exc),
        }


def list_competitors_service(db: Session):
    rows = db.query(Competitor).order_by(Competitor.id.desc()).all()
    return [_serialize_competitor(c) for c in rows]


def get_competitor_by_id_service(competitor_id: int, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")
    return _serialize_competitor(obj)


def update_competitor_service(competitor_id: int, payload: CompetitorUpdate, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    site_changed = False

    if payload.nom is not None:
        obj.nom = payload.nom.strip()

    if payload.actif is not None:
        obj.actif = payload.actif

    if payload.frequence_scraping_heures is not None:
        obj.frequence_scraping_heures = _normalize_frequency_hours(payload.frequence_scraping_heures, obj.frequence_scraping_heures)

    if payload.url_site is not None:
        normalized_site_url, site_host = normalize_site_url(str(payload.url_site))
        duplicate = db.query(Competitor).filter(
            Competitor.hote_site_normalise == site_host,
            Competitor.id != obj.id,
        ).first()
        if duplicate:
            raise ValueError("Un autre concurrent existe déjà pour ce site")

        if obj.hote_site_normalise != site_host:
            site_changed = True

        obj.url_site = normalized_site_url
        obj.hote_site_normalise = site_host

    if site_changed:
        obj.statut_decouverte = "running"
        obj.erreur_derniere_decouverte = None
        obj.date_derniere_decouverte = None
        obj.mots_cles_auto_json = []
        obj.urls_recherche = []

        db.query(CompetitorCatalog).filter(
            CompetitorCatalog.concurrent_id == obj.id
        ).delete(synchronize_session=False)

    db.commit()
    db.refresh(obj)

    result = _serialize_competitor(obj)
    result["discovery_required"] = site_changed
    return result


def update_advanced_config_service(
    competitor_id: int,
    payload: CompetitorAdvancedConfigUpdate,
    db: Session,
):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    if payload.selecteurs_override is not None:
        obj.selecteurs_override_json = payload.selecteurs_override
    elif payload.selectors_override is not None:
        obj.selecteurs_override_json = payload.selectors_override

    if payload.urls_recherche is not None:
        obj.urls_recherche = payload.urls_recherche
    elif payload.url_recherche is not None:
        obj.urls_recherche = payload.url_recherche

    db.commit()
    db.refresh(obj)
    return _serialize_competitor(obj)


def due_competitors_service(db: Session):
    rows = db.query(Competitor).filter(
        Competitor.actif.is_(True),
        Competitor.statut_decouverte.in_(["ready", "partial"]),
    ).all()

    now = datetime.utcnow()
    due_rows: list[tuple[datetime, Competitor]] = []

    for c in rows:
        next_time = _next_scraping_datetime(c)
        if next_time and next_time <= now:
            due_rows.append((next_time, c))

    # Ordre important : si plusieurs concurrents sont en retard,
    # le scraping automatique doit traiter le plus ancien d'abord,
    # mais pas les lancer tous dans le même run.
    due_rows.sort(key=lambda item: item[0])
    return [_serialize_competitor(c) for _, c in due_rows]


def update_last_scraping_service(competitor_id: int, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    obj.dernier_scraping = datetime.utcnow()
    db.commit()

    return {
        "status": "updated",
        "competitor_id": competitor_id,
        "dernier_scraping": _dt(obj.dernier_scraping),
    }


def replace_catalog_selection_service(competitor_id: int, catalog_ids: list[int], db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    catalogs = db.query(CompetitorCatalog).filter(
        CompetitorCatalog.concurrent_id == competitor_id
    ).all()

    selected_set = set(catalog_ids)

    for c in catalogs:
        selected = c.id in selected_set
        c.actif = selected
        # Compatibilité colonne DB isSelected si elle existe encore.
        if hasattr(c, "_is_selected_legacy"):
            c._is_selected_legacy = selected

    db.commit()
    db.refresh(obj)
    return _serialize_competitor(obj)
