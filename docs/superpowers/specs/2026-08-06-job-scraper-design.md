# Agregator ofert pracy z powiadomieniami mailowymi — design

Data: 2026-08-06

## Problem

Szukanie ofert pracy wymaga codziennego obchodzenia kilku portali. Oferty
publikowane bezpośrednio na stronach firm nie pojawiają się na portalach wcale
albo z opóźnieniem. Chcemy jeden strumień: nowa pasująca oferta trafia na maila
w ciągu godziny od publikacji, niezależnie od tego, gdzie się pojawiła.

## Zakres

W zakresie tego speca (etapy 1–3):

- Pobieranie ofert z JustJoinIT i NoFluffJobs.
- Pobieranie ofert ze stron firm przez parsery systemów ATS, na podstawie
  kurowanej listy firm.
- Filtrowanie wg konfigurowalnych profili szukania.
- Deduplikacja ofert występujących w wielu źródłach.
- Powiadomienie e-mail (SMTP) wyłącznie o ofertach nowych.
- Uruchamianie co godzinę przez GitHub Actions.

Poza zakresem (przyszły rozwój, patrz sekcja na końcu): Pracuj.pl, LinkedIn,
interfejs webowy, aplikacja mobilna, śledzenie statusu aplikacji.

## Decyzje i ich uzasadnienie

| Decyzja | Uzasadnienie |
| --- | --- |
| GitHub Actions zamiast VPS | Zero kosztów i zero administracji. Kosztem jest ryzyko blokad IP na części portali. |
| Stan w `data/jobs.jsonl`, nie SQLite | Actions nie zachowuje dysku między runami, więc stan wraca do repo. JSONL jest append-only: commit dodaje kilka linii zamiast przepisywać plik binarny. |
| E-mail przez SMTP | Wybór użytkownika. Zbiorczy mail sprawdza się jako lista do przejrzenia. |
| Kurowana lista firm zamiast crawlera z LLM | Większość firm używa gotowych ATS-ów, więc jeden parser obsługuje dziesiątki firm deterministycznie, bez kosztów tokenów i fałszywych trafień. |
| Playwright tylko jako ostateczność | Na Actions jest wolny i łatwo wykrywalny. Źródła z publicznym JSON-em pokrywają MVP. |

## Architektura

Jeden przebieg (`run.py`), wywoływany przez cron:

```
config.yaml (profile szukania)
        |
        v
  [ Sources ]  -- każde źródło zwraca List[RawJob]
   |- JustJoinIT     (publiczne API JSON)
   |- NoFluffJobs    (publiczne API JSON)
   \- Companies      (ATS: Recruitee / Traffit / Lever / Greenhouse / Workable)
        |
        v
  [ Normalizer ]  -> Job(id, title, company, city, url, salary, remote, posted_at, source)
        |
        v
  [ Matcher ]     -> filtr wg profilu (keywords, miasto, seniority, exclude)
        |
        v
  [ Deduper ]     -> klucz = slug(company)+slug(title)+city
        |
        v
  [ Store ]       -> data/jobs.jsonl (append-only), zna wszystko już widziane
        |
        v  (tylko nowe)
  [ Notifier ]    -> HTML mail przez SMTP
        |
        v
  git commit data/jobs.jsonl
```

Każde źródło implementuje jeden protokół `fetch(profile) -> List[RawJob]` i łapie
własne wyjątki. Awaria jednego źródła nie zatrzymuje pozostałych.

Deduplikacja następuje **przed** powiadomieniem, żeby ta sama oferta z trzech
źródeł dała jeden wpis w mailu. Przy konflikcie wygrywa źródło o wyższym
priorytecie (strona firmy > portal); pozostałe URL-e trafiają do tego samego
wpisu jako dodatkowe linki.

Stan zapisujemy **dopiero po udanej wysyłce maila**. Dzięki temu awaria SMTP
oznacza ponowne zgłoszenie tych ofert w kolejnym runie, a nie ich trwałe
przegapienie.

## Stack

Python 3.12, `httpx`, `selectolax`, `pydantic`, `jinja2`, `pytest`.

## Struktura projektu

```
work-scrapper/
├─ config.yaml              # profile szukania
├─ companies.yaml           # kurowana lista firm + ich ATS
├─ src/scrapper/
│  ├─ models.py             # Job, RawJob, Profile (pydantic)
│  ├─ config.py             # wczytanie + walidacja YAML-i
│  ├─ sources/
│  │   ├─ base.py           # protokół Source
│  │   ├─ justjoinit.py
│  │   ├─ nofluffjobs.py
│  │   └─ ats/
│  │       ├─ recruitee.py
│  │       ├─ traffit.py
│  │       ├─ lever.py
│  │       ├─ greenhouse.py
│  │       └─ workable.py
│  ├─ matcher.py
│  ├─ deduper.py
│  ├─ store.py
│  ├─ notifier.py
│  └─ run.py
├─ templates/email.html.j2
├─ data/jobs.jsonl
├─ tests/
└─ .github/workflows/scrape.yml
```

## Konfiguracja

`config.yaml` — kryteria szukania, edytowane na co dzień:

```yaml
smtp:
  host: smtp.gmail.com
  port: 587
  user: ${SMTP_USER}        # z GitHub Secrets
  password: ${SMTP_PASSWORD}
  to: olosolo16@gmail.com

profiles:
  - name: frontend-szczecin
    keywords: [frontend, react, javascript, typescript, next.js]
    exclude: [senior, lead, staff, architect]
    locations: [szczecin]
    include_remote: true
    max_age_days: 14
```

Obsługa wielu profili jest w kodzie od początku — to jedna pętla po liście, a nie
osobna funkcjonalność. Zmiana obszaru szukania to edycja YAML-a, nie kodu.

`companies.yaml` — kurowana lista firm:

```yaml
- name: BLStream
  ats: recruitee
  slug: blstream
- name: Tieto Szczecin
  ats: traffit
  slug: tietoevry
- name: SoftwareMill
  ats: custom
  url: https://softwaremill.com/join-us/
  parser: skip
```

Wpis z `ats: custom` i `parser: skip` jest logowany jako pominięty i nie
przerywa runu. Wypełnienie tej listy firmami IT ze Szczecina jest zadaniem
researchowym w etapie 3; start z kilkunastu firm, dokładanie kolejnych to jedna
linijka YAML-a.

## Obsługa błędów

| Sytuacja | Reakcja |
| --- | --- |
| Źródło rzuca wyjątkiem lub timeout | Log ostrzeżenia, źródło pominięte, run trwa dalej |
| Źródło zwraca 0 ofert | Ostrzeżenie w stopce maila (sygnał, że parser przestał działać) |
| Wszystkie źródła padły | Run kończy się błędem; GitHub wysyła powiadomienie o failed run |
| Błąd SMTP | Run kończy się błędem bez commitowania stanu; oferty zostaną zgłoszone ponownie |
| Zero nowych ofert | Mail nie jest wysyłany |

## Testy

Wszystkie testy działają bez sieci i są deterministyczne.

- **Parsery źródeł** — realne odpowiedzi API/HTML zapisane w `tests/fixtures/`,
  weryfikacja poprawnej normalizacji do modelu `Job`.
- **Matcher** — profil × zestaw ofert daje oczekiwane trafienia, w tym
  odrzucenie „Senior React Developer" przez listę `exclude`.
- **Deduper** — ta sama oferta z trzech źródeł daje jeden wpis, wygrywa strona
  firmy.
- **Store** — dwa przebiegi pod rząd; drugi nie zgłasza niczego jako nowe.
- **End-to-end** — pełny przebieg na fake'owych źródłach i fake'owym SMTP.

## Etapy realizacji

1. **Szkielet + JustJoinIT + mail + Actions.** Po tym etapie przychodzą pierwsze
   maile. Jedno źródło, ale cała pętla działa end-to-end.
2. **NoFluffJobs.** Drugie źródło i realny test deduplikacji między portalami.
3. **ATS-y + `companies.yaml`.** Recruitee, Traffit, Lever, Greenhouse, Workable
   oraz research firm ze Szczecina. Dowozi oferty ze stron firm.

## Znane ryzyka

**Blokady IP.** Pracuj.pl i LinkedIn blokują ruch z zakresów adresowych GitHuba i
wymagają realnej przeglądarki. Dlatego nie ma ich w MVP. Jeśli okażą się
potrzebne, będzie to argument za przeniesieniem na VPS.

**Zgnicie parserów.** Portale zmieniają formaty odpowiedzi. Mechanizmem
wykrywania jest ostrzeżenie o zerowej liczbie ofert w stopce maila oraz testy na
fixture'ach.

## Przyszły rozwój (poza tym specem)

Pracuj.pl i LinkedIn na VPS, interfejs webowy z historią i filtrami, oznaczanie
ofert jako „aplikowałem", powiadomienia push na telefon, dodatkowe miasta i
profile.
