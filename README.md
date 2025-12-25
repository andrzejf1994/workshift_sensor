# Workshift Sensor

Workshift Sensor is a custom Home Assistant integration that helps track rotating production shifts according to a flexible, cyclic timetable. It provides a four-step configuration wizard and exposes sensors that describe the current and upcoming shifts, making it easy to automate workflows around staff availability.

## Workshift Sensor — niestandardowa integracja HA do zarządzania grafikiem zmian

Integracja działa całkowicie po stronie Home Assistanta, nie wymaga dodatkowych usług ani połączenia zewnętrznego. Każdy wpis konfiguracyjny tworzy osobne urządzenie wraz z trzema encjami:

- `sensor.<prefix>_today_shift` – numer zmiany dla bieżącego dnia wraz z metadanymi (czas rozpoczęcia i zakończenia, opis, informacja o dniu roboczym).
- `sensor.<prefix>_tomorrow_shift` – prognoza na kolejny dzień.
- `binary_sensor.<prefix>_on_shift` – informacja czy w danej chwili trwa zmiana (uwzględnia zmiany przechodzące przez północ).

## Schemat działania – konfiguracja przez kreator 4-etapowy

Integracja korzysta z konfiguracyjnego kreatora UI Home Assistanta. Kolejne kroki obejmują:

1. **Ustawienia ogólne** – nazwa wpisu oraz opcjonalne wykorzystanie czujnika dnia roboczego (osobno dla dziś i jutra).
2. **Parametry zmian** – czas trwania pojedynczej zmiany oraz liczba zmian na dobę.
3. **Godziny rozpoczęcia zmian** – dynamicznie generowane pola odpowiadające liczbie zmian.
4. **Data startu i harmonogram** – wzorzec cyklicznych zmian zapętlany względem zadanej daty początkowej.
5. **Dni wolne** – możliwość dodania pojedynczych dni lub zakresów dat w formacie `RRRR-MM-DD` lub `RRRR-MM-DD – RRRR-MM-DD`, z podglądem już wprowadzonych okresów oraz możliwością ich usunięcia (analogicznie do integracji Workday Sensor).

Wszystkie kroki udostępniają tłumaczenia PL/EN oraz walidację danych w locie. Opcje można później zmienić w dedykowanym options flow.

## Logika harmonogramu – obiekty `WorkshiftConfigData` i `WorkshiftSchedule`

- **`WorkshiftConfigData`** przechowuje parametry wpisu konfiguracyjnego (czas zmiany, liczba zmian, godziny startów, wykorzystanie czujników dnia roboczego oraz wzorzec harmonogramu).
- **`WorkshiftSchedule`** odpowiada za obliczenia na podstawie daty startowej oraz zapętlonego ciągu cyfr harmonogramu. Dla dowolnej daty zwraca odpowiednią zmianę (albo dzień wolny) oraz dokładne znaczniki czasu rozpoczęcia i zakończenia zmiany.

Silnik aktualizacji działa w trybie asynchronicznym – integracja planuje kolejne odświeżenie zawsze na granicy zmiany (start, koniec, północ), zapewniając aktualne stany encji bez zbędnego odpytywania.

## Udostępniane encje

Każdy wpis integracji dodaje następujące encje:

| Encja | Opis |
| ----- | ---- |
| `sensor.<prefix>_today_shift` | Numer i szczegóły bieżącej zmiany (czas startu, koniec, opis, status dnia roboczego). |
| `sensor.<prefix>_tomorrow_shift` | Informacje o zmianie przewidzianej na jutro. |
| `binary_sensor.<prefix>_on_shift` | Stan włączony, gdy aktualnie trwa zmiana (również gdy rozpoczęła się poprzedniego dnia). |

Wszystkie encje mają stabilne identyfikatory `unique_id` oraz są powiązane z urządzeniem reprezentującym daną konfigurację.

## Założenia

- Harmonogram zapętla się względem daty startowej, a cyfra `0` oznacza dzień wolny.
- Dane wejściowe przechodzą sanityzację – format godzin `HH:MM`, rosnąca kolejność startów, weryfikacja długości zmian oraz zgodności cyfr harmonogramu z liczbą zmian.
- Integracja opcjonalnie korzysta z czujników dnia roboczego Home Assistanta (`binary_sensor.workday_sensor`). Można wskazać oddzielne encje dla dziś i jutra, a brak dedykowanego czujnika jutra skutkuje użyciem harmonogramu / prognozy dzisiejszego sensora.
- Aktualizacje są planowane tylko w punktach granicznych (start/koniec zmiany, północ), co minimalizuje obciążenie systemu.

## Instalacja przez HACS

1. Dodaj repozytorium jako **Custom Repository** w HACS (typ: Integration).
2. Zainstaluj integrację „Workshift Sensor”.
3. Po restarcie Home Assistanta przejdź do **Ustawienia → Urządzenia i usługi → Dodaj integrację**, wyszukaj „Workshift Sensor” i uruchom kreator konfiguracji.

## CHANGELOG

Zobacz plik [CHANGELOG.md](CHANGELOG.md) dla listy zmian.

## Licencja

Projekt udostępniany jest na licencji MIT – szczegóły znajdują się w pliku [LICENSE](LICENSE).
