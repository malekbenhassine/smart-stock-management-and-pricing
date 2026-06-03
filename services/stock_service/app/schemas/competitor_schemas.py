from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator


ALLOWED_SCRAPING_FREQUENCY_HOURS = {6, 12, 24}
DEFAULT_SCRAPING_FREQUENCY_HOURS = 24


def validate_scraping_frequency(value):
    if value is None or value == "":
        return DEFAULT_SCRAPING_FREQUENCY_HOURS

    try:
        number = int(value)
    except Exception as exc:
        raise ValueError("La fréquence doit être 6h, 12h ou 24h.") from exc

    if number not in ALLOWED_SCRAPING_FREQUENCY_HOURS:
        raise ValueError("La fréquence doit être 6h, 12h ou 24h.")

    return number


class CompetitorCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nom: str = Field(..., min_length=2, max_length=255)
    url_site: HttpUrl = Field(
        ...,
        validation_alias=AliasChoices("url_site", "site_url", "siteurl"),
        serialization_alias="url_site",
    )
    actif: bool = True
    frequence_scraping_heures: int = Field(
        default=DEFAULT_SCRAPING_FREQUENCY_HOURS,
        validation_alias=AliasChoices(
            "frequence_scraping_heures",
            "frequencescrapingheures",
            "frequenceScrapingHeures",
        ),
        serialization_alias="frequence_scraping_heures",
    )

    @field_validator("frequence_scraping_heures", mode="before")
    @classmethod
    def validate_frequency(cls, value):
        return validate_scraping_frequency(value)


class CompetitorUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nom: Optional[str] = Field(default=None, min_length=2, max_length=255)
    url_site: Optional[HttpUrl] = Field(
        default=None,
        validation_alias=AliasChoices("url_site", "site_url", "siteurl"),
        serialization_alias="url_site",
    )
    actif: Optional[bool] = None
    frequence_scraping_heures: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices(
            "frequence_scraping_heures",
            "frequencescrapingheures",
            "frequenceScrapingHeures",
        ),
        serialization_alias="frequence_scraping_heures",
    )

    @field_validator("frequence_scraping_heures", mode="before")
    @classmethod
    def validate_frequency(cls, value):
        if value is None or value == "":
            return None
        return validate_scraping_frequency(value)


class CompetitorAdvancedConfigUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    selectors_override: Optional[Dict[str, Any]] = None
    url_recherche: Optional[List[str]] = None

    selecteurs_override: Optional[Dict[str, Any]] = None
    urls_recherche: Optional[List[str]] = None


class CompetitorCatalogOut(BaseModel):
    id: int

    # Champs français
    titre: str
    url: str
    cle_url: Optional[str] = None
    url_parent: Optional[str] = None
    profondeur: int
    score: float
    source: str
    actif: bool
    date_decouverte: Optional[str] = None

    title: Optional[str] = None
    url_key: Optional[str] = None
    parent_url: Optional[str] = None
    depth: Optional[int] = None
    is_active: Optional[bool] = None
    discovered_at: Optional[str] = None


class CompetitorOut(BaseModel):
    id: int
    nom: str

    url_site: str
    hote_site_normalise: str
    actif: bool
    frequence_scraping_heures: int
    dernier_scraping: Optional[str] = None
    statut_decouverte: str
    date_derniere_decouverte: Optional[str] = None
    erreur_derniere_decouverte: Optional[str] = None
    mots_cles_auto: List[str] = Field(default_factory=list)
    selecteurs_override: Dict[str, Any] = Field(default_factory=dict)
    urls_recherche: List[str] = Field(default_factory=list)
    catalogues: List[CompetitorCatalogOut] = Field(default_factory=list)
    date_creation: Optional[str] = None
    date_modification: Optional[str] = None

    url_site: Optional[str] = None
    hote_site_normalise: Optional[str] = None
    statut_decouverte: Optional[str] = None
    date_derniere_decouverte: Optional[str] = None
    erreur_derniere_decouverte: Optional[str] = None
    mots_cles_auto: List[str] = Field(default_factory=list)
    selecteurs_override: Dict[str, Any] = Field(default_factory=dict)
    urls_recherche: List[str] = Field(default_factory=list)
    catalogues: List[CompetitorCatalogOut] = Field(default_factory=list)
    date_creation: Optional[str] = None
    date_modification: Optional[str] = None

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
