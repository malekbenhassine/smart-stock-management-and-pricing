# ============================================================
# SERVICES PRODUITS CONCURRENTS
# ============================================================

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.models.tables import Product, ProductCompetitor
from app.services.matching_service import compute_match_score, match_status


def _pick(data: dict, *keys, default=None):
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return data.get(key)
    return default


def _to_float(value):
    try:
        if value is None or value == "":
            return None

        return float(
            str(value)
            .replace(",", ".")
            .replace("DT", "")
            .replace("TND", "")
            .strip()
        )
    except Exception:
        return None

# ============================================================
# Règle anti-faux matching par prix
# ============================================================

PRICE_HARD_REJECT_PERCENT = 60.0


def _apply_price_gap_rule(
    score: float,
    details: dict,
    status: str,
    internal_price,
    competitor_price,
):
    """
    Si le prix concurrent est très différent du prix interne,
    on refuse le matching automatiquement.

    Exemple :
    - Produit interne : 1000 DT
    - Produit concurrent : 300 DT
    - Écart : 70%
    => IGNORED

    Cette règle évite de matcher deux produits qui se ressemblent dans le nom
    mais qui ne sont clairement pas du même niveau/gamme.
    """

    details = details or {}
    reasons = list(details.get("reasons") or [])

    internal_price = _to_float(internal_price)
    competitor_price = _to_float(competitor_price)

    if internal_price is None or competitor_price is None:
        return score, details, status

    if internal_price <= 0 or competitor_price <= 0:
        return score, details, status

    price_gap_percent = abs(competitor_price - internal_price) / internal_price * 100

    details["priceCheck"] = {
        "internalPrice": internal_price,
        "competitorPrice": competitor_price,
        "gapPercent": round(price_gap_percent, 2),
        "hardRejectThresholdPercent": PRICE_HARD_REJECT_PERCENT,
    }

    if price_gap_percent >= PRICE_HARD_REJECT_PERCENT:
        reasons.append(
            f"Produit rejeté : prix concurrent très différent du prix interne "
            f"({competitor_price} DT vs {internal_price} DT, écart {round(price_gap_percent, 2)}%)."
        )

        details["same_product"] = False
        details["sameProduct"] = False
        details["score"] = 0
        details["match_type"] = "NO_MATCH"
        details["matchType"] = "NO_MATCH"
        details["status"] = "IGNORED"
        details["reasons"] = reasons
        details["priceMismatch"] = True

        critical = list(details.get("criticalMismatches") or [])
        if "prix" not in critical:
            critical.append("prix")

        details["criticalMismatches"] = critical

        return 0.0, details, "IGNORED"

    details["reasons"] = reasons
    return score, details, status


def _serialize_competitor_product(pc: ProductCompetitor):
    return {
        "id": pc.id,
        "produit_id": pc.produit_id,
        "concurrentId": pc.concurrent_id,
        "concurrent_id": pc.concurrent_id,

        "urlProduit": pc.url_produit,
        "url_produit": pc.url_produit,

        "skuConcurrent": pc.sku_concurrent,
        "sku_concurrent": pc.sku_concurrent,

        "nomProduit": pc.nom_produit,
        "nom_produit": pc.nom_produit,

        "descriptionConcurrent": pc.description_concurrent,
        "description_concurrent": pc.description_concurrent,

        "prixConcurrent": pc.prix_concurrent,
        "prix_concurrent": pc.prix_concurrent,

        "ancienPrixConcurrent": pc.ancien_prix_concurrent,
        "ancien_prix_concurrent": pc.ancien_prix_concurrent,

        "isPromo": pc.is_promo,
        "is_promo": pc.is_promo,

        "disponibilite": pc.disponibilite,

        "dateCollecte": pc.date_collecte.isoformat() if pc.date_collecte else None,
        "date_collecte": pc.date_collecte.isoformat() if pc.date_collecte else None,

        "fiable": pc.fiable,

        "scoreMatching": pc.score_matching,
        "score_matching": pc.score_matching,
        "match_score": pc.score_matching,

        "statutMatching": pc.statut_matching,
        "statut_matching": pc.statut_matching,
        "match_status": pc.statut_matching,

        "detailsMatching": pc.details_matching,
        "details_matching": pc.details_matching,
    }


def _normalize_scraped_item(item: dict):
    produit_scrape = item.get("produitScrape") or item.get("produit_scrape") or item

    produit_id = (
        _pick(item, "produit_id", "product_id")
        or _pick(item.get("produitInterne") or {}, "id")
        or _pick(item.get("produit_interne") or {}, "id")
    )

    concurrent_id = (
        _pick(produit_scrape, "concurrentId", "concurrent_id")
        or _pick(item, "concurrentId", "concurrent_id")
    )

    return {
        "produit_id": produit_id,
        "concurrent_id": concurrent_id,

        "url_produit": _pick(
            produit_scrape,
            "urlProduit",
            "url_produit",
            "url",
            "product_url",
        ),

        "sku_concurrent": _pick(
            produit_scrape,
            "skuConcurrent",
            "sku_concurrent",
            "sku",
            "reference",
            "ref",
        ),

        "nom_produit": _pick(
            produit_scrape,
            "nomProduit",
            "nom_produit",
            "name",
            "product_name",
        ),

        "description_concurrent": _pick(
            produit_scrape,
            "descriptionConcurrent",
            "description_concurrent",
            "description",
        ),

        "prix_concurrent": _to_float(
            _pick(
                produit_scrape,
                "prixConcurrent",
                "prix_concurrent",
                "price",
                "prix",
            )
        ),

        "ancien_prix_concurrent": _to_float(
            _pick(
                produit_scrape,
                "ancienPrixConcurrent",
                "ancien_prix_concurrent",
                "old_price",
                "ancienPrix",
            )
        ),

        "is_promo": bool(
            _pick(
                produit_scrape,
                "isPromo",
                "is_promo",
                default=False,
            )
        ),

        "disponibilite": _pick(
            produit_scrape,
            "disponibilite",
            "availability",
            "stock",
        ),

        # Ces champs peuvent venir du scraping, mais ils ne seront plus utilisés
        # comme vérité finale. Le stock_service recalcule toujours le matching.
        "score_matching": _to_float(
            _pick(
                item,
                "scoreMatching",
                "score_matching",
                "match_score",
                "score",
            )
        ),

        "statut_matching": str(
            _pick(
                item,
                "statutMatching",
                "statut_matching",
                "match_status",
                "statut",
                default="",
            )
            or ""
        ).upper(),

        "details_matching": _pick(
            item,
            "detailsMatching",
            "details_matching",
            "details",
            "raw",
            default={},
        ),
    }


def _build_competitor_matching_text(item: dict) -> str:
    """
    Texte complet utilisé pour le matching.

    Important :
    Le matching doit recevoir aussi la référence concurrente.
    Exemple :
    - sku_concurrent = 912-V812-056
    - url_produit peut aussi contenir une référence utile.
    """
    return " ".join(
        [
            str(item.get("description_concurrent") or ""),
            str(item.get("sku_concurrent") or ""),
            str(item.get("url_produit") or ""),
        ]
    ).strip()


def _build_pc_matching_text(pc: ProductCompetitor) -> str:
    """
    Même logique que _build_competitor_matching_text,
    mais pour les lignes déjà sauvegardées en base.
    """
    return " ".join(
        [
            str(pc.description_concurrent or ""),
            str(pc.sku_concurrent or ""),
            str(pc.url_produit or ""),
        ]
    ).strip()



def _product_search_text(product: Product) -> str:
    return " ".join(
        [
            str(product.nom or ""),
            str(product.marque or ""),
            str(product.categorie or ""),
            str(product.sku or ""),
            str(product.description or ""),
        ]
    ).strip()


def _catalog_item_search_text(item: dict) -> str:
    return " ".join(
        [
            str(item.get("nom_produit") or ""),
            str(item.get("description_concurrent") or ""),
            str(item.get("sku_concurrent") or ""),
            str(item.get("url_produit") or ""),
        ]
    ).strip()


def _get_candidate_internal_products(item: dict, db, limit: int = 250) -> list[Product]:
    """
    Retourne une liste raisonnable de produits internes candidats pour un produit
    concurrent issu du scraping catalogue.

    On évite de comparer contre toute la base quand c'est possible :
    - marque détectée dans le nom concurrent ;
    - mots significatifs du nom ;
    - catégorie éventuelle.
    Si le filtre ne retourne rien, on fait un fallback limité.
    """
    try:
        from app.services.matching_service import extract_brand, normalize_text
    except Exception:
        extract_brand = None
        normalize_text = lambda x: str(x or "").lower()

    text = _catalog_item_search_text(item)
    normalized = normalize_text(text)
    brand = extract_brand(text) if extract_brand else None

    query = db.query(Product)

    if brand:
        like_brand = f"%{brand}%"
        candidates = (
            query.filter(
                (Product.marque.ilike(like_brand))
                | (Product.nom.ilike(like_brand))
                | (Product.description.ilike(like_brand))
            )
            .limit(limit)
            .all()
        )
        if candidates:
            return candidates

    # Mots utiles du titre concurrent. On élimine les mots trop génériques.
    generic = {
        "smartphone", "telephone", "portable", "pc", "ordinateur", "avec",
        "sans", "go", "gb", "to", "tb", "noir", "gris", "blanc", "bleu",
        "rouge", "vert", "rose", "silver", "black", "white", "gray",
        "neuf", "promo", "garantie", "ecran", "full", "hd", "ips",
    }
    tokens = []
    for token in normalized.split():
        token = token.strip()
        if len(token) < 3 or token in generic:
            continue
        if token not in tokens:
            tokens.append(token)

    # On garde les tokens les plus discriminants : chiffres/modèles d'abord.
    tokens.sort(key=lambda t: (not any(ch.isdigit() for ch in t), len(t)))
    tokens = tokens[:6]

    if tokens:
        q = query
        first = True
        from sqlalchemy import or_
        conditions = []
        for token in tokens:
            like = f"%{token}%"
            conditions.append(Product.nom.ilike(like))
            conditions.append(Product.sku.ilike(like))
            conditions.append(Product.description.ilike(like))
        candidates = q.filter(or_(*conditions)).limit(limit).all()
        if candidates:
            return candidates

    return query.limit(limit).all()


def _find_best_internal_product_for_catalog_item(item: dict, db):
    """
    Utilisé pour le scraping catalogue.
    Si le produit concurrent n'a pas produit_id, on cherche automatiquement
    le produit interne le plus proche, puis on laisse matching_service décider
    MATCHED / MANUAL_REVIEW / IGNORED.
    """
    competitor_name = item.get("nom_produit") or ""
    competitor_desc = _build_competitor_matching_text(item)

    if not competitor_name:
        return None, 0.0, {}

    candidates = _get_candidate_internal_products(item, db=db)

    best_product = None
    best_score = 0.0
    best_details = {}

    for product in candidates:
        score, details = compute_match_score(
            internal_name=product.nom or "",
            internal_desc=_product_search_text(product),
            competitor_name=competitor_name,
            competitor_desc=competitor_desc,
        )

        status = match_status(score or 0, details or {})

        # On applique aussi la règle de prix pendant le choix du meilleur candidat.
        score, details, status = _apply_price_gap_rule(
            score=score,
            details=details or {},
            status=status,
            internal_price=product.prix_vente,
            competitor_price=item.get("prix_concurrent"),
        )

        details = details or {}
        details["catalogAutoMatchedCandidate"] = True
        details["catalogCandidateProductId"] = product.id
        details["catalogCandidateStatus"] = status

        if score > best_score:
            best_product = product
            best_score = float(score or 0)
            best_details = details

    return best_product, best_score, best_details


def _should_save_catalog_match(score: float, details: dict | None) -> tuple[bool, str]:
    """
    Pour un scraping catalogue sans produit_id, on sauvegarde seulement les cas utiles :
    - MATCHED
    - MANUAL_REVIEW
    Les IGNORED ne sont pas insérés pour éviter de polluer produits_concurrents.
    """
    status = match_status(score or 0, details or {})
    return status in {"MATCHED", "MANUAL_REVIEW"}, status


def bulk_save_scraped_with_matching(items: list[dict], db):
    """
    Compatibilité avec l'ancien import utilisé par competitor_products.py.
    Sauvegarde les produits scrapés + applique le matching.
    """
    return bulk_save_scraped_competitor_products_service(items, db)


def _item_debug_identity(raw_item: dict) -> dict:
    """
    Retourne une petite trace lisible pour comprendre pourquoi une ligne
    n'est pas sauvegardée.
    """
    try:
        produit_scrape = raw_item.get("produitScrape") or raw_item.get("produit_scrape") or raw_item

        return {
            "produit_id": (
                _pick(raw_item, "produit_id", "product_id")
                or _pick(raw_item.get("produitInterne") or {}, "id")
                or _pick(raw_item.get("produit_interne") or {}, "id")
            ),
            "concurrent_id": (
                _pick(produit_scrape, "concurrentId", "concurrent_id")
                or _pick(raw_item, "concurrentId", "concurrent_id")
            ),
            "nomProduit": _pick(
                produit_scrape,
                "nomProduit",
                "nom_produit",
                "name",
                "product_name",
            ),
            "skuConcurrent": _pick(
                produit_scrape,
                "skuConcurrent",
                "sku_concurrent",
                "sku",
                "reference",
                "ref",
            ),
            "urlProduit": _pick(
                produit_scrape,
                "urlProduit",
                "url_produit",
                "url",
                "product_url",
            ),
        }
    except Exception:
        return {"raw_type": str(type(raw_item))}


def bulk_save_scraped_competitor_products_service(items: list[dict], db):
    """
    Sauvegarde robuste des résultats de scraping.

    Compatible avec deux flux :
    1) Scraping produit spécifique : produit_id est déjà présent.
       → on recalcule le matching et on sauvegarde aussi les IGNORED pour diagnostic.

    2) Scraping catalogue : produit_id est absent.
       → on cherche automatiquement le meilleur produit interne.
       → on sauvegarde seulement MATCHED / MANUAL_REVIEW.
       → les autres lignes sont retournées dans invalid_items avec une raison claire.
    """
    inserted = 0
    updated = 0
    invalid = 0

    results = []
    invalid_items = []

    for raw_item in items or []:
        try:
            if not isinstance(raw_item, dict):
                invalid += 1
                invalid_items.append(
                    {
                        "reason": "item_not_dict",
                        "item": str(raw_item),
                    }
                )
                continue

            item = _normalize_scraped_item(raw_item)

            missing = []
            is_catalog_item = not bool(item.get("produit_id"))

            if not item.get("concurrent_id"):
                missing.append("concurrent_id")

            if not item.get("url_produit"):
                missing.append("urlProduit")

            if not item.get("nom_produit"):
                missing.append("nomProduit")

            if missing:
                invalid += 1
                invalid_items.append(
                    {
                        "reason": "missing_required_fields",
                        "missing": missing,
                        "identity": _item_debug_identity(raw_item),
                    }
                )
                continue

            product = None
            computed_score = 0.0
            computed_details = {}

            if is_catalog_item:
                product, computed_score, computed_details = _find_best_internal_product_for_catalog_item(
                    item=item,
                    db=db,
                )

                if not product:
                    invalid += 1
                    invalid_items.append(
                        {
                            "reason": "catalog_item_no_internal_candidate",
                            "identity": _item_debug_identity(raw_item),
                        }
                    )
                    continue

                should_save, auto_status = _should_save_catalog_match(
                    computed_score,
                    computed_details,
                )

                if not should_save:
                    invalid += 1
                    invalid_items.append(
                        {
                            "reason": "catalog_item_no_reliable_match",
                            "score": computed_score,
                            "status": auto_status,
                            "details": computed_details,
                            "identity": _item_debug_identity(raw_item),
                            "best_product_id": product.id,
                            "best_product_name": product.nom,
                        }
                    )
                    continue

                item["produit_id"] = product.id

            else:
                product = (
                    db.query(Product)
                    .filter(Product.id == int(item["produit_id"]))
                    .first()
                )

                if not product:
                    invalid += 1
                    invalid_items.append(
                        {
                            "reason": "product_not_found",
                            "identity": _item_debug_identity(raw_item),
                        }
                    )
                    continue

                competitor_matching_desc = _build_competitor_matching_text(item)

                computed_score, computed_details = compute_match_score(
                    internal_name=product.nom or "",
                    internal_desc=product.description or "",
                    competitor_name=item["nom_produit"] or "",
                    competitor_desc=competitor_matching_desc,
                )

            score = computed_score
            details = computed_details or {}
            status = match_status(score or 0, details)

            score, details, status = _apply_price_gap_rule(
                score=score,
                details=details,
                status=status,
                internal_price=product.prix_vente,
                competitor_price=item.get("prix_concurrent"),
            )

            # Pour le scraping catalogue, on ne pollue pas la table avec les IGNORED.
            if is_catalog_item and status == "IGNORED":
                invalid += 1
                invalid_items.append(
                    {
                        "reason": "catalog_item_ignored_after_price_or_matching_rule",
                        "score": score,
                        "status": status,
                        "details": details,
                        "identity": _item_debug_identity(raw_item),
                        "best_product_id": product.id,
                        "best_product_name": product.nom,
                    }
                )
                continue

            existing = (
                db.query(ProductCompetitor)
                .filter(
                    ProductCompetitor.produit_id == int(item["produit_id"]),
                    ProductCompetitor.concurrent_id == int(item["concurrent_id"]),
                    ProductCompetitor.url_produit == item["url_produit"],
                )
                .first()
            )

            if existing:
                pc = existing
                was_insert = False
            else:
                pc = ProductCompetitor(
                    produit_id=int(item["produit_id"]),
                    concurrent_id=int(item["concurrent_id"]),
                    url_produit=item["url_produit"],
                )
                db.add(pc)
                was_insert = True

            pc.sku_concurrent = item["sku_concurrent"]
            pc.nom_produit = item["nom_produit"]
            pc.description_concurrent = item["description_concurrent"]
            pc.prix_concurrent = item["prix_concurrent"]
            pc.ancien_prix_concurrent = item["ancien_prix_concurrent"]
            pc.is_promo = item["is_promo"]
            pc.disponibilite = item["disponibilite"]
            pc.date_collecte = datetime.utcnow()

            # Marquer clairement l'origine catalogue pour aider le front/debug.
            details = details or {}
            if is_catalog_item:
                details["source"] = "CATALOG_SCRAPING"
                details["autoLinkedInternalProductId"] = product.id
                details["autoLinkedInternalProductName"] = product.nom

            pc.score_matching = score
            pc.statut_matching = status
            pc.details_matching = details

            pc.fiable = str(status or "").upper() in {
                "MATCHED",
                "AUTO_MATCHED",
                "VALIDATED",
                "MANUAL_VALIDATED",
            }

            db.flush()
            saved_row = _serialize_competitor_product(pc)
            db.commit()

            if was_insert:
                inserted += 1
            else:
                updated += 1

            results.append(saved_row)

        except IntegrityError as e:
            db.rollback()
            invalid += 1
            invalid_items.append(
                {
                    "reason": "integrity_error",
                    "error": str(e.orig) if getattr(e, "orig", None) else str(e),
                    "identity": (
                        _item_debug_identity(raw_item)
                        if isinstance(raw_item, dict)
                        else {"raw": str(raw_item)}
                    ),
                }
            )

        except Exception as e:
            db.rollback()
            invalid += 1
            invalid_items.append(
                {
                    "reason": "exception",
                    "error": str(e),
                    "identity": (
                        _item_debug_identity(raw_item)
                        if isinstance(raw_item, dict)
                        else {"raw": str(raw_item)}
                    ),
                }
            )
            print(
                "[bulk_save_scraped_competitor_products_service] skipped:",
                e,
                flush=True,
            )

    matched = len(
        [
            x
            for x in results
            if str(x.get("statutMatching", "")).upper()
            in {"MATCHED", "AUTO_MATCHED", "VALIDATED", "MANUAL_VALIDATED"}
        ]
    )

    manual_review = len(
        [
            x
            for x in results
            if str(x.get("statutMatching", "")).upper() == "MANUAL_REVIEW"
        ]
    )

    ignored = len(
        [
            x
            for x in results
            if str(x.get("statutMatching", "")).upper() == "IGNORED"
        ]
    )

    manual_items = [
        x for x in results if str(x.get("statutMatching", "")).upper() == "MANUAL_REVIEW"
    ]

    return {
        "status": "success",
        "total_received": len(items or []),
        "inserted": inserted,
        "updated": updated,
        "saved": inserted + updated,
        "rows": inserted + updated,
        "skipped": invalid,
        "invalid": invalid,
        "matched": matched,
        "manual_review": manual_review,
        "ignored": ignored,
        "items": results,
        "manual_items": manual_items,
        "saved_items": results,
        "scraped_products": results,
        "invalid_items": invalid_items,
    }


def get_competitor_products_by_product_service(product_id: int, db):
    rows = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id)
        .order_by(
            ProductCompetitor.score_matching.desc().nullslast(),
            ProductCompetitor.date_collecte.desc().nullslast(),
        )
        .all()
    )

    items = [_serialize_competitor_product(row) for row in rows]

    matched = [
        x
        for x in items
        if str(x.get("statutMatching") or "").upper()
        in {"MATCHED", "AUTO_MATCHED", "VALIDATED", "MANUAL_VALIDATED"}
    ]

    manual = [
        x
        for x in items
        if str(x.get("statutMatching") or "").upper() == "MANUAL_REVIEW"
    ]

    ignored = [
        x
        for x in items
        if str(x.get("statutMatching") or "").upper() == "IGNORED"
    ]

    prices = [
        x.get("prixConcurrent")
        for x in matched
        if x.get("prixConcurrent") is not None
    ]

    return {
        "status": "success",
        "product_id": product_id,
        "total": len(items),
        "items": items,
        "summary": {
            "total": len(items),
            "matched": len(matched),
            "manualReview": len(manual),
            "ignored": len(ignored),
            "bestPrice": min(prices) if prices else None,
            "maxPrice": max(prices) if prices else None,
            "avgPrice": round(sum(prices) / len(prices), 2) if prices else None,
        },
    }


def get_pending_validation_service(db):
    rows = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.statut_matching == "MANUAL_REVIEW")
        .order_by(ProductCompetitor.date_collecte.desc().nullslast())
        .all()
    )

    return {
        "status": "success",
        "total": len(rows),
        "items": [_serialize_competitor_product(row) for row in rows],
    }


def validate_match_service(
    competitor_product_id: int,
    accepted: bool,
    produit_id: int | None,
    db,
):
    pc = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.id == competitor_product_id)
        .first()
    )

    if not pc:
        raise Exception("Produit concurrent introuvable")

    if produit_id:
        pc.produit_id = produit_id

    pc.statut_matching = "MATCHED" if accepted else "IGNORED"
    pc.fiable = bool(accepted)

    details = pc.details_matching or {}
    details["manual_validation"] = True
    details["accepted"] = bool(accepted)
    details["validated_at"] = datetime.utcnow().isoformat()
    details["status"] = pc.statut_matching
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit concurrent validé." if accepted else "Produit concurrent refusé.",
        "item": _serialize_competitor_product(pc),
    }


def unmatch_competitor_product_service(competitor_product_id: int, db):
    pc = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.id == competitor_product_id)
        .first()
    )

    if not pc:
        raise Exception("Produit concurrent introuvable")

    pc.statut_matching = "IGNORED"
    pc.fiable = False

    details = pc.details_matching or {}
    details["unmatched_manually"] = True
    details["status"] = "IGNORED"
    details["unmatched_at"] = datetime.utcnow().isoformat()
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit concurrent dématché.",
        "item": _serialize_competitor_product(pc),
    }


def rematch_product_service(product_id: int, db):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if not product:
        raise Exception("Produit interne introuvable")

    rows = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id)
        .all()
    )

    updated = 0

    for pc in rows:
        competitor_matching_desc = _build_pc_matching_text(pc)

        score, details = compute_match_score(
            internal_name=product.nom or "",
            internal_desc=product.description or "",
            competitor_name=pc.nom_produit or "",
            competitor_desc=competitor_matching_desc,
        )

        status = match_status(score or 0, details or {})

        score, details, status = _apply_price_gap_rule(
            score=score,
            details=details or {},
            status=status,
            internal_price=product.prix_vente,
            competitor_price=pc.prix_concurrent,
        )

        pc.score_matching = score
        pc.details_matching = details or {}
        pc.statut_matching = status
        pc.fiable = str(pc.statut_matching or "").upper() in {
            "MATCHED",
            "AUTO_MATCHED",
            "VALIDATED",
            "MANUAL_VALIDATED",
        }

        updated += 1

    db.commit()

    return {
        "status": "success",
        "product_id": product_id,
        "updated": updated,
        "message": f"{updated} produit(s) concurrent(s) recalculé(s).",
    }