"""Normalizacja stringów lokalizacji z ATS-ów do (city, remote).

Powód istnienia tego modułu: ATS-y nie mają znormalizowanego pola miasta.
Zwracają jeden string wpisany ręcznie przez firmę i **każdy robi to inaczej**,
a co gorsza — różne firmy w tym samym ATS-ie robią to inaczej:

    "ul. Zbożowa 4, 70-653 Stettin"   Greenhouse / home.pl  (adres pocztowy + egzonim)
    "Szczecin, Poland"                Greenhouse / typowy board
    "Portugal, Lisbon"                Lever / pipedrive     (kraj PRZED miastem)
    "San Francisco, CA"               Lever / typowy board  (miasto przed stanem)
    "Remote"                          oba

Pierwsze podejście (osobno w każdym parserze: "weź ostatni segment po
przecinku") działało dla firmy, na której je napisano, i dawało kraj zamiast
miasta dla najpowszechniejszego formatu — czyli ciche zero ofert, bez błędu i
bez logu. Dlatego reguła jest jedna, wspólna i testowana na kontrprzykładach,
a nie dopasowana do jednej firmy.

Reguła: odrzuć segmenty, które są krajami/regionami albo samym kodem
pocztowym; z reszty wybierz segment z polskim kodem pocztowym (adres), a jeśli
takiego nie ma — pierwszy pozostały. Na końcu zmapuj egzonim.
"""

import re

# Polski kod pocztowy "NN-NNN". Rozpoznajemy go, bo w adresie pocztowym miasto
# stoi PO nim ("70-653 Stettin") — to jedyny sygnał odróżniający adres od
# formatu "Miasto, Kraj", w którym miasto jest pierwsze.
_POSTAL_PREFIX = re.compile(r"^(\d{2}-\d{3})\s+(?=\S)")
# Segment będący samym kodem pocztowym (dowolnego kraju) nie jest miastem.
_POSTAL_ONLY = re.compile(r"^\d[\d\s-]*$")

# Segmenty odrzucane jako kraj/region. Nie jest to kompletna lista krajów
# świata i nie musi być — chodzi o te, które realnie występują w ogłoszeniach
# firm z naszego rejestru i w boardach, z których braliśmy fixture'y.
_NOT_A_CITY = {
    "poland", "polska", "pl",
    "germany", "deutschland", "de",
    "uk", "united kingdom", "great britain", "england", "scotland", "wales",
    "usa", "us", "united states", "united states of america",
    "ireland", "portugal", "spain", "france", "italy", "netherlands",
    "belgium", "austria", "switzerland", "sweden", "norway", "denmark",
    "finland", "estonia", "latvia", "lithuania", "czechia", "czech republic",
    "slovakia", "hungary", "romania", "bulgaria", "greece", "croatia",
    "slovenia", "serbia", "ukraine", "canada", "australia", "india",
    "brazil", "mexico", "japan", "singapore", "europe", "emea", "worldwide",
}

# Niemieckie egzonimy polskich miast. POTWIERDZONE realnymi danymi tylko dla
# "Stettin" (home.pl na Greenhousie). Reszta dopisana defensywnie — dopasowanie
# idzie po CAŁYM segmencie, nie po podciągu, więc fałszywe trafienie jest
# praktycznie niemożliwe (żadne inne miasto nie nazywa się "Danzig").
_CITY_EXONYMS = {
    "stettin": "Szczecin",  # POTWIERDZONE: boards-api.greenhouse.io/v1/boards/homepl/jobs
    "warschau": "Warszawa",
    "krakau": "Kraków",
    "danzig": "Gdańsk",
    "breslau": "Wrocław",
    "posen": "Poznań",
}

REMOTE_MARKERS = ("remote", "zdalnie", "zdalna", "anywhere")


def is_remote(location_name: str | None) -> bool:
    """Czy string lokalizacji oznacza pracę zdalną.

    Używane tam, gdzie ATS nie ma osobnego pola boolowskiego (Greenhouse).
    Bez tego oferta z `location.name == "Remote"` dostawałaby `remote=False`
    i `city="Remote"`, więc `matcher._location_ok` nie wszedłby w gałąź
    `include_remote`, tylko szukał miasta z profilu w słowie "remote" — i
    odrzuciłby każdą ofertę zdalną.
    """
    if not location_name:
        return False
    text = location_name.casefold()
    return any(marker in text for marker in REMOTE_MARKERS)


def extract_city(location_name: str | None) -> str | None:
    """Wyciąga nazwę miasta ze stringa lokalizacji ATS-u. Patrz reguła w
    docstringu modułu."""
    if not location_name:
        return None

    segments = []
    for raw in location_name.split(","):
        segment = raw.strip()
        if not segment:
            continue
        if segment.casefold() in _NOT_A_CITY:
            continue
        if _POSTAL_ONLY.match(segment):
            continue
        segments.append(segment)

    if not segments:
        return None

    # Segment z kodem pocztowym to adres — miasto stoi zaraz za kodem.
    for segment in segments:
        match = _POSTAL_PREFIX.match(segment)
        if match:
            return _normalize(segment[match.end():].strip())

    # Bez kodu pocztowego zakładamy "Miasto, <cokolwiek>" — miasto jest
    # pierwsze. Segmenty krajów już odpadły wyżej, więc "Portugal, Lisbon"
    # też trafia tutaj poprawnie jako "Lisbon".
    return _normalize(segments[0])


def _normalize(city: str) -> str | None:
    city = city.strip()
    if not city:
        return None
    return _CITY_EXONYMS.get(city.casefold(), city)
