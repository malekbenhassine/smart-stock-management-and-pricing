def compute_safe_stock_demand(
    ml_weekly_demand: float,
    recent_sales_7d: float,
    observed_weekly_30d: float,
) -> dict:
    """
    Demande retenue pour le stock :
    on ne laisse jamais le ML sous-estimer fortement la demande réelle récente.
    """
    ml = float(ml_weekly_demand or 0)
    recent_7 = float(recent_sales_7d or 0)
    obs_30 = float(observed_weekly_30d or 0)

    safety_from_7d = recent_7 * 0.70 if recent_7 > 0 else 0
    safety_from_30d = obs_30 * 0.50 if obs_30 > 0 else 0

    retained = max(ml, safety_from_7d, safety_from_30d)

    if retained > ml:
        status = "ML_SECURED_BY_RECENT_SALES"
        label = "Prévision sécurisée"
        message = (
            "La demande retenue utilise un garde-fou basé sur la vitesse réelle "
            "pour éviter une sous-estimation du besoin de stock."
        )
    else:
        status = "ML_FORECAST_USED"
        label = "Prévision ML utilisée"
        message = "La prévision ML est cohérente avec les ventes récentes."

    return {
        "ml_weekly_demand": round(ml, 2),
        "recent_sales_7d": round(recent_7, 2),
        "observed_weekly_30d": round(obs_30, 2),
        "safe_weekly_demand": round(retained, 2),
        "status": status,
        "label": label,
        "message": message,
    }
