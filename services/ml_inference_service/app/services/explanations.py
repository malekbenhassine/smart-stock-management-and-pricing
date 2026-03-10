def explain_demand_weekly(p10: float, p50: float, p90: float) -> str:
    return (
        f"La prévision est basée sur les ventes récentes du produit. "
        f"La demande hebdomadaire la plus probable est estimée à {p50:.0f} unités. "
        f"Dans un scénario bas, elle pourrait être d’environ {p10:.0f} unités, "
        f"et dans un scénario élevé, jusqu’à {p90:.0f} unités."
    )