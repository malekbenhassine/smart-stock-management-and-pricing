from pathlib import Path
import pandas as pd

#charger un fichier CSV à partir d’un chemin donné
def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"CSV introuvable: {path}")
    return pd.read_csv(path)

#charger tous les fichier pour l’entraînement du modéle
def load_all(data_dir: Path):
    products = load_csv(data_dir / "products.csv")
    sales = load_csv(data_dir / "sales.csv")
    competitor_prices = load_csv(data_dir / "competitor_prices.csv")
    product_suppliers = load_csv(data_dir / "product_suppliers.csv")
    promotions = load_csv(data_dir / "promotions.csv")
    return {
        "products": products,
        "sales": sales,
        "competitor_prices": competitor_prices,
        "product_suppliers": product_suppliers,
        "promotions": promotions,
    }
