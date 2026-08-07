# work-scrapper

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

Działa to tak, bo portale tagują ofertę zdalną miastem siedziby firmy — Shoper
ma 18 ofert `remote=True`, wszystkie z `city: Kraków`. Zapytanie wyłącznie o
Szczecin by ich nie zwróciło, mimo że można na nie pracować ze Szczecina.
Dlatego przy `include_remote: true` źródła dociągają dodatkowo pulę
ogólnopolską, a matcher przepuszcza z niej tylko oferty zdalne (stacjonarne
spoza `locations` odpada).

Koszt: przebieg pobiera ~3700 ofert zamiast ~360 i trwa ok. 12 s zamiast 3 s.

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
