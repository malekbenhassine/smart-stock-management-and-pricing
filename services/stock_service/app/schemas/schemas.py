from datetime import date, datetime
from pydantic import BaseModel, field_validator
from typing import Optional


class ProductIn(BaseModel):
    id: int
    sku: str
    nom: str
    categorie: Optional[str] = None
    marque: Optional[str] = None
    description: Optional[str] = None
    prixcout: Optional[float] = None
    prixvente: Optional[float] = None
    margereservee: Optional[float] = None
    stockdisponible: Optional[int] = None
    stockreserve: Optional[int] = None
    stockminimum: Optional[int] = None
    seuilmax: Optional[int] = None
    seuilmin: Optional[int] = None
    statut: Optional[str] = None
    datedebutobservation: Optional[date] = None
    datefinobservation: Optional[date] = None


class SupplierIn(BaseModel):
    id: int
    nom: str
    tel: Optional[str] = None
    adresse: Optional[str] = None
    leadtimejours: Optional[int] = None
    scorefiabilite: Optional[float] = None

    @field_validator("tel", mode="before")
    @classmethod
    def coerce_tel_to_str(cls, v):
        if v is None:
            return None
        return str(v).strip()

class SupplierOrderIn(BaseModel):
    id: int
    fournisseur_id: int
    idcommande: str
    datecommande: Optional[date] = None
    datereceptionprevue: Optional[date] = None
    datereceptionreelle: Optional[date] = None
    statut: Optional[str] = None


class SupplierOrderLineIn(BaseModel):
    id: int
    commande_id: int
    produit_id: int
    quantitecommandee: Optional[int] = None
    quantiterecue: Optional[int] = None
    prixachatunitaire: Optional[float] = None


class SaleIn(BaseModel):
    id: int
    datevente: Optional[datetime] = None
    source: Optional[str] = None
    statut: Optional[str] = None


class SaleLineIn(BaseModel):
    id: int
    vente_id: int
    produit_id: int
    quantite: int
    prixventeunitaire: Optional[float] = None


class PromotionIn(BaseModel):
    id: int
    nom: Optional[str] = None
    type: Optional[str] = None
    valeur: Optional[float] = None
    datedebut: Optional[date] = None
    datefin: Optional[date] = None
    stockminimumrequis: Optional[int] = None
    actif: Optional[bool] = None
    prixpromo: Optional[float] = None


class ProductPromotionIn(BaseModel):
    produit_id: int
    promotion_id: int
    prixpromo: Optional[float] = None


class CompetitorIn(BaseModel):
    id: int
    nom: str
    siteurl: Optional[str] = None
    actif: Optional[bool] = None
    frequencescrapingheures: Optional[int] = None
    dernierscraping: Optional[datetime] = None


class ProductCompetitorIn(BaseModel):
    id: int
    urlproduit: Optional[str] = None
    skuconcurrent: Optional[str] = None
    nomproduit: Optional[str] = None
    concurrent_id: int
    produit_id: int
    prixconcurrent: Optional[float] = None
    ispromo: Optional[bool] = None
    disponibilite: Optional[str] = None
    datecollecte: Optional[datetime] = None
    fiable: Optional[bool] = None


class StockMovementIn(BaseModel):
    id: int
    produit_id: int
    type: str
    quantite: int
    datemouvement: Optional[datetime] = None
    justification: Optional[str] = None
    
class SalesHistoryIn(BaseModel):
    date: date
    store_id: str
    product_id: str
    category: Optional[str] = None
    region: Optional[str] = None
    units_sold: float
    price: float
    inventory_level: Optional[float] = None
    discount: Optional[float] = None
    competitor_pricing: Optional[float] = None
    units_ordered: Optional[float] = None
    weather_condition: Optional[str] = None
    holiday_promotion: Optional[int] = None
    seasonality: Optional[str] = None  
class ProductCreate(BaseModel):
    sku: str
    nom: str
    categorie: Optional[str] = None
    marque: Optional[str] = None
    description: Optional[str] = None
    prixCout: Optional[float] = None
    prixVente: Optional[float] = None
    margeReservee: Optional[float] = None
    stockDisponible: Optional[int] = None
    stockReserve: Optional[int] = None
    stockMinimum: Optional[int] = None
    seuilMax: Optional[int] = None
    seuilMin: Optional[int] = None
    statut: Optional[str] = None
    dateDebutObservation: Optional[date] = None
    dateFinObservation: Optional[date] = None


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    nom: Optional[str] = None
    categorie: Optional[str] = None
    marque: Optional[str] = None
    description: Optional[str] = None
    prixCout: Optional[float] = None
    prixVente: Optional[float] = None
    margeReservee: Optional[float] = None
    stockDisponible: Optional[int] = None
    stockReserve: Optional[int] = None
    stockMinimum: Optional[int] = None
    seuilMax: Optional[int] = None
    seuilMin: Optional[int] = None
    statut: Optional[str] = None
    dateDebutObservation: Optional[date] = None
    dateFinObservation: Optional[date] = None


class ProductPriceUpdate(BaseModel):
    newPrixVente: float
    justification: Optional[str] = None


class SupplierCreate(BaseModel):
    nom: str
    tel: Optional[str] = None
    adresse: Optional[str] = None
    leadTimejours: Optional[int] = None
    scorefiabilite: Optional[float] = None

    @field_validator("tel", mode="before")
    @classmethod
    def coerce_tel_to_str_create(cls, v):
        if v is None:
            return None
        return str(v).strip()


class SupplierUpdate(BaseModel):
    nom: Optional[str] = None
    tel: Optional[str] = None
    adresse: Optional[str] = None
    leadTimejours: Optional[int] = None
    scorefiabilite: Optional[float] = None

    @field_validator("tel", mode="before")
    @classmethod
    def coerce_tel_to_str_update(cls, v):
        if v is None:
            return None
        return str(v).strip()


class SupplierOrderCreate(BaseModel):
    fournisseur_id: int
    idCommande: str
    dateCommande: Optional[date] = None
    dateReceptionPrevue: Optional[date] = None
    dateReceptionReelle: Optional[date] = None
    statut: Optional[str] = None


class SupplierOrderUpdate(BaseModel):
    fournisseur_id: Optional[int] = None
    idCommande: Optional[str] = None
    dateCommande: Optional[date] = None
    dateReceptionPrevue: Optional[date] = None
    dateReceptionReelle: Optional[date] = None
    statut: Optional[str] = None


class SupplierOrderLineCreate(BaseModel):
    produit_id: int
    quantiteCommandee: Optional[int] = None
    quantiteRecue: Optional[int] = None
    prixAchatUnitaire: Optional[float] = None


class SupplierOrderLineUpdate(BaseModel):
    produit_id: Optional[int] = None
    quantiteCommandee: Optional[int] = None
    quantiteRecue: Optional[int] = None
    prixAchatUnitaire: Optional[float] = None      