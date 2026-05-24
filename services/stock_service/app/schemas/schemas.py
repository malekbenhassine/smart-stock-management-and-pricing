from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal, Optional


class ProductIn(BaseModel):
    """
    Schéma utilisé par /products/bulk.

    Correction mapping import :
    - accepte les noms standards du backend : stockdisponible, prixvente...
    - accepte les noms camelCase du modèle Produit : stockDisponible, prixVente...
    - accepte les noms alternatifs venant des fichiers CSV/JSON : reference, designation,
      famille_produit, prix_achat, quantite_disponible, stock_alerte...

    Important : on garde les anciens champs internes en minuscules pour ne pas casser
    products.py qui utilise item.prixvente, item.stockdisponible, etc.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[int] = None
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
    analyseconcurrentiellestatut: Optional[str] = None
    statutprix: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_product_import_fields(cls, data):
        if not isinstance(data, dict):
            return data

        result = dict(data)

        def first_present(*names):
            for name in names:
                if name in result and result[name] not in (None, ""):
                    return result[name]
            return None

        def put(target, *sources):
            if result.get(target) not in (None, ""):
                return
            value = first_present(*sources)
            if value not in (None, ""):
                result[target] = value

        # Identité produit
        put("sku", "sku", "SKU", "reference", "référence", "ref", "code", "code_produit", "product_id")
        put("nom", "nom", "name", "designation", "désignation", "libelle", "libellé", "product_name")
        put("categorie", "categorie", "catégorie", "category", "famille", "famille_produit", "familleproduit", "categorie_produit", "product_category")
        put("marque", "marque", "brand", "fabricant", "manufacturer")
        put("description", "description", "details", "détails", "detail", "product_description")

        # Prix / marge
        put("prixcout", "prixcout", "prixCout", "prix_cout", "prix_achat", "prixachat", "cost", "cost_price", "purchase_price")
        put("prixvente", "prixvente", "prixVente", "prix_vente", "prix_public", "prixpublic", "selling_price", "sale_price", "price")
        put("margereservee", "margereservee", "margeReservee", "marge_reservee", "marge_minimale", "margeminimale", "minimum_margin")

        # Stock / seuils
        put("stockdisponible", "stockdisponible", "stockDisponible", "stock_disponible", "stock", "quantite_disponible", "quantitedisponible", "inventory", "inventory_level", "available_stock")
        put("stockreserve", "stockreserve", "stockReserve", "stock_reserve", "stock_réservé", "quantite_reservee", "quantitereservee", "reserved_stock")
        put("stockminimum", "stockminimum", "stockMinimum", "stock_minimum", "stock_alerte", "stockalerte", "minimum_stock", "min_stock")
        put("seuilmax", "seuilmax", "seuilMax", "seuil_max", "stock_plafond", "stockplafond", "maximum_stock", "max_stock")
        put("seuilmin", "seuilmin", "seuilMin", "seuil_min", "stock_min", "stockmin", "minimum_threshold")

        # Statuts / dates
        put("statut", "statut", "etat_produit", "etat", "status")
        put("datedebutobservation", "datedebutobservation", "dateDebutObservation", "date_debut_observation", "observation_start_date")
        put("datefinobservation", "datefinobservation", "dateFinObservation", "date_fin_observation", "observation_end_date")
        put("analyseconcurrentiellestatut", "analyseconcurrentiellestatut", "analyseConcurrentielleStatut", "analyse_concurrentielle_statut")
        put("statutprix", "statutprix", "statutPrix", "statut_prix")

        return result

    @field_validator(
        "prixcout",
        "prixvente",
        "margereservee",
        mode="before",
    )
    @classmethod
    def parse_float_fields(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace(",", ".")
        return float(value)

    @field_validator(
        "stockdisponible",
        "stockreserve",
        "stockminimum",
        "seuilmax",
        "seuilmin",
        mode="before",
    )
    @classmethod
    def parse_int_fields(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace(",", ".")
        return int(float(value))



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
    id: Optional[int] = None
    nom: str
    siteurl: Optional[str] = None
    actif: Optional[bool] = None
    frequencescrapingheures: Optional[int] = None
    dernierscraping: Optional[datetime] = None


class ProductCompetitorIn(BaseModel):
    id: Optional[int] = None
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
    id: Optional[int] = None
    produit_id: int
    type: str
    quantite: int
    datemouvement: Optional[datetime] = None
    justification: Optional[str] = None
    
class SalesHistoryIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: date

    magasin_id: str = Field(..., alias="store_id")
    produit_id: str = Field(..., alias="product_id")

    categorie: Optional[str] = Field(None, alias="category")
    region: Optional[str] = None

    ventes: float = Field(..., alias="sales")
    prix: float = Field(..., alias="price")

    stock: Optional[float] = None
    remise: Optional[float] = Field(None, alias="discount")
    prix_concurrent: Optional[float] = Field(None, alias="competitor_pricing")
    unites_commandees: Optional[float] = Field(None, alias="units_ordered")
    condition_meteo: Optional[str] = Field(None, alias="weather_condition")
    promotion_jour_ferie: Optional[int] = Field(None, alias="holiday_promotion")
    saisonnalite: Optional[str] = Field(None, alias="seasonality")
     
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

class PriceApprovalRequest(BaseModel):
    prixValide: float
    justification: Optional[str] = None
    strategy: Optional[str] = "competitive"

StockMovementType = Literal[
    "ENTREE",
    "SORTIE",
    "AJUSTEMENT_POSITIF",
    "AJUSTEMENT_NEGATIF",
    "RESERVATION",
    "ANNULATION_RESERVATION",
]
class StockMovementCreate(BaseModel):
    produit_id: int
    type: StockMovementType
    quantite: int = Field(gt=0)
    justification: Optional[str] = None
    dateMouvement: Optional[datetime] = None


class StockMovementUpdate(BaseModel):
    type: Optional[StockMovementType] = None
    quantite: Optional[int] = Field(default=None, gt=0)
    justification: Optional[str] = None
    dateMouvement: Optional[datetime] = None


class StockMovementOut(BaseModel):
    id: int
    produit_id: int
    type: str
    quantite: int
    dateMouvement: datetime
    justification: Optional[str] = None
    
class PostImportWorkflowRequest(BaseModel):
    table_name: str
    max_products: int = 30
    async_mode: bool = True

    # Nouveau : permet de scanner uniquement les produits importés
    product_ids: Optional[list[int]] = None    