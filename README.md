# JETLOGG 704 – nettviser

Privat nettvisar for peledataa fra riggen. Sida er eit reint statisk nettsted
(HTML/CSS/JS) som blir publisert pa **Cloudflare Pages** og last bak
**Cloudflare Access**.

---

## 0. Kort om kva som vernar kva

| Lag | Kva det er | Vernar det dataa? |
|---|---|---|
| **Cloudflare Access** | Innlogging med eingongskode pa e-post, i Cloudflare sitt nett | **Ja. Dette er lasen.** |
| Passordfeltet pa `index.html` | Ein sperre i grensesnittet | **Nei.** Sida er statisk – HTML, JS og JSON-filer blir sendt til nettlesaren. Passordet kan ikkje gøymast. |

> **VIKTIG — LES DETTE FORST:**
> Sa lenge **Cloudflare Access-policyen ikkje er sett opp**, er sida heilt open.
> Den som kjenner adressa kan hente `data/index.json` og alle JSON-filene
> direkte i nettlesaren, heilt utanom passordfeltet.
> **Rekkjefolgja er difor: set opp Access-policyen FØRST, og pek ikkje nokon
> mot adressa før policyen er pa plass.**
> Passordfeltet pa framsida er berre ein ekstra sperre i grensesnittet, som
> operatoren bad om.

---

## 1. Kva ligg kor

Nettstedet er **repo-rota**. Det vil seie at innhaldet i denne mappa
(`nettsted/`) blir pusht som toppen av git-repoet, og Pages publiserer
«rotmappa» utan noko byggjesteg.

```
.                       <- repo-rota (innhaldet i nettsted/)
├── index.html          forside: logo + inngang (passordfelt)
├── viser.html          sjolve viseren (nedtrekk, sok, plott)
├── css/style.css
├── js/viser.js         all logikk for viseren
├── logo/Seabrokers_Dolomiti_RGB.svg
├── data/               JSON-filene (hendelser + index.json)
│   ├── index.json      lista nedtrekksmenyen blir bygd fra – hald ho oppdatert
│   ├── 2026-10-01_K83_grouting.json
│   ├── 2026-10-01_K83_pilotboring.json
│   ├── 2026-10-01_K83_prejet.json
│   ├── 2026-10-01_K87_grouting.json
│   ├── _alle_2026-10-01.json        (kombinert fil – ikkje i nedtrekksmenyen)
│   ├── index.js        JS-tvilling av index.json (reserve for file://)
│   └── <navn>.js       JS-tvilling av kvar hendelses-JSON (same reserve)
└── .github/workflows/deploy.yml     automatisert publisering (valfri, sjaa 4b)
```

Plottbiblioteket blir henta fra CDN, **versjon pinnet til `plotly.js v3.5.0`**
(`https://cdn.plot.ly/plotly-3.5.0.min.js` i `viser.html`). Ingenting blir
bygga; Cloudflare serverer filene som dei er.

Kvar JSON-fil har ein liten **JS-tvilling** ved sida av seg (`index.js`,
`<navn>.js`). Tvillingane inneheld nøyaktig den same JSON-en, berre pakka inn
i `window.JETLOGG_INDEKS` / `window.JETLOGG_HENDELSE[...]`. Dei blir skrivne av
den same generatoren som lagar `index.json`, slik at dei aldri kan kome i
utakt, og dei er berre ein **reserve for `file://`** – der nettlesaren blokkerer
`fetch`, men tillèt ein vanleg `<script src>`. Pa http(s) (Cloudflare eller
lokal tenar) blir `index.json` og hendelses-JSON-filene lesne direkte, og
tvillingane blir ikkje brukte.

---

## 2. Legg prosjektet i eit privat GitHub-repo

```bash
cd nettsted
git init
git add .
git commit -m "JETLOGG 704 - nettviser"
```

Lag eit **privat** repo og push (byt ut `<brukar>` og `<repo>`):

```bash
gh repo create <repo> --private --source=. --push
```

eller utan GitHub CLI:

```bash
git remote add origin https://github.com/<brukar>/<repo>.git
git branch -M main
git push -u origin main
```

**Vel «private».** Men merk: eit privat repo er ikkje det som vernar
*publikasjonen* – det er Access-policyen i steg 4.

---

## 3. Opprett Pages-prosjektet i Cloudflare

Logg inn pa <https://dash.cloudflare.com> → **Workers & Pages** →
**Create** → **Pages**.

Namnet pa prosjektet avgjer adressa: `<prosjektnamn>.pages.dev`.
Dømet i dette repoet brukar `jetlogg-704` (same namn som i
`.github/workflows/deploy.yml`). Vel eit namn og bruk det same overalt.

**Byggjeoppsett** (same kva metode du vel i steg 4):

| Innstilling | Verdi |
|---|---|
| Build command | *(la sta tomt)* |
| Build output directory | `/` (rotmappa – sida ER rota) |
| Root directory | `/` |

### 4a. Enklaste veg: koble Pages til GitHub-repoet

I steg 3: vel **Connect to Git**, gi Cloudflare tilgang til repoet, vel
repoet og greina `main`, og bruk innstillingane over. Cloudflare byggjer og
publiserer sjølv ved kvar push. Da treng du **ikkje** workflow-fila i det
heile, og heller ikkje secrets (steg 5 kan hoppast over).

### 4b. Alternativ veg: publiser fra GitHub Actions (fila er alt laga)

Workflow-fila ligg i `.github/workflows/deploy.yml` og brukar
`cloudflare/wrangler-action@v4` med kommandoen
`wrangler pages deploy . --project-name=jetlogg-704`.

> **Om handlinga:** `cloudflare/pages-action` er **trekt tilbake og sletta
> fra GitHub** (repoet svarar 404), sa den ma ikkje brukast – workflows som
> brukar ho feilar alt ved oppstart. Cloudflare si gjeldande oppskrift for
> «Direct Upload med CI» er `cloudflare/wrangler-action` med
> `wrangler pages deploy`. Er du i tvil om kva som er nyast, sjekk
> <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>.
>
> **Framtidsvarsel:** Cloudflare har sagt at *Pages* blir avloyst av
> *Workers* for nye prosjekt. Pages verkar framleis, og Access fungerer likt
> pa begge, men dersom du set opp noko heilt nytt seinare kan det vere
> enklare a legge den statiske sida pa Workers i staden.

> **Om tokenet og `workflow`-scope:** GitHub nektar a ta imot ei fil under
> `.github/workflows/` fra eit token som ikkje har `workflow`-scopet. Feilen
> ser slik ut:
> `refusing to allow an OAuth App to create or update workflow ... without 'workflow' scope`.
> Har tokenet ikkje scopet, køyr desse to kommandoane, sa er ho ogsa ute:
>
> ```bash
> gh auth refresh -s workflow
> cd nettsted
> git push
> ```

Hugs a byte prosjektnamnet i `env: CLOUDFLARE_PROJECT_NAME` i workflow-fila
om du valde eit anna namn enn `jetlogg-704`.

---

## 5. Secrets i GitHub (berre for 4b)

Legg desse to inn under repoet → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**:

| Secret | Kvar du finn han |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare → **My Profile** → **API Tokens** → **Create Token** → malen **«Edit Cloudflare Workers»**, eller ein eigen token med rettane *Account → Cloudflare Pages → Edit*. Kopier tokenen med ein gong – han blir berre vist éin gong. |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare-dashbordet → **Workers & Pages** → høgre sida (Account ID), eller kommandoen `npx wrangler whoami`. |

`GITHUB_TOKEN` treng du ikkje leggje inn; han finst i workflowen automatisk.

---

## 6. Set opp Cloudflare Access (DETTE ER LASEN)

1. Cloudflare-dashbordet → **Zero Trust** → **Access** → **Applications**
   → **Add an application** → **Self-hosted**.
2. **Application domain:** legg inn Pages-domenet, t.d.
   `jetlogg-704.pages.dev`, og (om du har) eit eige domene i tillegg.
   Legg gjerne inn begge som to «public hostnames» i same app.
3. **Policy:** lag ein policy av typen **Allow** med **Include → Emails**,
   og list opp **berre** dei e-postadressene som skal ha tilgang.
   (Ikkje bruk «Everyone», og ikkje bruk eit domene som slepp inn fleire enn
   du meiner.)
4. Set **session duration** til det du vil (t.d. 24 timar).
5. Lagre.

Korleis det opplevest for operatoren: første gong nokon opnar adressa, blir
dei stoppa av Cloudflare og beden om e-postadressa si. Dei far ein
**eingongskode pa e-post**, skriv han inn, og kjem først *da* vidare til
sida. Alt dette skjer **i Cloudflare sitt nett, før sida i det heile blir
sendt til nettlesaren** – og før passordfeltet pa framsida blir vist.

**Test med ein gong:** opne adressa i eit privat/inkognito-vindauge. Du skal
da bli beden om e-post og kode – ikkje fa framsida.

---

## 7. Passordfeltet pa framsida (berre grensesnitt)

Framssida (`index.html`) har eit passordfelt. Det er ein ekstra sperre
operatoren bad om, og det er **ikkje** eit vern: alt innhaldet er statiske
filer, sa bade sida og dataa blir sendt til nettlesaren, og passordet kan
ikkje gøymast.

Koden lagrar difor ikkje passordet i klartekst, men **SHA-256-summen** av det
(i `index.html`, variabelen `PASSORD_SHA256`). Feltet samanliknar summar.

**Byte passord:** rekn ut summen av det nye passordet og byt ut verdien:

```bash
python -c "import hashlib;print(hashlib.sha256('NYTT_PASSORD'.encode('utf-8')).hexdigest())"
```

Summen verkar berre over `https://` eller pa `localhost` (nettlesaren krev
ein «secure context» for a rekne SHA-256 i det heile). Cloudflare Pages
køyrer pa https, sa det er greitt; opnar du `index.html` som lokal fil
(`file://`), vil feltet seie fra om at det ikkje far rekne summen.

---

## 8. Leggje til nye hendelser seinare

1. Legg den nye hendelses-JSON-fila i `data/`
   (namn som `<dato>_<pel>_<metode>.json`).
2. Oppdater `data/index.json` slik at ho far med den nye fila.
   Fila har forma:

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

   Felta nedtrekksmenyen brukar er `fil`, `dato`, `pel`, `metode`,
   `lengde_cm` og `stopp`. Nye hendelser blir oftast skrivne ut av
   `eksporter_hendelser.py` – køyr den, sa blir `index.json` oppdatert.
   Den same generatoren skriv ogsa **JS-tvillingane** (`index.js` og eit
   `<navn>.js` per hendelse) i same slengen, sa dei ikkje kan kome i utakt.
3. Commit og push. Er Pages kopla til repoet (4a) eller workflowen køyrer
   (4b), er dei nye filene ute i lopet av eit minutt.

Vil du raskt leggje ut éi fil utan a pushe, kan du bruke **Direct Upload** i
Cloudflare-dashbordet eller `npx wrangler pages deploy . --project-name=jetlogg-704`.

---

## 9. Slik verkar viseren

- **Nedtrekk** bygd fra `data/index.json`, med lesbar tekst per rad:
  `2026-10-01 · K83 · grouting · 143,2 cm · 4 pausar`.
- **Sokefelt** som filtrerer lista pa pel, metode og dato – utan a bry seg om
  store/sma bokstavar, og utan at du treng skrive `K` foran peltalet (`83`
  finn ogsa `K83`). Det star kor mange treff det er, og seier klart fra nar
  ingenting passar. Er det berre eitt treff, blir hendelsen vist med ein gong.
- **Klippet / Fullt** – byte vising utan a laste sida pa nytt:
  - *Klippet* (standard): pausane og uryddig-fasane er tekne ut av x-aksen.
    Farga bruddmerke og stopplinjer (P1–P4 i si eiga farge, gratt `‖` for
    uryddig), ein komprimert tidsakse, og ei fargestripe nedst som viser
    kva fasar som tel med i lengd og snittfart.
  - *Fullt*: heile hendelsen pa ein ubroten tidsakse. Kvar pause blir vist
    som eit **gjennomsiktig fargaband over heile plottet – eitt band per
    pause**, i same farge som pausen har i den klipte visinga og i fotnoten.
    Uryddig-fasane blir viste som gra band.
- **Rektangelzoom:** dra eit rektangel i plottet for a zoome til omradet.
  Dobbeltklikk nullstiller, og knappen **Nullstill zoom** gjer det same.
  Rulling zoomer.
- **Skriv ut / lagre bilete:** knappen under «Anna» renderar den figuren som
  star pa skjermen – same vising (Klippet/Fullt) og same levande zoom – til
  eit PNG, og opnar eit nytt vindauge med biletet, samandraget og fotnotane
  klare for utskrift. Der ligg ogsa ein **Last ned PNG**-knapp for ei rein
  bildeutskrift. Modebar-kameraet i plottet lagar biletet direkte, med
  filnamnet til hendelsen.
- **Fartstal:** fart-kurven er teken bort. Att star **stigningstala** som
  **berre tal** (`7,8`, ikkje `7,8 cm/min`) overst i plottet – eitt tal per
  seksjon som tel med, fordelt langs x-aksen. Eininga er forklart i
  fotnoten. I samandraget overst star eininga framleis, sidan det er ein
  tekstlesnad og ikkje ei merking i plottet.
- **Fotnote:** éi rad per pause i pausen sin eigen farge, med nummer,
  varighet, klokke og djupne ved stopp, klokke og djupne ved start, lengd,
  endring i djupne med forteikn, og grunn. Under ein fasetabell som viser
  kva fasar som tel med i lengd og snittfart.
- **Tala** er skrivne med norsk talformat (komma som desimalteikn).
- Firmalogoen ligg som eit svakt vassmerke bak kurvene.

Vil du opne ei hendelse direkte, kan du bruke
`viser.html?fil=2026-10-01_K83_grouting.json&vis=fullt`
(`fil` vel hendelse, `vis` vel `klippet` eller `fullt`).
Da ma sida køyrast fra ein tenar, fra Cloudflare eller som lokal fil med
JS-tvillingane ved sida (ho verkar ogsa pa `file://`).

---

## 10. Køyre sida lokalt

```bash
cd nettsted
python -m http.server 8788
```

Opne <http://localhost:8788/>. Da verkar nedtrekksmenyen, soket og
`?fil=`-parameteren, og alle JSON-filene blir lesne direkte.

Sida verkar og nar ho blir opna **direkte fra disken** (`file://`). Da
blokkerer nettlesaren `fetch`, men `data/index.js` og `data/<navn>.js` er
lasta som vanlege skript, sa nedtrekket blir fylt og hendelsene blir viste
fra dei innebygde tvillingane. Det kjem da eit lite hint om dette over
plottet. Denne vegen er ein **reserve** – den vanlege vegen er tenar eller
Cloudflare, der JSON-filene blir lesne direkte.

---

## 11. Sjekkliste før du slepp nokon inn

- [ ] Repoet er **privat**.
- [ ] Cloudflare Access-appen dekkjer domenet (`*.pages.dev`, og eige
      domene om du har).
- [ ] Policyen seier **Allow** og listar **berre** dei rette e-postane.
- [ ] Testa i inkognito-vindauge: e-post + eingongskode kjem **før** sida.
- [ ] Eventuelt: byte passordet pa framsida (steg 7).

Utan dei tre første punkta er sida heilt open for kven som helst med lenka.
