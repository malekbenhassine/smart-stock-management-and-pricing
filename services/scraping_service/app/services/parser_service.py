import re
from typing import Optional
from bs4 import BeautifulSoup

#Ce fichier concu pour nettoyer le texte et extraire les prix.
def normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def extract_text(soup_element) -> Optional[str]:
    if soup_element is None:
        return None
    return normalize_text(soup_element.get_text(" ", strip=True))


def parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None

    text = value.replace("\xa0", " ").strip()
    text = re.sub(r"[^\d,\.]", "", text)

    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")