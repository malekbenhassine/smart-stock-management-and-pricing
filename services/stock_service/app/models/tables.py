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
    __tablename__ = "sales_history"

    __table_args__ = (
        UniqueConstraint(
            "date",
            "store_id",
            "product_id",
            name="uq_sales_history_date_store_product_v2",
        ),
    )

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)

    magasin_id = Column("store_id", String(100), nullable=False)
    produit_id = Column("product_id", String(100), nullable=False)

    categorie = Column("category", String(100), nullable=True)
    region = Column(String(100), nullable=True)
    ventes = Column("sales", Float, nullable=False)
    prix = Column("price", Float, nullable=False)
    stock = Column(Float, nullable=True)
    remise = Column("discount", Float, nullable=True)
    prix_concurrent = Column("competitor_pricing", Float, nullable=True)
    unites_commandees = Column("units_ordered", Float, nullable=True)
    condition_meteo = Column("weather_condition", String(100), nullable=True)
    promotion_jour_ferie = Column("holiday_promotion", Integer, nullable=True)
    saisonnalite = Column("seasonality", String(50), nullable=True)
    date_creation = Column("created_at", DateTime, default=datetime.utcnow, nullable=False)
    
class Competitor(Base):
    __tablename__ = "concurrents"
    __table_args__ = (
        UniqueConstraint("siteHostNormalized", name="uq_competitor_site_host"),
    )

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=False)

    # Colonnes DB conservées, attributs Python francisés
    url_site = Column("siteUrl", String(500), nullable=False)
    hote_site_normalise = Column("siteHostNormalized", String(255), nullable=False, index=True)

    actif = Column(Boolean, default=True, nullable=False)
    # Fréquence propre au concurrent pour le scraping automatique.
    # Valeurs fonctionnelles autorisées : 6h, 12h ou 24h.
    frequence_scraping_heures = Column("frequenceScrapingHeures", Integer, default=24, nullable=False)
    dernier_scraping = Column("dernierScraping", DateTime, nullable=True)

    statut_decouverte = Column("discoveryStatus", String(50), default="pending", nullable=False)
    date_derniere_decouverte = Column("lastDiscoveryAt", DateTime, nullable=True)
    erreur_derniere_decouverte = Column("lastDiscoveryError", Text, nullable=True)

    mots_cles_auto_json = Column("autoKeywordsJson", JSON, default=list, nullable=False)
    selecteurs_override_json = Column("selectorsOverrideJson", JSON, default=dict, nullable=False)
    urls_recherche = Column("url_recherche", JSON, default=list, nullable=False)

    date_creation = Column("createdAt", DateTime, default=datetime.utcnow, nullable=False)
    date_modification = Column(
        "updatedAt",
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    catalogues = relationship(
        "CompetitorCatalog",
        back_populates="concurrent",
        cascade="all, delete-orphan",
    )


class CompetitorCatalog(Base):
    __tablename__ = "catalogues_concurrents"
    __table_args__ = (
        UniqueConstraint("competitor_id", "urlKey", name="uq_competitor_catalog_urlkey"),
    )

    id = Column(Integer, primary_key=True)

    concurrent_id = Column(
        "competitor_id",
        Integer,
        ForeignKey("concurrents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    titre = Column("title", String(255), nullable=False)
    url = Column(String(700), nullable=False)
    cle_url = Column("urlKey", String(700), nullable=False)

    url_parent = Column("parentUrl", String(700), nullable=True)
    profondeur = Column("depth", Integer, default=0, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    source = Column(String(50), default="auto_discovery", nullable=False)

    # isSelected n'est plus utilisé fonctionnellement.
    # On le garde en compatibilité DB pour éviter les erreurs si la colonne existe encore en NOT NULL.
    _is_selected_legacy = Column("isSelected", Boolean, default=True, nullable=False)

    actif = Column("isActive", Boolean, default=True, nullable=False)
    date_decouverte = Column("discoveredAt", DateTime, default=datetime.utcnow, nullable=False)

    concurrent = relationship("Competitor", back_populates="catalogues")


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
    disponibilite = Column(Text, nullable=True)
    date_collecte = Column("dateCollecte", DateTime, nullable=True)
    fiable = Column(Boolean, default=True, nullable=False)

    score_matching = Column("scoreMatching", Float, nullable=True)
    statut_matching = Column("statutMatching", String(50), default="IGNORED", nullable=True)
    details_matching = Column("detailsMatching", JSON, nullable=True)

class ScrapingCatalogFrequencyConfig(Base):
    """
    Configuration minimale du scraping catalogue périodique.

    On garde les jobs et l'historique détaillé dans le fichier JSON du
    scraping_service, mais les paramètres importants sont persistés en base
    pour éviter que la configuration redevienne inactive après un rebuild ou
    un redémarrage Docker.
    """

    __tablename__ = "scraping_catalog_frequency_config"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    # Champ conservé pour compatibilité avec l'ancien endpoint.
    # La fréquence réelle est maintenant portée par concurrents.frequenceScrapingHeures.
    interval_minutes = Column("intervalMinutes", Integer, default=1440, nullable=False)
    competitor_id = Column("competitorId", Integer, nullable=True)
    next_run_at = Column("nextRunAt", DateTime, nullable=True)
    updated_at = Column(
        "updatedAt",
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

