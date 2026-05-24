"""
sync_sales_history_from_csv_fixed.py
====================================
Synchronise data/sales.csv vers stock_service /sales-history/bulk.
Compatible avec ton stock_service actuel :
- route: POST /sales-history/bulk
- schema attendu: SalesHistoryIn(date, store_id, product_id, units_sold, price, inventory_level, ...)

Utilisation :
    python sync_sales_history_from_csv_fixed.py --csv data/sales.csv --base-url http://localhost:2004

Options utiles :
    --limit 1000          pour tester avec seulement 1000 lignes
    --chunk-size 500      taille des lots envoyés
"""

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


DEFAULT_ENDPOINTS = [
    "/sales-history/bulk",
    "/api/v1/sales-history/bulk",
]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les noms de colonnes et supprime les doublons créés par les scripts précédents."""
    df = df.copy()

    rename_map = {
        "Date": "date",
        "Store ID": "store_id",
        "Product ID": "product_id",
        "Category": "category",
        "Region": "region",
        "Inventory Level": "stock",
        "Units Sold": "sales",
        "Units Ordered": "units_ordered",
        "Demand Forecast": "demand_forecast",
        "Price": "price",
        "Discount": "discount",
        "Weather Condition": "weather_condition",
        "Holiday/Promotion": "holiday_promotion",
        "Competitor Pricing": "competitor_pricing",
        "Seasonality": "seasonality",
    }

    df = df.rename(columns=rename_map)
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.lower()
    )

    # Évite l'erreur pandas: cannot assemble with duplicate keys
    df = df.loc[:, ~df.columns.duplicated()].copy()
    return df


def choose_product_id_column(df: pd.DataFrame, explicit_col: str | None = None) -> str:
    """
    IMPORTANT : dans ton stock_service, historique_ventes.product_id est le SKU.
    Donc on préfère product_id_original si disponible, car product_id peut avoir été transformé en 1..36
    par fix_eval_columns.py pour l'évaluation ML.
    """
    if explicit_col:
        if explicit_col not in df.columns:
            raise ValueError(
                f"Colonne product_id demandée introuvable: {explicit_col}. "
                f"Colonnes disponibles: {list(df.columns)}"
            )
        return explicit_col

    for col in ["product_id_original", "sku", "product_sku", "product_id"]:
        if col in df.columns:
            return col

    raise ValueError("Aucune colonne produit trouvée: attendu product_id_original, sku ou product_id.")


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "date" not in df.columns:
        if "timestamp" in df.columns:
            df["date"] = df["timestamp"]
        else:
            raise ValueError("Le CSV doit contenir une colonne date ou timestamp.")

    if "sales" not in df.columns:
        if "qty" in df.columns:
            df["sales"] = df["qty"]
        elif "units_sold" in df.columns:
            df["sales"] = df["units_sold"]
        else:
            raise ValueError("Impossible de créer sales: colonnes sales/qty/units_sold absentes.")

    if "price" not in df.columns:
        if "unit_price" in df.columns:
            df["price"] = df["unit_price"]
        else:
            raise ValueError("Impossible de créer price: colonnes price/unit_price absentes.")

    defaults = {
        "store_id": "STORE_TUNIS",
        "category": "UNKNOWN",
        "region": "Tunis",
        "stock": 0,
        "discount": 0,
        "competitor_pricing": None,
        "units_ordered": 0,
        "weather_condition": "Normal",
        "holiday_promotion": 0,
        "seasonality": "Regular",
    }

    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    return df


def clean_dataframe(df: pd.DataFrame, product_col: str) -> pd.DataFrame:
    df = df.copy()

    date_series = df["date"]
    if isinstance(date_series, pd.DataFrame):
        date_series = date_series.iloc[:, 0]

    df["date"] = pd.to_datetime(date_series, errors="coerce")
    df = df.dropna(subset=["date"]).copy()

    for col in ["sales", "price", "stock", "discount", "competitor_pricing", "units_ordered", "holiday_promotion"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["sales"] = df["sales"].fillna(0)
    df["price"] = df["price"].fillna(0)
    df["stock"] = df["stock"].fillna(0)
    df["discount"] = df["discount"].fillna(0)
    df["units_ordered"] = df["units_ordered"].fillna(0)
    df["holiday_promotion"] = df["holiday_promotion"].fillna(0)
    df["competitor_pricing"] = df["competitor_pricing"].fillna(df["price"])

    df[product_col] = df[product_col].astype(str).str.strip()
    df = df[df[product_col] != ""].copy()

    for col in ["store_id", "category", "region", "weather_condition", "seasonality"]:
        df[col] = df[col].fillna("").astype(str)

    return df


def build_payload(df: pd.DataFrame, product_col: str) -> list[dict]:
    payload: list[dict] = []

    for row in df.itertuples(index=False):
        data = row._asdict()
        item = {
            "date": data["date"].date().isoformat(),
            "store_id": str(data.get("store_id") or "STORE_TUNIS"),
            "product_id": str(data[product_col]),  # SKU côté stock_service
            "category": str(data.get("category") or "UNKNOWN"),
            "region": str(data.get("region") or "Tunis"),
            # NOMS EXACTS attendus par SalesHistoryIn
            "units_sold": float(data.get("sales") or 0),
            "price": float(data.get("price") or 0),
            "inventory_level": float(data.get("stock") or 0),
            "discount": float(data.get("discount") or 0),
            "competitor_pricing": float(data.get("competitor_pricing") or 0),
            "units_ordered": float(data.get("units_ordered") or 0),
            "weather_condition": str(data.get("weather_condition") or "Normal"),
            "holiday_promotion": int(float(data.get("holiday_promotion") or 0)),
            "seasonality": str(data.get("seasonality") or "Regular"),
        }
        payload.append(item)

    return payload


def chunks(items: list[dict], chunk_size: int) -> Iterable[list[dict]]:
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


def check_service(base_url: str) -> None:
    base_url = base_url.rstrip("/")
    urls = [f"{base_url}/health", f"{base_url}/docs"]

    last_error = None
    for url in urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code < 500:
                print(f"✅ stock_service joignable : {url} -> {r.status_code}")
                return
        except requests.RequestException as exc:
            last_error = exc

    raise RuntimeError(
        "stock_service n'est pas joignable.\n"
        f"Base URL testée : {base_url}\n"
        "Vérifie d'abord : http://localhost:2004/docs\n"
        "Puis lance : docker compose up -d stock_service\n"
        f"Détail : {last_error}"
    )


def find_working_endpoint(base_url: str, sample: list[dict], endpoints: list[str]) -> str:
    base_url = base_url.rstrip("/")

    for endpoint in endpoints:
        url = f"{base_url}{endpoint}"
        try:
            r = requests.post(url, json=sample, timeout=30)
            if r.status_code < 400:
                print(f"✅ Endpoint valide : {url}")
                return url

            print(f"⚠️ Endpoint testé mais refusé : {url} -> {r.status_code}")
            print(r.text[:500])
        except requests.RequestException as exc:
            print(f"⚠️ Endpoint non joignable : {url} -> {exc}")

    raise RuntimeError(
        "Aucun endpoint d'import sales-history valide trouvé. "
        "Vérifie Swagger: /docs et la route POST /sales-history/bulk."
    )


def post_payload(base_url: str, payload: list[dict], chunk_size: int, dry_run: bool) -> None:
    if not payload:
        print("Aucune ligne à envoyer.")
        return

    if dry_run:
        print("Mode dry-run : aucun envoi effectué.")
        return

    check_service(base_url)

    # On teste avec la première ligne : ton endpoint est un bulk qui accepte list[SalesHistoryIn]
    url = find_working_endpoint(base_url, [payload[0]], DEFAULT_ENDPOINTS)

    total = len(payload)
    sent = 0

    for part in chunks(payload, chunk_size):
        r = requests.post(url, json=part, timeout=180)
        if r.status_code >= 400:
            print("\n❌ Erreur pendant l'import")
            print("URL:", url)
            print("Status:", r.status_code)
            print("Réponse:", r.text[:2000])
            r.raise_for_status()

        sent += len(part)
        print(f"✅ Synchronisé : {sent}/{total}")

    print("✅ Import terminé avec succès.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Chemin vers data/sales.csv")
    parser.add_argument("--base-url", default="http://localhost:2004")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=None, help="Limiter le nombre de lignes pour test")
    parser.add_argument("--product-id-column", default=None, help="Forcer la colonne produit à utiliser")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {csv_path}")

    df = pd.read_csv(csv_path)
    df = normalize_columns(df)
    df = ensure_required_columns(df)

    product_col = choose_product_id_column(df, args.product_id_column)
    df = clean_dataframe(df, product_col)

    if args.limit:
        df = df.head(args.limit).copy()

    payload = build_payload(df, product_col)

    print(f"Fichier : {csv_path}")
    print(f"Lignes payload : {len(payload)}")
    print(f"Colonne produit utilisée : {product_col}")
    print("Exemples product_id envoyés :", sorted({p["product_id"] for p in payload[:20]})[:10])
    print("Exemple première ligne :")
    print(payload[0] if payload else None)

    post_payload(args.base_url, payload, args.chunk_size, args.dry_run)


if __name__ == "__main__":
    main()
