from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.database import init_db
from .api.routes.health import router as health_router
from .api.routes.products import router as products_router
from .api.routes.bulk_imports import router as bulk_router
from .api.routes.sales_history import router as sales_history_router
from .api.routes.suppliers import router as suppliers_router
from .api.routes.supplier_orders import router as supplier_orders_router
from .api.routes.competitors import router as competitors_router
from .api.routes.competitor_products import router as competitor_products_router
from .api.routes.stock_movements import router as stock_movements_router
from .api.routes.import_workflows import router as import_workflows_router
from .api.routes.dashboard import router as dashboard_router

app = FastAPI(title="stock-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


app.include_router(health_router)
app.include_router(products_router)
app.include_router(bulk_router)
app.include_router(sales_history_router)
app.include_router(suppliers_router)
app.include_router(supplier_orders_router)
app.include_router(competitors_router)
app.include_router(competitor_products_router)
app.include_router(stock_movements_router)
app.include_router(import_workflows_router)
app.include_router(dashboard_router)
