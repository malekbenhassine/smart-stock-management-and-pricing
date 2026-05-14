"""
augment_competitor_anomalies.py
================================
Crée un competitor_prices.csv plus réaliste pour évaluer le modèle d'anomalies.

Pourquoi : un seul concurrent et 0 anomalie donnent forcément un F1-score inutile.
Ce script génère plusieurs concurrents simulés à partir du fichier existant,
puis injecte un faible pourcentage d'anomalies contrôlées.

Commande :
    python augment_competitor_anomalies.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
COMP_PATH = DATA_DIR / "competitor_prices.csv"
BACKUP_PATH = DATA_DIR / "competitor_prices_before_augmentation.csv"

RNG = np.random.default_rng(42)

COMPETITORS = [
    (1, "Mytek simulé", 1.00),
    (2, "Tunisianet simulé", 0.985),
    (3, "SpaceNet simulé", 1.015),
    (4, "Zoom simulé", 0.965),
    (5, "BestPC simulé", 1.035),
]

ANOMALY_RATE = 0.045  # environ 4.5% du total, raisonnable pour IsolationForest


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("-", "_")
        .str.lower()
    )
    return df


def main():
    if not COMP_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {COMP_PATH}")

    base = pd.read_csv(COMP_PATH)
    base = normalize_columns(base)

    if "collected_at" not in base.columns:
        if "timestamp" in base.columns:
            base["collected_at"] = base["timestamp"]
        elif "date" in base.columns:
            base["collected_at"] = base["date"]
        else:
            raise ValueError("competitor_prices.csv doit contenir collected_at, timestamp ou date")

    if "competitor_price" not in base.columns:
        if "competitor_pricing" in base.columns:
            base["competitor_price"] = base["competitor_pricing"]
        elif "price" in base.columns:
            base["competitor_price"] = base["price"]
        else:
            raise ValueError("Impossible de trouver competitor_price")

    base["collected_at"] = pd.to_datetime(base["collected_at"], errors="coerce")
    base = base.dropna(subset=["collected_at"]).copy()
    base["competitor_price"] = pd.to_numeric(base["competitor_price"], errors="coerce")
    base = base.dropna(subset=["competitor_price"]).copy()

    # Réduire si fichier énorme : on garde une observation par produit/jour/prix de base
    base = base[["collected_at", "product_id", "competitor_price"]].copy()
    base["date_only"] = base["collected_at"].dt.date
    base = base.drop_duplicates(subset=["product_id", "date_only"]).drop(columns=["date_only"])

    frames = []
    for cid, cname, price_factor in COMPETITORS:
        tmp = base.copy()
        noise = RNG.normal(loc=1.0, scale=0.035, size=len(tmp))
        tmp["competitor_id"] = cid
        tmp["competitor_name"] = cname
        tmp["competitor_price"] = (tmp["competitor_price"] * price_factor * noise).clip(lower=1).round(2)
        tmp["status"] = "OK"
        frames.append(tmp)

    df = pd.concat(frames, ignore_index=True)

    n = len(df)
    anomaly_count = max(1, int(n * ANOMALY_RATE))
    anomaly_idx = RNG.choice(df.index.to_numpy(), size=anomaly_count, replace=False)
    half = anomaly_count // 2

    # Prix anormalement bas
    low_idx = anomaly_idx[:half]
    df.loc[low_idx, "competitor_price"] = (df.loc[low_idx, "competitor_price"] * RNG.uniform(0.18, 0.45, size=len(low_idx))).round(2)
    df.loc[low_idx, "status"] = "OUTLIER_LOW"

    # Prix anormalement haut
    high_idx = anomaly_idx[half:]
    df.loc[high_idx, "competitor_price"] = (df.loc[high_idx, "competitor_price"] * RNG.uniform(1.8, 3.2, size=len(high_idx))).round(2)
    df.loc[high_idx, "status"] = "OUTLIER_HIGH"

    # Quelques erreurs de collecte sans modifier forcément le prix
    error_count = max(1, int(n * 0.006))
    error_idx = RNG.choice(df.index.to_numpy(), size=error_count, replace=False)
    df.loc[error_idx, "status"] = "ERROR"

    # Backup puis écriture
    if not BACKUP_PATH.exists():
        pd.read_csv(COMP_PATH).to_csv(BACKUP_PATH, index=False)

    df = df[["collected_at", "product_id", "competitor_id", "competitor_name", "competitor_price", "status"]]
    df.to_csv(COMP_PATH, index=False)

    print("✅ competitor_prices.csv enrichi")
    print(f"Lignes : {len(df)}")
    print(f"Concurrents : {df['competitor_id'].nunique()}")
    print("Répartition des statuts :")
    print(df["status"].value_counts().to_string())
    print(f"Backup : {BACKUP_PATH}")


if __name__ == "__main__":
    main()
