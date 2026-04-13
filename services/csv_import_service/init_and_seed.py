import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import init_db, SessionLocal
from app.services.csv_parser import parse_csv
from app.services.import_service import import_dataframe, log_import

CSV_ORDER = [
    "produits.csv",
    "fournisseurs.csv",
    "commandes_fournisseurs.csv",
    "lignes_commandes.csv",
    "ventes.csv",
    "lignes_ventes.csv",
    "promotions.csv",
    "produit_promotion.csv",
    "concurrents.csv",
    "produits_concurrents.csv",
    "sales_history.csv",
]


def seed(data_dir: Path):
    db = SessionLocal()
    try:
        for fname in CSV_ORDER:
            fpath = data_dir / fname
            if not fpath.exists():
                print(f"[SKIP] {fname} non trouvé")
                continue

            content = fpath.read_bytes()
            try:
                df, table_name = parse_csv(content, fname)
                rows = import_dataframe(df, table_name, db)
                db.commit()
                log_import(db, fname, table_name, "SUCCESS", rows)
                print(f"[OK] {fname} -> {table_name} ({rows} lignes)")
            except Exception as e:
                db.rollback()
                log_import(db, fname, "unknown", "ERROR", error=str(e))
                print(f"[ERR] {fname}: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("=== Initialisation de la base smart_postgres ===")
    init_db()
    print("Tables créées.")

    if "--seed" in sys.argv:
        idx = sys.argv.index("--seed")
        data_path = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else Path("./data")
        print(f"\n=== Seed depuis {data_path} ===")
        seed(data_path)

    print("\nTerminé.")