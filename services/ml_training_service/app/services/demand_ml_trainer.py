import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
from sklearn.ensemble import GradientBoostingRegressor
#Importe le modèle GradientBoostingRegressor de scikit-learn

@dataclass #transforme la classe en dataclass
class DemandMLArtifacts: #une classe servant à regrouper les objets créés après l’entraînement
    model_p10: GradientBoostingRegressor
    #Stocke le modèle entraîné pour prédire le quantile 10%
    model_p50: GradientBoostingRegressor
    #Stocke le modèle entraîné pour prédire le quantile 50%
    model_p90: GradientBoostingRegressor
    #Stocke le modèle entraîné pour prédire le quantile 90%
    feature_cols: List[str] #la liste des colonnes utilisées comme variables d’entrée du modèle
    meta: Dict[str, Any]

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame: #convertir les ventes brutes en ventes hebdomadaires (mn les ventes lkol ila osbou3eya )
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]) #convertit la colonne "timestamp" en vrai type date/heure
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time #crée une nv colonne qui représente la semaine à laquelle appartient chaque vente
    #df["timestamp"].dt → accès aux propriétés date
    #.to_period("W") → transforme chaque date en période hebdomadaire
    #.dt.start_time → récupère la date de début de la semaine
    weekly = df.groupby(["product_id", "week"], as_index=False)["qty"].sum()
    #regroupe les données par id et semaines
    #on passe de plusieurs ventes par produit dans une semaine à une seule ligne par produit et par semaine
    return weekly.sort_values(["product_id", "week"])
    #trie le résultat par produit puis par semaine

def make_supervised_features(weekly: pd.DataFrame, lags: int = 4) -> Tuple[pd.DataFrame, List[str]]: 
    "c'est une fonction qui transforme les données de ventes hebdomadaires en dataset supervisé elle prend ventes par semaine et 4 dérnier semaine "
    """
    Dataset global multi-produits:
    X = [product_id, lag1..lag4, roll_mean4, roll_std4]
    y = qty (semaine actuelle)
    """
    df = weekly.copy()
    df["product_id"] = df["product_id"].astype(int)
    df = df.sort_values(["product_id", "week"])
    #trie par produit puis par semaine

    # lags
    #On fait ça souvent en machine learning pour aider le modèle à comprendre l’historique des ventes
    #Un lag = une valeur passée lag_1 = la quantité de la période précédente
    #lag_2 = la quantité d’il y a 2 périodes
    #lag_3 = la quantité d’il y a 3 périodes
    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df.groupby("product_id")["qty"].shift(i)
        #shift prendre la ligne précédente d'ou chaque lag représente la qte de la semaine prec lag_2 = qte vendu il y a 2 semaine etc

    # rolling (sur les lags)
    df["roll_mean_4"] = df[[f"lag_{i}" for i in range(1, lags + 1)]].mean(axis=1)
    #roll_mean_4 : la moyenne des 4 lags pour chaque ligne (pour chaque produit et semaine) axis=1 : calculer la moyenne horizontalement sur les colonnes des lags
    df["roll_std_4"] = df[[f"lag_{i}" for i in range(1, lags + 1)]].std(axis=1).fillna(0.0)
    #calcule l’écart-type des 4 lags 
    #ecart-type la moy de la différence entre les lag si faible => ventes stables si élevé => ventes volatiles

    # target = qty actuelle (on prédit qty de la semaine t à partir des lags)
    df = df.dropna(subset=[f"lag_{i}" for i in range(1, lags + 1)]).copy()
    #supprime les lignes où au moins un lag manque(ex:on n’a pas encore 4 semaines passées)
    feature_cols = ["product_id"] + [f"lag_{i}" for i in range(1, lags + 1)] + ["roll_mean_4", "roll_std_4"]
    #construit la liste des colonnes d’entrée du modèle
    
    return df, feature_cols

def train_quantile_gbr(X: np.ndarray, y: np.ndarray, alpha: float) -> GradientBoostingRegressor:
    # loss quantile -> alpha = quantile (0.1, 0.5, 0.9)
    model = GradientBoostingRegressor(
        #le modèle doit faire une régression quantile
        loss="quantile", #Un quantile représente une position dans la distribution des valeurs (ex :quantile 0.5 → la médiane,quantile 0.1 → une valeur basse )
        #Donc le modèle peut apprendre :une prévision prudente/une prévision centrale/une prévision haute selon le quantile choisi.
        alpha=alpha, #fixe le quantile à apprendre 0.10 -> 10% ,0.50 -> 50% , 0.90 -> 90%
        n_estimators=300, #nb arbre de garadient boosting (plus il y en a, plus le modèle peut apprendre des relations complexes)
        learning_rate=0.05, #taux d’apprentissage (plus il est petit, plus le modèle apprend lentement mais peut mieux généraliser)
        max_depth=3, #profondeur max de chaque arbre (contrôle la complexité de chaque arbre, plus profond = plus complexe)
        random_state=42, #bloque l’aléatoire du modèle pour que les résultats restent stables d’une exécution à une autre
        #Le nombre 42 est juste très utilisé par habitude en informatique.
    )
    model.fit(X, y)
    #entraîne le modèle 
    return model

#Fonction principale d'entrainement
def train_demand_ml(sales: pd.DataFrame) -> DemandMLArtifacts:
    weekly = build_weekly_sales(sales)
    #transforme les ventes brutes en ventes hebdomadaires
    supervised, feature_cols = make_supervised_features(weekly, lags=4)
    #crée le dataset supervisé
    X = supervised[feature_cols].values.astype(float)
    #extrait les colonnes de features , les convertit en tableau NumPy et les transforme en float
    y = supervised["qty"].values.astype(float)#extrait la colonne cible qty...

    model_p10 = train_quantile_gbr(X, y, alpha=0.10)
    #entraîne le modèle du quantile 10%
    model_p50 = train_quantile_gbr(X, y, alpha=0.50) 
    #entraîne le modèle du quantile 50%
    model_p90 = train_quantile_gbr(X, y, alpha=0.90)
    #entraîne le modèle du quantile 90%

    meta = {
        "train_rows": int(len(supervised)), #nombre de lignes utilisées pour l’entraînement
        "n_products": int(supervised["product_id"].nunique()), #nombre de produits différents dans le dataset
        "lags": 4,
    }

    return DemandMLArtifacts(
        model_p10=model_p10,
        model_p50=model_p50,
        model_p90=model_p90,
        feature_cols=feature_cols,
        meta=meta
    )

def build_features_for_product_next_week(weekly: pd.DataFrame, product_id: int, feature_cols: List[str]) -> Dict[str, float]:
    """
    Construit les features (lag1..lag4 + rolling) pour un produit, pour prédire la semaine prochaine.
    """
    g = weekly[weekly["product_id"] == product_id].sort_values("week")
    #filtrer et garder le pdt concerné
    y = g["qty"].values.astype(float)

    # si pas assez d'historique
    if len(y) < 4:
        return {}

    lag_1, lag_2, lag_3, lag_4 = y[-1], y[-2], y[-3], y[-4]
    #récupère les 4 dernières quantités observées
    roll_mean_4 = float(np.mean([lag_1, lag_2, lag_3, lag_4]))
    roll_std_4 = float(np.std([lag_1, lag_2, lag_3, lag_4]))

    feats = {
        "product_id": float(product_id),
        "lag_1": float(lag_1),
        "lag_2": float(lag_2),
        "lag_3": float(lag_3),
        "lag_4": float(lag_4),
        "roll_mean_4": roll_mean_4,
        "roll_std_4": roll_std_4,
    }

    # garder seulement les colonnes attendues
    return {k: feats[k] for k in feature_cols}