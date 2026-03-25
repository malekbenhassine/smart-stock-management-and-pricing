import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any
from sklearn.ensemble import GradientBoostingRegressor

from .common_functions import (
    build_weekly_sales,
    competitor_week_median,
    promo_flag_week,
    add_lag_features,
    train_quantile_gbr,
)


@dataclass
class PriceDemandArtifacts:
    model_p10: GradientBoostingRegressor
    model_p50: GradientBoostingRegressor
    model_p90: GradientBoostingRegressor
    feature_cols: List[str]
    meta: Dict[str, Any]


def make_dataset(
    products: pd.DataFrame,
    sales: pd.DataFrame,
    competitor_prices: pd.DataFrame,
    promotions: pd.DataFrame,
) -> pd.DataFrame:
    weekly = build_weekly_sales(sales)
    comp = competitor_week_median(competitor_prices)
    promo = promo_flag_week(promotions)

    df = weekly.merge(comp, on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")

    df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)
    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["price"] = df["price_week"].astype(float)

    df = add_lag_features(df, target_col="qty_week", lags=4)
    return df


def train_price_demand_ml(
    products: pd.DataFrame,
    sales: pd.DataFrame,
    competitor_prices: pd.DataFrame,
    promotions: pd.DataFrame,
) -> PriceDemandArtifacts:
    df = make_dataset(products, sales, competitor_prices, promotions)

    feature_cols = [
        "product_id",
        "price",
        "comp_median",
        "promo_flag",
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_4",
        "roll_mean_4",
        "roll_std_4",
        "weekofyear",
    ]

    X = df[feature_cols].values.astype(float)
    y = df["qty_week"].values.astype(float)

    model_p10 = train_quantile_gbr(X, y, alpha=0.10)
    model_p50 = train_quantile_gbr(X, y, alpha=0.50)
    model_p90 = train_quantile_gbr(X, y, alpha=0.90)

    meta = {
        "train_rows": int(len(df)),
        "n_products": int(df["product_id"].nunique()),
    }

    return PriceDemandArtifacts(
        model_p10=model_p10,
        model_p50=model_p50,
        model_p90=model_p90,
        feature_cols=feature_cols,
        meta=meta,
    )
    
# import numpy as np
# import pandas as pd
# from dataclasses import dataclass
# from typing import List, Dict, Any
# from sklearn.ensemble import GradientBoostingRegressor

# @dataclass
# class PriceDemandArtifacts:
#     model_p10: GradientBoostingRegressor
#     model_p50: GradientBoostingRegressor
#     model_p90: GradientBoostingRegressor
#     feature_cols: List[str]
#     meta: Dict[str, Any]

# def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
#     #une fonction qui transforme les ventes brutes en ventes hebdomadaires
#     df = sales.copy()
#     df["timestamp"] = pd.to_datetime(df["timestamp"])
#     df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
#     w = df.groupby(["product_id","week"], as_index=False).agg(
#         qty_week=("qty","sum"),
#         price_week=("unit_price","mean"),
#     )
#     #agg(...) pour calculer plusieurs agrégations à la fois
#     return w.sort_values(["product_id","week"])

# def competitor_week_median(competitor_prices: pd.DataFrame) -> pd.DataFrame:
#     #une fonction qui calcule le prix moyen des concurrents par semaine
#     df = competitor_prices.copy()
#     df["collected_at"] = pd.to_datetime(df["collected_at"])
#     df["week"] = df["collected_at"].dt.to_period("W").dt.start_time
#     med = df.groupby(["product_id","week"], as_index=False)["competitor_price"].median()
#     #groupe par produit et semaine puis calcule la médiane du prix concurrent pour chaque groupe
#     return med.rename(columns={"competitor_price":"comp_median"}) #renomme la colonne competitor_price en comp_median

# def promo_flag_week(promotions: pd.DataFrame) -> pd.DataFrame:
#     #cette fonction transforme les périodes de promotion en indicateur hebdomadaire
#     df = promotions.copy()
#     df["start_date"] = pd.to_datetime(df["start_date"])
#     df["end_date"] = pd.to_datetime(df["end_date"])
#     #conversion en date en vrai format pandas => kanou des text 
#     rows = []
#     #on découpe les promotions en senmaines
#     for r in df.itertuples(index=False): #parcourt chaque ligne de promotion et transfotrme en tuple avec itertuples() et index=False pour ne pas inclure l’index dans le tuple
#         start = pd.to_datetime(r.start_date).to_period("W").start_time
#         #r.start_date pour acceder a la colonne start_date de la ligne r et convertir en datetime puis en période hebdomadaire et prendre le début de la semaine
#         end = pd.to_datetime(r.end_date).to_period("W").start_time
#         #.to_period("W") pour convertir une date en période hebdomadaire houni zeda nakhedhou debut de la semaine du fin promo
#         weeks = pd.date_range(start, end, freq="W-MON")
#         #crée une série de dates hebdomadaires entre start et end avec une fréquence de 1 semaine (W) en commençant le lundi (MON)
#         #maneha une date par semaine feha promo 
#         for w in weeks:
#             rows.append((int(r.product_id), pd.to_datetime(w), 1))
#     if not rows:
#         return pd.DataFrame(columns=["product_id","week","promo_flag"])
#     #Pour chaque semaine w, on ajoute une nouvelle ligne dans rows avec le product_id,la semaine w et un indicateur promo_flag à 1 (indiquant qu’il y a une promotion cette semaine-là)
#     return pd.DataFrame(rows, columns=["product_id","week","promo_flag"]).drop_duplicates()


# def make_dataset(products: pd.DataFrame, sales: pd.DataFrame,
#                  competitor_prices: pd.DataFrame, promotions: pd.DataFrame) -> pd.DataFrame:
#     #c’est la fonction qui construit le dataset final d’entraînement
#     weekly = build_weekly_sales(sales)
#     #transforme les ventes brutes en ventes hebdomadaires
#     comp = competitor_week_median(competitor_prices)
#     #calcule le prix médian concurrentiel par semaine
#     promo = promo_flag_week(promotions)
#     #calcule l’indicateur hebdomadaire de promotion

#     df = weekly.merge(comp, on=["product_id","week"], how="left")
#     #fusionne les ventes hebdomadaires avec les prix concurrents
#     df = df.merge(promo, on=["product_id","week"], how="left")
#     #fusionne le résultat précédent avec les indicateurs de promotion
#     df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)

#     # fallback comp_median
#     df["comp_median"] = df["comp_median"].fillna(df["price_week"])
#     #Si le prix concurrent médian est manquant, on le remplace par le prix hebdomadaire du produit lui-même (price_week)

#     # lags qty
#     df = df.sort_values(["product_id","week"])
#     for i in range(1, 5):
#         df[f"lag_{i}"] = df.groupby("product_id")["qty_week"].shift(i)
#         #cree des colonnes lag_1, lag_2, lag_3, lag_4 qui contiennent les quantités hebdomadaires décalées de 1 à 4 semaines pour chaque produit
#     df = df.dropna(subset=[f"lag_{i}" for i in range(1,5)]).copy() #Supprime les lignes qui ont des valeurs manquantes dans les colonnes lag_1 à lag_4 

#     df["roll_mean_4"] = df[[f"lag_{i}" for i in range(1,5)]].mean(axis=1) #calc moy lags
#     df["roll_std_4"] = df[[f"lag_{i}" for i in range(1,5)]].std(axis=1).fillna(0.0) #calc ecart type lags
#     df["weekofyear"] = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)
#     #Ajoute une colonne weekofyear qui contient le numéro de la semaine 
#     # dans l’année pour chaque ligne du dataset (ex: semaine 20 ..)

#     df["price"] = df["price_week"].astype(float)
    

#     return df

# def _train_quantile_gbr(X: np.ndarray, y: np.ndarray, alpha: float) -> GradientBoostingRegressor:
#     m = GradientBoostingRegressor(
#         loss="quantile",
#         alpha=alpha,
#         n_estimators=400,
#         learning_rate=0.05,
#         max_depth=3,
#         random_state=42,
#     )
#     m.fit(X, y)
#     return m

# def train_price_demand_ml(products: pd.DataFrame, sales: pd.DataFrame,
#                           competitor_prices: pd.DataFrame, promotions: pd.DataFrame) -> PriceDemandArtifacts:
#     df = make_dataset(products, sales, competitor_prices, promotions)

#     feature_cols = [
#         "product_id",
#         "price",
#         "comp_median",
#         "promo_flag",
#         "lag_1","lag_2","lag_3","lag_4",
#         "roll_mean_4","roll_std_4",
#         "weekofyear",
#     ]
#     X = df[feature_cols].values.astype(float)
#     y = df["qty_week"].values.astype(float)

#     m10 = _train_quantile_gbr(X, y, 0.10)
#     m50 = _train_quantile_gbr(X, y, 0.50)
#     m90 = _train_quantile_gbr(X, y, 0.90)

#     meta = {"train_rows": int(len(df)), "n_products": int(df["product_id"].nunique())}
#     return PriceDemandArtifacts(m10, m50, m90, feature_cols, meta)


# # La logique de ce code consiste à transformer toutes les données brutes en données hebdomadaires
# # afin de les rendre comparables et exploitables par le modèle de machine learning. Les ventes, 
# # les prix des concurrents et les promotions n’arrivent pas sous la même forme temporelle : 
# # certaines données ont une date précise, d’autres couvrent une période. 
# # Le code convertit donc chaque date en semaine correspondante, puis regroupe les informations
# # par produit et par semaine. Ainsi, pour chaque produit, on obtient une seule ligne contenant la quantité vendue pendant la semaine,
# # le prix moyen pratiqué, le prix médian des concurrents et l’indication de promotion. Ensuite, il ajoute l’historique des semaines 
# # précédentes avec les variables lag_1 à lag_4, ainsi que des indicateurs comme la moyenne et l’écart-type récents,
# # pour aider le modèle à comprendre la tendance de la demande. En résumé, ce code sert à aligner toutes les données sur la même échelle de temps,
# # la semaine, puis à construire un dataset clair et cohérent pour entraîner un modèle de prévision de la demande