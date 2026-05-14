CREATE TABLE IF NOT EXISTS demandes_modification_prix (
    id SERIAL PRIMARY KEY,
    produit_id INTEGER NOT NULL REFERENCES produits(id) ON DELETE CASCADE,
    "ancienPrix" DOUBLE PRECISION NOT NULL,
    "nouveauPrix" DOUBLE PRECISION NOT NULL,
    "variationPourcentage" DOUBLE PRECISION NOT NULL,
    justification TEXT,
    "sourceRecommandation" VARCHAR(100),
    strategie VARCHAR(100),
    statut VARCHAR(50) NOT NULL DEFAULT 'EN_ATTENTE_MANAGER',
    "demandePar" VARCHAR(100) DEFAULT 'RESPONSABLE_PRICING',
    "dateDemande" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "validePar" VARCHAR(100),
    "dateValidation" TIMESTAMP,
    "commentaireManager" TEXT
);

CREATE INDEX IF NOT EXISTS idx_demandes_modification_prix_statut ON demandes_modification_prix(statut);
CREATE INDEX IF NOT EXISTS idx_demandes_modification_prix_produit ON demandes_modification_prix(produit_id);

CREATE TABLE IF NOT EXISTS journal_activites (
    id SERIAL PRIMARY KEY,
    "roleUtilisateur" VARCHAR(50),
    "nomUtilisateur" VARCHAR(120),
    "typeAction" VARCHAR(100) NOT NULL,
    "typeEntite" VARCHAR(100),
    "entiteId" INTEGER,
    "produitId" INTEGER,
    description TEXT NOT NULL,
    donnees JSONB,
    "dateAction" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_journal_activites_role ON journal_activites("roleUtilisateur");
CREATE INDEX IF NOT EXISTS idx_journal_activites_date ON journal_activites("dateAction");
CREATE INDEX IF NOT EXISTS idx_journal_activites_produit ON journal_activites("produitId");
