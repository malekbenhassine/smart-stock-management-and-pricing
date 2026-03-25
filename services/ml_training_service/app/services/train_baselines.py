import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any
from datetime import datetime

@dataclass
class DemandModel:
    # on stocke stats par produit
    per_product: Dict[int, Dict[str, Any]]
    horizon_weeks: int

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    #Transformer les ventes brutes en ventes par semaine.
    sales = sales.copy()
    sales["timestamp"] = pd.to_datetime(sales["timestamp"])
    sales["week"] = sales["timestamp"].dt.to_period("W").dt.start_time
    weekly = sales.groupby(["product_id", "week"], as_index=False)["qty"].sum()
    return weekly.sort_values(["product_id", "week"])

def train_demand_baseline(weekly_sales: pd.DataFrame, horizon_weeks: int = 4) -> DemandModel:
    per_product = {}
    for pid, g in weekly_sales.groupby("product_id"):
        #g:les lignes des produits dont le product_id est égal à pid 
        y = g["qty"].values.astype(float)
        if len(y) < 4:
            # peu d'historique -> fallback
            p50 = float(np.mean(y)) if len(y) else 0.0
            resid = y - p50 if len(y) else np.array([0.0])
            #résidu = valeur_réelle - valeur_prédite par le modéle
        else:
            # p50 = moyenne des 8 dernières semaines (ou moins si pas dispo)
            window = min(8, len(y))
            p50 = float(np.mean(y[-window:]))
            resid = y[-window:] - p50
        # Interprétation de resid 
        # resid > 0 : le modèle a sous-estimé            
        # resid < 0 : le modèle a surestimé
        # resid = 0 : prédiction parfaite
        p10 = float(np.percentile(y, 10)) if len(y) else 0.0
        p90 = float(np.percentile(y, 90)) if len(y) else 0.0
        #percentile : valeur en dessous de laquelle se trouve un certain pourcentage des données (valeur seuil dans un ensemble de données.)

        # intervalle par résidus (simple)
        r10 = float(np.percentile(resid, 10)) if len(resid) else 0.0
        r90 = float(np.percentile(resid, 90)) if len(resid) else 0.0

        per_product[int(pid)] = {
            "p50": p50,
            "p10": max(0.0, p50 + r10),
            #p10 est la borne basse prédite (estimation du niveau bas possible)
            "p90": max(0.0, p50 + r90),
            "history_weeks": int(len(y)),
            "last_week": str(g["week"].max()) if len(g) else None,
        }

    return DemandModel(per_product=per_product, horizon_weeks=horizon_weeks)

def train_price_rules(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> Dict[int, Dict[str, Any]]:
    # on garde dernier prix concurrent par produit + médiane
    competitor_prices = competitor_prices.copy()
    competitor_prices["collected_at"] = pd.to_datetime(competitor_prices["collected_at"])
    competitor_prices = competitor_prices.sort_values("collected_at")

    latest = competitor_prices.groupby(["product_id", "competitor_id"], as_index=False).tail(1)
    #on garde le prix concurrent le plus récent
    #la dernière ligne de chaque groupe
    med = latest.groupby("product_id")["competitor_price"].median().to_dict()

    rules = {}
    for _, p in products.iterrows():
        #iterrows : retourne (index,ligne) _ pour ignorer index
        pid = int(p["product_id"])
        rules[pid] = {
            "min_price": float(p["min_price"]),
            "cost_price": float(p["cost_price"]),
            "current_price": float(p["current_price"]),
            "min_margin": float(p["min_margin"]),
            "competitor_median": float(med.get(pid)) if pid in med else None,
        } #construction du dict contenant les regles de prix 
    return rules

def train_restock_rules(products: pd.DataFrame, product_suppliers: pd.DataFrame) -> Dict[int, Dict[str, Any]]:
    # lead time préféré si dispo, sinon fallback 7j
    preferred = product_suppliers[product_suppliers.get("is_preferred", False) == True].copy()
    #produit_suppliers : table qui contient les fournisseurs 
    #get("is_preferred", False): on garde que les lignes ou is_preferred est True 
    lead_map = {}
    if not preferred.empty:
        for pid, g in preferred.groupby("product_id"):
            lead_map[int(pid)] = int(g["lead_time_days"].iloc[0])
            #lead_map : dict qui associe à chaque product_id le lead time préféré (en jours) pour ce produit
            #iloc[0] : pour prendre la première valeur de lead_time_days dans le groupe
            # (au cas où il y a plusieurs fournisseurs préférés pour le même produit, on prend le lead time du premier fournisseur trouvé)
    rules = {}
    for _, p in products.iterrows():
        pid = int(p["product_id"])
        rules[pid] = {
            "threshold_min": int(p["threshold_min"]),
            "threshold_max": int(p["threshold_max"]),
            "current_stock": int(p["current_stock"]),
            "lead_time_days": int(lead_map.get(pid, 7)),
        }
    return rules

def train_anomaly_rules() -> Dict[str, Any]:
    #détecter les seuils fixes 
    return {
        "competitor_price_jump_pct": 0.30, 
        #le pourcentage maximal de variation normale du prix concurrent
        # 30%
        "competitor_price_too_low_vs_cost": 0.90, 
        #Cela compare le prix du concurrent avec notre coût de revient
        # prix concurrent < 90% coût => suspect
        "sales_spike_z": 3.0,
        #z-score pour détecter les pics de vente anormaux
        #3.0 si les ventes dépassent de 3 écarts-types la moyenne historique => suspect (pic anormal)
    }
    
    #notre coût = 100
    #90% du coût = 90
    #Si le concurrent vend à 85
    #→ c’est en dessous de 90
    #→ le système considère cela comme suspect