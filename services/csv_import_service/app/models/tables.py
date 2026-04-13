from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class ImportLog(Base):
    __tablename__ = "import_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    table_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    rows_imported = Column(Integer, default=0)
    error_detail = Column(Text)
    imported_at = Column(DateTime, default=datetime.utcnow)