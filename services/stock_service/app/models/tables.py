from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    Boolean,
    DateTime,
    Date,
    Text,
    JSON,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Product(Base):
    __tablename__ = "produits"

    id = Column(Integer, primary_key=True)
    sku = Column(String(100), unique=True, index=True, nullable=False)
    nom = Column(String(255), nullable=False)
    categorie = Column(String(100), nullable=True)
    marque = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)

    prix_cout = Column("prixCout", Float, nullable=True)
    prix_vente = Column("prixVente", Float, nullable=True)
    marge_reservee = Column("margeReservee", Float, nullable=True)

    stock_disponible = Column("stockDisponible", Integer, nullable=True)
    stock_reserve = Column("stockReserve", Integer, nullable=True)
    stock_minimum = Column("stockMinimum", Integer, nullable=True)
    seuil_max = Column("seuilMax", Integer, nullable=True)
    seuil_min = Column("seuilMin", Integer, nullable=True)
    analyse_concurrentielle_statut = Column("analyseConcurrentielleStatut",String(50),default="NOT_STARTED",nullable=True,)
    analyse_concurrentielle_date = Column("analyseConcurrentielleDate",DateTime,nullable=True,)

    # Workflow pricing : le responsable stock crée le produit, le responsable pricing valide le prix.
    statut_prix = Column("statutPrix", String(50), default="EN_ATTENTE_PRICING", nullable=True)
    date_validation_prix = Column("dateValidationPrix", DateTime, nullable=True)
    note_validation_prix = Column("noteValidationPrix", Text, nullable=True)
    statut = Column(String(50), nullable=True)
    date_debut_observation = Column("dateDebutObservation", Date, nullable=True)
    date_fin_observation = Column("dateFinObservation", Date, nullable=True)


class DemandeModificationPrix(Base):
    __tablename__ = "demandes_modification_prix"

    id = Column(Integer, primary_key=True, index=True)
    produit_id = Column(Integer, ForeignKey("produits.id", ondelete="CASCADE"), nullable=False, index=True)

    ancien_prix = Column("ancienPrix", Float, nullable=False)
    nouveau_prix = Column("nouveauPrix", Float, nullable=False)
    variation_pourcentage = Column("variationPourcentage", Float, nullable=False)

    justification = Column(Text, nullable=True)
    source_recommandation = Column("sourceRecommandation", String(100), nullable=True)
    strategie = Column(String(100), nullable=True)

    statut = Column(String(50), default="EN_ATTENTE_MANAGER", nullable=False, index=True)

    demande_par = Column("demandePar", String(100), default="RESPONSABLE_PRICING", nullable=True)
    date_demande = Column("dateDemande", DateTime, default=datetime.utcnow, nullable=False)

    valide_par = Column("validePar", String(100), nullable=True)
    date_validation = Column("dateValidation", DateTime, nullable=True)
    commentaire_manager = Column("commentaireManager", Text, nullable=True)

    produit = relationship("Product")


class JournalActivite(Base):
    __tablename__ = "journal_activites"

    id = Column(Integer, primary_key=True, index=True)
    role_utilisateur = Column("roleUtilisateur", String(50), nullable=True, index=True)
    nom_utilisateur = Column("nomUtilisateur", String(120), nullable=True)
    type_action = Column("typeAction", String(100), nullable=False, index=True)
    type_entite = Column("typeEntite", String(100), nullable=True)
    entite_id = Column("entiteId", Integer, nullable=True, index=True)
    produit_id = Column("produitId", Integer, nullable=True, index=True)
    description = Column(Text, nullable=False)
    donnees = Column(JSON, nullable=True)
    date_action = Column("dateAction", DateTime, default=datetime.utcnow, nullable=False, index=True)


class Supplier(Base):
    __tablename__ = "fournisseurs"

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=False)
    tel = Column(String(50), nullable=True)
    adresse = Column(String(255), nullable=True)
    lead_time_jours = Column("leadTimejours", Integer, nullable=True)
    score_fiabilite = Column("scorefiabilite", Float, nullable=True)


class SupplierOrder(Base):
    __tablename__ = "commandes_fournisseurs"

    id = Column(Integer, primary_key=True)
    fournisseur_id = Column(Integer, nullable=False, index=True)
    id_commande = Column("idCommande", String(100), unique=True, index=True, nullable=False)
    date_commande = Column("dateCommande", Date, nullable=True)
    date_reception_prevue = Column("dateReceptionPrevue", Date, nullable=True)
    date_reception_reelle = Column("dateReceptionReelle", Date, nullable=True)
    statut = Column(String(50), nullable=True)


class SupplierOrderLine(Base):
    __tablename__ = "lignes_commandes"

    id = Column(Integer, primary_key=True)
    commande_id = Column(Integer, nullable=False, index=True)
    produit_id = Column(Integer, nullable=False, index=True)
    quantite_commandee = Column("quantiteCommandee", Integer, nullable=True)
    quantite_recue = Column("quantiteRecue", Integer, nullable=True)
    prix_achat_unitaire = Column("prixAchatUnitaire", Float, nullable=True)


class Sale(Base):
    __tablename__ = "ventes"

    id = Column(Integer, primary_key=True)
    date_vente = Column("dateVente", DateTime, nullable=True)
    source = Column(String(50), nullable=True)
    statut = Column(String(50), nullable=True)


class SaleLine(Base):
    __tablename__ = "lignes_ventes"

    id = Column(Integer, primary_key=True)
    vente_id = Column(Integer, nullable=False, index=True)
    produit_id = Column(Integer, nullable=False, index=True)
    quantite = Column(Integer, nullable=False)
    prix_vente_unitaire = Column("prixVenteUnitaire", Float, nullable=True)


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=True)
    type = Column(String(50), nullable=True)
    valeur = Column(Float, nullable=True)
    date_debut = Column("dateDebut", Date, nullable=True)
    date_fin = Column("dateFin", Date, nullable=True)
    stock_minimum_requis = Column("stockMinimumRequis", Integer, nullable=True)
    actif = Column(Boolean, default=False, nullable=False)
    prix_promo = Column("prixPromo", Float, nullable=True)


class ProductPromotion(Base):
    __tablename__ = "produit_promotion"

    produit_id = Column(Integer, primary_key=True)
    promotion_id = Column(Integer, primary_key=True)
    prix_promo = Column("prixPromo", Float, nullable=True)


class StockMovement(Base):
    __tablename__ = "mouvement_stock"

    id = Column(Integer, primary_key=True)
    produit_id = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)
    quantite = Column(Integer, nullable=False)
    date_mouvement = Column("dateMouvement", DateTime, default=datetime.utcnow, nullable=False)
    justification = Column(String(255), nullable=True)


class SalesHistory(Base):
    __tablename__ = "historique_ventes"

    __table_args__ = (
        UniqueConstraint(
            "date",
            "store_id",
            "product_id",
            name="uq_sales_history_date_store_product",
        ),
    )

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(String(100), nullable=False, index=True)
    product_id = Column(String(100), nullable=False, index=True)  # SKU

    category = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    sales = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Float, nullable=True)
    discount = Column(Float, nullable=True)
    competitor_pricing = Column(Float, nullable=True)
    units_ordered = Column(Float, nullable=True)
    weather_condition = Column(String(100), nullable=True)
    holiday_promotion = Column(Integer, nullable=True)
    seasonality = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Competitor(Base):
    __tablename__ = "concurrents"
    __table_args__ = (
        UniqueConstraint("siteHostNormalized", name="uq_competitor_site_host"),
    )

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=False)
    site_url = Column("siteUrl", String(500), nullable=False)
    site_host_normalized = Column("siteHostNormalized", String(255), nullable=False, index=True)

    actif = Column(Boolean, default=True, nullable=False)
    frequence_scraping_heures = Column("frequenceScrapingHeures", Integer, default=24, nullable=False)
    dernier_scraping = Column("dernierScraping", DateTime, nullable=True)

    discovery_status = Column("discoveryStatus", String(50), default="pending", nullable=False)
    last_discovery_at = Column("lastDiscoveryAt", DateTime, nullable=True)
    last_discovery_error = Column("lastDiscoveryError", Text, nullable=True)

    auto_keywords_json = Column("autoKeywordsJson", JSON, default=list, nullable=False)
    selectors_override_json = Column("selectorsOverrideJson", JSON, default=dict, nullable=False)

    created_at = Column("createdAt", DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        "updatedAt",
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    catalogs = relationship(
        "CompetitorCatalog",
        back_populates="competitor",
        cascade="all, delete-orphan",
    )


class CompetitorCatalog(Base):
    __tablename__ = "catalogues_concurrents"
    __table_args__ = (
        UniqueConstraint("competitor_id", "urlKey", name="uq_competitor_catalog_urlkey"),
    )

    id = Column(Integer, primary_key=True)
    competitor_id = Column(
        Integer,
        ForeignKey("concurrents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(255), nullable=False)
    url = Column(String(700), nullable=False)
    url_key = Column("urlKey", String(700), nullable=False)

    parent_url = Column("parentUrl", String(700), nullable=True)
    depth = Column(Integer, default=0, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    source = Column(String(50), default="auto_discovery", nullable=False)

    is_selected = Column("isSelected", Boolean, default=True, nullable=False)
    is_active = Column("isActive", Boolean, default=True, nullable=False)

    discovered_at = Column("discoveredAt", DateTime, default=datetime.utcnow, nullable=False)

    competitor = relationship("Competitor", back_populates="catalogs")


class ProductCompetitor(Base):
    __tablename__ = "produits_concurrents"
    __table_args__ = (
        UniqueConstraint(
            "produit_id",
            "concurrent_id",
            "urlProduit",
            name="uq_product_competitor_url",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    url_produit = Column("urlProduit", Text, nullable=False)
    sku_concurrent = Column("skuConcurrent", String(100), nullable=True)
    nom_produit = Column("nomProduit", String(500), nullable=False)
    description_concurrent = Column("descriptionConcurrent", Text, nullable=True)

    concurrent_id = Column(Integer, nullable=False, index=True)
    produit_id = Column(Integer, nullable=False, index=True)

    prix_concurrent = Column("prixConcurrent", Float, nullable=True)
    ancien_prix_concurrent = Column("ancienPrixConcurrent", Float, nullable=True)

    is_promo = Column("isPromo", Boolean, default=False, nullable=False)
    disponibilite = Column(String(100), nullable=True)
    date_collecte = Column("dateCollecte", DateTime, nullable=True)
    fiable = Column(Boolean, default=True, nullable=False)

    score_matching = Column("scoreMatching", Float, nullable=True)
    statut_matching = Column("statutMatching", String(50), default="IGNORED", nullable=True)
    details_matching = Column("detailsMatching", JSON, nullable=True)
