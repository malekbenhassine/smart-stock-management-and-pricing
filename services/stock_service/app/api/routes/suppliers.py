from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...schemas.schemas import SupplierCreate, SupplierUpdate
from ...services.supplier_service import (
    get_all_suppliers_service,
    get_supplier_by_id_service,
    create_supplier_service,
    update_supplier_service,
    delete_supplier_service,
)

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("")
def get_suppliers(q: str | None = None, db: Session = Depends(get_db)):
    return get_all_suppliers_service(db, q)


@router.get("/{supplier_id}")
def get_supplier_by_id(supplier_id: int, db: Session = Depends(get_db)):
    return get_supplier_by_id_service(supplier_id, db)


@router.post("")
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    return create_supplier_service(payload, db)


@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)):
    return update_supplier_service(supplier_id, payload, db)


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    return delete_supplier_service(supplier_id, db)