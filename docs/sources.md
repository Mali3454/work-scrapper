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
