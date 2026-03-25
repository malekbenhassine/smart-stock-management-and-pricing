from pathlib import Path
import json
import numpy as np
import pandas as pd

def _latest_json(reports_dir: Path, prefix: str) -> Path:
    files = sorted(reports_dir.glob(f"{prefix}*.json"))
    if not files:
        raise FileNotFoundError(f"Aucun meta trouvé: {prefix} dans {reports_dir}")
    return files[-1] #files[-1] : pour prendre le dernier fichier de la liste (le plus récent) correspondant au préfixe donné 
#Cette fonction cherche le dernier fichier JSON dans reports_dir
#glob : chercher les fichier 
class AnomalyMLEngine:
    """
    Détection anomalies ML non-supervisée:
    - StandardScaler + IsolationForest
    - score + explication via features dominantes (z-score)
    """
    # non-supervisé c'est a dire le modéle apprend à différencier les données normales des anomalies(il apprend plutôt ce qui ressemble à un comportement normal)
    def __init__(self, store, reports_dir: Path):
        self.store = store
        self.reports_dir = reports_dir

    def _prepare_features(self, product: dict, competitor_prices: pd.DataFrame) -> pd.DataFrame:
        pid = int(product["product_id"])
        cur = float(product["current_price"])

        df = competitor_prices[competitor_prices["product_id"] == pid].copy()
        if df.empty:
            return df

        df["collected_at"] = pd.to_datetime(df["collected_at"])
        df = df.sort_values(["competitor_id", "collected_at"])

        df["status_bad"] = (df["status"] != "OK").astype(int)
        # indicateur de mauvaise qualité de données 0 ou 1 selon que le status est OK ou pas
        df["ratio"] = df["competitor_price"] / max(cur, 1e-6)
        #Crée ratio = competitor_price / current_price
        #1e-6 pour éviter division par 0 si current_price est 0 (1e-6 = 0.000001))
        df["log_ratio"] = np.log(np.clip(df["ratio"], 1e-6, 1e6))
        #les modèles détectent souvent mieux les anomalies sur une échelle log que sur une échelle brute, surtout pour les rapports de prix
        # delta vs précédent (par competitor)
        #np.clip : limiter les valeurs de ratio (dans un intervalle) entre 1e-6(0.000001) et 1e6(1000000) si el val tres petite yakhou el min kan el akes yakhou el max eli ta3tih enty 
        df["prev_price"] = df.groupby("competitor_id")["competitor_price"].shift(1)
        #pour chaque concurent nakhod le prix précédent en décalant les prix d’une ligne vers le bas pour avoir le prix précédent sur la même ligne que le prix actuel
        df["delta_pct"] = (df["competitor_price"] - df["prev_price"]) / df["prev_price"]
        #Cette colonne mesure le pourcentage de variation du prix concurrent par rapport au relevé précédent
        df["delta_pct"] = df["delta_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # gap heures
        df["prev_time"] = df.groupby("competitor_id")["collected_at"].shift(1)
        #récupère la date de collecte précédente
        df["gap_hours"] = (df["collected_at"] - df["prev_time"]).dt.total_seconds() / 3600.0
        df["gap_hours"] = df["gap_hours"].fillna(df["gap_hours"].median() if df["gap_hours"].notna().any() else 0.0)
        #Cette feature mesure le temps écoulé entre deux collectes, en heures

        return df
    #resultat :status_bad , ratio , log_ratio , prev_price, delta_pct,prev_time,gap_hours
    
    def _explain_feature(self, feat: str) -> str:
        mapping = {
        "gap_hours": "La dernière collecte est trop ancienne / irrégulière (scraping instable ou retard).",
        "log_ratio": "Le ratio prix concurrent / prix interne est atypique (prix trop haut/bas ou mauvais matching).",
        "delta_pct": "Variation du prix concurrent très brusque par rapport à l’historique (choc ou donnée incohérente).",
        "status_bad": "Le scraping a retourné un statut non OK (donnée potentiellement invalide).",
        }
        return mapping.get(feat, f"Feature atypique: {feat}.")
    #pour une explication claire 
    #Feature atypique: {feat}.  si pas d'explication on dit feature atypique ...
    
    def detect_for_product_ml(self, product: dict, competitor_prices: pd.DataFrame) -> dict:
        scaler = self.store.load_latest("anomaly_scaler", "anomaly_scaler_")
        iforest = self.store.load_latest("anomaly_iforest", "anomaly_iforest_")
        #chargement du scaler et du modéle 
        #scaler sert à mettre les vars à la meme echelle
        meta_path = _latest_json(self.reports_dir, "anomaly_ml_meta_")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        #on charge les meta pour avoir les infossur les fetures a utilisée 
        feature_cols = meta["feature_cols"]
        threshold = float(meta["score_threshold"])
        feat_mean = np.array(meta["feature_mean"], dtype=float)
        feat_std = np.array(meta["feature_std"], dtype=float)

        df = self._prepare_features(product, competitor_prices)
        #leresultat de _prepare_features : un dataframe avec les features calculées à partir des prix concurrents et des infos du produit
        if df.empty:
            return {"product_id": int(product["product_id"]), "anomalies": []}

        # prendre la dernière observation par concurrent (c’est ce qu'on affiches dans le UI)
        latest = df.groupby("competitor_id", as_index=False).tail(1).copy()

        X = latest[feature_cols].values.astype(float)
        #On extrait les colonnes utilisées par le modèle et on les transforme en matrice numérique
        Xs = scaler.transform(X)
        scores = iforest.decision_function(Xs) 
        #calculer le score d’anomalie pour chaque ligne de données normalisées Xs avec le modèle iforest
        # plus grand => normal
        latest["score"] = scores

        anomalies = []
        for row in latest.itertuples(index=False):
            if float(row.score) < threshold:
                x = np.array([getattr(row, c) for c in feature_cols], dtype=float)
                #construit un tableau x avec les valeurs des features de cette ligne
                #getattr(row, c) : pour accéder à la valeur de la feature c dans la ligne row
                z = np.abs((x - feat_mean) / (feat_std + 1e-9))
                #calcule à quel point chaque feature est éloignée de son comportement normal
                #formule : z = abs((valeur - mean) / std)
                top_idx = int(np.argmax(z))
                #On cherche l’indice de la plus grande valeur dans z =>c'est la feature la plus anormale 
                top_feat = feature_cols[top_idx]
                #recupere le nom de feature la plus anormale
                
                reason = self._explain_feature(top_feat)
                #fonction pour les explications claire
                anomalies.append({
                    "type": "ML_ANOMALY",
                    "severity": "HIGH" if float(row.score) < threshold - 0.05 else "MEDIUM",
                    #bch naref est ce que c'est une anomalie très forte nchouf kani asgher ml seuil b 0.05 rahi barcha
                    "detail": f"Anomalie ML détectée (score={float(row.score):.3f}). {reason}"
                    #.3f 3 chiffre après la virgule pour le score dans le message d’explication
                })

        return {"product_id": int(product["product_id"]), "anomalies": anomalies}
#La boucle parcourt chaque dernière observation concurrente dans latest. Pour chaque ligne, 
# elle regarde d’abord si le score produit par le modèle est inférieur au seuil threshold :
# si non, la ligne est considérée normale et ignorée ; si oui, elle est considérée comme anomalie.
# Ensuite, elle récupère les valeurs des features de cette ligne (gap_hours, log_ratio, delta_pct, status_bad...), 
# calcule pour chacune à quel point elle s’éloigne du comportement moyen habituel grâce au z-score, puis repère la feature la plus anormale.
# Cette feature dominante est transformée en explication lisible avec _explain_feature, puis on ajoute dans anomalies un dictionnaire contenant le type d’anomalie, son niveau de gravité (HIGH ou MEDIUM selon à quel point le score est bas)
# et un message final expliquant la cause probable. À la fin, la fonction retourne l’identifiant du produit avec la liste de toutes les anomalies détectées pour ce produit