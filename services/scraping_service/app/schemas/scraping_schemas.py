from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RunNowRequest(BaseModel):
    competitor_id: Optional[int] = None


class DiscoverSiteRequest(BaseModel):
    competitor_name: str
    site_url: str


class CompetitorCatalogDTO(BaseModel):
    title: str
    url: str
    parent_url: Optional[str] = None
    depth: int = 0
    score: float = 0.0
    source: str = "auto_discovery"
    is_selected: bool = True


class DiscoverSiteResponse(BaseModel):
    site_url: str
    host: str
    selectors: Dict[str, Any] = Field(default_factory=dict)
    keywords: List[str] = Field(default_factory=list)
    catalogs: List[CompetitorCatalogDTO] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class CompetitorModel(BaseModel):
    id: int
    nom: str
    site_url: Optional[str] = None
    site_host_normalized: Optional[str] = None
    actif: bool = True
    frequence_scraping_heures: int = 24
    dernier_scraping: Optional[str] = None
    discovery_status: str = "pending"
    auto_keywords: List[str] = Field(default_factory=list)
    selectors_override: Dict[str, Any] = Field(default_factory=dict)
    catalogs: List[Dict[str, Any]] = Field(default_factory=list)

class ProductCompetitorPayload(BaseModel):
    urlProduit: str
    skuConcurrent: Optional[str] = None
    nomProduit: str
    descriptionConcurrent: Optional[str] = None

    concurrent_id: int
    produit_id: Optional[int] = None

    prixConcurrent: float
    ancienPrixConcurrent: Optional[float] = None
    isPromo: bool = False

    disponibilite: Optional[str] = None
    dateCollecte: str
    fiable: bool = True


class CatalogScrapeDetail(BaseModel):
    catalog_url: str
    catalog_title: Optional[str] = None
    pages_parcourues: int
    produits_bruts: int
    produits_uniques: int
    errors: List[str] = Field(default_factory=list)


class ScrapeSummary(BaseModel):
    competitor_id: int
    competitor_name: str
    pages_parcourues: int
    produits_bruts: int
    produits_uniques: int
    produits_enregistres: int
    produits_matches: int = 0
    produits_a_valider: int = 0
    produits_ignores: int = 0
    produits_invalides: int = 0
    inserted: int = 0
    updated: int = 0
    catalog_details: List[CatalogScrapeDetail] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    scraped_products: List[Dict[str, Any]] = Field(default_factory=list)
    saved_items: List[Dict[str, Any]] = Field(default_factory=list)
    

class ProductScheduleCreate(BaseModel):
    product_ids: List[int]
    run_at: str
    fast: bool = True
    debug: bool = False
    title: Optional[str] = None


class ProductRunNowRequest(BaseModel):
    product_ids: List[int]
    fast: bool = True
    debug: bool = False


class CatalogFrequencyConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(default=360, ge=5)
    competitor_id: Optional[int] = None
