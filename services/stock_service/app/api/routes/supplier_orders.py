from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...schemas.schemas import (
    SupplierOrderCreate,
    SupplierOrderUpdate,
    SupplierOrderLineCreate,
    SupplierOrderLineUpdate,
)
from ...services.supplier_order_service import (
    get_all_supplier_orders_service,
    get_supplier_order_by_id_service,
    create_supplier_order_service,
    update_supplier_order_service,
    delete_supplier_order_service,
    add_supplier_order_line_service,
    update_supplier_order_line_service,
    delete_supplier_order_line_service,
)

router = APIRouter(prefix="/supplier-orders", tags=["supplier-orders"])


@router.get("")
def get_supplier_orders(db: Session = Depends(get_db)):
    return get_all_supplier_orders_service(db)


@router.get("/{order_id}")
def get_supplier_order_by_id(order_id: int, db: Session = Depends(get_db)):
    return get_supplier_order_by_id_service(order_id, db)


@router.post("")
def create_supplier_order(payload: SupplierOrderCreate, db: Session = Depends(get_db)):
    return create_supplier_order_service(payload, db)


@router.put("/{order_id}")
def update_supplier_order(order_id: int, payload: SupplierOrderUpdate, db: Session = Depends(get_db)):
    return update_supplier_order_service(order_id, payload, db)


@router.delete("/{order_id}")
def delete_supplier_order(order_id: int, db: Session = Depends(get_db)):
    return delete_supplier_order_service(order_id, db)


@router.post("/{order_id}/lines")
def add_supplier_order_line(order_id: int, payload: SupplierOrderLineCreate, db: Session = Depends(get_db)):
    return add_supplier_order_line_service(order_id, payload, db)


@router.put("/{order_id}/lines/{line_id}")
def update_supplier_order_line(
    order_id: int,
    line_id: int,
    payload: SupplierOrderLineUpdate,
    db: Session = Depends(get_db),
):
    return update_supplier_order_line_service(order_id, line_id, payload, db)


@router.delete("/{order_id}/lines/{line_id}")
def delete_supplier_order_line(order_id: int, line_id: int, db: Session = Depends(get_db)):
    return delete_supplier_order_line_service(order_id, line_id, db)