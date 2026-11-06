#!/usr/bin/env python3
"""
vie_watch.py — surveille les pages carrières de plusieurs entreprises
pour repérer l'apparition d'une nouvelle offre VIE (Volontariat International
en Entreprise), en particulier dans le domaine commercial, et envoie une
alerte instantanée via ntfy.sh.

Deux méthodes de lecture selon le type de site :
  - "sitemap"   : le site publie un sitemap.xml listant chaque offre comme
                  une URL individuelle (rapide, fiable, pas besoin de
                  navigateur). Cas d'Air Liquide, Airbus, Decathlon.
  - "playwright": le site est une application JavaScript sans sitemap
                  exploitable (ex. Renault Group). On charge la page avec
                  un vrai navigateur headless et on surveille le texte
                  visible autour du mot "VIE".
  - "html"      : page HTML classique, lisible sans JavaScript (ex.
                  Sagemcom). Même logique de diff textuel que "playwright"
                  mais sans lancer de navigateur (plus rapide).

État persistant : un fichier JSON par entreprise dans state/, commité par
le workflow GitHub Actions après chaque exécution, pour ne pas re-alerter
sur une offre déjà vue.

Notification : ntfy.sh (gratuit, sans compte, une simple requête POST).
Configure NTFY_TOPIC dans les secrets du repo ou en variable d'environnement.
"""

import json
import os
import re
import sys
import hashlib
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests

STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None

# Mots-clés "commercial" : une offre doit contenir VIE ET au moins un de ces
# mots pour déclencher une alerte. Complète librement cette liste.
COMMERCIAL_KEYWORDS = [
    "commercial", "commerciale", "business developer", "business development",
    "sales", "vente", "ventes", "account manager", "key account",
    "export", "distribution", "partner", "partenariat", "client",
    "market", "marché", "b2b", "b2c", "développement commercial",
]

VIE_RE = re.compile(r"\bVIE\b")  # majuscule volontairement : évite les faux
                                  # positifs sur le mot français "vie"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; vie-watch-perso/1.0; +https://github.com/)"
}

# ---------------------------------------------------------------------------
# Configuration des entreprises à surveiller
# ---------------------------------------------------------------------------
# type: "sitemap" | "html" | "playwright"
# url : URL du sitemap XML, ou de la page (déjà filtrée si possible)
COMPANIES = [
    {
        "name": "Air Liquide",
        "type": "sitemap",
        "url": "https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer/siteMap.xml",
    },
    {
        "name": "Airbus",
        "type": "sitemap",
        "url": "https://ag.wd3.myworkdayjobs.com/Airbus/siteMap.xml",
    },
    {
        "name": "Decathlon",
        "type": "sitemap",
        "url": "https://joinus.decathlon.fr/sitemap.xml",
    },
    {
        "name": "Renault Group",
        "type": "playwright",
        "url": "https://www.renaultgroup.com/carrieres-renault/nos-offres-monde/?jobFunctions=L+-+Sales+%26+Marketing&q=",
    },
    {
        "name": "Sagemcom",
        "type": "html",
        "url": "https://careers.sagemcom.com/offre-de-emploi/liste-toutes-offres.aspx?all=1&mode=layer",
    },
    # Pour ajouter une entreprise : copie un bloc ci-dessus, choisis le type
    # qui correspond (sitemap si robots.txt en référence un contenant les
    # offres individuelles, sinon playwright), et complète l'URL.
]


def slug_text(url: str) -> str:
    """Convertit la fin d'une URL en texte lisible pour appliquer les
    filtres de mots-clés (remplace tirets/underscores par des espaces)."""
    tail = url.rstrip("/").split("/")[-1]
    tail = re.sub(r"_JR\d+$", "", tail)  # retire les référence Workday
    return re.sub(r"[-_]+", " ", tail)


def matches_commercial(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in COMMERCIAL_KEYWORDS)


# ---------------------------------------------------------------------------
# Méthode "sitemap"
# ---------------------------------------------------------------------------
def check_sitemap(company):
    resp = requests.get(company["url"], headers=HEADERS, timeout=30)
    resp.raise_for_status()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(resp.content)
    urls = set()
    for url_el in root.findall("sm:url", ns):
        loc_el = url_el.find("sm:loc", ns)
        if loc_el is not None and loc_el.text:
            urls.add(loc_el.text.strip())

    matches = {}
    for u in urls:
        title = slug_text(u)
        if re.search(r"(?:^|[/_-])VIE(?:[/_-]|$)", u, re.IGNORECASE) and matches_commercial(title):
            matches[u] = title

    return matches  # dict {url: titre_lisible}


# ---------------------------------------------------------------------------
# Méthode "html" (page statique, pas de JS nécessaire)
# ---------------------------------------------------------------------------
def check_html(company):
    resp = requests.get(company["url"], headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text = resp.text
    # on retire les balises pour ne garder que le texte visible
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return extract_vie_blocks(lines)


# ---------------------------------------------------------------------------
# Méthode "playwright" (site JavaScript sans sitemap exploitable)
# ---------------------------------------------------------------------------
def check_playwright(company):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(company["url"], wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(4000)  # laisse le temps au JS de finir de rendre
        body_text = page.inner_text("body")
        browser.close()

    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    return extract_vie_blocks(lines)


def extract_vie_blocks(lines):
    """Repère les lignes contenant 'VIE' et garde quelques lignes de
    contexte autour (le titre de poste est souvent juste avant/après)."""
    blocks = {}
    for i, line in enumerate(lines):
        if VIE_RE.search(line):
            context = lines[max(0, i - 2): i + 3]
            block_text = " | ".join(context)
            if matches_commercial(block_text) or matches_commercial(line):
                key = hashlib.sha1(block_text.encode("utf-8")).hexdigest()[:16]
                blocks[key] = block_text
    return blocks


# ---------------------------------------------------------------------------
# État / diff / notification
# ---------------------------------------------------------------------------
def load_state(name):
    path = STATE_DIR / f"{name.lower().replace(' ', '_')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(name, data):
    path = STATE_DIR / f"{name.lower().replace(' ', '_')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def notify(title, message):
    print(f"\n=== ALERTE ===\n{title}\n{message}\n")
    if not NTFY_URL:
        print("(NTFY_TOPIC non configuré : pas de notification envoyée, "
              "voir les logs ci-dessus.)")
        return
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "urgent",
                "Tags": "rotating_light,briefcase",
            },
            timeout=15,
        )
    except Exception as e:
        print(f"Échec d'envoi ntfy: {e}")


def main():
    any_new = False
    for company in COMPANIES:
        name = company["name"]
        print(f"--- Vérification: {name} ({company['type']}) ---")
        try:
            if company["type"] == "sitemap":
                current = check_sitemap(company)
            elif company["type"] == "html":
                current = check_html(company)
            elif company["type"] == "playwright":
                current = check_playwright(company)
            else:
                print(f"Type inconnu pour {name}: {company['type']}")
                continue
        except Exception as e:
            print(f"Erreur pendant la vérification de {name}: {e}")
            continue

        previous = load_state(name)
        new_keys = set(current) - set(previous)

        if new_keys:
            any_new = True
            for k in new_keys:
                label = current[k]
                url_hint = k if k.startswith("http") else company["url"]
                notify(
                    f"Nouvelle offre VIE — {name}",
                    f"{label}\n\nSource : {url_hint}",
                )

        save_state(name, current)
        print(f"{name}: {len(current)} correspondance(s) VIE/commercial actuellement suivie(s), "
              f"{len(new_keys)} nouvelle(s).")

    if not any_new:
        print("\nAucune nouvelle offre VIE commerciale détectée cette fois-ci.")


if __name__ == "__main__":
    sys.exit(main())
