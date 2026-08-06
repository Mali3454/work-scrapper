# Źródła — endpointy i kształt odpowiedzi

## JustJoinIT

### Endpoint

```
GET https://justjoin.it/api/candidate-api/offers
```

Opcjonalne parametry zapytania stosowane podczas researchu (nieudokumentowane
publicznie, ustalone eksperymentalnie):

- `city=<nazwa miasta>` — wpływa na kolejność/dobór wyników (nie jest to ścisły
  filtr — miasta inne niż podane też się pojawiają), np. `city=szczecin`.
- `itemsCount=<liczba>` — rozmiar strony (domyślnie 10, przetestowano do 100).

**Paginacja — zweryfikowana empirycznie w Task 9 (poprawka względem
wcześniejszego założenia w tym dokumencie):** parametr `cursor=<wartość>`
NIE działa — przekazanie go w query string jest po cichu ignorowane, serwer
zwraca dokładnie tę samą pierwszą stronę. Prawdziwy parametr paginacji to
**`from=<liczba>`** (offset, nie token nieprzezroczysty). Wartość
`meta.next.cursor` z odpowiedzi to liczba, którą trzeba podstawić jako
`from` w kolejnym zapytaniu — nazwa `cursor` w kluczu odpowiedzi jest myląca
(sugeruje kursor kryty, a to zwykły offset), ale mechanizm nawigacji nią jest
poprawny.

Zweryfikowano sekwencję `from=None → 0, 5, 10, 15 …` — kolejne strony
zwracają rozłączne zestawy `guid`, więc offset faktycznie przesuwa okno.

**Twardy limit okna wyników — pułapka przy dużym `max_offers`:** API zwraca
`meta.totalItems: 10000` niezależnie od faktycznej liczby ofert (wygląda na
domyślny limit okna wyszukiwarki pełnotekstowej, np. Elasticsearch
`max_result_window`). Żądania, w których `from + itemsCount > 10000`, kończą
się **HTTP 500** (`Internal Server Error`), a NIE pustą listą i NIE
`cursor: null` — `meta.next.cursor` rośnie bez końca aż do tej granicy, nigdy
nie sygnalizując końca danych samodzielnie. Task 9 obsługuje to tak: błąd HTTP
na drugiej i kolejnych stronach jest traktowany jako koniec dostępnych danych
(pobieranie kończy się z tym, co już zebrano), a nie jako awaria całego
źródła — błąd na pierwszej stronie nadal propaguje się jako prawdziwa awaria.

**Uwaga — jak do tego doszedłem:** próby oczywistych kandydatów
(`api.justjoin.it/v2/user-panel/offers`, `api.justjoin.it/v2/offers`,
`api.justjoin.it/offers`, samo `api.justjoin.it/`) kończyły się kodem 404 lub
odpowiedzią `Invalid endpoint` z prawdziwego API (nie Cloudflare challenge —
serwer żyje, ścieżka jest zła). Strona `justjoin.it` jest dziś aplikacją
Next.js (App Router, RSC), a w treści strony `/job-offers/szczecin/frontend`
(sama zresztą zwracała 404 — stary routing kategorii już nie działa) znaleziono
w zaszytej konfiguracji klucz `cpApiUrl: "/api/candidate-api"` (candidate panel
API), względny wobec `https://justjoin.it`. Podpięcie `/offers` do tej bazy
(`https://justjoin.it/api/candidate-api/offers`) zwróciło HTTP 200 z realnym
JSON-em ofert.

### Wymagane nagłówki

- `User-Agent: <dowolny nagłówek przeglądarki>` — bez tego serwer (Cloudflare
  przed API) może zablokować request. Użyto:
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`
- `Accept: application/json` — nie jest ściśle wymagany (endpoint i tak zwraca
  JSON), ale bezpiecznie go wysyłać.
- Brak wymaganego klucza API / tokena / ciasteczka — zapytanie anonimowe
  działa. Serwer ustawia własne `set-cookie: session-id=...` i
  `set-cookie: ghost-id=...`, ale nie są one wymagane do odczytu ofert (nie
  wysyłano ich w kolejnych requestach, a mimo to endpoint nadal zwracał dane).
- Nagłówek odpowiedzi `api-supported-versions: 1.0` sugeruje, że API jest
  wersjonowane, ale nie znaleziono nagłówka żądania (`version` czy podobny),
  który by to wymuszał.

### Data weryfikacji

2026-08-06

### Kształt odpowiedzi (korzeń)

```json
{
  "data": [ /* lista obiektów oferty, patrz niżej */ ],
  "meta": {
    "from": 0,
    "totalItems": 10000,
    "prev": { "cursor": null, "itemsCount": 10 },
    "next": { "cursor": 10, "itemsCount": 10 }
  }
}
```

Fixture (`tests/fixtures/justjoinit.json`) zachowuje tę samą strukturę
korzenia (`data` + `meta`), tylko z listą przyciętą do 3 ofert. Wartości w
`meta` przeliczone tak, by odpowiadały przyciętej liczbie elementów
(`totalItems: 3`) — oryginalne wartości `meta` z pełnej odpowiedzi (np.
`totalItems: 10000`) nie miałyby sensu przy 3-elementowej liście i wprowadzałyby
w błąd.

### Struktura pojedynczej oferty (pola istotne + pełen kontekst)

Każdy element `data[]` to obiekt z (m.in.) polami:

```
guid                — UUID oferty, unikalny identyfikator
slug                — unikalny slug używany w URL-u oferty
title               — tytuł stanowiska
workplaceType       — "office" | "hybrid" | "remote"
companyName         — nazwa firmy
city                — miasto głównej lokalizacji (string, może zawierać polskie znaki)
street              — ulica (nie używane w mapowaniu)
locations[]         — lista lokalizacji (dla ofert wielolokalizacyjnych), każda ma city/street/slug
publishedAt         — ISO 8601 timestamp (UTC, z ułamkami sekund), data publikacji
lastPublishedAt      — ISO 8601 timestamp ostatniej "odnowy" oferty
expiredAt           — ISO 8601 timestamp wygaśnięcia
employmentTypes[]   — lista wariantów wynagrodzenia (różne waluty/typy umowy),
                       każdy z polami from/to/fromPerUnit/toPerUnit/currency/
                       currencySource/type/unit/gross; from/to bywają null,
                       gdy firma nie podała widełek
applyUrl            — bezpośredni link do aplikowania (zewnętrzny, poza justjoin.it)
requiredSkills[]    — lista wymaganych umiejętności
category            — { key, parentKey } — kategoria oferty (np. "net", "testing")
```

**Ważne:** obiekt oferty NIE zawiera gotowego, pełnego URL-u do strony oferty
na justjoin.it — trzeba go zbudować samodzielnie ze `slug`:

```
https://justjoin.it/job-offer/{slug}
```

Zweryfikowano bezpośrednio: `GET https://justjoin.it/job-offer/<slug>` → HTTP
200 (stara ścieżka `https://justjoin.it/offers/<slug>` zwraca 301 redirect do
tej nowej formy).

### Mapowanie pól → `RawJob`

| Pole w API | Pole w RawJob | Uwagi |
| --- | --- | --- |
| `guid` | `external_id` | UUID, stabilny unikalny identyfikator oferty |
| `title` | `title` | bez zmian |
| `companyName` | `company` | bez zmian |
| `city` | `city` | string z polskimi znakami (UTF-8, poprawnie zdekodowany w JSON); `None`/brak nie zaobserwowano w próbce, ale traktować jako opcjonalne |
| `workplaceType == "remote"` | `remote` | `remote` → `True`; `office` i `hybrid` → `False`. Brak osobnej flagi bool w API — trzeba wyprowadzić z tego pola tekstowego. **Uwaga:** wariant `"hybrid"` NIE występuje w żadnej z 3 ofert fixture'a — gałąź `hybrid → False` jest w regule udokumentowana, ale nie pokryta przykładem w fixture. Task 9 powinien dodać osobny test jednostkowy na tę wartość zamiast polegać na fixture. |
| `slug` (zbudowany URL) | `url` | **W API NIE MA gotowego URL-a do oferty.** Trzeba zbudować: `f"https://justjoin.it/job-offer/{slug}"`. `applyUrl` to inny link (zewnętrzny formularz aplikacyjny danej firmy) — NIE używać go jako `url` |
| `employmentTypes[]` (wybrany wg reguły niżej) | `salary` | API nie zwraca jednego gotowego stringa z widełkami — trzeba go zbudować z `from`/`to`/`currency`/`unit`/`type` wybranego wpisu. Patrz **"Reguła wyboru wpisu wynagrodzenia"** poniżej — jest wiążąca dla Task 9, nie tylko rekomendacją. |
| `publishedAt` | `posted_at` | ISO 8601 z Z (UTC), parsowalne wprost przez `datetime.fromisoformat` (Python 3.11+) po zamianie `Z` na `+00:00`, lub przez `dateutil`. Pole ISTNIEJE i jest zawsze wypełnione w próbce — brak `None` nie zaobserwowano |
| — (stała) | `source` | brak odpowiednika w API — Task 9 ustawia na stałą wartość identyfikującą źródło, np. `"justjoinit"` |

### Reguła wyboru wpisu wynagrodzenia (wiążąca dla Task 9)

Oferta „Starszy Tester/Starsza Testerka…" w fixture ma DWA wpisy
`employmentTypes[]` z `currencySource == "original"` jednocześnie: jeden
`type: "permanent"`, drugi `type: "b2b"`. W tym konkretnym przypadku oba mają
`from`/`to` równe `null`, więc wynik wychodzi ten sam niezależnie od wyboru —
ale to nie jest ogólna gwarancja. Przy ofercie z dwoma różnymi, faktycznie
wypełnionymi widełkami (np. inne dla B2B i inne dla umowy o pracę), naiwny
wybór „pierwszego pasującego" zależałby od kolejności elementów w tablicy
zwróconej przez API — a ta kolejność nie jest nigdzie udokumentowana ani
gwarantowana jako stabilna.

Wiążąca reguła dla Task 9:

> Spośród wpisów `employmentTypes[]` bierz pod uwagę wyłącznie te z
> `currencySource == "original"` (kwoty podane przez firmę, nie przeliczenia
> kursowe) i z niepustymi `from` oraz `to`. Jeśli pasuje więcej niż jeden,
> wybierz według priorytetu typu umowy: `b2b`, potem `permanent`, potem
> pozostałe. Jeśli w ramach tego samego typu jest kilka wpisów, weź pierwszy.
> Jeśli żaden wpis nie ma wypełnionych `from` i `to`, `salary` wynosi `None`.

Uzasadnienie priorytetu B2B: to dominująca forma zatrudnienia w polskich
ofertach IT, i to te widełki są zwykle porównywalne między różnymi ofertami.

Przykład formatu wynikowego stringa (nieregulowany ściśle, do ustalenia w
Task 9): `"26000–31000 PLN/miesiąc (B2B)"`. Gdy wszystkie wpisy mają `from` i
`to` równe `null` (brak widełek) — `salary` powinno być `None` (patrz fixture:
oferty „Grid Converter Control Engineer" i „Starszy Tester…" nie mają
podanych widełek w żadnej walucie/typie umowy).

**Ostrzeżenie o wielkości liter:** wartości tekstowe pól `unit` i `type` NIE
są konsekwentne w API. W samym fixture występuje zarówno `"unit": "Month"`
(oferta „Senior .Net Developer") jak i `"unit": "month"` (pozostałe dwie
oferty). Proste porównanie `unit == "month"` przepuści wariant z wielką
literą niezauważenie. Task 9 musi porównywać wartości `unit` i `type`
bez uwzględniania wielkości liter, np. `value.casefold() == "month"` /
`value.casefold() == "b2b"`, a nie surowym `==`.

### Pola, których NIE MA w odpowiedzi (żeby Task 9 nie szukał ich po omacku)

- Brak gotowego pełnego URL-a oferty (`url`) — trzeba budować ze `slug`.
- Brak jednego gotowego stringa wynagrodzenia — trzeba budować z tablicy
  `employmentTypes[]`.
- Brak osobnego pola boolowskiego "remote" — trzeba wyprowadzić z
  `workplaceType`.
- Brak `description`/pełnego opisu stanowiska w tej liście (endpoint listy
  ofert zwraca tylko skrócone dane; pełny opis wymagałby osobnego zapytania
  o szczegóły oferty — nie badano, poza zakresem Task 8).

Fixture: `tests/fixtures/justjoinit.json` (przycięty do 3 ofert: jedna
stacjonarna w Szczecinie bez podanych widełek, jedna zdalna z podanymi
widełkami PLN, jedna stacjonarna bez podanych widełek).

## NoFluffJobs

### Endpoint

```
POST https://nofluffjobs.com/api/search/posting?salaryCurrency=PLN&salaryPeriod=month
```

**Uwaga — endpoint z briefu (`https://nofluffjobs.com/api/search/posting`)
okazał się poprawny co do ścieżki**, ale wymaga metody POST (GET zwraca
HTTP 405) oraz dwóch **wymaganych parametrów query string**, o których brief
nie wspominał:

- `salaryCurrency=PLN` — bez niego serwer zwraca HTTP 400
  (`Required parameter 'salaryCurrency' is not present.`).
- `salaryPeriod=month` — analogicznie, HTTP 400 dopóki brak.

Te dwa parametry **ujednolicają walutę i okres wynagrodzenia we wszystkich
zwróconych ofertach** — API samo przelicza widełki firmy (np. podane w EUR,
rocznie) na PLN/miesiąc. To wygodne (nie trzeba przeliczać walut ręcznie w
parserze), ale oznacza, że pole `salary` w odpowiedzi NIE jest surową kwotą
podaną przez firmę.

Ustalono to eksperymentalnie metodą kolejnych żądań: `GET` → 405 → `POST` z
pustym body → 400 (brak `salaryCurrency`) → dodanie `salaryCurrency=PLN` w
**body** (nie zadziałało, error się powtórzył) → dodanie `salaryCurrency=PLN`
jako **parametr query string** → zaakceptowane → kolejny błąd 400 (brak
`salaryPeriod`) → dodanie `salaryPeriod=month` jako query string → HTTP 200 z
realnym JSON-em ofert.

### Ciało zapytania (POST body)

Bez filtra miasta (wszystkie oferty):

```json
{"criteriaSearch": {}}
```

Z filtrem miasta (Szczecin):

```json
{"criteriaSearch": {"city": ["szczecin"]}}
```

`city` przyjmuje listę (małe litery, bez polskich znaków wystarcza —
`"szczecin"` zwraca oferty z miastem `"Szczecin"`). Klucz `criteriaSearch`
jest wymagany — request z całkowicie pustym body (`{}`) też zwraca HTTP 200,
ale wtedy odpowiedź i tak zawiera puste `criteriaSearch` w echo — nie testowano
efektu ubocznego pustego body poza tym, że działa identycznie do
`{"criteriaSearch": {}}` w próbkach research.

### Paginacja — zweryfikowana empirycznie

Parametr query string **`page`** (1-indeksowany; brak parametru = strona 1).
API zwraca **stały rozmiar strony: 20 ofert**, ostatnia strona bywa krótsza.
Zweryfikowano na zapytaniu z filtrem `city=szczecin` (`totalCount: 42`):
`page` bez parametru → 20 ofert, `page=2` → kolejne 20 (zbiór `id` rozłączny
z pierwszą stroną), `page=3` → ostatnie 2 oferty.

**Pułapka — pole `totalPages` w odpowiedzi jest niewiarygodne, analogicznie
do pułapki z `cursor` przy JustJoinIT (Task 9):** przy zapytaniu bez filtra
miasta wielokrotne identyczne zapytania (`{"criteriaSearch": {}}`, różne
strony) zwracały **różną liczbę ofert na stronę** (od 62 do 195 w próbkach) i
niestabilne `totalCount`/`totalPages` między kolejnymi wywołaniami (dane są
najwyraźniej dynamiczne/nieindeksowane deterministycznie przy dużym zbiorze
bez filtra). Wniosek dla implementacji: **nie polegać na `totalPages` jako
warunku zatrzymania paginacji** — zamiast tego traktować stronę krótszą niż
rozmiar strony (20) lub pustą jako koniec wyników. Dla zapytań z konkretnym
filtrem miasta (typowy przypadek użycia tego źródła) zachowanie paginacji
było stabilne i przewidywalne w testach.

### Wymagane nagłówki

- `User-Agent: <dowolny nagłówek przeglądarki>` — jak przy JustJoinIT, użyto
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like
  Gecko) Chrome/120.0.0.0 Safari/537.36`. Bez tego nagłówka nie testowano
  osobno (dołączany od pierwszego udanego żądania), ale JustJoinIT pokazał, że
  jego brak bywa blokowany.
- `Accept: application/json` — używany, choć nie potwierdzono, czy ściśle
  wymagany.
- `Content-Type: application/json` — **wymagany**, bo wysyłamy ciało JSON w
  POST.
- Brak wymaganego klucza API / tokena / ciasteczka — zapytanie anonimowe
  działa, żaden Cloudflare challenge nie pojawił się w żadnej próbie.

### Data weryfikacji

2026-08-06

### Kształt odpowiedzi (korzeń)

```json
{
  "criteriaSearch": { "...": "echo wysłanych kryteriów + puste pola pozostałych filtrów" },
  "postings": [ /* lista obiektów oferty, patrz niżej */ ],
  "totalCount": 42,
  "totalPages": 20,
  "exactMatchesPages": 20,
  "rawSearch": "",
  "locationCriteria": false,
  "divs": 42,
  "additionalSearch": [],
  "salaryMatchBlock": { "offers": [], "totalCount": 0, "divs": 0 },
  "overridenSalaryFilter": {}
}
```

Fixture (`tests/fixtures/nofluffjobs.json`) zachowuje tę samą strukturę
korzenia, tylko z listą `postings` przyciętą do 3 ofert i `totalCount`/
`totalPages`/`divs` przeliczonymi na 3 (oryginalne wartości z pełnej
odpowiedzi nie miałyby sensu przy 3-elementowej liście).

### Struktura pojedynczej oferty (pola istotne + pełen kontekst)

Każdy element `postings[]` to obiekt z (m.in.) polami:

```
id                  — identyfikator oferty, string typu "<slug-z-nazwa-firmy>-<Miasto>"
                       (wielkość liter miasta jak w oryginale, np. "...-Szczecin");
                       unikalny w obrębie odpowiedzi, użyty jako external_id
url                 — slug używany w URL-u oferty (małe litery, myślniki),
                       osobny od `id` (różni się wielkością liter w nazwie miasta)
name                — nazwa firmy
title               — tytuł stanowiska
location.places[]   — lista lokalizacji; każda ma `city` (string) — lub
                       specjalną wartość `"Remote"` dla wpisu oznaczającego
                       opcję pracy zdalnej — plus opcjonalnie street/postalCode/
                       geoLocation/country; ostatnie wpisy bywają tylko
                       `province`+`provinceOnly: true` (dostępność w całym
                       województwie, bez konkretnego adresu)
location.fullyRemote — bool, prawdziwe źródło informacji o pracy zdalnej —
                       `true`, gdy oferta ma "Remote" wśród `places` (praca
                       zdalna dostępna jako opcja, niekoniecznie wyłączna)
fullyRemote (poziom korzenia oferty) — bool, **w całej zbadanej próbce
                       (>1400 ofert) zawsze `false`** — pole wygląda na
                       nieużywane/zdeprecjonowane; NIE używać go, użyć
                       `location.fullyRemote`
posted              — epoch millisecond timestamp (int), data publikacji
renewed             — epoch millisecond timestamp odnowienia (nie zawsze
                       obecne — brak w niektórych ofertach)
salary              — obiekt `{from, to, type, currency, disclosedAt,
                       flexibleUpperBound}` — patrz sekcja niżej; kwoty
                       przeliczone do PLN/miesiąc przez parametry query
                       string zapytania (nie surowa wartość podana przez
                       firmę)
category            — string kategorii (np. "backend", "erp", "finance")
seniority[]          — lista poziomów doświadczenia (np. ["Senior"])
reference            — identyfikator wewnętrzny oferty w systemie NoFluffJobs
tiles.values[]        — lista tagów (kategoria + wymagania) do wyświetlenia na
                       liście ofert
```

**Ważne:** obiekt oferty NIE zawiera gotowego, pełnego URL-u do strony oferty
na nofluffjobs.com — trzeba go zbudować samodzielnie z `url`:

```
https://nofluffjobs.com/pl/job/{url}
```

Zweryfikowano bezpośrednio: `GET https://nofluffjobs.com/pl/job/<url>` → HTTP
200 (routing jest niewrażliwy na wielkość liter miasta w slugu — testowano
zarówno wariant z małą, jak i wielką literą miasta na końcu, oba 200).

### Mapowanie pól → `RawJob`

| Pole w API | Pole w RawJob | Uwagi |
| --- | --- | --- |
| `id` | `external_id` | string, stabilny w obrębie odpowiedzi; różni się wielkością liter miasta od `url` |
| `title` | `title` | bez zmian |
| `name` | `company` | bez zmian |
| `location.places[]` (pierwszy wpis z `city` różnym od `"Remote"`) | `city` | trzeba pominąć wpisy `"Remote"` oraz wpisy `provinceOnly` bez `city` |
| `location.fullyRemote` | `remote` | **UWAGA:** pole na poziomie korzenia oferty `fullyRemote` (bez `location.`) jest ZAWSZE `false` w próbce i NIE nadaje się do tego celu — trzeba użyć `location.fullyRemote` |
| `url` (zbudowany URL) | `url` | **W API NIE MA gotowego pełnego URL-a do oferty.** Trzeba zbudować: `f"https://nofluffjobs.com/pl/job/{url}"` |
| `salary` (obiekt) | `salary` | budowany string z `from`/`to`/`currency`/`type`, tylko gdy `disclosedAt == "VISIBLE"` i `from`/`to` niepuste; w zbadanej próbce (>1400 ofert z wielu stron/miast) **każda oferta miała `disclosedAt: "VISIBLE"`** — NoFluffJobs wydaje się wymuszać jawność wynagrodzenia na wszystkich ofertach IT. Parser mimo to obsługuje gałąź `None` defensywnie (przetestowaną syntetycznym payloadem w `tests/test_nofluffjobs.py`, bo fixture jej nie pokrywa) |
| `posted` | `posted_at` | epoch millisecond timestamp — `datetime.fromtimestamp(value / 1000, tz=timezone.utc)` |
| — (stała) | `source` | brak odpowiednika w API — ustawiane na stałą `"nofluffjobs"` |

### Pola, których NIE MA w odpowiedzi (żeby przyszła zmiana nie szukała ich po omacku)

- Brak gotowego pełnego URL-a oferty — trzeba budować z `url` (slug).
- Brak jednego pola boolowskiego "remote" na poziomie oferty, które faktycznie
  działa — pole `fullyRemote` (poziom korzenia) jest zawsze `false`
  (wygląda na zdeprecjonowane); prawdziwa wartość jest w `location.fullyRemote`.
- Brak wariantu oferty bez podanych widełek w całej zbadanej próbce (>1400
  ofert, wiele miast, wiele stron wyników) — `disclosedAt` zawsze `"VISIBLE"`.
  Nie jest to gwarancja na przyszłość (dlatego parser i tak obsługuje ten
  przypadek), ale fixture nie mógł go pokryć realnymi danymi.
- Brak `description`/pełnego opisu stanowiska w tej liście (endpoint listy
  ofert zwraca tylko skrócone dane do wyświetlenia na liście; pełny opis
  wymagałby osobnego zapytania o szczegóły oferty — nie badano, poza zakresem
  Task 13).
- Brak surowej kwoty wynagrodzenia w oryginalnej walucie/okresie podanej przez
  firmę w tym zapytaniu — parametry `salaryCurrency`/`salaryPeriod` wymuszają
  przeliczenie do PLN/miesiąc po stronie API, więc dostęp do oryginalnych
  wartości wymagałby innego zapytania (nie badano).

Fixture: `tests/fixtures/nofluffjobs.json` (przycięty do 3 ofert w Szczecinie:
jedna stacjonarna z podanymi widełkami B2B, jedna zdalna — "Remote" wśród
`location.places` — z podanymi widełkami B2B, jedna zdalna z podanymi
widełkami typu "permanent". Wariant "bez podanych widełek" nie występuje w
fixture, bo nie zaobserwowano go w żadnej z >1400 zbadanych ofert — patrz
wyżej).
