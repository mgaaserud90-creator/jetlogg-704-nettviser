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
