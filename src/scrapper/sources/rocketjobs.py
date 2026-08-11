"""RocketJobs.pl — siostrzany portal justjoin.it, oferty SPOZA IT.

Powód istnienia tego źródła: JustJoinIT i NoFluffJobs to portale wyłącznie IT.
Oferty inżynieryjno-budowlane (Tekla Structures, projektanci konstrukcji) na
nich nie występują — sprawdzone na żywo: 0 trafień na "tekla" w 4000 ofert
JustJoinIT i 6000 ofert NoFluffJobs. RocketJobs.pl prowadzi ten sam operator,
ale zbiera oferty spoza IT (PKP, Medicover, produkcja, budownictwo) — i tam
oferta z Teklą jest.

API jest IDENTYCZNE co do struktury: `data[]` + `meta.next.cursor`, te same
nazwy pól (`guid`, `slug`, `city`, `workplaceType`, `publishedAt`,
`employmentTypes`, `requiredSkills`), ta sama paginacja przez `from` i ten sam
limit okna wyników. Dlatego cała logika jest dziedziczona, a nie kopiowana —
kopia dublowałaby też wszystkie pułapki, które kosztowały nas osobne rundy
poprawek przy JustJoinIT.

Zweryfikowano 2026-08-07: `GET https://rocketjobs.pl/api/candidate-api/offers`
→ HTTP 200. Filtr `city=szczecin` → 441 ofert. Adres oferty
`https://rocketjobs.pl/oferta-pracy/<slug>` → HTTP 200, a slug zmyślony → 404
(czyli to prawdziwy URL kanoniczny, nie strona, która zawsze zwraca 200).
"""

from scrapper.models import RawJob
from scrapper.sources.justjoinit import JustJoinIt, parse

API_URL = "https://rocketjobs.pl/api/candidate-api/offers"
OFFER_URL = "https://rocketjobs.pl/oferta-pracy/{slug}"


def parse_rocketjobs(payload: dict | list) -> list[RawJob]:
    """Parser rodziny justjoin.it z podmienionym źródłem i adresem oferty."""
    return parse(payload, source="rocketjobs", offer_url=OFFER_URL)


class RocketJobs(JustJoinIt):
    name = "rocketjobs"
    api_url = API_URL
    offer_url = OFFER_URL
