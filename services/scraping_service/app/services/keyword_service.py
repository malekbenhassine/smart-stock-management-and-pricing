"""
keyword_service.py – extraction de mots-clés génériques à partir des titres collectés.
"""
from __future__ import annotations

import re
from collections import Counter


# Stopwords multilingues étendus (FR + EN + AR translittéré)
STOPWORDS = {
    # Français
    "de", "des", "du", "la", "le", "les", "et", "pour", "avec", "sur",
    "un", "une", "en", "au", "aux", "par", "ou", "dans", "que", "qui",
    # Anglais
    "the", "and", "for", "from", "new", "with", "our", "your",
    # E-commerce générique
    "prix", "promo", "promotion", "stock", "offre", "vente", "achat",
    "achetez", "solde", "gratuit", "livraison", "commande",
    "buy", "sale", "free", "shop", "store", "order", "best",
    # Petits mots
    "les", "pas", "plus", "tout", "tous", "sans", "bon", "non",
}


def normalize_token(value: str) -> str:
    value = value.lower().strip()
    # Garde : lettres latines, chiffres, caractères accentués, tiret, espace
    value = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ\- ]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def generate_keywords(
    category_titles: list[str],
    product_titles: list[str],
    visible_brands: list[str],
) -> list[str]:
    """
    Génère une liste de mots-clés pertinents à partir des titres récupérés.
    Fonctionne pour n'importe quel domaine produit.
    """
    tokens: list[str] = []

    for source in [*category_titles, *product_titles, *visible_brands]:
        text = normalize_token(source)
        if not text:
            continue
        # Séparer sur tiret et espace
        parts = re.split(r"[\s\-]+", text)
        tokens.extend(p for p in parts if p)

    counts = Counter(
        token for token in tokens
        if len(token) >= 3 and token not in STOPWORDS
    )

    return [token for token, _ in counts.most_common(30)]
