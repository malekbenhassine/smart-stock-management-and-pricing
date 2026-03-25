import numpy as np #biblio pour manipuler les tab et les calculs numériques
import pandas as pd
from dataclasses import dataclass #module pour créer une classe
from typing import List, Dict, Any #in+mporter les types
from sklearn.preprocessing import StandardScaler
#yrod les valeurs entre 0 w 1 bch modéle yefehmou
#un transformateur de données de scikit-learn utilisé pour normaliser les données avant d’entraîner le modèle
from sklearn.ensemble import IsolationForest
# algorithme de détection d’anomalies de scikit-learn qui utilise une approche d’isolation
# pour identifier les points de données anormaux dans un ensemble de données

@dataclass
class AnomalyArtifacts:
    scaler: StandardScaler
    iforest: IsolationForest
    feature_cols: List[str]
    meta: Dict[str, Any]

def build_anomaly_dataset(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> pd.DataFrame:
    
    prod = products[["product_id","current_price"]].copy()
    
    df = competitor_prices.merge(prod, on="product_id", how="left").copy()
    #join entre tab competitor_prices et prod par product_id
    #low="left" :garder tous les lignes de competitor_prices et ajouter les colonnes de prod si y a match sinon mettre NaN
    
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    #convertir la colonne collected_at en format datetime 
    df = df.sort_values(["product_id","competitor_id","collected_at"])
    #trier le tab par product_id, competitor_id et collected_at 
    #______________________
    
    df["status_bad"] = (df["status"] != "OK").astype(int)
    #créer une nouvelle colonne status_bad 1si ok 0 sinon 
    # indicateur de mauvaise qualité de données
    df["ratio"] = df["competitor_price"] / df["current_price"].replace(0, np.nan)
    #Crée ratio = competitor_price / current_price
    #Si current_price = 0, on remplace par NaN pour évite division par 0
    
    df["ratio"] = df["ratio"].fillna(1.0)
    #Si ratio est NaN on le remplace par 1.0 (neutre) pas de diff
    
    df["log_ratio"] = np.log(np.clip(df["ratio"], 1e-6, 1e6))
    #.clip : limiter les valeurs de ratio (dans un intervalle) entre 1e-6(0.000001) et 1e6(1000000) pour éviter les valeurs extrêmes
    #on a appliquer le log pour réduire l’impact des valeurs extrêmes et rendre la distribution plus symétrique

    df["prev_price"] = df.groupby(["product_id","competitor_id"])["competitor_price"].shift(1)
    #on join par product id et competitor_id pour créer 
    # une nouvelle colonne prev_price qui contient le prix concurrent précédent .
    # shift(1) :décaler les prix d’une ligne vers le bas pour avoir le prix précédent sur la même ligne que le prix actuel
    
    df["delta_pct"] = (df["competitor_price"] - df["prev_price"]) / df["prev_price"]
    #delta_pct : pourcentage de changement du prix concurrent par rapport au prix précédent
    df["delta_pct"] = df["delta_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    #remplacer les valeurs infinies par NaN puis les NaN par 0.0 inf=>infinie
    df["delta_pct"] = df["delta_pct"].clip(-2, 2)
    #limiter les valeurs de delta_pct entre -200% et +200% pour éviter les valeurs extrêmes
    df["prev_time"] = df.groupby(["product_id","competitor_id"])["collected_at"].shift(1)
    # prev_time contient le timestamp de la collecte précédente pour le même produit et concurrent
    df["gap_hours"] = (df["collected_at"] - df["prev_time"]).dt.total_seconds() / 3600.0 
    #nombre d’heures écoulées entre la collecte actuelle et la collecte précédente pour le même produit et concurrent
    #dt: accesoir pandas pour les ops dates dt.total_seconds() : convertir le gap en secondes puis diviser par 3600 pour avoir en heures
    df["gap_hours"] = df["gap_hours"].fillna(df["gap_hours"].median() if df["gap_hours"].notna().any() else 0.0)
    # remplacer les valeurs manquantes de gap_hours
    # par la médiane de la colonne (ou par 0 si toutes les valeurs sont NaN)
    #fillna:remplacer les NaN par une valeur
    #.median() : calculer moyenne de la colonne gap_hours
    #.notna().any() : vérifier s’il y a au moins une valeur non manquante dans gap_hours pour éviter erreur si toutes les valeurs sont NaN
    #sinon on remplace par 0.0 (aucun écart de temps)
    df["gap_hours"] = df["gap_hours"].clip(lower=0)
    df["gap_hours_log"] = np.log1p(df["gap_hours"])
    
    return df.dropna()
    #Supprime les lignes qui ont encore des NaN dans n’importe quelle colonne

def train_anomaly_ml(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> AnomalyArtifacts:
    df = build_anomaly_dataset(products, competitor_prices)

    feature_cols = ["log_ratio", "delta_pct", "gap_hours_log", "status_bad"]
    #choisir les colonnes à utiliser pour entrainer le modèle 
    X = df[feature_cols].values.astype(float)
    #x est une matrice numpy qui contient les valeurs des colonnes choisies converties en float

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    #StandardScaler est utilisé pour normaliser les données (mettre les valeurs dans la méme échelle)
    #.fit_transform : calculer la moyenne et l’écart type de chaque colonne de X
    # puis appliquer la normalisation pour obtenir Xs

    iforest = IsolationForest(
        n_estimators=400, #nombre d’arbres dans la forêt d’isolation
        contamination=0.02,#estimation de la proportion d’anomalies dans les données (5% dans notre cas)
        random_state=42
    )
    iforest.fit(Xs)
    #.fit : entrainer le modèle iforest sur les données normalisées Xs 

    # score threshold = 5e percentile (plus petit => plus anormal)
    scores = iforest.decision_function(Xs)
    #.decision_function : calculer un score d’anomalie pour chaque point de données dans Xs
    thr = float(np.quantile(scores, 0.05))
    #calcule le 5ᵉ percentile (les 5% des scores les plus petits.)
    #Prend le score du 5e percentile :

    #5% des scores sont en-dessous → considérés anomalies si on veut
    meta = {
        "train_rows": int(len(df)),
        "score_threshold": thr,
        "feature_mean": X.mean(axis=0).tolist(),
        "feature_std": X.std(axis=0).tolist(),
    }
    #Créer des métadonnées pour le rapport meta
    return AnomalyArtifacts(
        scaler=scaler,
        iforest=iforest,
        feature_cols=feature_cols,
        meta=meta
    )