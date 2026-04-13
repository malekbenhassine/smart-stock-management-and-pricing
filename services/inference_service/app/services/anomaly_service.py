from sqlalchemy.orm import Session

from app.services.stock_client import (
    get_product_from_stock_service,
    get_recent_history_from_stock_service,
)

def _score_to_severity(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    return "MEDIUM"


def detect_anomalies_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)

    current_stock = float(product.get("current_stock", 0.0))
    current_price = float(product.get("current_price", 0.0))
    threshold_min = float(product.get("threshold_min", 0.0))
    threshold_max = float(product.get("threshold_max", 0.0))

    sku = str(product.get("sku") or product.get("product_id") or product.get("id"))
    history_rows = get_recent_history_from_stock_service(product_id=sku, limit=30)

    anomalies = []

    if history_rows:
        sales_values = [float(r.get("sales") or 0.0) for r in history_rows]
        price_values = [float(r.get("price") or 0.0) for r in history_rows]
        stock_values = [float(r.get("stock") or 0.0) for r in history_rows if r.get("stock") is not None]
        avg_sales = sum(sales_values) / len(sales_values) if sales_values else 0.0
        avg_price = sum(price_values) / len(price_values) if price_values else current_price
        avg_stock = sum(stock_values) / len(stock_values) if stock_values else current_stock

        if current_stock <= threshold_min:
            score = round(min(0.99, (threshold_min - current_stock + 1) / max(threshold_min + 1, 1)), 3)
            anomalies.append({
                "severity": _score_to_severity(score),
                "type": "LOW_STOCK",
                "detail": f"(score={score}). Le stock actuel est inférieur ou égal au seuil minimum."
            })

        if threshold_max > 0 and current_stock >= threshold_max:
            score = round(min(0.99, (current_stock - threshold_max + 1) / max(threshold_max + 1, 1)), 3)
            anomalies.append({
                "severity": _score_to_severity(score),
                "type": "OVERSTOCK",
                "detail": f"(score={score}). Le stock actuel dépasse le seuil maximum."
            })

        if avg_price > 0:
            relative_gap = abs(current_price - avg_price) / avg_price
            if relative_gap >= 0.20:
                score = round(min(0.99, relative_gap), 3)
                anomalies.append({
                    "severity": _score_to_severity(score),
                    "type": "PRICE_SHIFT",
                    "detail": f"(score={score}). Le prix actuel s’écarte fortement du prix moyen récent."
                })

        if avg_stock > 0:
            stock_gap = abs(current_stock - avg_stock) / avg_stock
            if stock_gap >= 0.50:
                score = round(min(0.99, stock_gap), 3)
                anomalies.append({
                    "severity": _score_to_severity(score),
                    "type": "STOCK_SHIFT",
                    "detail": f"(score={score}). Le niveau de stock diffère fortement de l’historique récent."
                })

        if avg_sales == 0 and current_stock > 0:
            score = 0.82
            anomalies.append({
                "severity": "HIGH",
                "type": "NO_SALES_WITH_STOCK",
                "detail": f"(score={score}). Aucun mouvement de vente récent malgré un stock disponible."
            })

    else:
        if current_stock <= threshold_min:
            anomalies.append({
                "severity": "HIGH",
                "type": "LOW_STOCK",
                "detail": "(score=0.900). Stock faible détecté sans historique suffisant."
            })
        elif threshold_max > 0 and current_stock >= threshold_max:
            anomalies.append({
                "severity": "MEDIUM",
                "type": "OVERSTOCK",
                "detail": "(score=0.700). Surstock détecté sans historique suffisant."
            })

    anomaly_detected = len(anomalies) > 0
    max_score = 0.0

    for anomaly in anomalies:
        try:
            score_str = anomaly["detail"].split("score=")[1].split(")")[0]
            max_score = max(max_score, float(score_str))
        except Exception:
            pass

    explanation = (
        "Des écarts inhabituels ont été détectés sur ce produit."
        if anomaly_detected
        else "Aucune anomalie significative détectée."
    )

    return {
        "product_id": product_id,
        "anomaly_detected": anomaly_detected,
        "anomaly_score": round(max_score, 3),
        "explanation": explanation,
        "anomalies": anomalies,
    }