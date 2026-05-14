
"""
Reconstruit toutes les features nécessaires au modèle à partir de
l'historique des ventes stocké en base, pour une date cible donnée.

Version adaptée au projet :
- tolère les champs absents ou inconnus
- évite d'inventer des valeurs métier incohérentes
- reste compatible avec les modèles déjà entraînés
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.services.stock_client import get_sales_history_from_stock_service


def _season(month: int) -> str:
    return {
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Autumn", 10: "Autumn", 11: "Autumn",
    }.get(month, "Winter")


HOLIDAY_DATES = {
    (1, 1), (2, 14), (4, 1), (7, 4), (10, 31),
    (11, 25), (11, 26), (12, 24), (12, 25), (12, 31)
}


def _is_holiday(d: date) -> int:
    return int((d.month, d.day) in HOLIDAY_DATES)


# ── Chargement de l'historique ───────────────────────────────────────────────

def _fetch_history(
    db: Session,
    store_id: str,
    product_id: str,
    target_date: date,
    n_days: int = 90,
) -> pd.DataFrame:
    rows = get_sales_history_from_stock_service(
        store_id=store_id,
        product_id=product_id,
        target_date=target_date.isoformat(),
        n_days=n_days,
    )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)

# ── Construction des features ────────────────────────────────────────────────

def build_features(
    db: Session,
    store_id: str,
    product_id: str,
    target_date: date,
    price: float,
    stock: float,
    discount: float = 0.0,
    competitor_pricing: float = None,
    units_ordered: float = 0.0,
    weather_condition: str = None,
    category: str = None,
    region: str = None,
    trained_features: list = None,
) -> dict:
    """
    Retourne un dict de features prêt pour model.predict().
    Utilise l'historique DB pour les lags et rolling stats.
    """

    hist = _fetch_history(db, store_id, product_id, target_date)
    has_history = not hist.empty

    # Valeurs par défaut sûres
    effective_competitor_pricing = competitor_pricing if competitor_pricing is not None else price
    effective_units_ordered = units_ordered if units_ordered is not None else 0.0
    effective_weather = weather_condition if weather_condition else "Unknown"
    effective_region = region if region else "UNKNOWN"
    effective_category = category if category else "UNKNOWN"

    # ── Série des ventes passées (indexée par date) ─────────────────────────
    if has_history:
        hist = hist.sort_values("date").set_index("date")
        sales_series = hist["sales"]
        price_series = hist["price"]
    else:
        sales_series = pd.Series(dtype=float)
        price_series = pd.Series(dtype=float)

    def lag(n: int):
        """Ventes il y a n jours."""
        target_minus_n = target_date - timedelta(days=n)
        if target_minus_n in sales_series.index:
            return float(sales_series[target_minus_n])
        return np.nan

    def rolling_mean(window: int):
        recent = sales_series.tail(window)
        return float(recent.mean()) if len(recent) > 0 else np.nan

    def rolling_std(window: int):
        recent = sales_series.tail(window)
        return float(recent.std()) if len(recent) > 1 else 0.0

    def rolling_max(window: int):
        recent = sales_series.tail(window)
        return float(recent.max()) if len(recent) > 0 else np.nan

    def rolling_min(window: int):
        recent = sales_series.tail(window)
        return float(recent.min()) if len(recent) > 0 else np.nan

    lag1 = lag(1)
    lag2 = lag(2)
    rm7 = rolling_mean(7)
    rm14 = rolling_mean(14)
    rm30 = rolling_mean(30)

    # ── Features temporelles ────────────────────────────────────────────────
    d = pd.Timestamp(target_date)
    month = d.month
    dow = d.weekday()
    season = _season(month)
    holiday = _is_holiday(target_date)

    last_price = float(price_series.iloc[-1]) if len(price_series) > 0 else float(price)

    feats = {
        # Prix
        "price": float(price),
        "price_lag_1": last_price,
        "price_change": (
            (float(price) - last_price) / (last_price + 1e-9)
            if len(price_series) > 0 else 0.0
        ),

        # Temporelles
        "day": int(d.day),
        "month": int(month),
        "day_of_week": int(dow),
        "week_of_year": int(d.isocalendar().week),
        "is_weekend": int(dow >= 5),
        "quarter": int(d.quarter),
        "is_month_start": int(d.is_month_start),
        "is_month_end": int(d.is_month_end),
        "is_quarter_start": int(d.is_quarter_start),
        "is_quarter_end": int(d.is_quarter_end),
        "month_sin": float(np.sin(2 * np.pi * month / 12)),
        "month_cos": float(np.cos(2 * np.pi * month / 12)),
        "dow_sin": float(np.sin(2 * np.pi * dow / 7)),
        "dow_cos": float(np.cos(2 * np.pi * dow / 7)),

        # Lags
        "lag_1": lag1,
        "lag_7": lag(7),
        "lag_14": lag(14),
        "lag_21": lag(21),
        "lag_30": lag(30),

        # Rolling
        "rolling_mean_7": rm7,
        "rolling_mean_14": rm14,
        "rolling_mean_30": rm30,
        "rolling_std_7": rolling_std(7),
        "rolling_max_7": rolling_max(7),
        "rolling_min_7": rolling_min(7),

        # Différences / tendances
        "sales_diff": (lag1 - lag2) if not np.isnan(lag1) and not np.isnan(lag2) else 0.0,
        "trend": (rm7 - rm30) if not np.isnan(rm7) and not np.isnan(rm30) else 0.0,
        "trend_short_medium": (rm7 - rm14) if not np.isnan(rm7) and not np.isnan(rm14) else 0.0,
        "trend_medium_long": (rm14 - rm30) if not np.isnan(rm14) and not np.isnan(rm30) else 0.0,

        # Stock
        "stock": float(stock),
        "stock_lag": float(stock),
        "stock_to_sales": float(stock) / (lag1 + 1) if not np.isnan(lag1) else float(stock),
        "stock_vs_avg_sales": float(stock) / (rm7 + 1) if not np.isnan(rm7) else float(stock),

        # Métier
        "discount": float(discount),
        "competitor_pricing": float(effective_competitor_pricing),
        "units_ordered": float(effective_units_ordered),
        "price_discount_interaction": float(price) * float(discount),
        "price_vs_competitor": float(price) - float(effective_competitor_pricing),
        "competitor_ratio": float(price) / (float(effective_competitor_pricing) + 1),
        "promo_discount_interaction": holiday * float(discount),
    }

    # ── One-hot catégorielles ────────────────────────────────────────────────
    one_hot_groups = {
        "category_": effective_category,
        "region_": effective_region,
        "weather_condition_": effective_weather,
        "holiday_promotion_": str(holiday),
        "seasonality_": season,
        "store_id_": str(store_id),
        "product_id_": str(product_id),
    }

    if trained_features:
        for prefix, value in one_hot_groups.items():
            for feat in trained_features:
                if feat.startswith(prefix):
                    feats[feat] = 0

            col = f"{prefix}{value}"
            if col in trained_features:
                feats[col] = 1

    # ── Alignement final sur trained_features ────────────────────────────────
    if trained_features:
        row = {f: feats.get(f, 0.0) for f in trained_features}
        row = {
            k: (
                0.0 if (
                    v is None or
                    (isinstance(v, float) and np.isnan(v))
                ) else v
            )
            for k, v in row.items()
        }
        return row

    # Sans trained_features : nettoyer les NaN quand même
    cleaned = {
        k: (
            0.0 if (
                v is None or
                (isinstance(v, float) and np.isnan(v))
            ) else v
        )
        for k, v in feats.items()
    }
    return cleaned