import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    STOCK_MANAGER = "STOCK_MANAGER"
    PRICING_MANAGER = "PRICING_MANAGER"
    MANAGER = "MANAGER"