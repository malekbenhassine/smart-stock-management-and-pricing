from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl


class CompetitorCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=255)
    site_url: HttpUrl
    actif: bool = True
    frequence_scraping_heures: int = Field(default=24, ge=1, le=168)


class CompetitorUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=2, max_length=255)
    site_url: Optional[HttpUrl] = None
    actif: Optional[bool] = None
    frequence_scraping_heures: Optional[int] = Field(default=None, ge=1, le=168)


class CompetitorAdvancedConfigUpdate(BaseModel):
    selectors_override: Optional[Dict[str, Any]] = None


class CompetitorCatalogOut(BaseModel):
    id: int
    title: str
    url: str
    parent_url: Optional[str] = None
    depth: int
    score: float
    source: str
    is_selected: bool
    is_active: bool


class CompetitorOut(BaseModel):
    id: int
    nom: str
    site_url: str
    site_host_normalized: str
    actif: bool
    frequence_scraping_heures: int
    dernier_scraping: Optional[str] = None

    discovery_status: str
    last_discovery_at: Optional[str] = None
    last_discovery_error: Optional[str] = None

    auto_keywords: List[str] = Field(default_factory=list)
    selectors_override: Dict[str, Any] = Field(default_factory=dict)
    catalogs: List[CompetitorCatalogOut] = Field(default_factory=list)


class CompetitorCatalogSelectionUpdate(BaseModel):
    catalog_ids: List[int]


class ProductCompetitorCreate(BaseModel):
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
    dateCollecte: Optional[str] = None
    fiable: bool = True