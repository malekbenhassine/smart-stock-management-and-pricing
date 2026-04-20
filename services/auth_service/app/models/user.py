from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, Integer, String

from app.core.database import Base
from app.models.role import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)

    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)

    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), nullable=False)

    phone = Column(String(30), nullable=True)
    address = Column(String(255), nullable=True)
    birth_date = Column(Date, nullable=True)

    is_active = Column(Boolean, default=False, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)