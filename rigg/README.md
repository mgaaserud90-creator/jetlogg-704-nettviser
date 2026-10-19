# rigg/ – kjeden som kjører på GitHub Actions

Denne mappen gjør jobben kontor-PC-en gjorde: henter ACRON-eksporten fra Gmail,
dekoder den til hendelses-JSON og skriver dem rett i nettstedets `data/`.
Workflowen [`.github/workflows/rigg-hent.yml`](../.github/workflows/rigg-hent.yml)
kjører den hvert 15. minutt.

## Filer

| fil | hva |
|---|---|
| `hent_og_plott.py` | hent + dekod + del. **Endret kopi:** ny bryter `--json-dir` |
| `eksporter_hendelser.py` | UENDRET kopi (kanonisk verktøy) |
| `regenerer_acron_plott.py` | UENDRET kopi (kanonisk verktøy) |
| `requirements.txt` | `numpy`, `pandas`, `matplotlib` |
| `behandlet_epost.txt` | tilstand: Message-ID-er vi har hentet (committes) |
| `behandlet_filer.txt` | tilstand: SHA-256 per eksport (committes) |

## Slik virker det

1. Workflowen skriver `rigg/epost.cred` fra secrets (`GMAIL_USER`, `GMAIL_APP_PASSWORD`).
2. `python rigg/hent_og_plott.py --still --json-dir data`
   Da er `data/` **både kilden og resultatet**: hendelses-JSON, `index.json` og
   JS-tvillingene skrives dit. Ingen `json/`-mappe dupliseres. Regelen
   «større versjon vinner» sammenligner mot filene som alt ligger i `data/`.
3. Workflowen committer `data/` + de to `behandlet`-filene og pusher. Er det
   ingenting nytt, committes ingenting.

## Secrets som må ligge i repoet

Settings → Secrets and variables → Actions:

- `GMAIL_USER` – f.eks. `borrigg170@gmail.com`
- `GMAIL_APP_PASSWORD` – Gmails **app-passord** (roter det – det gamle var eksponert)

Uten disse feiler jobben med en tydelig melding i stedet for å gjøre noe halvveis.

## Utenfor repoet (ignorert i `.gitignore`)

`rigg/hentet/`, `rigg/arbeid/`, `rigg/plot/`, `rigg/logg_*.txt`, `rigg/*.cred`.

## Slå av kontor-PC-en

Den gamle oppgaven `JETLOGG 704 - kontor kjor alt` må fjernes når denne er
bekreftet, ellers kjører begge:

```
schtasks /delete /tn "JETLOGG 704 - kontor kjor alt" /f
```

Begge er idempotente, så en overlapp gjør ingen skade – bare dobbeltarbeid.

## Forskjell fra kontor-pc-kopien

- Ny bryter `--json-dir` (standard uendret: `json/`). Actions peker den på `data/`.
- `publiser_til_nett.py` er **ikke** med her – den trengs ikke når vi skriver
  rett i `data/`.
- Ingen `plot/`: grafene ligger på nettstedet, som før.

## Kjør lokalt (for prøving)

```
py -3 rigg/hent_og_plott.py --test --still --json-dir data
```

`--test` henter og endrer ingenting.

## Importere eldre eller større data

**Fra GitHub – maks 20 døgn.** Actions → *JETLOGG - importer zip (manuell)* →
**Run workflow**. Oppgi enten en sti til en zip i repoet (`import/fil.zip`)
eller en https-URL (en Release-asset tåler opptil 2 GB). Jobben sjekker vinduet
med `rigg/vindu.py` og **stopper før den dekoder noe** hvis eksporten er større
enn feltet `maks_dager` (standard 20 døgn).

**Fra PC-en – 200 døgn og mer.** Skriptet deler zippen i biter på 20 døgn,
dekoder hver bit og pusher:

```
rigg\import_del_opp.bat "C:\sti\stor.zip"
rigg\import_del_opp.bat "C:\sti\stor.zip" --dager 15
rigg\import_del_opp.bat "C:\sti\stor.zip" --test        (ingen commit/push)
```

Csv-en **strømmes rett fra zippen** – den pakkes aldri ut som én stor fil og
lastes aldri helt inn i minnet. Hver bit blir en liten midlertidig zip som
dekodes og slettes med en gang. Kilden du peker på røres ikke.

## Disk – ingenting stort blir liggende
- `--slett-arbeid` fjerner utpakket csv etter hver kjøring. Både den daglige
  jobben og importjobben bruker den.
- Begge jobbene rydder i tillegg `rigg/arbeid` og `rigg/hentet` uansett utfall,
  og den lokale oppdeleren fjerner alt den har laget selv.
- Ingenting av dette committes – se `.gitignore` (`rigg/arbeid/`, `rigg/hentet/`,
  `rigg/import_tmp/`).

**Grenser å kjenne til:** Gmail tar ~18 MB zip per e-post (≈56 døgn). GitHub
avviser enkeltfiler over 100 MB i en push, men med ~1,8 MB JSON per døgn slår
den grensen først rundt 125 døgn. Det som faktisk begrenser én vanlig kjøring er
minne og tid: hold deg til **≤ 20 døgn per bit**.

## Pel som er logget under feil nummer

Riggen kan gå videre til neste pel uten at `PEL_NR`-feltet blir med. Da havner
arbeidet til neste pel under den forrige. `rigg/pel_overstyring.json` retter
slike tilfeller med tidsstempler, så rettelsen blir lik hver gang eksporten
dekodes på nytt:

```json
[
  {
    "fra": "2026-10-15T15:10:36",
    "til": "2026-10-15T23:59:59",
    "fra_pel": "k100",
    "pel": "k101",
    "grunn": "k101 ble boret, jettet og groutet mens loggen fortsatt sa k100"
  }
]
```

Tre regler til gjelder i dekodingen:

- **Logging av = ikke arbeid.** Er `START_STOPP_LOGG` null for hele vinduet, blir
  det ingen hendelse. Det er slangetrekk og handtering, ikke boring eller
  jetting – uten denne reglen ble slike strekk til «hendelser» på noen
  sekunder.
- **Pilotboring måler hele strekket.** En boring som starter på −32 cm og ender
  på 100 cm er 132 cm, ikke 100 − 32 = 68. Prejet og grouting beholder
  «summen av seksjonene som teller med», som er tallet i plottets overskrift.
- **Prejet og grouting begynner på bunnen.** Vinduet rommer også nedkjøringen
  til bunnen. Ligger bunnen et stykke inn i vinduet, flyttes starten dit, så
  prejet og grouting for samme pel starter på samme dybde (f.eks. 164,2 og
  164,5 cm) i stedet for at prejet ser ut til å gå fra 0 cm.

