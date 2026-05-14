from __future__ import annotations

import logging
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.services.manager_service import enregistrer_activite
from app.models.tables import Product, ProductCompetitor, SalesHistory, DemandeModificationPrix
from app.services.price_recommendation_service import calculate_price_recommendation
from app.services.stock_movement_service import (
    estimate_demand_from_movements,
    record_stock_trace_only,
)
from app.services.manager_service import enregistrer_activite
logger = logging.getLogger(__name__)

STATUT_PRIX_EN_ATTENTE = "EN_ATTENTE_PRICING"
STATUT_PRIX_RECOMMANDATION_PRETE = "RECOMMANDATION_PRETE"
PRIX_VALIDE = "PRIX_VALIDE"
PRIX_REFUSE = "PRIX_REFUSE"


def serialize_product(p: Product) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "nom": p.nom,
        "categorie": p.categorie,
        "marque": p.marque,
        "description": p.description,
        "prixVente": p.prix_vente,
        "prixCout": p.prix_cout,
        "margeReservee": p.marge_reservee,
        "stockDisponible": p.stock_disponible,
        "stockReserve": p.stock_reserve,
        "stockMinimum": p.stock_minimum,
        "seuilMin": p.seuil_min,
        "seuilMax": p.seuil_max,
        "statut": p.statut,
        "dateDebutObservation": p.date_debut_observation,
        "dateFinObservation": p.date_fin_observation,
        "analyseConcurrentielleStatut": getattr(p, "analyse_concurrentielle_statut", None),
        "analyseConcurrentielleDate": getattr(p, "analyse_concurrentielle_date", None),
        "statutPrix": getattr(p, "statut_prix", None) or STATUT_PRIX_EN_ATTENTE,
        "dateValidationPrix": getattr(p, "date_validation_prix", None),
        "noteValidationPrix": getattr(p, "note_validation_prix", None),
    }


def get_all_products(db: Session, q: str | None = None):
    query = db.query(Product)
    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Product.nom.ilike(search),
                Product.sku.ilike(search),
                Product.marque.ilike(search),
                Product.categorie.ilike(search),
            )
        )
    rows = query.order_by(Product.id.desc()).all()
    return [serialize_product(p) for p in rows]


def get_product_by_id_service(product_id: int, db: Session):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return serialize_product(p)


def get_product_pricing_details_service(product_id: int, db: Session):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return {
        "id": p.id,
        "sku": p.sku,
        "nom": p.nom,
        "prixVente": p.prix_vente,
        "prixCout": p.prix_cout,
        "margeReservee": p.marge_reservee,
        "categorie": p.categorie,
        "marque": p.marque,
        "statutPrix": getattr(p, "statut_prix", None) or STATUT_PRIX_EN_ATTENTE,
        "analyseConcurrentielleStatut": getattr(p, "analyse_concurrentielle_statut", None),
    }


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def get_product_stock_details_service(product_id: int, db: Session):
    """
    Détail stock complet calculé dans stock_service.

    Cette route remplace l'ancien appel frontend vers inference_service :
    GET /products/{id}/stock-details

    Elle retourne exactement les blocs attendus par StockProductDetailPage.jsx :
    - product
    - demand_prediction
    - stock_risk
    - restock_recommendation
    - anomalies
    """
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    current_stock = _safe_float(p.stock_disponible, 0)
    threshold_min = _safe_float(p.seuil_min if p.seuil_min is not None else p.stock_minimum, 0)
    threshold_max = _safe_float(p.seuil_max, 0)

    # Si aucun seuil max n'existe, on crée une cible métier simple et défendable.
    # Exemple : seuil max = seuil min * 3. Si seuil min absent, cible = stock actuel.
    target_stock = threshold_max if threshold_max > 0 else max(threshold_min * 3, current_stock)

    # On se base sur la dernière date disponible en base, pas sur la date du jour,
    # pour éviter les résultats vides si le dataset date de 2024/2025.
    latest_row = None
    history_rows = []
    if p.sku:
        latest_row = (
            db.query(SalesHistory)
            .filter(SalesHistory.product_id == p.sku)
            .order_by(SalesHistory.date.desc())
            .first()
        )

    analysis_days = 30
    if latest_row and latest_row.date:
        end_date = latest_row.date
        start_date = end_date - timedelta(days=analysis_days - 1)
        history_rows = (
            db.query(SalesHistory)
            .filter(SalesHistory.product_id == p.sku)
            .filter(SalesHistory.date >= start_date)
            .filter(SalesHistory.date <= end_date)
            .order_by(SalesHistory.date.asc())
            .all()
        )
    else:
        end_date = None
        start_date = None

    total_sales = sum(_safe_float(row.sales, 0) for row in history_rows)
    avg_daily_sales = total_sales / analysis_days if analysis_days > 0 else 0.0
    weekly_forecast = avg_daily_sales * 7
    demand_source = "historique_ventes" if history_rows else "none"

    # Cas important :
    # Si le produit est nouveau et n'a pas encore d'historique de ventes,
    # on utilise UNIQUEMENT les sorties de stock justifiées comme ventes client.
    # Les casses, pertes, transferts et corrections ne doivent pas créer une fausse demande.
    movement_demand = {"source": "none"}

    if not history_rows:
        movement_demand = estimate_demand_from_movements(
            product_id=p.id,
            db=db,
            days=analysis_days,
        )

    if movement_demand.get("source") == "mouvement_stock_vente_client":
        avg_daily_sales = movement_demand["avg_daily_output"]
        weekly_forecast = movement_demand["weekly_forecast"]
        total_sales = movement_demand["total_output"]
        demand_source = "mouvement_stock_vente_client"

    stock_coverage_days = None
    if avg_daily_sales > 0:
        stock_coverage_days = current_stock / avg_daily_sales

    # Risque métier clair.
    if threshold_max > 0 and current_stock >= threshold_max:
        risk = "OVERSTOCK"
        probability = 0.10
        risk_explanation = (
            "Le stock actuel est supérieur ou égal au seuil maximum. "
            "Le risque principal n'est pas la rupture, mais le surstockage."
        )
    elif current_stock <= 0:
        risk = "STOCKOUT"
        probability = 1.00
        risk_explanation = "Le stock est nul : le risque de rupture est immédiat."
    elif threshold_min > 0 and current_stock <= threshold_min:
        risk = "LOW_STOCK"
        probability = 0.75
        risk_explanation = (
            "Le stock actuel est inférieur ou proche du seuil minimum. "
            "Un réapprovisionnement doit être étudié."
        )
    elif stock_coverage_days is not None and stock_coverage_days <= 7:
        risk = "LOW_STOCK"
        probability = 0.65
        risk_explanation = (
            "Selon le rythme de vente historique, le stock pourrait devenir insuffisant "
            "dans moins d'une semaine."
        )
    else:
        risk = "NORMAL"
        probability = 0.05
        risk_explanation = (
            "Le stock actuel couvre la demande estimée. "
            "Aucun risque de rupture significatif n'est détecté."
        )

    # Recommandation de réassort :
    # - si stock insuffisant ou couverture faible : remonter vers le stock cible
    # - sinon : quantité 0 avec une vraie explication au lieu de '-'
    should_restock = risk in ("STOCKOUT", "LOW_STOCK")
    if should_restock:
        recommended_qty = max(0, int(round(target_stock - current_stock)))
        if recommended_qty == 0 and weekly_forecast > 0:
            recommended_qty = int(round(weekly_forecast))
    else:
        recommended_qty = 0

    if recommended_qty > 0:
        restock_explanation = (
            f"Réassort recommandé de {recommended_qty} unité(s). "
            f"Le stock actuel est de {int(current_stock)} unité(s), avec un seuil minimum de "
            f"{int(threshold_min)} unité(s) et une demande prévisionnelle d'environ "
            f"{round(weekly_forecast, 2)} unité(s) sur 7 jours."
        )
    else:
        restock_explanation = (
            f"Aucun réassort nécessaire pour le moment : le stock actuel ({int(current_stock)}) "
            f"est supérieur au seuil minimum ({int(threshold_min)})."
        )

    demand_explanation = (
        f"Prévision calculée à partir des ventes historiques des {analysis_days} derniers jours "
        f"disponibles pour le SKU {p.sku}."
        if history_rows
        else "Aucun historique de vente trouvé pour ce SKU. La prévision est donc fixée à 0."
    )

    anomalies = []
    if risk == "OVERSTOCK":
        anomalies.append({
            "type": "OVERSTOCK",
            "severity": "MEDIUM",
            "detail": "Surstock détecté : le stock actuel dépasse le seuil maximum défini.",
        })
    if risk == "STOCKOUT":
        anomalies.append({
            "type": "STOCKOUT",
            "severity": "HIGH",
            "detail": "Rupture détectée : le stock actuel est nul.",
        })

    return {
        "product": {
            "product_id": p.id,
            "id": p.id,
            "sku": p.sku,
            "name": p.nom,
            "nom": p.nom,
            "category": p.categorie,
            "categorie": p.categorie,
            "brand": p.marque,
            "marque": p.marque,
            "description": p.description,
            "current_stock": current_stock,
            "stockDisponible": p.stock_disponible,
            "stock": current_stock,
            "threshold_min": threshold_min,
            "seuilMin": p.seuil_min,
            "stockMinimum": p.stock_minimum,
            "threshold_max": threshold_max,
            "seuilMax": p.seuil_max,
            "current_price": p.prix_vente,
            "prixVente": p.prix_vente,
            "cost_price": p.prix_cout,
            "prixCout": p.prix_cout,
            "statut": p.statut,
        },
        "demand_prediction": {
            "p10": round(max(0, weekly_forecast * 0.8), 2),
            "p50": round(max(0, weekly_forecast), 2),
            "p90": round(max(0, weekly_forecast * 1.2), 2),
            "avg_daily_sales": round(avg_daily_sales, 2),
            "period_days": analysis_days,
            "history_rows_count": len(history_rows),
            "demand_source": demand_source,
            "analysis_start_date": str(start_date) if start_date else None,
            "analysis_end_date": str(end_date) if end_date else None,
            "explanation": demand_explanation,
        },
        "stock_risk": {
            "risk": risk,
            "probability": probability,
            "coverage_days": round(stock_coverage_days, 2) if stock_coverage_days is not None else None,
            "explanation": risk_explanation,
            "inputs": {
                "current_stock": current_stock,
                "threshold_min": threshold_min,
                "threshold_max": threshold_max,
                "avg_daily_sales": round(avg_daily_sales, 2),
                "weekly_forecast": round(weekly_forecast, 2),
            },
        },
        "restock_recommendation": {
            "recommended_qty": recommended_qty,
            "recommended_restock_qty": recommended_qty,
            "forecast_weekly_demand": round(weekly_forecast, 2),
            "current_stock": current_stock,
            "target_stock": target_stock,
            "lead_time_days": 7,
            "explanation": restock_explanation,
        },
        "anomalies": {
            "count": len(anomalies),
            "anomalies": anomalies,
        },
    }

def create_product_service(payload, db: Session):
    existing = db.query(Product).filter(Product.sku == payload.sku).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Un produit avec ce SKU existe déjà",
        )

    obj = Product(
        sku=payload.sku,
        nom=payload.nom,
        categorie=payload.categorie,
        marque=payload.marque,
        description=payload.description,
        prix_cout=payload.prixCout,
        prix_vente=payload.prixVente,
        marge_reservee=payload.margeReservee,
        stock_disponible=payload.stockDisponible or 0,
        stock_reserve=payload.stockReserve or 0,
        stock_minimum=payload.stockMinimum,
        seuil_max=payload.seuilMax,
        seuil_min=payload.seuilMin,
        statut=payload.statut or "actif",
        date_debut_observation=payload.dateDebutObservation,
        date_fin_observation=payload.dateFinObservation,
    )

    if hasattr(obj, "statut_prix"):
        obj.statut_prix = STATUT_PRIX_EN_ATTENTE

    if hasattr(obj, "analyse_concurrentielle_statut"):
        obj.analyse_concurrentielle_statut = "NOT_STARTED"

    db.add(obj)
    db.commit()
    db.refresh(obj)
    enregistrer_activite(
        db=db,
        role_utilisateur="RESPONSABLE_STOCK",
        nom_utilisateur="Responsable stock",
        type_action="CREATION_PRODUIT",
        type_entite="PRODUIT",
        entite_id=obj.id,
        produit_id=obj.id,
        description=f"Création du produit : {obj.nom}",
        donnees={
            "sku": obj.sku,
            "nom": obj.nom,
            "categorie": obj.categorie,
            "marque": obj.marque,
            "prixVente": obj.prix_vente,
            "stockDisponible": obj.stock_disponible,
        },
    )
    db.commit()
    initial_stock = _safe_int(obj.stock_disponible, 0)

    if initial_stock > 0:
        record_stock_trace_only(
            db=db,
            produit_id=obj.id,
            movement_type="ENTREE",
            quantite=initial_stock,
            justification="Stock initial lors de l'ajout du produit",
        )
        db.commit()

    db.refresh(obj)

    return serialize_product(obj)



def update_product_service(product_id: int, payload, db: Session):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    data = payload.model_dump(exclude_unset=True)

    if "sku" in data and data["sku"] != obj.sku:
        existing = db.query(Product).filter(Product.sku == data["sku"], Product.id != product_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Un autre produit utilise déjà ce SKU")

    mapping = {
        "sku": "sku",
        "nom": "nom",
        "categorie": "categorie",
        "marque": "marque",
        "description": "description",
        "prixCout": "prix_cout",
        "prixVente": "prix_vente",
        "margeReservee": "marge_reservee",
        "stockDisponible": "stock_disponible",
        "stockReserve": "stock_reserve",
        "stockMinimum": "stock_minimum",
        "seuilMax": "seuil_max",
        "seuilMin": "seuil_min",
        "statut": "statut",
        "dateDebutObservation": "date_debut_observation",
        "dateFinObservation": "date_fin_observation",
    }

    for key, value in data.items():
        if key in mapping:
            setattr(obj, mapping[key], value)

    db.commit()
    db.refresh(obj)
    return serialize_product(obj)


def delete_product_service(product_id: int, db: Session):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    db.delete(obj)
    db.commit()
    return {"message": "Produit supprimé avec succès"}


def get_pending_pricing_products_service(db: Session) -> dict:
    products = db.query(Product).order_by(Product.id.desc()).all()
    items = []

    for p in products:
        statut_prix = getattr(p, "statut_prix", None) or STATUT_PRIX_EN_ATTENTE
        analysis_status = getattr(p, "analyse_concurrentielle_statut", None) or "NOT_STARTED"

        matched_count = (
            db.query(ProductCompetitor)
            .filter(
                ProductCompetitor.produit_id == p.id,
                ProductCompetitor.statut_matching == "MATCHED",
            )
            .count()
        )

        # On affiche dans la liste pricing tout produit non validé ou avec analyse exploitable.
        if statut_prix == PRIX_VALIDE:
            continue

        item = serialize_product(p)
        item["matchedCompetitorProducts"] = matched_count
        item["analyseConcurrentielleStatut"] = analysis_status
        item["statutPrix"] = statut_prix

        if analysis_status == "RUNNING":
            item["workflowLabel"] = "Analyse concurrentielle en cours"
        elif matched_count > 0:
            item["workflowLabel"] = "Recommandation disponible"
        elif analysis_status == "DONE":
            item["workflowLabel"] = "Analyse terminée sans concurrent matché"
        else:
            item["workflowLabel"] = "En attente d'analyse"

        items.append(item)

    return {
        "status": "success",
        "total": len(items),
        "items": items,
    }


def update_product_price_service(product_id: int, new_price: float, justification: str | None, db: Session):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    if new_price is None or new_price < 0:
        raise HTTPException(status_code=400, detail="Le nouveau prix doit être >= 0")

    old_price = float(product.prix_vente or 0)
    if old_price <= 0:
        variation_percent = 100.0
    else:
        variation_percent = ((float(new_price) - old_price) / old_price) * 100

    justification_clean = justification.strip() if justification else None

    if abs(variation_percent) >= 50:
        if not justification_clean:
            raise HTTPException(
                status_code=400,
                detail="Une justification est obligatoire pour une variation de prix supérieure ou égale à ±50%.",
            )

        demande = DemandeModificationPrix(
            produit_id=product.id,
            ancien_prix=old_price,
            nouveau_prix=float(new_price),
            variation_pourcentage=round(variation_percent, 2),
            justification=justification_clean,
            source_recommandation="PRICING",
            strategie="competitive",
            statut="EN_ATTENTE_MANAGER",
            demande_par="RESPONSABLE_PRICING",
        )
        db.add(demande)
        db.flush()

        product.statut_prix = "EN_ATTENTE_MANAGER"
        product.note_validation_prix = justification_clean

        enregistrer_activite(
            db,
            role_utilisateur="PRICING",
            type_action="DEMANDE_MODIFICATION_PRIX",
            type_entite="DEMANDE_MODIFICATION_PRIX",
            entite_id=demande.id,
            produit_id=product.id,
            description=f"Le responsable pricing a demandé une modification du prix de {old_price} à {new_price} pour le produit {product.nom}. Validation manager obligatoire car variation = {round(variation_percent, 2)}%.",
            donnees={
                "ancienPrix": old_price,
                "nouveauPrix": float(new_price),
                "variationPourcentage": round(variation_percent, 2),
                "justification": justification_clean,
            },
        )

        db.commit()
        db.refresh(demande)
        db.refresh(product)

        return {
            "status": "EN_ATTENTE_MANAGER",
            "message": "La variation du prix dépasse ±50%. La demande a été envoyée au manager pour validation.",
            "demandeId": demande.id,
            "product": serialize_product(product),
            "oldPrixVente": old_price,
            "newPrixVente": float(new_price),
            "variationPercent": round(variation_percent, 2),
            "managerValidationRequired": True,
            "justificationRequired": True,
            "justificationProvided": True,
            "justification": justification_clean,
        }

    product.prix_vente = float(new_price)
    product.statut_prix = PRIX_VALIDE
    product.date_validation_prix = datetime.utcnow()
    product.note_validation_prix = justification_clean

    enregistrer_activite(
        db,
        role_utilisateur="PRICING",
        type_action="VALIDATION_PRIX_DIRECTE",
        type_entite="PRODUIT",
        entite_id=product.id,
        produit_id=product.id,
        description=f"Le responsable pricing a validé directement le prix du produit {product.nom} : {old_price} → {new_price}.",
        donnees={
            "ancienPrix": old_price,
            "nouveauPrix": float(new_price),
            "variationPourcentage": round(variation_percent, 2),
            "justification": justification_clean,
        },
    )

    db.commit()
    db.refresh(product)

    return {
        "status": "PRIX_VALIDE",
        "message": "Prix validé directement avec succès.",
        "product": serialize_product(product),
        "oldPrixVente": old_price,
        "newPrixVente": float(new_price),
        "variationPercent": round(variation_percent, 2),
        "managerValidationRequired": False,
        "justificationRequired": False,
        "justificationProvided": bool(justification_clean),
        "justification": justification_clean,
    }


def approve_product_price_service(
    product_id: int,
    prix_valide: float,
    justification: str | None,
    db: Session,
) -> dict:
    return update_product_price_service(
        product_id=product_id,
        new_price=prix_valide,
        justification=justification,
        db=db,
    )


def calculate_initial_price_recommendation_service(product_id: int, db: Session):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return calculate_price_recommendation(product_id=product.id, db=db)
