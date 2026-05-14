from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
MODELS_DIR = APP_DIR / "models"

FEATURES_PATH = MODELS_DIR / "demand_features.pkl"
MAPPING_PATH = MODELS_DIR / "product_id_mapping.csv"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _get(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def load_demand_features() -> list[str]:
    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"Fichier features introuvable : {FEATURES_PATH}")
    features = joblib.load(FEATURES_PATH)
    return list(features)


def load_product_mapping() -> dict[str, str]:
    """
    Retourne mapping SKU/original -> product_id numérique du training.
    Supporte les colonnes :
    - product_id_original / product_id_numeric
    """
    if not MAPPING_PATH.exists():
        return {}

    df = pd.read_csv(MAPPING_PATH)

    if "product_id_original" in df.columns and "product_id_numeric" in df.columns:
        return {
            str(r.product_id_original): str(r.product_id_numeric)
            for r in df.itertuples(index=False)
        }

    return {}


def normalize_history_rows(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("-", "_")
        .str.lower()
    )
    df = df.loc[:, ~df.columns.duplicated()].copy()

    if "date" not in df.columns and "timestamp" in df.columns:
        df["date"] = df["timestamp"]

    if "units_sold" not in df.columns:
        if "sales" in df.columns:
            df["units_sold"] = df["sales"]
        elif "qty" in df.columns:
            df["units_sold"] = df["qty"]
        else:
            df["units_sold"] = 0

    if "inventory_level" not in df.columns:
        if "stock" in df.columns:
            df["inventory_level"] = df["stock"]
        else:
            df["inventory_level"] = 0

    if "price" not in df.columns:
        if "unit_price" in df.columns:
            df["price"] = df["unit_price"]
        else:
            df["price"] = 0

    defaults = {
        "discount": 0,
        "competitor_pricing": np.nan,
        "units_ordered": 0,
        "holiday_promotion": 0,
        "store_id": "S001",
        "region": "Tunis",
        "weather_condition": "Sunny",
        "seasonality": "Regular",
        "category": "Accessories",
    }

    for col, value in defaults.items():
        if col not in df.columns:
            df[col] = value

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date")

    numeric_cols = [
        "units_sold",
        "inventory_level",
        "price",
        "discount",
        "competitor_pricing",
        "units_ordered",
        "holiday_promotion",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["units_sold"] = df["units_sold"].fillna(0.0)
    df["inventory_level"] = df["inventory_level"].fillna(0.0)

# Corrigé pour pandas récent
    df["price"] = df["price"].ffill().fillna(0.0)

    df["discount"] = df["discount"].fillna(0.0)
    df["competitor_pricing"] = df["competitor_pricing"].fillna(df["price"])
    df["units_ordered"] = df["units_ordered"].fillna(0.0)
    df["holiday_promotion"] = df["holiday_promotion"].fillna(0).astype(int)
    return df


def _last_or_default(df: pd.DataFrame, col: str, default):
    if df.empty or col not in df.columns:
        return default
    value = df[col].dropna()
    if value.empty:
        return default
    return value.iloc[-1]


def _lag(series: pd.Series, n: int) -> float:
    if len(series) > n:
        return _safe_float(series.iloc[-n - 1], 0.0)
    if len(series) > 0:
        return _safe_float(series.iloc[0], 0.0)
    return 0.0


def _rolling_mean(series: pd.Series, n: int) -> float:
    if len(series) == 0:
        return 0.0
    return _safe_float(series.tail(n).mean(), 0.0)


def _rolling_std(series: pd.Series, n: int) -> float:
    if len(series) <= 1:
        return 0.0
    return _safe_float(series.tail(n).std(), 0.0)


def _rolling_max(series: pd.Series, n: int) -> float:
    if len(series) == 0:
        return 0.0
    return _safe_float(series.tail(n).max(), 0.0)


def _rolling_min(series: pd.Series, n: int) -> float:
    if len(series) == 0:
        return 0.0
    return _safe_float(series.tail(n).min(), 0.0)


def _one_hot(features: dict, prefix: str, value: Any):
    key = f"{prefix}_{value}"
    features[key] = 1.0


def resolve_training_product_id(req: Any, mapping: dict[str, str]) -> str | None:
    """
    Convertit SKU réel -> id numérique du training, si mapping disponible.
    """
    sku = _get(req, "sku", None)
    pid = _get(req, "product_id", None)

    for candidate in [sku, pid]:
        if candidate is None:
            continue
        key = str(candidate)
        if key in mapping:
            return str(mapping[key])

    if pid is not None:
        return str(pid)

    return None


def build_features_for_model(
    req: Any,
    history_rows: list[dict],
    demand_features: list[str] | None = None,
) -> pd.DataFrame:
    """
    Reconstruit une ligne de features alignée exactement avec demand_features.pkl.
    """
    demand_features = demand_features or load_demand_features()
    mapping = load_product_mapping()

    hist = normalize_history_rows(history_rows)
    sales = hist["units_sold"] if not hist.empty else pd.Series(dtype=float)

    price = _safe_float(_get(req, "price", None), _safe_float(_last_or_default(hist, "price", 0), 0))
    stock = _safe_float(_get(req, "stock", None), _safe_float(_last_or_default(hist, "inventory_level", 0), 0))
    discount = _safe_float(_get(req, "discount", None), _safe_float(_last_or_default(hist, "discount", 0), 0))
    competitor = _safe_float(
        _get(req, "competitor_pricing", None),
        _safe_float(_last_or_default(hist, "competitor_pricing", price), price),
    )
    units_ordered = _safe_float(
        _get(req, "units_ordered", None),
        _safe_float(_last_or_default(hist, "units_ordered", 0), 0),
    )

    latest_date = hist["date"].max() if not hist.empty else pd.Timestamp.today()
    latest_date = pd.to_datetime(latest_date)

    features = {
        "price": price,
        "price_change": 0.0,
        "price_lag_1": price,
        "day": float(latest_date.day),
        "month": float(latest_date.month),
        "day_of_week": float(latest_date.dayofweek),
        "week_of_year": float(latest_date.isocalendar().week),
        "is_weekend": float(latest_date.dayofweek >= 5),
        "quarter": float(latest_date.quarter),
        "is_month_start": float(latest_date.is_month_start),
        "is_month_end": float(latest_date.is_month_end),
        "is_quarter_start": float(latest_date.is_quarter_start),
        "is_quarter_end": float(latest_date.is_quarter_end),
        "month_sin": float(np.sin(2 * np.pi * latest_date.month / 12)),
        "month_cos": float(np.cos(2 * np.pi * latest_date.month / 12)),
        "dow_sin": float(np.sin(2 * np.pi * latest_date.dayofweek / 7)),
        "dow_cos": float(np.cos(2 * np.pi * latest_date.dayofweek / 7)),
        "stock": stock,
        "stock_lag": _safe_float(_last_or_default(hist, "inventory_level", stock), stock),
        "discount": discount,
        "competitor_pricing": competitor,
        "units_ordered": units_ordered,
        "price_discount_interaction": price * discount,
        "price_vs_competitor": price - competitor,
        "competitor_ratio": price / competitor if competitor else 1.0,
        "promo_discount_interaction": discount * float(_get(req, "holiday_promotion", 0) or 0),
    }

    for n in [1, 7, 14, 21, 30, 60, 90]:
        features[f"lag_{n}"] = _lag(sales, n)

    for n in [7, 14, 30, 60, 90]:
        features[f"rolling_mean_{n}"] = _rolling_mean(sales, n)

    features["rolling_std_7"] = _rolling_std(sales, 7)
    features["rolling_std_30"] = _rolling_std(sales, 30)
    features["rolling_max_7"] = _rolling_max(sales, 7)
    features["rolling_min_7"] = _rolling_min(sales, 7)

    features["sales_diff"] = features["lag_1"] - features["lag_7"]
    features["trend"] = features["rolling_mean_7"] - features["rolling_mean_30"]
    features["trend_short_medium"] = features["rolling_mean_7"] - features["rolling_mean_14"]
    features["trend_medium_long"] = features["rolling_mean_30"] - features["rolling_mean_60"]
    features["trend_long"] = features["rolling_mean_60"] - features["rolling_mean_90"]
    features["cumulative_sales"] = _safe_float(sales.sum(), 0.0)

    features["stock_to_sales"] = stock / features["rolling_mean_7"] if features["rolling_mean_7"] else 999.0
    features["stock_vs_avg_sales"] = stock - features["rolling_mean_30"]

    promo_active = int(discount > 0 or _safe_float(_get(req, "holiday_promotion", 0), 0) > 0)
    features["is_promo_active"] = float(promo_active)
    features["promo_discount"] = discount
    features["promo_expected_lift"] = 1.0 + min(discount, 50.0) / 100.0
    features["is_promo_active_lag1"] = float(promo_active)
    features["promo_expected_lift_lag1"] = features["promo_expected_lift"]
    features["price_x_promo"] = price * promo_active
    features["lift_x_discount"] = features["promo_expected_lift"] * discount

    category = str(_get(req, "category", _last_or_default(hist, "category", "Accessories")))
    region = str(_get(req, "region", _last_or_default(hist, "region", "Tunis")))
    store_id = str(_get(req, "store_id", _last_or_default(hist, "store_id", "S001")))
    weather = str(_get(req, "weather_condition", _last_or_default(hist, "weather_condition", "Sunny")))
    seasonality = str(_get(req, "seasonality", _last_or_default(hist, "seasonality", "Regular")))
    holiday = int(_safe_float(_get(req, "holiday_promotion", _last_or_default(hist, "holiday_promotion", 0)), 0))

    _one_hot(features, "category", category)
    _one_hot(features, "region", region)
    _one_hot(features, "store_id", store_id)
    _one_hot(features, "weather_condition", weather)
    _one_hot(features, "seasonality", seasonality)
    _one_hot(features, "holiday_promotion", holiday)

    training_pid = resolve_training_product_id(req, mapping)
    if training_pid is not None:
        _one_hot(features, "product_id", training_pid)

    row = {name: _safe_float(features.get(name, 0.0), 0.0) for name in demand_features}
    return pd.DataFrame([row], columns=demand_features)

def _season_from_month(month: int) -> str:
    return {
        12: "Winter", 1: "Winter", 2: "Winter",
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Autumn", 10: "Autumn", 11: "Autumn",
    }.get(int(month), "Regular")


def build_features(*args, **kwargs) -> dict:
    """
    Fonction de compatibilité utilisée par price_service.py.
    Elle accepte l'ancien appel par mots-clés : build_features(db=..., product_id=..., trained_features=...).
    Elle reconstruit les features avec le même moteur que predict_demand afin de garder la logique ML.
    """
    from types import SimpleNamespace
    from datetime import date as date_cls
    from app.services.stock_client import get_recent_history_from_stock_service

    # Cas ancien : build_features(db=..., store_id=..., product_id=..., target_date=..., trained_features=...)
    if kwargs:
        target_date = kwargs.get("target_date") or date_cls.today()
        month = getattr(target_date, "month", pd.Timestamp.today().month)
        req = SimpleNamespace(
            product_id=kwargs.get("product_id"),
            sku=kwargs.get("product_id"),
            price=_safe_float(kwargs.get("price"), 0.0),
            stock=_safe_float(kwargs.get("stock"), 0.0),
            discount=_safe_float(kwargs.get("discount"), 0.0),
            competitor_pricing=_safe_float(kwargs.get("competitor_pricing"), _safe_float(kwargs.get("price"), 0.0)),
            units_ordered=_safe_float(kwargs.get("units_ordered"), 0.0),
            weather_condition=kwargs.get("weather_condition") or "Sunny",
            category=kwargs.get("category") or "Accessories",
            region=kwargs.get("region") or "Tunis",
            store_id=kwargs.get("store_id") or "S001",
            seasonality=kwargs.get("seasonality") or _season_from_month(month),
            holiday_promotion=kwargs.get("holiday_promotion") or 0,
        )
        trained_features = kwargs.get("trained_features") or load_demand_features()
        history_rows = get_recent_history_from_stock_service(req.sku or req.product_id, limit=140)
        X = build_features_for_model(req, history_rows, demand_features=list(trained_features))
        return X.iloc[0].to_dict()

    # Cas simple : build_features(request)
    request = args[0] if args else None
    if request is None:
        return {}

    data = request.model_dump() if hasattr(request, "model_dump") else request.dict() if hasattr(request, "dict") else request if isinstance(request, dict) else {}
    return {
        "product_id": data.get("product_id"),
        "sku": data.get("sku") or data.get("product_id"),
        "category": data.get("category") or "Accessories",
        "brand": data.get("brand"),
        "price": _safe_float(data.get("price") or data.get("current_price"), 0.0),
        "stock": _safe_float(data.get("stock") or data.get("inventory_level"), 0.0),
        "discount": _safe_float(data.get("discount"), 0.0),
        "competitor_pricing": _safe_float(data.get("competitor_pricing") or data.get("competitor_price"), 0.0),
        "units_ordered": _safe_float(data.get("units_ordered"), 0.0),
        "store_id": data.get("store_id") or "S001",
        "region": data.get("region") or "Tunis",
    }

# Alias
build_model_features = build_features_for_model
