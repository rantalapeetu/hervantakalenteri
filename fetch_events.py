#!/usr/bin/env python3
"""Hakee tapahtumat lähteistä ja tallentaa ne Supabaseen.

Käyttö:
  python fetch_events.py --dry-run     # tulostaa tapahtumat, ei tallenna
  python fetch_events.py               # tallentaa (vaatii SUPABASE_URL ja SUPABASE_SERVICE_KEY)

Lisää uusi lähde lisäämällä rivi SOURCES-listaan. Jos lähteellä on ICS-kalenteri
(tai RSS/JSON), kirjoita sille oma adapteri samalla tavalla kuin parse_ics().
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time, timezone

import requests
from icalendar import Calendar

# TODO: täytä osoitteet sen jälkeen, kun olet tarkistanut lähteiden käyttöehdot
# ja löytänyt oikean kalenterisyötteen (ks. "Miten tarkistat lähteen tilan").
SOURCES = [
    {"name": "trey", "type": "ics", "url": "https://example.org/TODO-trey.ics", "organizer": "TREY"},
    {"name": "sahkokilta", "type": "ics", "url": "https://example.org/TODO-kilta.ics", "organizer": "Sähkökilta"},
]

USER_AGENT = "hervanta-opiskelijakalenteri/0.1 (opiskelijaprojekti; yhteys: TODO-sähköposti)"

# Yksinkertainen kategoriointi avainsanoilla. Laajenna omien tapahtumien mukaan.
CATEGORY_KEYWORDS = {
    "bileet": ["appro", "sitsit", "bileet", "saunailta", "vuosijuhla"],
    "urheilu": ["liikunta", "salibandy", "juoksu", "jalkapallo", "vuoro"],
    "ura": ["rekry", "yritysvierailu", "messut", "ura", "työpaikka"],
    "opinnot": ["kurssi", "tentti", "opinto", "ilmoittautuminen aukeaa"],
}

# Etsii kuvauksesta esim. "Ilmoittautuminen päättyy 12.10.2026" (vuosi valinnainen)
REG_RE = re.compile(
    r"ilmoittautumi\w*\s+(?:päättyy|sulkeutuu)\s+(\d{1,2})\.(\d{1,2})\.(\d{4})?",
    re.IGNORECASE,
)


def to_datetime(value):
    """ICS-arvo (date tai datetime) -> aikavyöhykkeellinen datetime (UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    return None


def guess_category(title, description):
    text = f"{title} {description or ''}".lower()
    for category, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            return category
    return None


def parse_registration_close(description, starts_at):
    m = REG_RE.search(description or "")
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else starts_at.year
    try:
        return datetime(year, month, day, 23, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_ics(text, source):
    """Muuntaa ICS-tekstin yhteiseen tapahtumamuotoon."""
    events = []
    for comp in Calendar.from_ical(text).walk("VEVENT"):
        starts_at = to_datetime(comp.decoded("DTSTART")) if comp.get("DTSTART") else None
        if not starts_at:
            continue
        title = str(comp.get("SUMMARY", "")).strip()
        description = str(comp.get("DESCRIPTION", "")) or None
        ends_at = to_datetime(comp.decoded("DTEND")) if comp.get("DTEND") else None
        events.append({
            "source": source["name"],
            "external_id": str(comp.get("UID") or f"{title}|{starts_at.isoformat()}"),
            "title": title,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat() if ends_at else None,
            "location": str(comp.get("LOCATION", "")) or None,
            "organizer": source.get("organizer"),
            "category": guess_category(title, description),
            "description": description,
            "url": str(comp.get("URL", "")) or None,
            "registration_opens": None,
            "registration_closes": (
                c.isoformat() if (c := parse_registration_close(description, starts_at)) else None
            ),
        })
    return events


ADAPTERS = {"ics": parse_ics}


def fetch_source(source):
    resp = requests.get(source["url"], headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return ADAPTERS[source["type"]](resp.text, source)


def upsert(events):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/events?on_conflict=source,external_id"
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(events), timeout=30)
    resp.raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    all_events = []
    for source in SOURCES:
        try:
            found = fetch_source(source)
            print(f"{source['name']}: {len(found)} tapahtumaa", file=sys.stderr)
            all_events.extend(found)
        except Exception as exc:  # yhden lähteen virhe ei kaada muita
            print(f"{source['name']}: virhe: {exc}", file=sys.stderr)

    if args.dry_run or not all_events:
        print(json.dumps(all_events, ensure_ascii=False, indent=2))
        return
    upsert(all_events)
    print(f"Tallennettu {len(all_events)} tapahtumaa.", file=sys.stderr)


if __name__ == "__main__":
    main()
