# inference_service

Microservice FastAPI pour la prévision de demande, la recommandation de prix
et la recommandation de restock.

## Structure

```
inference_service/
├── main.py              # Point d'entrée FastAPI
├── config.py            # Variables d'environnement
├── database.py          # Modèles SQLAlchemy + connexion PostgreSQL
├── model_loader.py      # Chargement du modèle XGBoost
├── feature_builder.py   # Construction des features depuis l'historique DB
├── schemas.py           # Schémas Pydantic (requêtes / réponses)
├── requirements.txt
├── models/              # ← Copier depuis train_service/models/
│   ├── demand_model.pkl
│   ├── demand_features.pkl
│   └── use_log_transform.pkl
└── routes/
    ├── demand.py        # POST /demand/forecast
    ├── pricing.py       # POST /pricing/recommend
    ├── restock.py       # POST /restock/recommend
    └── sales.py         # POST /sales/upload-csv  |  POST /sales/record
```

## Installation

```bash
cd inference_service
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

## Configuration

Crée un fichier `.env` ou définis ces variables d'environnement :

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=retail_db
DB_USER=postgres
DB_PASSWORD=postgres

MODELS_DIR=models

RESTOCK_THRESHOLD=1.5
RESTOCK_MULTIPLIER=3.0
MIN_MARGIN_RATIO=0.30
MAX_PRICE_CHANGE=0.20
```

## Copier le modèle depuis train_service

```bash
# Windows
xcopy /E /I train_service\models inference_service\models

# Linux/Mac
cp -r train_service/models inference_service/models
```

## Démarrage

```bash
cd inference_service
uvicorn main:app --reload --port 8001
```

Documentation interactive : http://localhost:8001/docs

---

## Endpoints

### 1. Prévision de demande
**POST /demand/forecast**

```json
{
  "store_id": "S001",
  "product_id": "P0001",
  "date": "2024-07-15",
  "price": 43.71,
  "stock": 150,
  "discount": 10,
  "competitor_pricing": 45.0,
  "weather_condition": "Sunny",
  "category": "Groceries",
  "region": "North"
}
```

Réponse :
```json
{
  "store_id": "S001",
  "product_id": "P0001",
  "date": "2024-07-15",
  "predicted_demand": 187.3,
  "confidence_low": 159.2,
  "confidence_high": 215.4,
  "history_days_used": 60
}
```

---

### 2. Recommandation de prix
**POST /pricing/recommend**

Même body que /demand/forecast.

Réponse :
```json
{
  "current_price": 43.71,
  "recommended_price": 46.30,
  "price_change_pct": 5.93,
  "predicted_demand_at_current_price": 187.3,
  "predicted_demand_at_recommended_price": 181.0,
  "reasoning": "Augmenter le prix de 5.9% devrait générer un revenu supérieur..."
}
```

---

### 3. Recommandation de restock
**POST /restock/recommend**

Même body que /demand/forecast.

Réponse :
```json
{
  "current_stock": 150,
  "predicted_demand": 187.3,
  "restock_needed": true,
  "recommended_order_qty": 412,
  "days_of_stock_remaining": 0.8,
  "urgency": "critical",
  "reasoning": "Stock faible (150 unités) — seulement 0.8 jour(s) de couverture..."
}
```

---

### 4. Ingestion de l'historique des ventes

**POST /sales/upload-csv** — importer le fichier data.csv du train_service  
**POST /sales/record** — insérer un enregistrement unique  
**POST /sales/records** — insérer un batch JSON  
**GET  /sales/history?store_id=S001&product_id=P0001** — consulter l'historique

> ⚠️ Le service a besoin d'historique pour calculer les lags et rolling stats.
> Lance d'abord POST /sales/upload-csv avec ton data.csv pour alimenter la base.

---

### 5. Santé
**GET /health** — vérifie que le modèle est chargé  
**GET /** — status du service
