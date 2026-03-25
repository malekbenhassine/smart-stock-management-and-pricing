from fastapi import APIRouter, Query

from ...services.product_service import (
    get_all_products,
    get_product_by_id_service,
    get_product_pricing_details_service,
    get_product_stock_details_service,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def get_products(
    q: str | None = Query(default=None, description="Recherche par nom, SKU, marque ou catégorie"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return get_all_products(q=q, limit=limit)


@router.get("/{product_id}")
def get_product_by_id(product_id: int):
    return get_product_by_id_service(product_id)


@router.get("/{product_id}/pricing-details")
def get_product_pricing_details(product_id: int):
    return get_product_pricing_details_service(product_id)


@router.get("/{product_id}/stock-details")
def get_product_stock_details(product_id: int):
    return get_product_stock_details_service(product_id)