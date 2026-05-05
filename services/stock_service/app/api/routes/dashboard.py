from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.dashboard_metrics_service import DashboardMetricsService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _params(
    period_days: int = Query(30, ge=1, le=365),
    categorie: str | None = None,
    marque: str | None = None,
    statut_stock: str | None = None,
    statut_promotion: str | None = None,
    position_marche: str | None = None,
):
    return {
        "period_days": period_days,
        "categorie": categorie,
        "marque": marque,
        "statut_stock": statut_stock,
        "statut_promotion": statut_promotion,
        "position_marche": position_marche,
    }


@router.get("/filters")
def dashboard_filters(db: Session = Depends(get_db)):
    return DashboardMetricsService(db).filters()


@router.get("/stock")
def stock_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    return DashboardMetricsService(db).stock_dashboard(params)


@router.get("/pricing")
def pricing_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    return DashboardMetricsService(db).pricing_dashboard(params)


@router.get("/manager")
def manager_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    return DashboardMetricsService(db).manager_dashboard(params)


def _build_pdf_or_raise(dashboard_type: str, data: dict, params: dict) -> bytes:
    """
    Import volontairement ici pour afficher une vraie erreur API si reportlab
    n'est pas installé, au lieu de faire tomber stock_service au démarrage.
    """
    try:
        from app.services.dashboard_pdf_service import build_dashboard_pdf
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", "module")
        raise HTTPException(
            status_code=500,
            detail=(
                f"Module Python manquant pour l'export PDF: {missing}. "
                "Ajoute reportlab dans requirements.txt puis lance: "
                "docker compose up --build stock_service"
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur import service PDF: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return build_dashboard_pdf(dashboard_type, data, params)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur génération PDF {dashboard_type}: {type(exc).__name__}: {exc}",
        ) from exc


def _pdf_response(filename: str, pdf_bytes: bytes) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/export/stock")
def export_stock_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    data = DashboardMetricsService(db).stock_dashboard(params)
    pdf = _build_pdf_or_raise("stock", data, params)
    return _pdf_response("dashboard-stock.pdf", pdf)


@router.get("/export/pricing")
def export_pricing_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    data = DashboardMetricsService(db).pricing_dashboard(params)
    pdf = _build_pdf_or_raise("pricing", data, params)
    return _pdf_response("dashboard-pricing.pdf", pdf)


@router.get("/export/manager")
def export_manager_dashboard(params: dict = Depends(_params), db: Session = Depends(get_db)):
    data = DashboardMetricsService(db).manager_dashboard(params)
    pdf = _build_pdf_or_raise("manager", data, params)
    return _pdf_response("dashboard-manager.pdf", pdf)
