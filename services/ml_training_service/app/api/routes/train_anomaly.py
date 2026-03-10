from fastapi import APIRouter #objet fast api pour créer des routes
from joblib import dump   #fonction pour sauvegarder les modèles entrainés (objets python) dans de fichiers .joblib
from datetime import datetime
import json #module pour manipuler les données au format JSON ahna bch nconvertiw bih un objet python 
import pandas as pd #bibliothèque Python utilisée pour manipuler et analyser des données (les DataFrames)

from ...core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from ...services.anomaly_detectors import train_anomaly_ml

# REPORTS_DIR: fichier JSON de rapport qui enregistre les informations de l’entraînement du modèle IA
router = APIRouter(prefix="/train")
@router.post("/anomaly-ml")
def train_anomaly():
    products = pd.read_csv(DATA_DIR / "products.csv") # lire et transformer le fichier csv en dataframe 
    competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")

    art = train_anomaly_ml(products, competitor_prices) #fonction qui entraine le modèle et retourne un objet avec les artefacts (scaler, iforest) et les métadonnées (feature_cols, meta)
    #artifact :objet produit aprés l'entrainement du modèle 
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S") #date de l'entrainement du modèle au format YYYYMMDD_HHMMSS (année, mois, jour, heure, minute, seconde) 
    #scaler: objet de scikit-learn utilisé pour normaliser les données d'entrée avant de les passer à l'iforest (mettre les valeurs dans la méme échelle)
    #iforest: objet de scikit-learn utilisé pour détecter les anomalyes en utilisant l'algorithme Isolation Forest
    #feature_cols: liste des colonnes utilisées pour entrainer le modèle
    #meta : dict des informations supplémentaires sur l'entraînement du modèle 
    dump(art.scaler, MODELS_DIR / f"anomaly_scaler_{ts}.joblib")
    dump(art.iforest, MODELS_DIR / f"anomaly_iforest_{ts}.joblib")

    meta = {
        "trained_at_utc": ts,
        "feature_cols": art.feature_cols,
        **art.meta #<= copie tous le contenue du dict dans meta
    }
    (REPORTS_DIR / f"anomaly_ml_meta_{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    # cette ligne convertit meta en JSON et l’enregistre dans un fichier dans le dossier reports 
    #ensure_ascii=False:garder les carctéres spéciaux
    #indent=2:ajouter 2 espaces dans le JSON pur lisibilité du docs
    return {"status": "ok", "meta": meta}