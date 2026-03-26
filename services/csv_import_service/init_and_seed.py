"""
init_and_seed.py
────────────────
Lance ce script UNE FOIS pour :
  1. Créer toutes les tables dans smart_postgres
  2. (Optionnel) Pré-charger les CSV de data/

Usage:
    python init_and_seed.py                  # crée les tables uniquement
    python init_and_seed.py --seed /path/data  # crée + importe les CSV
"""

import sys
import os
from pathlib import Path

# Ajoute le dossier parent au path pour pouvoir importer app
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import init_db, SessionLocal
from app.services.csv_parser import parse_csv
from app.services.import_service import import_dataframe, log_import

# Ordre d'import important (respecter les FK)
CSV_ORDER = [
    "products.csv",
    "product_suppliers.csv",
    "sales.csv",
    "competitor_prices.csv",
    "promotions.csv",
    "stock_movements.csv",
]


def seed(data_dir: Path):
    db = SessionLocal()
    try:
        for fname in CSV_ORDER:
            fpath = data_dir / fname
            if not fpath.exists():
                print(f"  [SKIP] {fname} non trouvé")
                continue

            content = fpath.read_bytes()
            try:
                df, table_name = parse_csv(content, fname)
                rows = import_dataframe(df, table_name, db)
                db.commit()
                log_import(db, fname, table_name, "SUCCESS", rows)
                print(f"  [OK]   {fname} → {table_name} ({rows} lignes)")
            except Exception as e:
                db.rollback()
                print(f"  [ERR]  {fname}: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("=== Initialisation de la base smart_postgres ===")
    init_db()
    print("Tables créées.")

    if "--seed" in sys.argv:
        idx = sys.argv.index("--seed")
        data_path = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else Path("../data")
        print(f"\n=== Seed depuis {data_path} ===")
        seed(data_path)

    print("\nTerminé.")
