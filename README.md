# work-scrapper

## Aktualne zrodla bezposrednie (2026-09-04)

Scraper nie ogranicza sie do portali. Rejestr ma 26 firm, z czego 24 sa
aktywnie odpytywanych bezposrednio. Obejmuje TietoEVRY, home.pl, Sii Polska,
Spyrosoft, Demant, BTC, Raynet, GryfTec, Global Wind Service, Code & Pepper,
MasterBorn, Espeo, Shoper, Red Sky, Strix, Asseco Data Systems, GlobalLogic,
3Shape, GammaSoft, HEUTHES, Appidea, Macrobond, Coloplast i Icotera. Dwa
pozostale wpisy sa zachowane jako
rozpoznane strony bez stabilnego publicznego interfejsu i nie sa liczone jako
dzialajace zrodla.

W tescie na zywo 2026-09-04 strony firm zwrocily 898 aktywnych ogloszen. Profil
IT wybral z nich 73 pasujace oferty: 30 lokalnych oraz 43 zdalne. Liczby beda
sie naturalnie zmieniac wraz z publikowaniem i zamykaniem rekrutacji.

Profile w `config.yaml` obejmuja frontend, szersze role IT ze
Szczecina/Mierzyna i zdalne z Polski oraz BIM/Revit/Tekla. Dla ostatniego
profilu przeszukiwany jest rowniez opis oferty, poniewaz nazwa narzedzia czesto
nie wystepuje w tytule.

Agreguje oferty pracy z portali i stron firm, wysyła mailem tylko nowe.

## Jak działa

Co godzinę GitHub Actions uruchamia `python -m scrapper.run`. Skrypt pobiera
oferty ze skonfigurowanych źródeł, filtruje wg profili z `config.yaml`,
deduplikuje, porównuje z `data/jobs.jsonl` i wysyła maila wyłącznie o nowych
znaleziskach. Stan zapisuje dopiero po udanej wysyłce, więc awaria poczty nie
powoduje przegapienia ofert.

## Konfiguracja

1. Ustaw sekrety w repo: **Settings → Secrets and variables → Actions**
   - `SMTP_USER` — Twój adres Gmail
   - `SMTP_PASSWORD` — hasło aplikacji (nie hasło do konta!), wygenerowane na
     https://myaccount.google.com/apppasswords przy włączonym 2FA
2. Dostosuj `config.yaml` — słowa kluczowe, miasta, wykluczenia.
3. Dostosuj `companies.yaml` — lista firm do sprawdzania stron karier.

### Co dokładnie znaczy `include_remote: true`

**Oferty zdalne z całej Polski** plus wszystkie oferty (zdalne i stacjonarne)
z miast wymienionych w `locations`.

Działa to tak, bo portale tagują ofertę zdalną miastem siedziby firmy — np.
zdalne oferty Shopera mogą mieć `city: Kraków`. Zapytanie wyłącznie o Szczecin
by ich nie zwróciło, mimo że można na nie pracować ze Szczecina.
Dlatego przy `include_remote: true` źródła dociągają dodatkowo pulę
ogólnopolską, a matcher przepuszcza z niej tylko oferty zdalne (stacjonarne
spoza `locations` odpada).

Koszt: przebieg pobiera ~4100 ofert zamiast ~360 i trwa ok. 13 s zamiast 3 s.

### `nofluffjobs_categories` — bez tego NoFluffJobs prawie nic nie dowozi

NoFluffJobs ma ~21 600 ofert ogólnopolsko, **nie sortuje po dacie** i ignoruje
parametry sortowania (sprawdzone: `sort`, `rawSearch`). Pobranie budżetowego
wycinka daje więc losowy przekrój, w którym świeże oferty bywają nieobecne — w
pomiarze przed poprawką NFJ dawał **0 dopasowań**, bo wszystkie cztery znalezione
oferty frontendowe miały 18–24 dni przy `max_age_days: 14`.

Filtr kategorii zawęża pulę po stronie serwera do rozmiaru, który da się pobrać
**w całości** — a wtedy kolejność przestaje mieć znaczenie. Rozmiary kategorii
(2026-08-07): `frontend` 508, `mobile` 419, `fullstack` 1274, `testing` 1273,
`devops` 1474, `data` 2832, `backend` 3461, `embedded` 199.

**Literówka w nazwie kategorii nie daje błędu** — API zwraca HTTP 200 i zero
ofert. Objawi się ostrzeżeniem „nofluffjobs zwróciło 0 ofert" w stopce maila
i jako `::warning::` w logu Actions.

### Oferty spoza IT (Tekla Structures) — RocketJobs.pl

JustJoinIT i NoFluffJobs to portale **wyłącznie IT** i nie mają ofert
inżynieryjno-budowlanych: 0 trafień na „tekla" w 4000 ofert JustJoinIT i w
6000 ofert NoFluffJobs. Dlatego doszło czwarte źródło — **RocketJobs.pl**,
prowadzone przez tego samego operatora co justjoin.it, ale zbierające oferty
spoza IT.

Ważny szczegół: słowo „tekla" praktycznie nigdy nie jest w **tytule** oferty —
siedzi w wymaganych umiejętnościach. Przykład z realnych danych:

```
title:  "Asystent/ka Projektanta Konstrukcji (konstrukcje żelbetowe i stalowe)"
skills: ["Allplan", "język angielski", "tekla"]
```

Dlatego matcher przeszukuje **tytuł + umiejętności**. Wykluczenia (`exclude`)
celowo patrzą tylko na tytuł, żeby `exclude: [senior]` nie odrzucało oferty
juniorskiej wymagającej współpracy z seniorem.

## Oferty ze stron firm (`companies.yaml`)

Obsługiwane systemy ATS: **Recruitee, Greenhouse, Lever, Workable,
SmartRecruiters i SAP SuccessFactors**. Są też bezpośrednie integracje z API
Sii i Spyrosoft oraz parser prostych firmowych stron HTML.

Stan na 2026-09-04: **898 ofert z 24 aktywnie parsowanych firm**. Rejestr
obejmuje duże centra technologiczne, lokalne software house'y oraz firmy
e-commerce. Liczby są zmienne i służą jako punkt kontrolny przy diagnozowaniu
parserów.

Z `parser: skip` pozostają tylko Arvato Systems i SoftwareMill. Ich własne
systemy nadal nie mają w projekcie stabilnej integracji; oferty mogą jednak
wpadać przez portale.

### Jak znaleźć slug nowej firmy

1. Otwórz stronę kariery firmy i poszukaj w HTML nazwy któregoś ATS-a.
2. Slug bywa **nieoczywisty**: Code & Pepper to `codepepper` (nie
   `codeandpepper` — 404), MasterBorn to `masterborn-2`, TietoEVRY to `Tieto2`.
3. **Zawsze sprawdź, ile ofert wróciło.** Greenhouse i Recruitee dają 404 na zły
   slug, ale SmartRecruiters zwraca HTTP 200 z zerem — literówka wygląda wtedy
   jak firma bez ofert.
4. Sprawdź też, czy trafienie to na pewno ta firma. `accenture.recruitee.com`
   zwraca HTTP 200 z dwiema ofertami, ale to konto demonstracyjne („Senior
   Marketer (Sample)", Amsterdam), nie Accenture.

## Czego ten agregator nadal nie znajdzie

**Pracuj.pl i OLX** są poza zakresem: blokują ruch z zakresów adresowych
GitHuba i wymagają realnej przeglądarki (patrz „Znane ryzyka" w specyfikacji).
Dołożenie ich wymagałoby przeniesienia całości na VPS.

Uwaga: **pusta lista `locations` w jednym profilu nie zdejmuje filtra miast**
dla pozostałych — źródła dostaną unię lokalizacji ze wszystkich profili.
Przebieg loguje wtedy ostrzeżenie.

## Uruchomienie lokalne

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest
SMTP_USER=... SMTP_PASSWORD=... .venv/Scripts/python -m scrapper.run
```

### Weryfikacja certyfikatów TLS (`truststore`)

Projekt używa pakietu [`truststore`](https://pypi.org/project/truststore/) do
weryfikacji TLS przez systemowy magazyn certyfikatów, zamiast wbudowanej listy
`certifi`. Na Windowsie z aktywnym antywirusem lub firmowym proxy, które
przechwytuje ruch TLS (podmienia certyfikat serwera na własny), domyślna
weryfikacja `httpx`/`certifi` kończy się błędem `SSLCertVerificationError`,
bo `certifi` nie zna certyfika antywirusa. Systemowy magazyn (Windows
Certificate Store) już go zna — korzysta z niego przeglądarka i `curl`.
`truststore` każe Pythonowi weryfikować połączenia przez ten sam magazyn.
Weryfikacja certyfikatów nigdy nie jest wyłączana — jeśli `truststore` jest
niedostępny lub jego inicjalizacja się nie powiedzie, kod wraca do domyślnej
weryfikacji `httpx` (czyli `certifi`), nie do braku weryfikacji.

## Pierwszy przebieg

Pierwszy przebieg zgłosi wszystkie pasujące oferty z ostatnich `max_age_days`
dni naraz — to normalne. Kolejne będą już tylko przyrostowe.

## Gdy przestaną przychodzić oferty

Sprawdź stopkę ostatniego maila — ostrzeżenie „zwróciło 0 ofert" oznacza, że
portal zmienił format odpowiedzi. Odśwież fixture wg `docs/sources.md` i popraw
parser.

Źródło JustJoinIT odpytuje realny endpoint
`https://justjoin.it/api/candidate-api/offers`. Jeśli ten adres albo kształt
odpowiedzi się zmieni, odśwież fixture testowy oraz opis w `docs/sources.md`
przed poprawą parsera w `src/scrapper/sources/justjoinit.py`.
