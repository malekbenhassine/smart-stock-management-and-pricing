from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, Date, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Product(Base):
    __tablename__ = "produits"

    id = Column(Integer, primary_key=True)
    sku = Column(String(100), unique=True, index=True, nullable=False)
    nom = Column(String(255), nullable=False)
    categorie = Column(String(100))
    marque = Column(String(100))
    description = Column(Text)

    prix_cout = Column("prixCout", Float)
    prix_vente = Column("prixVente", Float)
    marge_reservee = Column("margeReservee", Float)

    stock_disponible = Column("stockDisponible", Integer)
    stock_reserve = Column("stockReserve", Integer)
    stock_minimum = Column("stockMinimum", Integer)
    seuil_max = Column("seuilMax", Integer)
    seuil_min = Column("seuilMin", Integer)

    statut = Column(String(50))
    date_debut_observation = Column("dateDebutObservation", Date)
    date_fin_observation = Column("dateFinObservation", Date)


class Supplier(Base):
    __tablename__ = "fournisseurs"

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=False)
    tel = Column(String(50))
    adresse = Column(String(255))
    lead_time_jours = Column("leadTimejours", Integer)
    score_fiabilite = Column("scorefiabilite", Float)


class SupplierOrder(Base):
    __tablename__ = "commandes_fournisseurs"

    id = Column(Integer, primary_key=True)
    fournisseur_id = Column(Integer, nullable=False)
    id_commande = Column("idCommande", String(100), unique=True, index=True, nullable=False)
    date_commande = Column("dateCommande", Date)
    date_reception_prevue = Column("dateReceptionPrevue", Date)
    date_reception_reelle = Column("dateReceptionReelle", Date)
    statut = Column(String(50))


class SupplierOrderLine(Base):
    __tablename__ = "lignes_commandes"

    id = Column(Integer, primary_key=True)
    commande_id = Column(Integer, nullable=False)
    produit_id = Column(Integer, nullable=False)
    quantite_commandee = Column("quantiteCommandee", Integer)
    quantite_recue = Column("quantiteRecue", Integer)
    prix_achat_unitaire = Column("prixAchatUnitaire", Float)


class Sale(Base):
    __tablename__ = "ventes"

    id = Column(Integer, primary_key=True)
    date_vente = Column("dateVente", DateTime)
    source = Column(String(50))
    statut = Column(String(50))


class SaleLine(Base):
    __tablename__ = "lignes_ventes"

    id = Column(Integer, primary_key=True)
    vente_id = Column(Integer, nullable=False)
    produit_id = Column(Integer, nullable=False)
    quantite = Column(Integer, nullable=False)
    prix_vente_unitaire = Column("prixVenteUnitaire", Float)


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    nom = Column(String(255))
    type = Column(String(50))
    valeur = Column(Float)
    date_debut = Column("dateDebut", Date)
    date_fin = Column("dateFin", Date)
    stock_minimum_requis = Column("stockMinimumRequis", Integer)
    actif = Column(Boolean, default=False)
    prix_promo = Column("prixPromo", Float)


class ProductPromotion(Base):
    __tablename__ = "produit_promotion"

    produit_id = Column(Integer, primary_key=True)
    promotion_id = Column(Integer, primary_key=True)
    prix_promo = Column("prixPromo", Float)


class Competitor(Base):
    __tablename__ = "concurrents"

    id = Column(Integer, primary_key=True)
    nom = Column(String(255), nullable=False)
    site_url = Column("siteUrl", String(255))
    actif = Column(Boolean, default=True)
    frequence_scraping_heures = Column("frequenceScrapingHeures", Integer)
    dernier_scraping = Column("dernierScraping", DateTime)


class ProductCompetitor(Base):
    __tablename__ = "produits_concurrents"

    id = Column(Integer, primary_key=True)
    url_produit = Column("urlProduit", Text)
    sku_concurrent = Column("skuConcurrent", String(100))
    nom_produit = Column("nomProduit", String(255))
    concurrent_id = Column(Integer, nullable=False)
    produit_id = Column(Integer, nullable=False)
    prix_concurrent = Column("prixConcurrent", Float)
    is_promo = Column("isPromo", Boolean, default=False)
    disponibilite = Column(String(50))
    date_collecte = Column("dateCollecte", DateTime)
    fiable = Column(Boolean, default=True)


class StockMovement(Base):
    __tablename__ = "mouvement_stock"

    id = Column(Integer, primary_key=True)
    produit_id = Column(Integer, nullable=False)
    type = Column(String(50), nullable=False)
    quantite = Column(Integer, nullable=False)
    date_mouvement = Column("dateMouvement", DateTime, default=datetime.utcnow)
    justification = Column(String(255))

class SalesHistory(Base):
    __tablename__ = "sales_history"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(String(100), nullable=False, index=True)
    product_id = Column(String(100), nullable=False, index=True)  # SKU
    category = Column(String(100))
    region = Column(String(100))
    sales = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Float)
    discount = Column(Float)
    competitor_pricing = Column(Float)
    units_ordered = Column(Float)
    weather_condition = Column(String(100))
    holiday_promotion = Column(Integer)
    seasonality = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)    