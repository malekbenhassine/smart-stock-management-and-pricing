from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models.tables import (
    Supplier,
    SupplierOrder,
    SupplierOrderLine,
    Sale,
    SaleLine,
    Promotion,
    ProductPromotion,
    Competitor,
    ProductCompetitor,
    StockMovement,
)
from ...schemas.schemas import (
    SupplierIn,
    SupplierOrderIn,
    SupplierOrderLineIn,
    SaleIn,
    SaleLineIn,
    PromotionIn,
    ProductPromotionIn,
    CompetitorIn,
    ProductCompetitorIn,
    StockMovementIn,
)

router = APIRouter(tags=["bulk-imports"])


@router.post("/suppliers/bulk")
def bulk_suppliers(items: list[SupplierIn], db: Session = Depends(get_db)):
    """
    On garde le fonctionnement par id pour les fournisseurs,
    car les commandes fournisseurs peuvent dépendre de ces ids dans les CSV.
    """
    for item in items:
        obj = db.query(Supplier).filter(Supplier.id == item.id).first()
        if not obj:
            obj = Supplier(id=item.id)
            db.add(obj)

        obj.nom = item.nom
        obj.tel = item.tel
        obj.adresse = item.adresse
        obj.lead_time_jours = item.leadtimejours
        obj.score_fiabilite = item.scorefiabilite

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/supplier-orders/bulk")
def bulk_supplier_orders(items: list[SupplierOrderIn], db: Session = Depends(get_db)):
    """
    On garde le fonctionnement par id pour préserver les relations avec lignes_commandes.
    """
    for item in items:
        obj = db.query(SupplierOrder).filter(SupplierOrder.id == item.id).first()
        if not obj:
            obj = SupplierOrder(id=item.id)
            db.add(obj)

        obj.fournisseur_id = item.fournisseur_id
        obj.id_commande = item.idcommande
        obj.date_commande = item.datecommande
        obj.date_reception_prevue = item.datereceptionprevue
        obj.date_reception_reelle = item.datereceptionreelle
        obj.statut = item.statut

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/supplier-order-lines/bulk")
def bulk_supplier_order_lines(
    items: list[SupplierOrderLineIn],
    db: Session = Depends(get_db),
):
    """
    On garde le fonctionnement par id pour préserver l'import relationnel.
    """
    for item in items:
        obj = db.query(SupplierOrderLine).filter(SupplierOrderLine.id == item.id).first()
        if not obj:
            obj = SupplierOrderLine(id=item.id)
            db.add(obj)

        obj.commande_id = item.commande_id
        obj.produit_id = item.produit_id
        obj.quantite_commandee = item.quantitecommandee
        obj.quantite_recue = item.quantiterecue
        obj.prix_achat_unitaire = item.prixachatunitaire

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/sales/bulk")
def bulk_sales(items: list[SaleIn], db: Session = Depends(get_db)):
    """
    On garde le fonctionnement par id pour préserver les relations avec lignes_ventes.
    """
    for item in items:
        obj = db.query(Sale).filter(Sale.id == item.id).first()
        if not obj:
            obj = Sale(id=item.id)
            db.add(obj)

        obj.date_vente = item.datevente
        obj.source = item.source
        obj.statut = item.statut

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/sale-lines/bulk")
def bulk_sale_lines(items: list[SaleLineIn], db: Session = Depends(get_db)):
    """
    On garde le fonctionnement par id pour préserver l'import relationnel.
    """
    for item in items:
        obj = db.query(SaleLine).filter(SaleLine.id == item.id).first()
        if not obj:
            obj = SaleLine(id=item.id)
            db.add(obj)

        obj.vente_id = item.vente_id
        obj.produit_id = item.produit_id
        obj.quantite = item.quantite
        obj.prix_vente_unitaire = item.prixventeunitaire

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/promotions/bulk")
def bulk_promotions(items: list[PromotionIn], db: Session = Depends(get_db)):
    """
    On garde le fonctionnement par id car produit_promotion dépend de promotion_id.
    """
    for item in items:
        obj = db.query(Promotion).filter(Promotion.id == item.id).first()
        if not obj:
            obj = Promotion(id=item.id)
            db.add(obj)

        obj.nom = item.nom
        obj.type = item.type
        obj.valeur = item.valeur
        obj.date_debut = item.datedebut
        obj.date_fin = item.datefin
        obj.stock_minimum_requis = item.stockminimumrequis
        obj.actif = item.actif
        obj.prix_promo = item.prixpromo

    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/product-promotions/bulk")
def bulk_product_promotions(
    items: list[ProductPromotionIn],
    db: Session = Depends(get_db),
):
    for item in items:
        obj = (
            db.query(ProductPromotion)
            .filter(
                ProductPromotion.produit_id == item.produit_id,
                ProductPromotion.promotion_id == item.promotion_id,
            )
            .first()
        )

        if not obj:
            obj = ProductPromotion(
                produit_id=item.produit_id,
                promotion_id=item.promotion_id,
            )
            db.add(obj)

        obj.prix_promo = item.prixpromo

    db.commit()
    return {"status": "success", "rows": len(items)}


def normalize_site_url(raw_url: str | None) -> tuple[str | None, str | None]:
    if not raw_url:
        return None, None

    raw = str(raw_url).strip()

    if not raw:
        return None, None

    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or "").lower().strip()

    if host.startswith("www."):
        host = host[4:]

    if not host:
        return None, None

    normalized = urlunparse((scheme, host, "/", "", "", ""))
    return normalized, host


@router.post("/competitors/bulk")
def bulk_competitors(items: list[CompetitorIn], db: Session = Depends(get_db)):
    """
    Import concurrents.

    Règle métier :
    - L'id CSV est ignoré.
    - Le concurrent est reconnu par site_host_normalized / site_url.
    - Si trouvé : update.
    - Sinon : create avec nouvel id DB.
    """

    rows_processed = 0
    created_count = 0
    updated_count = 0
    ignored_rows = []

    for index, item in enumerate(items, start=1):
        if not item.nom or not str(item.nom).strip():
            ignored_rows.append(
                {
                    "row": index,
                    "reason": "Nom concurrent manquant.",
                }
            )
            continue

        normalized_site, host = normalize_site_url(item.siteurl)

        if not normalized_site or not host:
            ignored_rows.append(
                {
                    "row": index,
                    "nom": item.nom,
                    "reason": "siteurl invalide ou manquant.",
                }
            )
            continue

        obj = (
            db.query(Competitor)
            .filter(Competitor.site_host_normalized == host)
            .first()
        )

        if not obj:
            obj = (
                db.query(Competitor)
                .filter(Competitor.site_url == normalized_site)
                .first()
            )

        is_new = obj is None

        if is_new:
            obj = Competitor()
            db.add(obj)
            created_count += 1
        else:
            updated_count += 1

        obj.nom = str(item.nom).strip()
        obj.site_url = normalized_site
        obj.site_host_normalized = host
        obj.actif = bool(item.actif) if item.actif is not None else True
        obj.frequence_scraping_heures = item.frequencescrapingheures or 24
        obj.dernier_scraping = item.dernierscraping

        # Ne pas écraser ready en pending si le concurrent était déjà découvert.
        if not obj.discovery_status:
            obj.discovery_status = "pending"

        obj.auto_keywords_json = obj.auto_keywords_json or []
        obj.selectors_override_json = obj.selectors_override_json or {}

        rows_processed += 1

    db.commit()

    return {
        "status": "success",
        "message": "Import concurrents terminé. L'id CSV a été ignoré, l'upsert s'est fait par site_url / host.",
        "rows_received": len(items),
        "rows_processed": rows_processed,
        "created": created_count,
        "updated": updated_count,
        "ignored": len(ignored_rows),
        "ignored_rows": ignored_rows,
    }


@router.post("/product-competitors/bulk")
def bulk_product_competitors(
    items: list[ProductCompetitorIn],
    db: Session = Depends(get_db),
):
    """
    Import produits concurrents.

    Règle :
    - L'id est optionnel.
    - Si id fourni et trouvé : update.
    - Sinon on cherche par produit_id + concurrent_id + url_produit.
    - Sinon create.
    """

    rows_processed = 0
    created_count = 0
    updated_count = 0
    ignored_rows = []

    for index, item in enumerate(items, start=1):
        if not item.concurrent_id or not item.produit_id:
            ignored_rows.append(
                {
                    "row": index,
                    "reason": "concurrent_id ou produit_id manquant.",
                }
            )
            continue

        obj = None

        if item.id is not None:
            obj = db.query(ProductCompetitor).filter(ProductCompetitor.id == item.id).first()

        if not obj and item.urlproduit:
            obj = (
                db.query(ProductCompetitor)
                .filter(
                    ProductCompetitor.produit_id == item.produit_id,
                    ProductCompetitor.concurrent_id == item.concurrent_id,
                    ProductCompetitor.url_produit == item.urlproduit,
                )
                .first()
            )

        is_new = obj is None

        if is_new:
            obj = ProductCompetitor()
            db.add(obj)
            created_count += 1
        else:
            updated_count += 1

        obj.url_produit = item.urlproduit
        obj.sku_concurrent = item.skuconcurrent
        obj.nom_produit = item.nomproduit
        obj.concurrent_id = item.concurrent_id
        obj.produit_id = item.produit_id
        obj.prix_concurrent = item.prixconcurrent
        obj.is_promo = item.ispromo
        obj.disponibilite = item.disponibilite
        obj.date_collecte = item.datecollecte
        obj.fiable = item.fiable

        rows_processed += 1

    db.commit()

    return {
        "status": "success",
        "message": "Import produits concurrents terminé.",
        "rows_received": len(items),
        "rows_processed": rows_processed,
        "created": created_count,
        "updated": updated_count,
        "ignored": len(ignored_rows),
        "ignored_rows": ignored_rows,
    }


@router.post("/stock-movements/bulk")
def bulk_stock_movements(items: list[StockMovementIn], db: Session = Depends(get_db)):
    """
    Import mouvements de stock.

    Règle :
    - L'id CSV est ignoré.
    - Chaque ligne crée un nouveau mouvement.
    - La DB génère l'id.
    """

    rows_processed = 0
    created_count = 0
    ignored_rows = []

    for index, item in enumerate(items, start=1):
        if not item.produit_id:
            ignored_rows.append(
                {
                    "row": index,
                    "reason": "produit_id manquant.",
                }
            )
            continue

        if not item.type or not str(item.type).strip():
            ignored_rows.append(
                {
                    "row": index,
                    "reason": "type manquant.",
                }
            )
            continue

        if item.quantite is None or item.quantite <= 0:
            ignored_rows.append(
                {
                    "row": index,
                    "reason": "quantité invalide.",
                }
            )
            continue

        obj = StockMovement()
        db.add(obj)

        obj.produit_id = item.produit_id
        obj.type = str(item.type).strip()
        obj.quantite = item.quantite
        obj.date_mouvement = item.datemouvement
        obj.justification = item.justification

        rows_processed += 1
        created_count += 1

    db.commit()

    return {
        "status": "success",
        "message": "Import mouvements terminé. L'id CSV a été ignoré.",
        "rows_received": len(items),
        "rows_processed": rows_processed,
        "created": created_count,
        "ignored": len(ignored_rows),
        "ignored_rows": ignored_rows,
    }