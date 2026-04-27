from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models.tables import (
    Supplier, SupplierOrder, SupplierOrderLine, Sale, SaleLine,
    Promotion, ProductPromotion, Competitor, ProductCompetitor, StockMovement
)
from ...schemas.schemas import (
    SupplierIn, SupplierOrderIn, SupplierOrderLineIn, SaleIn, SaleLineIn,
    PromotionIn, ProductPromotionIn, CompetitorIn, ProductCompetitorIn, StockMovementIn
)

router = APIRouter(tags=["bulk-imports"])


@router.post("/suppliers/bulk")
def bulk_suppliers(items: list[SupplierIn], db: Session = Depends(get_db)):
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
def bulk_supplier_order_lines(items: list[SupplierOrderLineIn], db: Session = Depends(get_db)):
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
def bulk_product_promotions(items: list[ProductPromotionIn], db: Session = Depends(get_db)):
    for item in items:
        obj = db.query(ProductPromotion).filter(
            ProductPromotion.produit_id == item.produit_id,
            ProductPromotion.promotion_id == item.promotion_id
        ).first()
        if not obj:
            obj = ProductPromotion(
                produit_id=item.produit_id,
                promotion_id=item.promotion_id
            )
            db.add(obj)
        obj.prix_promo = item.prixpromo
    db.commit()
    return {"status": "success", "rows": len(items)}

def normalize_site_url(raw_url: str | None) -> tuple[str | None, str | None]:
    if not raw_url:
        return None, None

    parsed = urlparse(str(raw_url).strip())
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
    for item in items:
        obj = db.query(Competitor).filter(Competitor.id == item.id).first()
        if not obj:
            obj = Competitor(id=item.id)
            db.add(obj)

        normalized_site, host = normalize_site_url(item.siteurl)

        obj.nom = item.nom
        obj.site_url = normalized_site or f"https://competitor-{item.id}.local/"
        obj.site_host_normalized = host or f"competitor-{item.id}.local"
        obj.actif = bool(item.actif) if item.actif is not None else True
        obj.frequence_scraping_heures = item.frequencescrapingheures or 24
        obj.dernier_scraping = item.dernierscraping
        obj.discovery_status = "ready" if normalized_site else "pending"
        obj.auto_keywords_json = obj.auto_keywords_json or []
        obj.selectors_override_json = obj.selectors_override_json or {}

    db.commit()
    return {"status": "success", "rows": len(items)}

@router.post("/product-competitors/bulk")
def bulk_product_competitors(items: list[ProductCompetitorIn], db: Session = Depends(get_db)):
    for item in items:
        obj = db.query(ProductCompetitor).filter(ProductCompetitor.id == item.id).first()
        if not obj:
            obj = ProductCompetitor(id=item.id)
            db.add(obj)
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
    db.commit()
    return {"status": "success", "rows": len(items)}


@router.post("/stock-movements/bulk")
def bulk_stock_movements(items: list[StockMovementIn], db: Session = Depends(get_db)):
    for item in items:
        obj = db.query(StockMovement).filter(StockMovement.id == item.id).first()
        if not obj:
            obj = StockMovement(id=item.id)
            db.add(obj)
        obj.produit_id = item.produit_id
        obj.type = item.type
        obj.quantite = item.quantite
        obj.date_mouvement = item.datemouvement
        obj.justification = item.justification
    db.commit()
    return {"status": "success", "rows": len(items)}