def build_demand_explanation(predicted_demand: float, history_days_used: int) -> str:
    demand = float(predicted_demand or 0.0)

    if history_days_used <= 0:
        return (
            "Aucune donnée historique exploitable n’a été trouvée pour ce produit. "
            "La prévision est donc peu fiable et doit être interprétée avec prudence."
        )

    if demand <= 0:
        return (
            f"La prévision de demande est très faible pour la période à venir. "
            f"Le calcul s’appuie sur {history_days_used} jour(s) d’historique disponible. "
            f"Aucune pression forte sur le stock n’est détectée à court terme."
        )

    return (
        f"La prévision de demande a été calculée à partir de {history_days_used} jour(s) "
        f"d’historique exploitable. La demande attendue est estimée à {demand:.1f} unité(s) "
        f"sur la prochaine semaine. Cette valeur doit être utilisée comme aide à la décision "
        f"et comparée au stock actuel ainsi qu’au rythme de vente observé."
    )


def build_stock_risk_explanation(
    risk: str,
    current_stock: float,
    threshold_min: float,
    threshold_max: float,
    weekly_demand: float,
    coverage_weeks: float | None,
) -> str:
    stock_txt = f"{current_stock:.0f}"
    min_txt = f"{threshold_min:.0f}"
    max_txt = f"{threshold_max:.0f}"
    demand_txt = f"{weekly_demand:.1f}"

    coverage_part = (
        f" La couverture estimée est d’environ {coverage_weeks:.2f} semaine(s)."
        if coverage_weeks is not None
        else ""
    )

    if risk == "STOCKOUT":
        return (
            f"Le produit présente un risque de rupture. Le stock actuel est de {stock_txt} unité(s) "
            f"pour une demande hebdomadaire estimée à {demand_txt}.{coverage_part} "
            f"Une action rapide est recommandée : vérifier le délai fournisseur et lancer un "
            f"réapprovisionnement prioritaire."
        )

    if risk == "LOW_STOCK":
        return (
            f"Le stock actuel ({stock_txt} unité(s)) est inférieur au seuil minimum ({min_txt}). "
            f"La demande hebdomadaire prévue est de {demand_txt}.{coverage_part} "
            f"Le produit doit être surveillé de près, avec un réapprovisionnement préventif "
            f"si la tendance de vente se maintient."
        )

    if risk == "OVERSTOCK":
        return (
            f"Le stock actuel ({stock_txt} unité(s)) dépasse significativement le niveau attendu, "
            f"au regard du seuil maximum ({max_txt}) et de la demande hebdomadaire prévue ({demand_txt}). "
            f"Une commande supplémentaire n’est pas prioritaire. Il est préférable de surveiller "
            f"l’écoulement du produit avant toute nouvelle décision d’achat."
        )

    return (
        f"Le niveau de stock semble cohérent avec la demande prévue. Le stock actuel est de "
        f"{stock_txt} unité(s), pour une demande hebdomadaire estimée à {demand_txt}.{coverage_part} "
        f"Aucune tension majeure n’est détectée à court terme, mais un suivi régulier reste conseillé."
    )


def build_restock_explanation(
    current_stock: float,
    predicted_demand: float,
    recommended_qty: float,
    days_remaining: float,
    urgency: str,
    threshold_min: float | None = None,
    threshold_max: float | None = None,
    used_rule_based: bool = False,
) -> str:
    stock_txt = f"{current_stock:.0f}"
    demand_txt = f"{predicted_demand:.1f}"
    qty_txt = f"{recommended_qty:.0f}"
    days_txt = f"{days_remaining:.1f}"

    threshold_part = ""
    if threshold_min is not None and threshold_max is not None:
        threshold_part = (
            f" Les seuils de référence sont min={threshold_min:.0f} et max={threshold_max:.0f}."
        )

    if recommended_qty <= 0:
        return (
            f"Aucun réapprovisionnement immédiat n’est recommandé. Le stock actuel ({stock_txt} unité(s)) "
            f"semble suffisant au regard de la demande estimée ({demand_txt})."
            f"{threshold_part} La couverture restante est d’environ {days_txt} jour(s)."
        )

    mode_part = (
        " La recommandation repose sur une règle métier, car l’historique disponible est insuffisant."
        if used_rule_based
        else " La recommandation repose sur la demande prévue, le stock actuel et la couverture restante."
    )

    urgency_part = {
        "critical": "Le niveau d’urgence est critique.",
        "high": "Le niveau d’urgence est élevé.",
        "medium": "Le niveau d’urgence est modéré.",
        "low": "Le niveau d’urgence est faible.",
    }.get(urgency, "Le niveau d’urgence est standard.")

    return (
        f"Le stock actuel est de {stock_txt} unité(s) pour une demande estimée à {demand_txt}. "
        f"La couverture restante est d’environ {days_txt} jour(s). Une commande de {qty_txt} unité(s) "
        f"est recommandée afin de réduire le risque de rupture."
        f"{threshold_part}{mode_part} {urgency_part}"
    )


def build_price_explanation(
    current_price: float,
    recommended_price: float,
    predicted_demand: float,
    price_direction: str,
    current_demand: float | None = None,
    season: str | None = None,
    is_peak_season: bool | None = None,
) -> str:
    current_txt = f"{current_price:.2f}"
    recommended_txt = f"{recommended_price:.2f}"
    demand_txt = f"{predicted_demand:.1f}"

    price_diff = recommended_price - current_price
    price_diff_abs = abs(price_diff)
    price_diff_txt = f"{price_diff_abs:.2f}"

    if current_price > 0:
        price_diff_pct = abs((price_diff / current_price) * 100)
    else:
        price_diff_pct = 0.0
    price_diff_pct_txt = f"{price_diff_pct:.1f}"

    demand_comment = ""
    if current_demand is not None:
        if current_demand < 10:
            demand_comment = (
                " La demande actuelle est relativement faible, ce qui justifie un ajustement tarifaire "
                "pour mieux soutenir la performance commerciale du produit."
            )
        elif current_demand < 25:
            demand_comment = (
                " La demande actuelle reste modérée, ce qui invite à adopter un positionnement prix prudent "
                "et cohérent avec le rythme de vente."
            )
        else:
            demand_comment = (
                " Le produit affiche déjà une demande intéressante, ce qui permet d’envisager une optimisation "
                "du prix avec davantage de confiance."
            )

    season_comment = ""
    if season:
        if is_peak_season is True:
            season_comment = (
                f" De plus, nous sommes en saison favorable pour ce produit ({season}), "
                "ce qui renforce l’intérêt de cette décision commerciale."
            )
        elif is_peak_season is False:
            season_comment = (
                f" En revanche, la saison actuelle ({season}) n’est pas la plus porteuse pour ce produit, "
                "ce qui incite à rester prudent afin de ne pas freiner davantage la demande."
            )
        else:
            season_comment = (
                f" La saison actuelle identifiée pour l’analyse est {season}, "
                "un élément à prendre en compte dans l’interprétation de cette recommandation."
            )

    if price_direction == "UP":
        return (
            f"Une hausse de prix est recommandée : le prix peut passer de {current_txt} à {recommended_txt}, "
            f"soit une augmentation de {price_diff_txt} (+{price_diff_pct_txt} %). "
            f"La demande estimée reste à {demand_txt} unités, ce qui montre que le produit peut supporter "
            f"cette revalorisation sans perte brutale de performance."
            f"{demand_comment}"
            f"{season_comment} "
            f"Cette action représente une opportunité intéressante pour améliorer la rentabilité du produit."
        )

    if price_direction == "DOWN":
        return (
            f"Une baisse de prix est recommandée : le prix peut passer de {current_txt} à {recommended_txt}, "
            f"soit une diminution de {price_diff_txt} (-{price_diff_pct_txt} %). "
            f"La demande estimée est de {demand_txt} unités, ce qui suggère qu’un prix plus attractif "
            f"peut favoriser un meilleur écoulement."
            f"{demand_comment}"
            f"{season_comment} "
            f"Cette décision vise à stimuler les ventes et à améliorer la fluidité du stock."
        )

    return (
        f"Le prix recommandé reste proche du prix actuel : {current_txt} contre {recommended_txt}. "
        f"L’écart reste limité à {price_diff_txt} ({price_diff_pct_txt} %), avec une demande estimée à "
        f"{demand_txt} unités."
        f"{demand_comment}"
        f"{season_comment} "
        f"Dans ce contexte, aucun changement tarifaire majeur n’est nécessaire."
    )