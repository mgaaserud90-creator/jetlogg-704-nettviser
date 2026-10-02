# JETLOGG 704 – nettviser

Nettviser for peledataene fra riggen. Siden er et reint statisk nettsted
(HTML/CSS/JS), publisert **helt åpent på GitHub Pages**:

**<https://mgaaserud90-creator.github.io/jetlogg-704-nettviser/>**

Alle som kjenner adressen kommer inn på forsiden, og passordfeltet der slipper
dem videre til viseren.

---

## 0. Tilgang – slik er det bestemt

Siden er **åpen**. Alle som kjenner adressen ser forsiden, og den som skriver
riktig passord kommer videre til viseren. Det er et bevisst valg fra
operatøren: det skal være enkelt å slippe folk inn, uten e-postlister eller
innloggingsporter.

Det du bør vite om hva passordfeltet faktisk gjør:

| | |
|---|---|
| Stopper den som skriver adressa i nettleseren | **Delvis.** Forsiden ber om passordet, og `viser.html` sender deg tilbake dit om du ikke har skrevet det. Sperren ligger i nettleseren, så den som leser kildekoden eller slår av JavaScript kommer forbi. |
| Stopper den som kjenner filnavnet til en datafil | **Nei.** `data/index.json` og hver hendelses-JSON er vanlige statiske filer. Skriver du `.../data/2026-10-01_K83_grouting.json` i nettleseren, får du hele fila – uten passord. |
| Stopper søkemotorer | **Nei.** GitHub Pages er åpent indekserbart, og repoet er offentlig, så både kildekoden og datafilene ligger fritt tilgjengelig på GitHub i tillegg. |

Passordet ligger ikke i klartekst: feltet regner ut **SHA-256-summen** av det
du skriver og sammenligner med summen i `index.html` (`PASSORD_SHA256`). Det
hindrer at passordet står synlig i kildekoden, men det er ikke kryptering –
sjekksummen er offentlig, og datafilene er det også.

> **Vil du låse dataene på ekte?** Da duger ikke GitHub Pages, som ikke kan
> passordbeskytte noe som helst. Du må over på noe som sjekker passordet *før*
> fila blir sendt. Steg 6 viser de to måtene. Operatøren har vurdert dette og
> valgt den åpne varianten.

---

## 1. Hva ligger hvor

Nettstedet er **repo-rota**. Det vil si at innholdet i denne mappa
(`nettsted/`) er toppen av git-repoet, og GitHub Pages publiserer rotmappa
uten noe byggesteg.

```
.                       <- repo-rota (innholdet i nettsted/)
├── .nojekyll           slår av Jekyll – filene skal serveres som de er
├── index.html          forside: logo + inngang (passordfelt)
├── viser.html          selve viseren (nedtrekk, søk, plott)
├── css/style.css
├── js/viser.js         all logikk for viseren
├── logo/Seabrokers_Dolomiti_RGB.svg
└── data/               JSON-filene (hendelser + index.json)
    ├── index.json      lista nedtrekksmenyen blir bygd fra – hold den oppdatert
    ├── 2026-10-01_K83_grouting.json
    ├── 2026-10-01_K83_pilotboring.json
    ├── 2026-10-01_K83_prejet.json
    ├── 2026-10-01_K87_grouting.json
    ├── _alle_2026-10-01.json        (kombinert fil – ikke i nedtrekksmenyen)
    ├── index.js        JS-tvilling av index.json (reserve for file://)
    └── <navn>.js       JS-tvilling av hver hendelses-JSON (samme reserve)
```

Plottbiblioteket blir hentet fra CDN, **versjon pinnet til `plotly.js v3.5.0`**
(`https://cdn.plot.ly/plotly-3.5.0.min.js` i `viser.html`). Ingenting blir
bygd; serveren leverer filene som de er. Alle stier i HTML-en er relative, så
siden virker like godt i en undermappe (`/jetlogg-704-nettviser/`) som i rota.

`.nojekyll` må ligge der. Uten den prøver GitHub å kjøre filene gjennom
Jekyll, og det kan endre eller holde tilbake filer.

Hver JSON-fil har en liten **JS-tvilling** ved siden av seg (`index.js`,
`<navn>.js`). Tvillingene inneholder nøyaktig den samme JSON-en, bare pakket inn
i `window.JETLOGG_INDEKS` / `window.JETLOGG_HENDELSE[...]`. De blir skrevet av
den samme generatoren som lager `index.json`, slik at de aldri kan komme i
utakt, og de er bare en **reserve for `file://`** – der nettleseren blokkerer
`fetch`, men tillater en vanlig `<script src>`. På http(s) blir `index.json` og
hendelses-JSON-filene lest direkte, og tvillingene blir ikke brukt.

---

## 2. Legg prosjektet i et GitHub-repo

```bash
cd nettsted
git init
git add .
git commit -m "JETLOGG 704 - nettviser"
git branch -M main
gh repo create <repo> --public --source=. --push
```

eller uten GitHub CLI:

```bash
git remote add origin https://github.com/<bruker>/<repo>.git
git push -u origin main
```

Repoet **må være offentlig** for at GitHub Pages skal virke på gratiskontoen.
Er det privat, svarer GitHub «Your current plan does not support GitHub Pages
for this repository». Da må du enten oppgradere planen eller bruke
Cloudflare Pages i steg 5.

---

## 3. Slå på GitHub Pages

**Via nettleseren:** repoet → **Settings** → **Pages** → under *Build and
deployment*, sett **Source** til **Deploy from a branch**, velg **Branch:
`main`** og mappa **`/ (root)`**, og lagre. Det er alt – ingen byggjekommando,
ingen miljøvariabler.

**Via kommandolinjen:**

```bash
gh api -X POST repos/<bruker>/<repo>/pages \
  -f "source[branch]=main" -f "source[path]=/"
```

Første publisering tar et par minutter. Adressen blir

```
https://<bruker>.github.io/<repo>/
```

for dette prosjektet altså
<https://mgaaserud90-creator.github.io/jetlogg-704-nettviser/>.

Åpne adressen og skriv passordet. Ser du forsiden, er alt i orden.

---

## 4. Oppdatere siden senere

Alt du gjør, er å pushe til `main`:

```bash
git add -A
git commit -m "Nye hendelser"
git push
```

GitHub Pages bygger og publiserer på nytt av seg selv, normalt i løpet av et
minutt. Du kan følge det under **Actions** i repoet (arbeidsflyten heter
`pages build and deployment`).

Det er ingen hemmeligheter å holde styr på og ingen workflow-fil å vedlikeholde
– GitHub har sin egen, innebygd.

---

## 5. Vil du heller bruke Cloudflare Pages? (valgfritt)

GitHub Pages holder for dette. Vil du flytte siden til Cloudflare senere, er
oppskriften denne:

1. <https://dash.cloudflare.com> → **Workers & Pages** → **Create** → **Pages**
   → koble til GitHub-repoet, velg greina `main`.
2. **Build command:** *(tomt)*. **Build output directory:** `/`.
   **Root directory:** `/`.
3. Publiser. Da får du `<prosjektnavn>.pages.dev`.

Merk at `cloudflare/pages-action` er **trukket tilbake og slettet fra GitHub**
(repoet svarer 404), så en gammel workflow som bruker den feiler med en gang.
Vil du publisere fra Actions i stedet for Git-integrasjonen, er
`cloudflare/wrangler-action` med `wrangler pages deploy .` det som gjelder nå,
og da trenger du secrets `CLOUDFLARE_API_TOKEN` og `CLOUDFLARE_ACCOUNT_ID`.
Git-integrasjonen i punkt 1 krever ingenting av dette.

---

## 6. Vil du låse dataene likevel? (valgfritt, ikke gjort)

Den åpne varianten i steg 0 er valgt med åpne øyne. GitHub Pages kan ikke
passordbeskytte noe, så skal passordet gjelde også for filene, må siden flyttes.

**A. Cloudflare Pages + Cloudflare Access – e-post og engangskode før siden vises.**

Flytt siden til Cloudflare (steg 5) og sett opp:
**Zero Trust** → **Access** → **Applications** → **Add an application** →
**Self-hosted**, domene `ditt-prosjekt.pages.dev`, policy **Allow** med
**Include → Emails** og bare de adressene som skal slippe inn. Da møter den som
kjenner lenka en Cloudflare-side som ber om e-post og en **engangskode** – alt
skjer i Cloudflares nett *før* siden blir sendt til nettleseren.

**B. Én delt kode, sjekket på serversiden – Cloudflare Pages Function.**

Legg en funksjon i `functions/data/[[sti]].js` som krever en cookie eller
header med den delte koden og først da henter fila fra `data/`. Da er ikke
JSON-filene fritt tilgjengelige statiske filer lenger. Det krever litt arbeid i
`js/viser.js` også, siden den i dag henter `data/index.json` rett fra stien.
Si fra om du vil ha det bygget.

---

## 7. Passordet på forsiden – dette er sperren

Forsiden (`index.html`) har et passordfelt. Det er med vilje den eneste sperren
på siden, og den fungerer slik operatøren vil: alle ser forsiden, den som kan
passordet kommer videre. Se steg 0 for hva den gjør og ikke gjør.

Koden lagrer ikke passordet i klartekst, men **SHA-256-summen** av det
(`index.html`, variabelen `PASSORD_SHA256`). Feltet sammenligner summer.

**Bytt passord:** regn ut summen av det nye passordet og bytt ut verdien:

```bash
python -c "import hashlib;print(hashlib.sha256('NYTT_PASSORD'.encode('utf-8')).hexdigest())"
```

Summen virker bare over `https://` eller på `localhost` (nettleseren krever en
«secure context» for å regne SHA-256 i det hele tatt). GitHub Pages kjører på
https, så det er greit. Også `file://` regnes som secure context i Chrome, så
feltet virker der óg.

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
3. Commit og push. Siden er oppdatert i løpet av et minutt.

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
  - *Fullt*: hele hendelsen på en ubrutt tidsakse. Hver pause blir vist som et
    **gjennomsiktig fargebånd over hele plottet – ett bånd per pause**, i samme
    farge som pausen har i den klippede visningen og i fotnoten. Uryddig-fasene
    blir vist som grå bånd.
- **Rektangelzoom:** dra et rektangel i plottet for å zoome til området.
  Dobbeltklikk nullstiller, og knappen **Nullstill zoom** gjør det samme.
  Rulling zoomer.
- **Skriv ut / lagre bilde:** knappen under «Annet» renderer den figuren som
  står på skjermen – samme visning (Klippet/Fullt) og samme levende zoom – til
  et PNG, og åpner et nytt vindu lagt opp for **liggende A4**. Der er grafen
  hovedsaken: bildet lages i 3840 × 2400 px (ca. 350 dpi på papir) og fyller
  nesten hele arket, med tittel og sammendrag som ei tynn stripe overst.
  Pausetabellene kommer på neste ark. Der ligger også en **Last ned PNG**-knapp
  for rein bildeutskrift. Modebar-kameraet i plottet lager bildet direkte, med
  filnavnet til hendelsen. Skriver du ut selve sida med Ctrl+P, blir den også
  liggende.
- **Fartstall:** fart-kurven er tatt bort. Igjen står **stigningstallene** som
  **bare tall** (`7,8`, ikke `7,8 cm/min`) øverst i plottet – ett tall per
  seksjon som teller med, fordelt langs x-aksen. Enheten er forklart i fotnoten.
  I sammendraget øverst står enheten fortsatt, siden det er en tekstlesing og
  ikke en merking i plottet.
- **Fotnote:** én rad per pause i pausens egen farge, med nummer, varighet,
  klokke og dybde ved stopp, klokke og dybde ved start, lengde, endring i dybde
  med fortegn, og grunn. Under en fasetabell som viser hvilke faser som teller
  med i lengde og snittfart.
- **Tallene** er skrevet med norsk tallformat (komma som desimaltegn).
- Firmalogoen ligger som et svakt vannmerke bak kurvene.

Vil du åpne en hendelse direkte, kan du bruke
`viser.html?fil=2026-10-01_K83_grouting.json&vis=fullt`
(`fil` velger hendelse, `vis` velger `klippet` eller `fullt`). Det virker både
på GitHub Pages og lokalt.

---

## 10. Kjøre siden lokalt

```bash
cd nettsted
python -m http.server 8788
```

Åpne <http://localhost:8788/>. Da virker nedtrekksmenyen, søket og
`?fil=`-parameteren, og alle JSON-filene blir lest direkte.

Siden virker også når den blir åpnet **direkte fra disken** (`file://`). Da
blokkerer nettleseren `fetch`, men `data/index.js` og `data/<navn>.js` er lastet
som vanlige skript, så nedtrekket blir fylt og hendelsene blir vist fra de
innebygde tvillingene. Det kommer da et lite hint om dette over plottet. Denne
veien er en reserve – den vanlige veien er GitHub Pages eller en lokal server,
der JSON-filene blir lest direkte.

---

## 11. Sjekkliste

- [x] Repoet er offentlig, og GitHub Pages publiserer fra `main` / rot.
- [x] `.nojekyll` ligger i rota.
- [x] Adressa er åpnet og forsiden kommer opp.
- [x] Passordet på forsiden virker (`PASSORD_SHA256` i `index.html`).
- [ ] Du er klar over at datafilene under `data/` er lesbare for den som
      kjenner filnavnet, uten passord, og at de også ligger i det offentlige
      repoet. Dette er valgt med vilje – se steg 0.
- [ ] Vil du ikke det likevel: steg 6.

Er du i tvil om du bør dele lenka bredt: alt som ligger under `data/` blir
tilgjengelig for den som får tak i et filnavn, og søkemotorer kan finne det av
seg selv.
