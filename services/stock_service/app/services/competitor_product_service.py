from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.tables import Product, ProductCompetitor, Competitor
from app.schemas.competitor_schemas import ProductCompetitorCreate
from app.services.matching_service import compute_match_score, match_status


# ============================================================
# Helpers
# ============================================================

def _safe_parse_date(date_str: Optional[str]) -> datetime:
    if not date_str:
        return datetime.utcnow()

    try:
        return datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def _to_float(value):
    if value is None or value == "":
        return None

    try:
        return float(value)
    except Exception:
        return None


def _get_attr(obj, *names, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _set_attr(obj, value, *names):
    for name in names:
        if hasattr(obj, name):
            setattr(obj, name, value)
            return


def _normalize_raw_item(raw: dict) -> dict:
    return {
        "concurrent_id": raw.get("concurrent_id") or raw.get("competitor_id"),
        "urlProduit": raw.get("urlProduit") or raw.get("url_produit") or raw.get("url"),
        "nomProduit": raw.get("nomProduit") or raw.get("nom_produit") or raw.get("name"),
        "descriptionConcurrent": (
            raw.get("descriptionConcurrent")
            or raw.get("description_concurrent")
            or raw.get("description")
            or raw.get("descriptionProduit")
        ),
        "skuConcurrent": raw.get("skuConcurrent") or raw.get("sku_concurrent"),
        "produit_id": raw.get("produit_id") or raw.get("product_id"),
        "prixConcurrent": raw.get("prixConcurrent") or raw.get("prix_concurrent") or raw.get("price"),
        "ancienPrixConcurrent": (
            raw.get("ancienPrixConcurrent")
            or raw.get("ancien_prix_concurrent")
            or raw.get("ancienPrix")
            or raw.get("ancien_prix")
            or raw.get("old_price")
        ),
        "isPromo": raw.get("isPromo", raw.get("is_promo", False)),
        "disponibilite": raw.get("disponibilite") or raw.get("availability"),
        "dateCollecte": raw.get("dateCollecte") or raw.get("date_collecte"),
        "fiable": raw.get("fiable", True),
    }


# ============================================================
# Serializer utilisé par les routes
# ============================================================

def _serialize_pc(pc: ProductCompetitor, competitor: Competitor | None = None) -> dict:
    return {
        "id": pc.id,
        "concurrentId": _get_attr(pc, "concurrent_id"),
        "concurrent": competitor.nom if competitor else None,

        "urlProduit": _get_attr(pc, "url_produit"),
        "skuConcurrent": _get_attr(pc, "sku_concurrent"),
        "nomProduit": _get_attr(pc, "nom_produit"),
        "descriptionConcurrent": _get_attr(pc, "description_concurrent"),

        "produit_id": _get_attr(pc, "produit_id"),
        "prixConcurrent": _get_attr(pc, "prix_concurrent"),
        "ancienPrixConcurrent": _get_attr(pc, "ancien_prix_concurrent"),
        "isPromo": _get_attr(pc, "is_promo"),

        "disponibilite": _get_attr(pc, "disponibilite"),
        "dateCollecte": _get_attr(pc, "date_collecte"),
        "fiable": _get_attr(pc, "fiable"),

        "scoreMatching": _get_attr(pc, "score_matching"),
        "statutMatching": _get_attr(pc, "statut_matching"),
        "detailsMatching": _get_attr(pc, "details_matching"),
    }


# ============================================================
# Matching
# ============================================================

def _find_best_product_match(
    item: ProductCompetitorCreate,
    db: Session,
    products_cache: list[Product] | None = None,
):
    """
    Optimisé :
    - si produit_id est envoyé par scraping_service, on matche uniquement ce produit
    - sinon on utilise le cache des produits internes chargé une seule fois
    """
    if item.produit_id:
        products = db.query(Product).filter(Product.id == item.produit_id).all()
    else:
        products = products_cache or db.query(Product).all()

    best_product = None
    best_score = 0.0
    best_details = None

    for product in products:
        internal_description = " ".join([
            product.description or "",
            product.marque or "",
            product.sku or "",
            product.categorie or "",
        ])

        score, details = compute_match_score(
            internal_name=product.nom or "",
            internal_desc=internal_description,
            competitor_name=item.nomProduit or "",
            competitor_desc=item.descriptionConcurrent or "",
        )

        if score > best_score:
            best_score = score
            best_product = product
            best_details = details

    if not best_product:
        return None, 0.0, None

    return best_product, best_score, best_details


def _is_better_candidate(new_candidate: dict, current_candidate: dict | None) -> bool:
    """
    Garde un seul meilleur candidat pour :
    produit interne + concurrent.
    """
    if current_candidate is None:
        return True

    priority = {
        "MATCHED": 3,
        "MANUAL_REVIEW": 2,
        "IGNORED": 1,
    }

    new_status = new_candidate.get("status") or "IGNORED"
    current_status = current_candidate.get("status") or "IGNORED"

    if priority.get(new_status, 0) > priority.get(current_status, 0):
        return True

    if priority.get(new_status, 0) < priority.get(current_status, 0):
        return False

    new_score = float(new_candidate.get("score") or 0)
    current_score = float(current_candidate.get("score") or 0)

    if new_score > current_score:
        return True

    if new_score < current_score:
        return False

    new_item = new_candidate.get("item")
    current_item = current_candidate.get("item")

    if bool(getattr(new_item, "fiable", False)) and not bool(getattr(current_item, "fiable", False)):
        return True

    return False


# ============================================================
# Upsert : un seul produit concurrent par produit interne + concurrent
# ============================================================

def _upsert_best_competitor_product(
    db: Session,
    item: ProductCompetitorCreate,
    product: Product,
    score: float,
    details: dict,
    status: str,
):
    existing = (
        db.query(ProductCompetitor)
        .filter(
            ProductCompetitor.produit_id == product.id,
            ProductCompetitor.concurrent_id == item.concurrent_id,
        )
        .first()
    )

    date_collecte = _safe_parse_date(item.dateCollecte)

    details_payload = {
        **(details or {}),
        "status": status,
        "descriptionConcurrent": item.descriptionConcurrent,
    }

    if existing:
        _set_attr(existing, item.urlProduit, "url_produit")
        _set_attr(existing, item.skuConcurrent, "sku_concurrent")
        _set_attr(existing, item.nomProduit, "nom_produit")
        _set_attr(existing, item.descriptionConcurrent, "description_concurrent")

        _set_attr(existing, item.prixConcurrent, "prix_concurrent")
        _set_attr(existing, item.ancienPrixConcurrent, "ancien_prix_concurrent")
        _set_attr(existing, item.isPromo, "is_promo")

        _set_attr(existing, item.disponibilite, "disponibilite")
        _set_attr(existing, date_collecte, "date_collecte")
        _set_attr(existing, bool(item.fiable) if status == "MATCHED" else False, "fiable")

        _set_attr(existing, score, "score_matching")
        _set_attr(existing, status, "statut_matching")
        _set_attr(existing, details_payload, "details_matching")

        return existing, "updated"

    obj = ProductCompetitor(
        url_produit=item.urlProduit,
        sku_concurrent=item.skuConcurrent,
        nom_produit=item.nomProduit,
        description_concurrent=item.descriptionConcurrent,

        concurrent_id=item.concurrent_id,
        produit_id=product.id,

        prix_concurrent=item.prixConcurrent,
        ancien_prix_concurrent=item.ancienPrixConcurrent,
        is_promo=item.isPromo,

        disponibilite=item.disponibilite,
        date_collecte=date_collecte,
        fiable=bool(item.fiable) if status == "MATCHED" else False,

        score_matching=score,
        statut_matching=status,
        details_matching=details_payload,
    )

    db.add(obj)
    return obj, "inserted"


# ============================================================
# Route POST /competitor-products/from-scraping
# ============================================================

def bulk_save_scraped_with_matching(items: list[dict], db: Session) -> dict:
    inserted = 0
    updated = 0
    manual_review = 0
    ignored = 0
    invalid = 0

    manual_items = []
    discarded_candidates = 0

    best_by_product_and_competitor: dict[tuple[int, int], dict] = {}

    # Optimisation importante : on charge les produits internes une seule fois
    products_cache = db.query(Product).all()

    for raw in items:
        try:
            normalized = _normalize_raw_item(raw)

            if (
                not normalized["concurrent_id"]
                or not normalized["urlProduit"]
                or not normalized["nomProduit"]
                or normalized["prixConcurrent"] is None
            ):
                invalid += 1
                continue

            item = ProductCompetitorCreate(
                concurrent_id=int(normalized["concurrent_id"]),
                urlProduit=str(normalized["urlProduit"]),
                nomProduit=str(normalized["nomProduit"]),
                descriptionConcurrent=normalized["descriptionConcurrent"],
                skuConcurrent=normalized["skuConcurrent"],
                produit_id=normalized["produit_id"],
                prixConcurrent=float(normalized["prixConcurrent"]),
                ancienPrixConcurrent=_to_float(normalized["ancienPrixConcurrent"]),
                isPromo=bool(normalized["isPromo"]),
                disponibilite=normalized["disponibilite"],
                dateCollecte=normalized["dateCollecte"],
                fiable=bool(normalized["fiable"]),
            )

            product, score, details = _find_best_product_match(
                item=item,
                db=db,
                products_cache=products_cache,
            )

            if not product or not details:
                ignored += 1
                continue

            status = details.get("status") or match_status(score, details)

            if status == "IGNORED":
                ignored += 1
                continue

            candidate = {
                "product": product,
                "item": item,
                "score": score,
                "details": details,
                "status": status,
            }

            key = (product.id, item.concurrent_id)
            current_best = best_by_product_and_competitor.get(key)

            if _is_better_candidate(candidate, current_best):
                if current_best is not None:
                    discarded_candidates += 1

                best_by_product_and_competitor[key] = candidate
            else:
                discarded_candidates += 1

        except Exception as exc:
            print("Erreur matching item:", exc)
            invalid += 1
            continue

    for candidate in best_by_product_and_competitor.values():
        product = candidate["product"]
        item = candidate["item"]
        score = candidate["score"]
        details = candidate["details"]
        status = candidate["status"]

        _, action = _upsert_best_competitor_product(
            db=db,
            item=item,
            product=product,
            score=score,
            details=details,
            status=status,
        )

        if action == "inserted":
            inserted += 1
        else:
            updated += 1

        if status == "MANUAL_REVIEW":
            manual_review += 1
            manual_items.append({
                "nomProduitConcurrent": item.nomProduit,
                "produitInterne": product.nom,
                "produitId": product.id,
                "scoreMatching": score,
                "urlProduit": item.urlProduit,
            })

    ignored += discarded_candidates

    db.commit()

    return {
        "status": "success",
        "total_received": len(items),
        "inserted": inserted,
        "updated": updated,
        "manual_review": manual_review,
        "ignored": ignored,
        "invalid": invalid,
        "manual_items": manual_items,
    }


# ============================================================
# Read services
# ============================================================

def get_competitor_products_by_product_service(product_id: int, db: Session):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    rows = (
        db.query(ProductCompetitor, Competitor)
        .outerjoin(Competitor, ProductCompetitor.concurrent_id == Competitor.id)
        .filter(ProductCompetitor.produit_id == product_id)
        .order_by(
            ProductCompetitor.statut_matching.asc(),
            ProductCompetitor.score_matching.desc(),
            ProductCompetitor.prix_concurrent.asc(),
        )
        .all()
    )

    items = [_serialize_pc(pc, competitor) for pc, competitor in rows]

    matched_items = [
        item for item in items
        if item.get("statutMatching") == "MATCHED"
    ]

    manual_items = [
        item for item in items
        if item.get("statutMatching") == "MANUAL_REVIEW"
    ]

    prices = [
        item["prixConcurrent"]
        for item in matched_items
        if item.get("prixConcurrent") is not None
    ]

    return {
        "product": {
            "id": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "prixVente": product.prix_vente,
            "prixCout": product.prix_cout,
        },
        "summary": {
            "total": len(items),
            "matched": len(matched_items),
            "manualReview": len(manual_items),
            "bestPrice": min(prices) if prices else None,
            "maxPrice": max(prices) if prices else None,
            "avgPrice": round(sum(prices) / len(prices), 2) if prices else None,
        },
        "items": items,
    }


def get_pending_validation_service(db: Session):
    rows = (
        db.query(ProductCompetitor, Competitor)
        .outerjoin(Competitor, ProductCompetitor.concurrent_id == Competitor.id)
        .filter(ProductCompetitor.statut_matching == "MANUAL_REVIEW")
        .order_by(ProductCompetitor.score_matching.desc())
        .all()
    )

    return {
        "count": len(rows),
        "items": [_serialize_pc(pc, competitor) for pc, competitor in rows],
    }


def validate_competitor_product_service(pc_id: int, db: Session):
    pc = db.query(ProductCompetitor).filter(ProductCompetitor.id == pc_id).first()

    if not pc:
        raise HTTPException(status_code=404, detail="Produit concurrent introuvable")

    pc.statut_matching = "MATCHED"
    pc.fiable = True

    details = pc.details_matching or {}
    details["status"] = "MATCHED"
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit concurrent validé",
        "item": _serialize_pc(pc),
    }


def reject_competitor_product_service(pc_id: int, db: Session):
    pc = db.query(ProductCompetitor).filter(ProductCompetitor.id == pc_id).first()

    if not pc:
        raise HTTPException(status_code=404, detail="Produit concurrent introuvable")

    pc.statut_matching = "IGNORED"
    pc.fiable = False

    details = pc.details_matching or {}
    details["status"] = "IGNORED"
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit concurrent rejeté",
        "item": _serialize_pc(pc),
    }
# ============================================================
# Compatibilité avec les anciennes routes
# À garder pour éviter les erreurs d'import dans competitor_products.py
# ============================================================

def bulk_save_scraped_competitor_products_service(
    items: list[ProductCompetitorCreate],
    db: Session,
) -> dict:
    """
    Ancienne route /competitor-products/bulk.
    Convertit les objets Pydantic en dict puis utilise la nouvelle logique :
    - matching
    - un seul meilleur produit par concurrent
    - update sans doublon
    """
    dict_items = []

    for item in items:
        if hasattr(item, "model_dump"):
            dict_items.append(item.model_dump())
        else:
            dict_items.append(item.dict())

    return bulk_save_scraped_with_matching(dict_items, db)


# Alias possible si une ancienne partie du code utilise cet ancien nom
bulk_save_competitor_products_service = bulk_save_scraped_competitor_products_service


def validate_match_service(
    competitor_product_id: int,
    accepted: bool,
    produit_id: Optional[int],
    db: Session,
) -> dict:
    """
    Ancienne route :
    POST /competitor-products/{id}/validate

    accepted = true  => MATCHED
    accepted = false => IGNORED sauf si produit_id fourni
    """
    pc = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.id == competitor_product_id)
        .first()
    )

    if not pc:
        raise HTTPException(status_code=404, detail="Produit concurrent introuvable")

    if produit_id:
        product = db.query(Product).filter(Product.id == produit_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produit interne introuvable")

        pc.produit_id = produit_id

    if accepted:
        pc.statut_matching = "MATCHED"
        pc.fiable = True
    else:
        pc.statut_matching = "IGNORED"
        pc.fiable = False

    details = pc.details_matching or {}
    details["status"] = pc.statut_matching
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Validation mise à jour",
        "item": _serialize_pc(pc),
    }


def rematch_product_service(product_id: int, db: Session) -> dict:
    """
    Recalcule le matching pour tous les produits concurrents liés à un produit interne.
    Garde ensuite uniquement le meilleur produit par concurrent.
    """
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit interne introuvable")

    competitor_products = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id)
        .all()
    )

    best_by_competitor: dict[int, ProductCompetitor] = {}

    for pc in competitor_products:
        internal_description = " ".join([
            product.description or "",
            product.marque or "",
            product.sku or "",
            product.categorie or "",
        ])

        score, details = compute_match_score(
            internal_name=product.nom or "",
            internal_desc=internal_description,
            competitor_name=pc.nom_produit or "",
            competitor_desc=pc.description_concurrent or "",
        )

        status = details.get("status") or match_status(score, details)

        pc.score_matching = score
        pc.statut_matching = status
        pc.details_matching = {
            **details,
            "status": status,
            "descriptionConcurrent": pc.description_concurrent,
        }
        pc.fiable = True if status == "MATCHED" else False

        current_best = best_by_competitor.get(pc.concurrent_id)

        if current_best is None:
            best_by_competitor[pc.concurrent_id] = pc
        else:
            current_score = current_best.score_matching or 0
            new_score = pc.score_matching or 0

            if new_score > current_score:
                best_by_competitor[pc.concurrent_id] = pc

    best_ids = {pc.id for pc in best_by_competitor.values()}

    deleted = 0

    for pc in competitor_products:
        if pc.id not in best_ids:
            db.delete(pc)
            deleted += 1

    db.commit()

    return {
        "status": "success",
        "productId": product_id,
        "rematched": len(best_ids),
        "deletedDuplicates": deleted,
        "message": "Rematching terminé avec conservation du meilleur produit par concurrent.",
    }    