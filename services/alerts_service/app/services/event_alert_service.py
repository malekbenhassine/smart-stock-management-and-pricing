from __future__ import annotations

from typing import Any, List

from app.schemas.alert_schemas import AlertCreate, AlertEventCreate

ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_STOCK = "STOCK"
ROLE_PRICING = "PRICING"


def _meta(event: AlertEventCreate) -> dict[str, Any]:
    data = dict(event.metadata or {})
    data.update(
        {
            "event_type": event.event_type,
            "event_user_id": event.user_id,
            "event_user_email": event.user_email,
            "event_user_role": event.user_role,
        }
    )
    return {k: v for k, v in data.items() if v is not None}


def _targeted(
    event: AlertEventCreate,
    *,
    title: str,
    message: str,
    alert_type: str,
    priority: str,
    role: str | None = None,
    user_id: int | None = None,
    broadcast: bool = False,
    value: Any = None,
    threshold: Any = None,
) -> AlertCreate:
    return AlertCreate(
        title=title,
        message=message,
        alert_type=alert_type,
        priority=priority,
        source_service=event.source_service,
        recipient_user_id=user_id,
        target_role=role,
        broadcast=broadcast,
        product_id=event.product_id,
        product_name=event.product_name,
        value=str(value if value is not None else event.value)
        if (value is not None or event.value is not None)
        else None,
        threshold=str(threshold if threshold is not None else event.threshold)
        if (threshold is not None or event.threshold is not None)
        else None,
        metadata=_meta(event),
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def alerts_from_event(event: AlertEventCreate) -> List[AlertCreate]:
    t = event.event_type.upper().strip()
    m = event.metadata or {}

    if t == "SCRAPING_SUCCESS":
        message = m.get("message") or "Le scraping est terminé avec succès."
        alerts = []

        # Si le front envoie user_id, l'alerte est personnelle.
        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Scraping terminé",
                    message=message,
                    alert_type="SCRAPING_SUCCESS",
                    priority="LOW",
                    user_id=event.user_id,
                    value=m.get("value"),
                )
            )

        # Fallback indispensable : si user_id est absent, l'alerte reste visible
        # dans le centre d'alertes des responsables stock.
        if not event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Scraping terminé",
                    message=message,
                    alert_type="SCRAPING_SUCCESS",
                    priority="LOW",
                    role=ROLE_STOCK,
                    value=m.get("value"),
                )
            )

        return alerts

    if t in {"SCRAPING_FAILED", "SCRAPING_ERROR"}:
        message = m.get("message") or "Le scraping a échoué."
        alerts = []

        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Échec du scraping",
                    message=message,
                    alert_type="SCRAPING_FAILED",
                    priority="IMPORTANT",
                    user_id=event.user_id,
                )
            )

        if not event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Échec du scraping",
                    message=message,
                    alert_type="SCRAPING_FAILED",
                    priority="IMPORTANT",
                    role=ROLE_STOCK,
                )
            )

        return alerts

    if t == "COMPETITOR_PRODUCT_TO_VALIDATE":
        count = m.get("count") or event.value
        return [
            _targeted(
                event,
                title="Produit concurrent à valider",
                message=m.get("message")
                or f"{count or 'Un'} produit(s) concurrent(s) nécessitent une validation.",
                alert_type="COMPETITOR_PRODUCT_TO_VALIDATE",
                priority=m.get("priority", "MEDIUM"),
                user_id=event.user_id,
                value=count,
            )
        ]

    if t == "COMPETITOR_CREATED":
        msg = m.get("message") or (
            f"Le concurrent {m.get('competitor_name') or ''} a été ajouté avec succès."
        )
        alerts = [
            _targeted(
                event,
                title="Concurrent ajouté avec succès",
                message=msg,
                alert_type="COMPETITOR_CREATED",
                priority="MEDIUM",
                role=ROLE_STOCK,
            )
        ]

        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Concurrent ajouté avec succès",
                    message=msg,
                    alert_type="COMPETITOR_CREATED",
                    priority="MEDIUM",
                    user_id=event.user_id,
                )
            )

        return alerts

    if t in {"COMPETITOR_CATALOGS_READY", "COMPETITOR_CATALOGS_PARTIAL", "COMPETITOR_CATALOGS_FAILED"}:
        count = m.get("catalogs_count") or event.value or 0
        competitor_name = m.get("competitor_name") or "le concurrent"

        if t == "COMPETITOR_CATALOGS_READY":
            title = "Catalogues concurrent prêts"
            priority = "MEDIUM"
            alert_type = "COMPETITOR_CATALOGS_READY"
            msg = m.get("message") or (
                f"Les catalogues de {competitor_name} sont prêts : {count} catalogue(s) détecté(s)."
            )
        elif t == "COMPETITOR_CATALOGS_PARTIAL":
            title = "Découverte catalogues partielle"
            priority = "IMPORTANT"
            alert_type = "COMPETITOR_CATALOGS_PARTIAL"
            msg = m.get("message") or (
                f"Découverte partielle pour {competitor_name} : {count} catalogue(s) détecté(s)."
            )
        else:
            title = "Échec découverte catalogues"
            priority = "IMPORTANT"
            alert_type = "COMPETITOR_CATALOGS_FAILED"
            msg = m.get("message") or (
                f"La découverte des catalogues de {competitor_name} a échoué."
            )

        alerts = [
            _targeted(
                event,
                title=title,
                message=msg,
                alert_type=alert_type,
                priority=priority,
                role=ROLE_STOCK,
                value=count,
            )
        ]

        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title=title,
                    message=msg,
                    alert_type=alert_type,
                    priority=priority,
                    user_id=event.user_id,
                    value=count,
                )
            )

        return alerts

    if t == "AUTH_FAILED":
        email = event.user_email or m.get("email") or "inconnu"
        return [
            _targeted(
                event,
                title="Échec d’authentification",
                message=f"Une tentative de connexion a échoué pour : {email}.",
                alert_type="AUTH_FAILED",
                priority="MEDIUM",
                role=ROLE_ADMIN,
            )
        ]

    if t == "ACCOUNT_CREATED":
        full_name = (
            m.get("full_name")
            or f"{m.get('prenom', '')} {m.get('nom', '')}".strip()
            or event.user_email
            or m.get("email")
            or "Utilisateur"
        )

        roles_raw = m.get("roles") or event.user_role or []

        if isinstance(roles_raw, list):
            roles_text = ", ".join(str(role) for role in roles_raw if role)
        elif isinstance(roles_raw, str):
            roles_text = roles_raw
        else:
            roles_text = ""

        if not roles_text:
            roles_text = "Non précisé"

        message = (
            f"Un nouveau compte a été créé : {full_name}. "
            f"Rôle(s) attribué(s) : {roles_text}."
        )

        return [
            _targeted(
                event,
                title="Nouveau compte créé",
                message=message,
                alert_type="ACCOUNT_CREATED",
                priority="MEDIUM",
                role=ROLE_ADMIN,
            ),
            _targeted(
                event,
                title="Nouveau compte créé",
                message=message,
                alert_type="ACCOUNT_CREATED",
                priority="MEDIUM",
                role=ROLE_MANAGER,
            ),
        ]
    if t == "ACCOUNT_ACTIVATED":
        full_name = (
            m.get("full_name")
            or f"{m.get('prenom', '')} {m.get('nom', '')}".strip()
            or event.user_email
            or m.get("email")
            or "Utilisateur"
        )

        return [
            _targeted(
                event,
                title="Compte activé",
                message=f"Le compte de {full_name} est passé de INACTIVE à ACTIVE.",
                alert_type="ACCOUNT_ACTIVATED",
                priority="MEDIUM",
                role=ROLE_ADMIN,
            )
        ]

    if t in {"PASSWORD_CHANGED", "PASSWORD_RESET"}:
        full_name = (
            m.get("full_name")
            or f"{m.get('prenom', '')} {m.get('nom', '')}".strip()
            or event.user_email
            or m.get("email")
            or "Utilisateur"
        )

        return [
            _targeted(
                event,
                title="Mot de passe modifié",
                message=f"Le mot de passe du compte {full_name} a été modifié.",
                alert_type="PASSWORD_CHANGED",
                priority="MEDIUM",
                role=ROLE_ADMIN,
            )
        ]

    if t == "CSV_IMPORT_SUCCESS":
        rows = _safe_int(event.value or m.get("rows_imported") or m.get("rows_count"))
        table = m.get("table") or "données"
        filename = m.get("filename") or "fichier CSV"

        priority = (
            "IMPORTANT"
            if table in {"ventes", "lignes_ventes", "sales_history"}
            else "MEDIUM"
            if rows >= 1000
            else "LOW"
        )

        alerts = []

        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Import terminé",
                    message=f"Votre import de {table} est terminé : {rows} ligne(s).",
                    alert_type="CSV_IMPORT_SUCCESS",
                    priority=priority,
                    user_id=event.user_id,
                    value=rows,
                )
            )

        alerts.append(
            _targeted(
                event,
                title="Import terminé",
                message=f"Le responsable stock a importé le fichier {filename} ({rows} lignes importées).",
                alert_type="CSV_IMPORT_SUCCESS",
                priority=priority,
                role=ROLE_MANAGER,
                value=rows,
            )
        )
    

        return alerts    
    if t == "CSV_IMPORT_FAILED":
        table = m.get("table") or "données"
        msg = m.get("error") or "Erreur inconnue."

        alerts = []

        if event.user_id:
            alerts.append(
                _targeted(
                    event,
                    title="Votre import a échoué",
                    message=f"L’import de {table} a échoué : {msg}",
                    alert_type="CSV_IMPORT_FAILED",
                    priority="IMPORTANT",
                    user_id=event.user_id,
                )
            )
        

        alerts.append(
            _targeted(
                event,
                title="Import échoué",
                message=f"L’import de {table} a échoué : {msg}",
                alert_type="CSV_IMPORT_FAILED",
                priority="IMPORTANT",
                role=ROLE_MANAGER,
            )
         )
    
        return alerts

    if t == "PRICE_CHANGE_IMPORTANT":
        return [
            _targeted(
                event,
                title="Modification importante du prix",
                message=m.get("message")
                or f"Variation importante détectée pour {event.product_name or 'un produit'}.",
                alert_type="PRICE_CHANGE_IMPORTANT",
                priority=m.get("priority", "IMPORTANT"),
                role=ROLE_MANAGER,
            )
        ]

    if t == "PRICE_CHANGE_REQUEST_APPROVED":
        product_name = event.product_name or m.get("product_name") or "un produit"
        ancien_prix = m.get("ancien_prix")
        nouveau_prix = m.get("nouveau_prix")
        manager = m.get("manager") or "Manager"

        return [
            _targeted(
                event,
                title="Prix accepté par le manager",
                message=m.get("message")
                or (
                    f"Le manager a accepté le nouveau prix pour {product_name}. "
                    f"Ancien prix : {ancien_prix} TND, nouveau prix : {nouveau_prix} TND."
                ),
                alert_type="PRICE_CHANGE_REQUEST_APPROVED",
                priority=m.get("priority", "MEDIUM"),
                role=ROLE_PRICING,
                value=nouveau_prix,
            )
        ]

    if t == "PRICE_CHANGE_REQUEST_REJECTED":
        product_name = event.product_name or m.get("product_name") or "un produit"
        ancien_prix = m.get("ancien_prix")
        nouveau_prix = m.get("nouveau_prix")
        commentaire = m.get("commentaire_manager")

        message = m.get("message") or (
            f"Le manager a refusé la modification de prix pour {product_name}. "
            f"Le responsable pricing doit proposer ou fixer un nouveau prix."
        )

        if commentaire:
            message += f" Commentaire manager : {commentaire}"

        return [
            _targeted(
                event,
                title="Prix refusé par le manager",
                message=message,
                alert_type="PRICE_CHANGE_REQUEST_REJECTED",
                priority="IMPORTANT",
                role=ROLE_PRICING,
                value=nouveau_prix,
            )
        ]
    if t == "PRICE_RECOMMENDATION_AVAILABLE":
        return [
            _targeted(
                event,
                title="Recommandation de prix disponible",
                message=m.get("message")
                or f"Une recommandation de prix est disponible pour {event.product_name or 'un produit'}.",
                alert_type="PRICE_RECOMMENDATION_AVAILABLE",
                priority=m.get("priority", "MEDIUM"),
                role=ROLE_PRICING,
            )
        ]

    return [
        _targeted(
            event,
            title="Nouvelle alerte",
            message=m.get("message") or "Un événement a été reçu par le centre d’alertes.",
            alert_type=t,
            priority="MEDIUM",
            role=event.target_role,
            user_id=event.user_id,
        )
    ]