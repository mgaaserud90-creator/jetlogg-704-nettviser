# JETLOGG 704 – nettviser

Privat nettviser for peledataene fra riggen. Siden er et reint statisk nettsted
(HTML/CSS/JS) som blir publisert på **Cloudflare Pages** og låst bak
**Cloudflare Access**.

---

## 0. Kort om hva som verner hva

| Lag | Hva det er | Verner det dataene? |
|---|---|---|
| **Cloudflare Access** | Innlogging med engangskode på e-post, i Cloudflares nett | **Ja. Dette er låsen.** |
| Passordfeltet på `index.html` | En sperre i grensesnittet | **Nei.** Siden er statisk – HTML, JS og JSON-filer blir sendt til nettleseren. Passordet kan ikke skjules. |

> **VIKTIG — LES DETTE FØRST:**
> Så lenge **Cloudflare Access-policyen ikke er satt opp**, er siden helt åpen.
> Den som kjenner adressen kan hente `data/index.json` og alle JSON-filene
> direkte i nettleseren, helt utenom passordfeltet.
> **Rekkefølgen er derfor: sett opp Access-policyen FØRST, og pek ikke noen
> mot adressen før policyen er på plass.**
> Passordfeltet på forsiden er bare en ekstra sperre i grensesnittet, som
> operatøren ba om.

---

## 1. Hva ligger hvor

Nettstedet er **repo-rota**. Det vil si at innholdet i denne mappa
(`nettsted/`) blir pushet som toppen av git-repoet, og Pages publiserer
«rotmappa» uten noe byggesteg.

```
.                       <- repo-rota (innholdet i nettsted/)
├── index.html          forside: logo + inngang (passordfelt)
├── viser.html          selve viseren (nedtrekk, søk, plott)
├── css/style.css
├── js/viser.js         all logikk for viseren
├── logo/Seabrokers_Dolomiti_RGB.svg
├── data/               JSON-filene (hendelser + index.json)
│   ├── index.json      lista nedtrekksmenyen blir bygd fra – hold den oppdatert
│   ├── 2026-10-01_K83_grouting.json
│   ├── 2026-10-01_K83_pilotboring.json
│   ├── 2026-10-01_K83_prejet.json
│   ├── 2026-10-01_K87_grouting.json
│   ├── _alle_2026-10-01.json        (kombinert fil – ikke i nedtrekksmenyen)
│   ├── index.js        JS-tvilling av index.json (reserve for file://)
│   └── <navn>.js       JS-tvilling av hver hendelses-JSON (samme reserve)
└── .github/workflows/deploy.yml     automatisert publisering (valgfri, se 4b)
```

Plottbiblioteket blir hentet fra CDN, **versjon pinnet til `plotly.js v3.5.0`**
(`https://cdn.plot.ly/plotly-3.5.0.min.js` i `viser.html`). Ingenting blir
bygd; Cloudflare serverer filene som de er.

Hver JSON-fil har en liten **JS-tvilling** ved siden av seg (`index.js`,
`<navn>.js`). Tvillingene inneholder nøyaktig den samme JSON-en, bare pakket inn
i `window.JETLOGG_INDEKS` / `window.JETLOGG_HENDELSE[...]`. De blir skrevet av
den samme generatoren som lager `index.json`, slik at de aldri kan komme i
utakt, og de er bare en **reserve for `file://`** – der nettleseren blokkerer
`fetch`, men tillater en vanlig `<script src>`. På http(s) (Cloudflare eller
lokal server) blir `index.json` og hendelses-JSON-filene lest direkte, og
tvillingene blir ikke brukt.

---

## 2. Legg prosjektet i et privat GitHub-repo

```bash
cd nettsted
git init
git add .
git commit -m "JETLOGG 704 - nettviser"
```

Lag et **privat** repo og push (bytt ut `<brukar>` og `<repo>`):

```bash
gh repo create <repo> --private --source=. --push
```

eller uten GitHub CLI:

```bash
git remote add origin https://github.com/<brukar>/<repo>.git
git branch -M main
git push -u origin main
```

**Velg «private».** Men merk: et privat repo er ikke det som verner
*publikasjonen* – det er Access-policyen i steg 4.

---

## 3. Opprett Pages-prosjektet i Cloudflare

Logg inn på <https://dash.cloudflare.com> → **Workers & Pages** →
**Create** → **Pages**.

Navnet på prosjektet avgjør adressen: `<prosjektnamn>.pages.dev`.
Dømet i dette repoet bruker `jetlogg-704` (samme navn som i
`.github/workflows/deploy.yml`). Velg et navn og bruk det samme overalt.

**Bygg-oppsett** (samme hvilken metode du velger i steg 4):

| Innstilling | Verdi |
|---|---|
| Build command | *(la stå tomt)* |
| Build output directory | `/` (rotmappa – siden ER rota) |
| Root directory | `/` |

### 4a. Enkleste vei: koble Pages til GitHub-repoet

I steg 3: velg **Connect to Git**, gi Cloudflare tilgang til repoet, velg
repoet og greina `main`, og bruk innstillingene over. Cloudflare bygger og
publiserer selv ved hver push. Da trenger du **ikke** workflow-fila i det
hele tatt, og heller ikke secrets (steg 5 kan hoppes over).

### 4b. Alternativ vei: publiser fra GitHub Actions (fila er alt laget)

Workflow-fila ligger i `.github/workflows/deploy.yml` og bruker
`cloudflare/wrangler-action@v4` med kommandoen
`wrangler pages deploy . --project-name=jetlogg-704`.

> **Om handlingen:** `cloudflare/pages-action` er **trukket tilbake og slettet
> fra GitHub** (repoet svarer 404), så den må ikke brukes – workflows som
> bruker den feiler alt ved oppstart. Cloudflares gjeldende oppskrift for
> «Direct Upload med CI» er `cloudflare/wrangler-action` med
> `wrangler pages deploy`. Er du i tvil om hva som er nyest, sjekk
> <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>.
>
> **Fremtidsvarsel:** Cloudflare har sagt at *Pages* blir avløst av
> *Workers* for nye prosjekter. Pages virker fortsatt, og Access fungerer likt
> på begge, men hvis du setter opp noe helt nytt senere kan det være
> enklere å legge den statiske siden på Workers i stedet.

> **Om tokenet og `workflow`-scope:** GitHub nekter å ta imot ei fil under
> `.github/workflows/` fra et token som ikke har `workflow`-scopet. Feilen
> ser slik ut:
> `refusing to allow an OAuth App to create or update workflow ... without 'workflow' scope`.
> Har tokenet ikke scopet, kjør disse to kommandoene, så er den også ute:
>
> ```bash
> gh auth refresh -s workflow
> cd nettsted
> git push
> ```

Husk å bytte prosjektnavnet i `env: CLOUDFLARE_PROJECT_NAME` i workflow-fila
hvis du valgte et annet navn enn `jetlogg-704`.

---

## 5. Secrets i GitHub (bare for 4b)

Legg disse to inn under repoet → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**:

| Secret | Hvor du finner den |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare → **My Profile** → **API Tokens** → **Create Token** → malen **«Edit Cloudflare Workers»**, eller et eget token med rettighetene *Account → Cloudflare Pages → Edit*. Kopier tokenen med en gang – den blir bare vist én gang. |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare-dashbordet → **Workers & Pages** → høyre side (Account ID), eller kommandoen `npx wrangler whoami`. |

`GITHUB_TOKEN` trenger du ikke legge inn; det finnes i workflowen automatisk.

---

## 6. Sett opp Cloudflare Access (DETTE ER LÅSEN)

1. Cloudflare-dashbordet → **Zero Trust** → **Access** → **Applications**
   → **Add an application** → **Self-hosted**.
2. **Application domain:** legg inn Pages-domenet, f.eks.
   `jetlogg-704.pages.dev`, og (hvis du har) et eget domene i tillegg.
   Legg gjerne inn begge som to «public hostnames» i samme app.
3. **Policy:** lag en policy av typen **Allow** med **Include → Emails**,
   og list opp **bare** de e-postadressene som skal ha tilgang.
   (Ikke bruk «Everyone», og ikke bruk et domene som slipper inn flere enn
   du mener.)
4. Sett **session duration** til det du vil (f.eks. 24 timer).
5. Lagre.

Hvordan det oppleves for operatøren: første gang noen åpner adressen, blir
de stoppet av Cloudflare og bedt om e-postadressen sin. De får en
**engangskode på e-post**, skriver den inn, og kommer først *da* videre til
siden. Alt dette skjer **i Cloudflares nett, før siden i det hele tatt blir
sendt til nettleseren** – og før passordfeltet på forsiden blir vist.

**Test med en gang:** åpne adressen i et privat/inkognito-vindu. Du skal
da bli bedt om e-post og kode – ikke få forsiden.

---

## 7. Passordfeltet på forsiden (bare grensesnitt)

Forsiden (`index.html`) har et passordfelt. Det er en ekstra sperre
operatøren ba om, og det er **ikke** et vern: alt innholdet er statiske
filer, så både siden og dataene blir sendt til nettleseren, og passordet kan
ikke skjules.

Koden lagrer derfor ikke passordet i klartekst, men **SHA-256-summen** av det
(i `index.html`, variabelen `PASSORD_SHA256`). Feltet sammenligner summer.

**Bytt passord:** regn ut summen av det nye passordet og bytt ut verdien:

```bash
python -c "import hashlib;print(hashlib.sha256('NYTT_PASSORD'.encode('utf-8')).hexdigest())"
```

Summen virker bare over `https://` eller på `localhost` (nettleseren krever
en «secure context» for å regne SHA-256 i det hele tatt). Cloudflare Pages
kjører på https, så det er greit; åpner du `index.html` som lokal fil
(`file://`), vil feltet si fra om at det ikke får regne summen.

---

## 8. Legge til nye hendelser senere

1. Legg den nye hendelses-JSON-fila i `data/`
   (navn som `<dato>_<pel>_<metode>.json`).
2. Oppdater `data/index.json` slik at den får med den nye fila.
   Fila har formen:

   ```json
   {
     "generert": "2026-10-02T16:10:45",
     "antall": 5,
     "hendelser": [
       { "fil": "2026-10-01_K83_grouting.json", "kombinert": false,
         "pel": "K83", "metode": "grouting", "dato": "2026-10-01",
         "lengde_cm": 143.2, "snitt_cm_min": 5.95, "stopp": 4,
         "varighet": "2 t 17 min" }
     ]
   }
   ```

   Feltene nedtrekksmenyen bruker er `fil`, `dato`, `pel`, `metode`,
   `lengde_cm` og `stopp`. Nye hendelser blir oftest skrevet ut av
   `eksporter_hendelser.py` – kjør den, så blir `index.json` oppdatert.
   Den samme generatoren skriver også **JS-tvillingene** (`index.js` og et
   `<navn>.js` per hendelse) i samme slengen, så de ikke kan komme i utakt.
3. Commit og push. Er Pages koblet til repoet (4a) eller workflowen kjører
   (4b), er de nye filene ute i løpet av et minutt.

Vil du raskt legge ut én fil uten å pushe, kan du bruke **Direct Upload** i
Cloudflare-dashbordet eller `npx wrangler pages deploy . --project-name=jetlogg-704`.

---

## 9. Slik virker viseren

- **Nedtrekk** bygd fra `data/index.json`, med lesbar tekst per rad:
  `2026-10-01 · K83 · grouting · 143,2 cm · 4 pausar`.
- **Søkefelt** som filtrerer lista på pel, metode og dato – uten å bry seg om
  store/små bokstaver, og uten at du trenger å skrive `K` foran peltallet (`83`
  finner også `K83`). Det står hvor mange treff det er, og sier klart fra når
  ingenting passer. Er det bare ett treff, blir hendelsen vist med en gang.
- **Klippet / Fullt** – bytte visning uten å laste siden på nytt:
  - *Klippet* (standard): pausene og uryddig-fasene er tatt ut av x-aksen.
    Fargede bruddmerker og stopplinjer (P1–P4 i sin egen farge, grått `‖` for
    uryddig), en komprimert tidsakse, og en fargestripe nederst som viser
    hvilke faser som teller med i lengde og snittfart.
  - *Fullt*: hele hendelsen på en ubrutt tidsakse. Hver pause blir vist
    som et **gjennomsiktig fargebånd over hele plottet – ett bånd per
    pause**, i samme farge som pausen har i den klippede visningen og i fotnoten.
    Uryddig-fasene blir vist som grå bånd.
- **Rektangelzoom:** dra et rektangel i plottet for å zoome til området.
  Dobbeltklikk nullstiller, og knappen **Nullstill zoom** gjør det samme.
  Rulling zoomer.
- **Skriv ut / lagre bilde:** knappen under «Annet» renderer den figuren som
  står på skjermen – samme visning (Klippet/Fullt) og samme levende zoom – til
  et PNG, og åpner et nytt vindu med bildet, sammendraget og fotnotene klare
  for utskrift. Der ligger også en **Last ned PNG**-knapp for rein
  bildeutskrift. Modebar-kameraet i plottet lager bildet direkte, med
  filnavnet til hendelsen.
- **Fartstall:** fart-kurven er tatt bort. Igjen står **stigningstallene** som
  **bare tall** (`7,8`, ikke `7,8 cm/min`) øverst i plottet – ett tall per
  seksjon som teller med, fordelt langs x-aksen. Enheten er forklart i
  fotnoten. I sammendraget øverst står enheten fortsatt, siden det er en
  tekstlesing og ikke en merking i plottet.
- **Fotnote:** én rad per pause i pausens egen farge, med nummer,
  varighet, klokke og dybde ved stopp, klokke og dybde ved start, lengde,
  endring i dybde med fortegn, og grunn. Under en fasetabell som viser
  hvilke faser som teller med i lengde og snittfart.
- **Tallene** er skrevet med norsk tallformat (komma som desimaltegn).
- Firmalogoen ligger som et svakt vannmerke bak kurvene.

Vil du åpne en hendelse direkte, kan du bruke
`viser.html?fil=2026-10-01_K83_grouting.json&vis=fullt`
(`fil` velger hendelse, `vis` velger `klippet` eller `fullt`).
Da må siden kjøres fra en server, fra Cloudflare eller som lokal fil med
JS-tvillingene ved siden av (den virker også på `file://`).

---

## 10. Kjøre siden lokalt

```bash
cd nettsted
python -m http.server 8788
```

Åpne <http://localhost:8788/>. Da virker nedtrekksmenyen, søket og
`?fil=`-parameteren, og alle JSON-filene blir lest direkte.

Siden virker også når den blir åpnet **direkte fra disken** (`file://`). Da
blokkerer nettleseren `fetch`, men `data/index.js` og `data/<navn>.js` er
lastet som vanlige skript, så nedtrekket blir fylt og hendelsene blir vist
fra de innebygde tvillingene. Det kommer da et lite hint om dette over
plottet. Denne veien er en **reserve** – den vanlige veien er server eller
Cloudflare, der JSON-filene blir lest direkte.

---

## 11. Sjekkliste før du slipper noen inn

- [ ] Repoet er **privat**.
- [ ] Cloudflare Access-appen dekker domenet (`*.pages.dev`, og eget
      domene om du har).
- [ ] Policyen sier **Allow** og lister **bare** de rette e-postene.
- [ ] Testet i inkognito-vindu: e-post + engangskode kommer **før** siden.
- [ ] Eventuelt: bytt passordet på forsiden (steg 7).

Uten de tre første punktene er siden helt åpen for hvem som helst med lenka.
