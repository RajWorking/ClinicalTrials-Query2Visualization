"""Lightweight entity normalization for drug names and conditions.

Not a substitute for full MeSH lookup — this is a small starter set of
common brand→generic and condition synonyms that catches the most common
user inputs. The CT.gov v2 API does its own fuzzy matching server-side,
so this layer only helps when the user types a brand name the API ranks
poorly (e.g. "Keytruda" → "Pembrolizumab" gets a stronger result).
"""
from __future__ import annotations

# Brand-name -> generic / WHO INN. Lowercased keys.
DRUG_ALIASES: dict[str, str] = {
    # oncology immunotherapies
    "keytruda": "pembrolizumab",
    "opdivo": "nivolumab",
    "tecentriq": "atezolizumab",
    "imfinzi": "durvalumab",
    "yervoy": "ipilimumab",
    "bavencio": "avelumab",
    # oncology targeted therapies
    "tagrisso": "osimertinib",
    "iressa": "gefitinib",
    "tarceva": "erlotinib",
    "gleevec": "imatinib",
    "glivec": "imatinib",
    "herceptin": "trastuzumab",
    "kadcyla": "trastuzumab emtansine",
    "perjeta": "pertuzumab",
    # diabetes
    "ozempic": "semaglutide",
    "wegovy": "semaglutide",
    "mounjaro": "tirzepatide",
    "trulicity": "dulaglutide",
    "victoza": "liraglutide",
    "saxenda": "liraglutide",
    # cardiovascular
    "lipitor": "atorvastatin",
    "crestor": "rosuvastatin",
    "eliquis": "apixaban",
    "xarelto": "rivaroxaban",
    # cns
    "lexapro": "escitalopram",
    "zoloft": "sertraline",
    "prozac": "fluoxetine",
}

# Condition synonyms / common abbreviations.
CONDITION_ALIASES: dict[str, str] = {
    "nsclc": "Non-small cell lung cancer",
    "sclc": "Small cell lung cancer",
    "tnbc": "Triple negative breast cancer",
    "aml": "Acute myeloid leukemia",
    "all": "Acute lymphoblastic leukemia",
    "cll": "Chronic lymphocytic leukemia",
    "cml": "Chronic myeloid leukemia",
    "mds": "Myelodysplastic syndrome",
    "covid": "COVID-19",
    "covid 19": "COVID-19",
    "t1d": "Type 1 diabetes",
    "t2d": "Type 2 diabetes",
    "ms": "Multiple sclerosis",
    "ibd": "Inflammatory bowel disease",
    "uc": "Ulcerative colitis",
    "ra": "Rheumatoid arthritis",
    "psa": "Psoriatic arthritis",
}


def normalize_drug(name: str | None) -> str | None:
    if not name:
        return name
    canonical = DRUG_ALIASES.get(name.strip().lower())
    return canonical or name


def normalize_condition(name: str | None) -> str | None:
    if not name:
        return name
    canonical = CONDITION_ALIASES.get(name.strip().lower())
    return canonical or name
