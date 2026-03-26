from sqlalchemy import (
    Column, Integer, Float, String, Boolean,
    DateTime, Date, Text, ForeignKey, Numeric
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    product_id    = Column(Integer, primary_key=True)
    name          = Column(String(255))
    category      = Column(String(100))
    current_price = Column(Float)
    cost          = Column(Float)
    stock         = Column(Integer)
    min_price     = Column(Float)
    max_price     = Column(Float)
    weight_kg     = Column(Float)
    is_active     = Column(Boolean, default=True)
    supplier_id   = Column(Integer)
    lead_time_days= Column(Integer)
    reorder_point = Column(Integer)
    unit          = Column(String(50))
    tax_rate      = Column(Float)


class Sale(Base):
    __tablename__ = "sales"

    sale_id    = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"))
    timestamp  = Column(DateTime)
    qty        = Column(Integer)
    unit_price = Column(Float)
    channel    = Column(String(50))


class CompetitorPrice(Base):
    __tablename__ = "competitor_prices"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    product_id       = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"))
    competitor_id    = Column(String(100))
    competitor_price = Column(Float)
    collected_at     = Column(DateTime)
    status           = Column(String(50))
    source           = Column(String(100))


class ProductSupplier(Base):
    __tablename__ = "product_suppliers"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    product_id      = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"))
    supplier_id     = Column(Integer)
    lead_time_days  = Column(Integer)
    last_cost_price = Column(Float)
    is_preferred    = Column(Boolean, default=False)


class Promotion(Base):
    __tablename__ = "promotions"

    promo_id     = Column(Integer, primary_key=True)
    product_id   = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"))
    start_date   = Column(Date)
    end_date     = Column(Date)
    discount_pct = Column(Float)
    promo_type   = Column(String(100))
    channel      = Column(String(100))
    min_qty      = Column(Integer)
    max_discount = Column(Float)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    movement_id         = Column(Integer, primary_key=True)
    product_id          = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"))
    movement_type       = Column(String(100))
    direction           = Column(String(10))
    qty                 = Column(Integer)
    timestamp           = Column(DateTime)
    performed_by_user_id= Column(Integer)
    reference           = Column(String(255))


class ImportLog(Base):
    """Trace chaque import CSV : fichier, table, statut, lignes importées."""
    __tablename__ = "import_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    filename    = Column(String(255))
    table_name  = Column(String(100))
    status      = Column(String(50))   # SUCCESS / ERROR
    rows_imported = Column(Integer, default=0)
    error_detail  = Column(Text)
    imported_at   = Column(DateTime)
