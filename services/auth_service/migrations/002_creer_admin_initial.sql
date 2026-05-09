CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE utilisateur
ADD COLUMN IF NOT EXISTS adresse VARCHAR(255);

ALTER TABLE utilisateur
ADD COLUMN IF NOT EXISTS telephone VARCHAR(50);

ALTER TABLE utilisateur
ADD COLUMN IF NOT EXISTS date_naissance DATE;

ALTER TABLE utilisateur
ADD COLUMN IF NOT EXISTS doit_changer_mot_de_passe BOOLEAN DEFAULT TRUE;

ALTER TABLE utilisateur
ADD COLUMN IF NOT EXISTS roles JSONB DEFAULT '[]'::jsonb;

INSERT INTO utilisateur (
    prenom,
    nom,
    email,
    mot_de_passe_hash,
    roles,
    telephone,
    adresse,
    date_naissance,
    est_actif,
    email_verifie,
    doit_changer_mot_de_passe,
    cree_le,
    modifie_le
)
VALUES (
    'Admin',
    'IT',
    'admin@gmail.com',
    crypt('admin1234', gen_salt('bf')),
    '["ADMIN"]'::jsonb,
    NULL,
    NULL,
    NULL,
    TRUE,
    TRUE,
    TRUE,
    NOW(),
    NOW()
)
ON CONFLICT (email) DO UPDATE SET
    prenom = EXCLUDED.prenom,
    nom = EXCLUDED.nom,
    mot_de_passe_hash = EXCLUDED.mot_de_passe_hash,
    roles = '["ADMIN"]'::jsonb,
    est_actif = TRUE,
    email_verifie = TRUE,
    doit_changer_mot_de_passe = TRUE,
    modifie_le = NOW();