from sqlalchemy import create_engine, Column, Integer, Float, String, Date, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SalesHistory(Base):
    __tablename__ = "sales_history"
    __table_args__ = (
        UniqueConstraint("date", "store_id", "product_id", name="uq_sales_history_date_store_product"),
    )

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=False, index=True)
    category = Column(String, nullable=True)
    region = Column(String, nullable=True)
    sales = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Float, nullable=True)
    discount = Column(Float, nullable=True)
    competitor_pricing = Column(Float, nullable=True)
    units_ordered = Column(Float, nullable=True)
    weather_condition = Column(String, nullable=True)
    holiday_promotion = Column(Integer, nullable=True)
    seasonality = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PredictionLog(Base):
    __tablename__ = "prediction_log"

    id = Column(Integer, primary_key=True, index=True)
    requested_at = Column(DateTime, default=datetime.utcnow)
    store_id = Column(String, nullable=False)
    product_id = Column(String, nullable=False)
    target_date = Column(Date, nullable=False)
    predicted_demand = Column(Float, nullable=False)
    recommended_price = Column(Float, nullable=True)
    restock_needed = Column(Boolean, nullable=True)
    restock_qty = Column(Float, nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()