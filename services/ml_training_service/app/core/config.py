import os 
from pathlib import Path


# Déf du répertoire racine du backend
# __file__ : chemin du fichier config.py
# resolve() : chemin absolu
# parents[3] : remonte de 3 niveaux pour arriver au dossier backend/
BASE_DIR = Path(__file__).resolve().parents[4]

# Déf du dossier contenant les données d'entraînement
# Si DATA_DIR existe Sinon backend/data
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))


# Définition du dossier racine des artefacts ML
# Les artefacts sont les fichiers générés par l'entraînement (modèles, rapports)
# Par défaut : services/ml_training_service/artifacts
ARTIFACTS_DIR = Path(
    os.getenv(
        "ARTIFACTS_DIR",
        str(Path(__file__).resolve().parents[1] / "artifacts")
    )
)


# Définition du dossier contenant les modèles entraînés
# Ce dossier stocke les modèles sauvegardés (.pkl, .joblib, etc.)
MODELS_DIR = Path(os.getenv("MODELS_DIR", str(ARTIFACTS_DIR / "models")))


# Définition du dossier contenant les rapports d'entraînement
# Ce dossier stocke les métriques, logs et résultats d'évaluation
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(ARTIFACTS_DIR / "reports")))


# Création automatique du dossier des modèles s'il n'existe pas
# parents=True : crée tous les dossiers parents nécessaires
# exist_ok=True : évite une erreur si le dossier existe déjà
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# Création automatique du dossier des rapports s'il n'existe pas
# Garantit que le service ML peut sauvegarder ses résultats sans erreur
REPORTS_DIR.mkdir(parents=True, exist_ok=True)