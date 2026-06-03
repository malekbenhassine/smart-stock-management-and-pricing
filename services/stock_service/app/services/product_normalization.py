from __future__ import annotations

import re
import unicodedata
from typing import Any


_MULTI_SPACE_RE = re.compile(r"\s+")

# Marques connues : on garde un affichage propre et stable au lieu de créer
# plusieurs valeurs comme hp / HP / Hp.
_BRAND_CANONICAL: dict[str, str] = {
    "acer": "Acer",
    "apple": "Apple",
    "asus": "ASUS",
    "dell": "Dell",
    "epson": "Epson",
    "hp": "HP",
    "hewlett packard": "HP",
    "honor": "Honor",
    "huawei": "Huawei",
    "lenovo": "Lenovo",
    "lg": "LG",
    "msi": "MSI",
    "nokia": "Nokia",
    "oppo": "OPPO",
    "samsung": "Samsung",
    "sony": "Sony",
    "toshiba": "Toshiba",
    "xiaomi": "Xiaomi",
}

# Catégories / familles fréquentes : utile pour éviter Smartphone, smartphone,
# smartphones comme trois valeurs différentes.
_CATEGORY_CANONICAL: dict[str, str] = {
    "smartphone": "Smartphone",
    "smartphones": "Smartphone",
    "telephone": "Smartphone",
    "telephones": "Smartphone",
    "telephone portable": "Smartphone",
    "telephones portables": "Smartphone",
    "téléphone": "Smartphone",
    "téléphones": "Smartphone",
    "téléphone portable": "Smartphone",
    "téléphones portables": "Smartphone",
    "pc": "PC",
    "pcs": "PC",
    "pc portable": "PC portable",
    "pcs portables": "PC portable",
    "ordinateur portable": "PC portable",
    "ordinateurs portables": "PC portable",
    "laptop": "PC portable",
    "laptops": "PC portable",
    "tablette": "Tablette",
    "tablettes": "Tablette",
    "imprimante": "Imprimante",
    "imprimantes": "Imprimante",
    "accessoire": "Accessoire",
    "accessoires": "Accessoire",
}

_UPPER_WORDS = {"pc", "tv", "ssd", "hdd", "usb", "ram", "cpu", "gpu", "led", "wifi", "wi-fi", "4g", "5g"}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _compact(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("_", " ").replace("-", " ")
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def normalize_label_key(value: Any) -> str:
    """Clé technique pour comparer deux libellés sans tenir compte de la casse/accents."""
    text = _compact(value).lower()
    text = _strip_accents(text)
    text = re.sub(r"[^a-z0-9+ ]+", " ", text)
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def _title_keep_acronyms(key: str) -> str:
    words = []
    for word in key.split():
        if word in _UPPER_WORDS or (len(word) <= 3 and any(ch.isdigit() for ch in word)):
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words).strip()


def _singular_key(key: str) -> str:
    """
    Normalisation volontairement prudente : uniquement le dernier mot, pour éviter
    les doublons simples comme smartphone/smartphones sans casser les marques.
    """
    words = key.split()
    if not words:
        return key

    last = words[-1]
    exceptions = {"asus", "msi", "ios", "windows", "access", "gps"}
    if (
        len(last) > 4
        and last.endswith("s")
        and not last.endswith(("ss", "us", "is"))
        and last not in exceptions
    ):
        words[-1] = last[:-1]
    return " ".join(words)


def normalize_category(value: Any) -> str | None:
    text = _compact(value)
    if not text:
        return None

    key = normalize_label_key(text)
    if not key:
        return None

    if key in _CATEGORY_CANONICAL:
        return _CATEGORY_CANONICAL[key]

    singular = _singular_key(key)
    if singular in _CATEGORY_CANONICAL:
        return _CATEGORY_CANONICAL[singular]

    return _title_keep_acronyms(singular)


def normalize_brand(value: Any) -> str | None:
    text = _compact(value)
    if not text:
        return None

    key = normalize_label_key(text)
    if not key:
        return None

    if key in _BRAND_CANONICAL:
        return _BRAND_CANONICAL[key]

    # Cas où une famille produit a été importée par erreur dans la colonne marque.
    if key in _CATEGORY_CANONICAL:
        return _CATEGORY_CANONICAL[key]

    singular = _singular_key(key)
    if singular in _CATEGORY_CANONICAL:
        return _CATEGORY_CANONICAL[singular]

    if len(text) <= 4 and text.isupper():
        return text

    return _title_keep_acronyms(singular)
