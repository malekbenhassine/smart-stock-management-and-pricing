from sqlalchemy.orm import Session

from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.price_service import recommend_price_service
from app.services.restock_service import recommend_restock_service


def recommend_promo_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    price_result = recommend_price_service(req, db)
    restock_result = recommend_restock_service(req, db)

    current_price = float(product.get("current_price", 0.0))
    threshold_max = float(product.get("threshold_max", 0.0))
    current_stock = float(product.get("current_stock", 0.0))

    should_promote = False
    recommended_discount = 0.0
    reason_parts = []

    if threshold_max > 0 and current_stock >= threshold_max:
        should_promote = True
        recommended_discount = 10.0
        reason_parts.append("Stock au-dessus du seuil maximum.")

    if current_price > 0 and price_result.recommended_price < current_price:
        should_promote = True
        recommended_discount = max(
            recommended_discount,
            round((current_price - price_result.recommended_price) / current_price * 100, 2)
        )
        reason_parts.append("Le pricing recommande une baisse de prix.")

    if restock_result.urgency in ["high", "critical"]:
        should_promote = False
        recommended_discount = 0.0
        reason_parts = [
            "Promotion déconseillée : le stock est déjà faible ou en risque de rupture."
        ]

    recommended_discount = min(max(recommended_discount, 0.0), 25.0)
    promo_price = round(current_price * (1 - recommended_discount / 100), 2)

    explanation = (
        " ".join(reason_parts)
        if reason_parts
        else ("Une promotion peut accélérer l’écoulement du stock." if should_promote else "Aucune promotion recommandée pour le moment.")
    )

    return {
        "product_id": product_id,

        # champs principaux
        "should_promote": should_promote,
        "recommended_discount": recommended_discount,
        "promo_price": promo_price,
        "explanation": explanation,

        "promotion_recommended": should_promote,
        "promo_recommendation": "Oui" if should_promote else "Non",
        "discount_percent": recommended_discount,
        "discount_rate": recommended_discount,
        "promotional_price": promo_price,
        "recommended_price_after_discount": promo_price,
        "reasoning": explanation,
        "message": explanation,
    }