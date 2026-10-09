"""Regenererer Acron-plottet: alle kanaler i ETT plott med delt Y-akse, pluss
et underplott med klammer som viser stigningstallet (cm/min) per fase.

Skriptet er laget for aa virke paa ETHVERT datasett i samme format:

* tabseparert grafeksport med desimalkomma og dato i forste kolonne
  (`testrapport_*.txt`), eller
* dagseksport fra Acron (`Plant1_Pro_YYYYMMDD.csv`): semikolonseparert,
  `Date;Time;Millisecond;DaylightSavingTime` forst, og deretter to kolonner
  per kanal - `Kanal_pval` med verdien og `Kanal_type` med kvaliteten, der
  noe annet enn 'A' (ALOSS) betyr tapt maaling og blir hull i kurven.
  En slik fil inneholder hele skiftet - flere peler etter hverandre.

Dybdekolonnen kalles 'Dybde_rapp' (eller Dybderapp/Dybde/Depth). Den lagres
alltid med positivt tall nedover, uansett hva eksporten gjorde.

Standard er de fem kanalene Acron selv viser (grouttrykk, lufttrykk,
rotasjonshastighet, groutflow, luftflow). Har filen ingen av dem, blir alle
brukbare kanaler med. Dode sensorer (konstant verdi), 0/1-flagg og
administrasjonskolonner holdes alltid utenfor. Vil du ha flere:

    --kanaler grouttrykk,opptrekkshastighet,nedforingshastighet
    --alle-kanaler

Y-AKSENE ER FASTE, SLIK RIGGEN ARBEIDER:

    lufttrykk 0-7 bar    grouttrykk 0-400 bar    rotasjon 0-30 o/min
    groutflow 0-400 l/min    luftflow 0-3000 l/min

Faste grenser er med vilje: da blir aksene like i hver rapport, og plott fra
ulike peler og skift kan legges ved siden av hverandre og sammenlignes. En
lufttrykk-kanal som ligger jevnt paa 2 bar og vandrer +/- 0,1 blir dessuten
en rolig linje paa en 0-7-akse, i stedet for aa fylle arket og se ut som en
feil.

Kanaler vi ikke kjenner (andre sensorer i samme filformat) faar grenser
regnet fra dataene, slik at de ogsaa havner paa en fornuftig hoeyde.

Vil du overstyre: ``--akse grouttrykk=500``, ``--smarte-akser`` for aa regne
alle grensene fra filen, eller ``--auto-akser`` for aa la matplotlib skala
helt fritt.

STOPP (PAUSER) OG URYDDIG KLIPPES UT AV X-AKSEN
En lang pause gjoer grafen uleselig. HOVEDKRITERIET for en pause er
DYBDE-SPENNET: staar dybden innenfor +/-``--stopp-spenn-cm`` (standard 2,0,
altsaa 4 cm spenn) i minst ``--stopp-min-s`` sekunder (standard 600 = 10 min),
er det en pause. Den blir tatt UT av x-aksen - proven er der fortsatt, men
ikke tegnet - og merket med det vanlige bruddmerket (to skraa streker over
aksen). En pause er en trapp av encodersprang paa 0,1 cm, saa farten er et
daarlig maal; derfor ser regelen paa hvor dybden ER, ikke hvor fort den
flytter seg. En LANG SOM stigning har et stort spenn og blir derfor ikke
klippet - den faar cm/min-tallet sitt i klammen.

De andre kriteriene er fortsatt tilgjengelige og kombineres med
``--stopp-kombi`` ('eller'/'og') naar flere er i bruk:

    --stopp-med-fart            |cm/min| under --stopp-cm-min (av som standard)
    --stopp-kanal/--stopp-verdi navngitt kanal under/over en grense

Hver stopp faar sin egen farge (gronn = stopp 1, rod = stopp 2, gul = stopp
3, ...) og en fotnote med klokke og dybde ved stopp og restart, lengde og
delta dybde. Stoppene NUMMERERES FRA DYPEST TIL GRUNNEST - stopp 1 er den
dypeste. Bruk ``--vis-uryddig`` for aa beholde de uryddige fasene i plottet.

Bare numpy/pandas/matplotlib - kan kjoeres paa industripc-en.

Ett skift er ÉN fil med flere peler; `--pel N` tar den N-te, og listen over
peler skrives ut naar du kjoerer. For hver pel skrives plottet baade som PNG
og som interaktiv HTML (zoom, av/paa og egen skala per akse, utskrift til A4
liggende).

    python tools\\regenerer_acron_plott.py demo\\testrapport_3.txt
"""

from __future__ import annotations

import argparse
import base64
import io
import math
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Kanaler vi kjenner igjen fra Acron-eksporten: nokkel -> (etikett, farge).
KJENTE: dict[str, tuple[str, str]] = {
    "grouttrykk": ("Grouttrykk [Bar]", "#8b0000"),
    "lufttrykk": ("Lufttrykk [Bar]", "#1f77b4"),
    "rotasjonshastighet": ("Rotasjonshastighet [o/min]", "#2ca02c"),
    "groutflow": ("Groutflow [l/min]", "#ff7f0e"),
    "luftflow": ("Luftflow [l/min]", "#9467bd"),
}
# Faste aksegrenser per kanal - STANDARDEN. Lik skala i hver rapport, slik at
# plott fra ulike peler og skift kan sammenlignes direkte.
FASTE_GRENSER: dict[str, tuple[float, float]] = {
    "grouttrykk": (0.0, 400.0),
    "lufttrykk": (0.0, 7.0),
    "rotasjonshastighet": (0.0, 30.0),
    "groutflow": (0.0, 400.0),
    "luftflow": (0.0, 3000.0),
}
# Rekkefolgen kjente kanaler tegnes i (bestemmer hoyreaksenes rekkefolge).
KANALREKKEFOLGE = ["grouttrykk", "lufttrykk", "rotasjonshastighet",
                   "groutflow", "luftflow"]
# Farger til ukjente kanaler.
PALETT = ["#17becf", "#bcbd22", "#e377c2", "#7f7f7f", "#8c564b", "#aec7e8",
          "#ffbb78", "#98df8a"]

FARGE_DYBDE = "#a052ad"
# Rekkefolgen vi leter etter dybdekolonnen i. 'Dybde_rapp' foretrekkes: det er
# den rapporterte dybden (filtrert, én desimal), mens raa 'Dybde' er ufiltrert
# telling i hele centimeter.
DYDDE_RAKKEFOLGE = ["dybde_rapp", "dybderapp", "dybdemaaling", "dybde", "depth"]
DYDDE_NAVN = set(DYDDE_RAKKEFOLGE)
# Pelnummeret og metoden staar som tekst i dagseksporten. Det er de ekte
# grensene i loggen - riggen skriver selv hvilken pel den staar i og hva den
# gjor, i stedet for at vi gjetter det fra flowen.
PEL_KOLONNE = "pel_nr"
MODUS_KOLONNE = "opp_ned"
# Operatørens eget start/stopp-flagg: 1 saa lenge prosessen gaar. Det er
# sannheten om naar arbeidet begynte og sluttet - se ``start_stopp_vinduer``.
STARTSTOPP_KOLONNE = "start_stopp_logg"
MODUS_NAVN: dict[str, str] = {
    "PILOTDRILL": "pilotboring",
    "PREJETTING": "prejet",
    "GROUTING": "grouting",
}
# Anleggsdata som hoerer i overskriften: (kolonnenavn, etikett).
OKT_OVERSKRIFT: list[tuple[str, str]] = [("anlegg", "anlegg"),
                                         ("prosj_nr", "prosjekt"),
                                         ("oppdragsgiver", "oppdragsgiver")]
# Hvilken kanal som best viser at arbeidet gaar, per metode. Rekkefolgen er et
# forslag: den forste kandidaten som har noe over terskelen blir brukt. Under
# en pilotboring staar grouttrykket paa null hele tiden - der er det lufta og
# rotasjonen som viser at det bores.
KUTT_PER_MODUS: dict[str, tuple[str, ...]] = {
    "PILOTDRILL": ("luftflow", "rotasjonshastighet", "lufttrykk",
                   "nedforingshastighet"),
    "PREJETTING": ("grouttrykk", "luftflow", "groutflow"),
    "GROUTING": ("grouttrykk", "groutflow", "luftflow"),
}
# Kanaler som viser at riggen arbeider, hver med sin egen terskel. Til sammen
# avgjor de produksjonsomraadet for en hel pel: det er nok at én av dem gaar.
# Under en pilotboring staar grouttrykket paa null hele tiden, og naar det
# groutes staar lufta av - derfor maa alle vaere med.
# Merk: ingen enkeltkanal sier at riggen arbeider. G19 den 23.09.2026 borer
# uten baade luft og rotasjon (bare nedforing), G21 og K80 jetter med trykk og
# luft, og K27 spinner i 30 minutter uten at stanga beveger seg. Derfor blir
# produksjonsomraadet regnet ut oekt for oekt, med metodens egen kanal.
# Enheter for kanaler der overskriften ikke har dem. Acrons dagseksport
# navngir kanalene 'Grouttrykk_pval' uten enhet, mens den gamle graf-
# eksporten skrev 'Grouttrykk [Bar]'.
ENHETER: dict[str, str] = {
    "grouttrykk": "Bar", "lufttrykk": "Bar", "vanntrykk": "Bar",
    "oljetrykk_nedforing": "Bar", "oljetrykk_opptrekk": "Bar",
    "oljetrykk_rotasjon": "Bar",
    "groutflow": "l/min", "luftflow": "l/min", "vannflow": "l/min",
    "rotasjonshastighet": "o/min", "sp_rot_hast": "o/min",
    "nedforingshastighet": "cm/min", "opptrekkshastighet": "cm/min",
    "sp_opptr_hast": "cm/min",
    "dybde": "cm", "dybde_rapp": "cm", "pel_lengde": "cm",
    "loddvinkel": "grader", "vinkelm_f_b": "grader", "vinkelm_s_v": "grader",
    "grouttemp": "C", "vanntemp": "C",
    "densitet": "kg/l", "head_densitet": "kg/l",
}
# Administrative kolonner i dagseksporten - de er 0/1-flagg og hoeres ikke
# hjemme som kurve. Bruk --kanaler for aa ta dem med.
ADMIN: set[str] = {"lagre_batch_data", "start_stopp_logg", "rapp_id",
                   "pel_nr"}
# En logg kan romme flere skift - eller en hel maaned. To ting maa da brytes:
# en oekt som staar stille i loggen (riggen er slutt for dagen), og en pel som
# kommer tilbake lenge etterpaa (nytt skift, ny dag). Uten dette blir 'hele
# produksjonsomraadet' atten timer langt og delplottet viser feil vindu.
LOGG_HULL_S = 900.0            # stillstand i loggen = skiftet er over
SKIFT_HULL_TIMER = 6.0         # samme pel tilbake etter dette = ny oekt
AVSTAND_AKSE = 45.0            # piksler mellom hver hoyreakse
TRINN_NEDRE, TRINN_OVRE = 0.35, 0.92   # hvor lavt/hoyt typenivaaet skal ligge

# -- stopp: naar grafen klippes og merkes -----------------------------------
# Stoppene NUMMERERES FRA DYPEST TIL GRUNNEST (ikke kronologisk): stopp 1 er
# den dypeste. Fargen foelger nummeret. De tre foerste er operatorens valg
# (gronn, rod, gul); deretter en videre syklus som er lett aa skille fra
# kanalfargene: blaa, magenta, cyan.
STOPP_FARGER = ["#2ca02c", "#d62728", "#e6b800",
                "#1f77b4", "#e377c2", "#17becf"]
# Kanalgrensen kan virke begge veier: 'under' (grouttrykk < 50 bar) eller
# 'over'. Operatoren beskrev 'under'.
STOPP_RETNINGER = ("under", "over")
# Hvordan de to kriteriene settes sammen naar BEGGE er oppgitt:
#   'eller' - stille naar bevegelsen er under grensen ELLER kanalen slaar ut
#             (standard: operatoren vil at et trykkfall ER en stopp)
#   'og'    - stille bare naar begge holder samtidig (strengere)
STOPP_KOMBIER = ("eller", "og")


# -- firmalogo: svakt vannmerke bak kurvene ---------------------------------
# Logoen ligger i mappa 'Seabrokers Dolomiti' (SVG til nettviserne, PNG til
# PNG-plottet). Den tegnes dempet og bak dataene, saa den ikke stjeler
# oppmerksomheten fra kurvene. Mangler logoen, tegnes plottet som for.
FIRMA_LOGO_OPACITY = 0.08


def _logo_sti(undermappe: str) -> Path | None:
    """Finner en logofil under mappa 'Seabrokers Dolomiti'.

    Soeker oppover fra scriptmappa og praver baade mappa selv og
    'rigg_kontor/Seabrokers Dolomiti', slik at baade tools/ og rigg_kontor/
    finner den samme logoen.
    """
    her = Path(__file__).resolve().parent
    deler = ("Seabrokers Dolomiti", "rigg_kontor/Seabrokers Dolomiti")
    for base in (her, *her.parents):
        for del_ in deler:
            kandidat = base / Path(del_) / undermappe
            if kandidat.is_file():
                return kandidat
    return None


def logo_datauri(mime: str = "image/svg+xml") -> str | None:
    """Logoen som data-URI (base64), for innbygging i HTML-en."""
    sti = _logo_sti("SVG/Seabrokers_Dolomiti_RGB.svg")
    if sti is None:
        return None
    return f"data:{mime};base64," + base64.b64encode(
        sti.read_bytes()).decode("ascii")


def _tegn_logo_akse(akse: Any) -> None:
    """Legger firmalogoen som et svakt, gjennomsiktig vannmerke i aksen.

    Den hvite bakgrunnen i PNG-en blir gjennomsiktig, slik at bare selve
    merket synes. Feiler noe, tegnes plottet videre uten logo.
    """
    sti = _logo_sti("PNG/Seabrokers_Dolomiti_RGB.png")
    if sti is None:
        return
    try:
        img = np.asarray(plt.imread(str(sti)), dtype=float)
    except Exception:                                    # pragma: no cover
        return
    if img.ndim == 2:
        img = np.dstack([img, img, img])
    if img.shape[2] == 4:
        alfa = img[:, :, 3:4]
        img = img[:, :, :3] * alfa + (1.0 - alfa)
    hvit = np.all(img[:, :, :3] > 0.96, axis=2)
    # Dybdeaksen er invertert, saa bildet maa speiles loddrett for aa staa rett.
    rgba = np.flipud(np.dstack([img[:, :, :3], np.where(hvit, 0.0, 1.0)]))
    x0, x1 = akse.get_xlim()
    y0, y1 = akse.get_ylim()
    midx, midy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    bx, by = 0.42 * abs(x1 - x0), 0.30 * abs(y1 - y0)
    akse.imshow(rgba,
                extent=(midx - bx / 2, midx + bx / 2,
                        midy - by / 2, midy + by / 2),
                aspect="auto", alpha=FIRMA_LOGO_OPACITY, zorder=0,
                interpolation="bilinear")
    akse.set_xlim(x0, x1)
    akse.set_ylim(y0, y1)


# ---------------------------------------------------------------------------
# Innlesing
# ---------------------------------------------------------------------------


def _normaliser(navn: str) -> str:
    tekst = str(navn).strip().lower()
    if "[" in tekst:
        tekst = tekst.split("[", 1)[0]
    tekst = (tekst.replace("\u00e6", "ae").replace("\u00f8", "o")
             .replace("\u00e5", "a"))
    ren = "".join(t if t.isalnum() else "_" for t in tekst)
    return "_".join(del_ for del_ in ren.split("_") if del_)


def les_logg(filbane: str | Path) -> pd.DataFrame:
    """Leser eksporten. Gir 'Tid', 'dybde' og én kolonne per kanal.

    I ``df.attrs['etiketter']`` legges den opprinnelige kolonneoverskriften
    (med enhet), slik at ukjente kanaler faar riktig navn paa aksen.
    """
    sti = Path(filbane)
    if not sti.exists():
        raise FileNotFoundError(f"Finner ikke filen: {sti}")

    raa = sti.read_bytes()
    tekst = None
    for kode in ("cp1252", "utf-8-sig", "utf-8", "latin-1"):
        try:
            tekst = raa.decode(kode)
            break
        except UnicodeDecodeError:
            continue
    if tekst is None:                                          # pragma: no cover
        tekst = raa.decode("latin-1", errors="replace")
    del raa                      # 274 MB for en maaned - ikke hold to kopier

    forste = next((ln for ln in tekst.splitlines() if ln.strip()), "")
    skilletegn = "\t" if "\t" in forste else (";" if ";" in forste else ",")
    desimal = "." if skilletegn == "," else ","

    # Komma er desimaltegn i hele denne eksporten. Bytter vi dem til punktum
    # for hele teksten paa én gang, kan pandas lese tallene selv - i C, og uten
    # aa lage en tekststreng per tall. 'decimal=,' tvinger pandas over i
    # Python-motoren, som bruker flere ganger saa lang tid.
    # (Kolonneoverskriftene har aldri komma - enhetene staar i klammer.)
    if skilletegn == ",":                     # komma skiller - da er det punktum
        df = pd.read_csv(io.StringIO(tekst), sep=skilletegn, decimal=desimal,
                         engine="python", skip_blank_lines=True)
    else:
        tekst = tekst.replace(",", ".")       # den gamle teksten frigis
        hode = next((ln for ln in tekst.splitlines() if ln.strip()), "")
        navn = [k.strip() for k in hode.split(skilletegn)]
        typer: dict[str, Any] = {}
        if any(k.endswith("_pval") for k in navn):
            # Dagseksporten har to kolonner per kanal. '_type' inneholder 'A'
            # eller 'ALOSS' - én tekststreng per kanal per prove. Som 'category'
            # koster de noen byte i stedet for hundre, og pelnummer og metode
            # blir liggende som tekst. Uten dette ble en maaned i én fil 3,0 GB
            # i minnet.
            typer = {k: "category" for k in navn
                     if k != "Millisecond" and not k.endswith("_pval")}
        if typer:
            df = pd.read_csv(io.StringIO(tekst), sep=skilletegn, engine="c",
                             skip_blank_lines=True, low_memory=False,
                             dtype=typer)          # type: ignore[arg-type]
        else:
            df = pd.read_csv(io.StringIO(tekst), sep=skilletegn, engine="c",
                             skip_blank_lines=True)
    df.columns = [str(k).strip() for k in df.columns]

    # -- hvilke kolonner hoerer sammen? ------------------------------------
    # Dagseksporten har to kolonner per kanal: 'Grouttrykk_pval' med verdien
    # og 'Grouttrykk_type' med kvaliteten ('A' = ok, 'ALOSS' = tapt maaling).
    # Den gamle graf-eksporten har én kolonne per kanal, med enhet i navnet.
    verdikol: dict[str, str] = {}
    typekol: dict[str, str] = {}
    for kolonne in df.columns:
        if kolonne.endswith("_pval"):
            verdikol[kolonne[:-5]] = kolonne
        elif kolonne.endswith("_type"):
            typekol[kolonne[:-5]] = kolonne

    tid_kolonne = df.columns[0]
    tider = None
    if "Date" in df.columns and "Time" in df.columns and verdikol:
        tekst = (df["Date"].astype(str).str.strip() + " "
                 + df["Time"].astype(str).str.strip())
        tider = pd.to_datetime(tekst, format="%d.%m.%Y %H:%M:%S",
                               errors="coerce")
        if "Millisecond" in df.columns:
            ms = pd.to_numeric(df["Millisecond"], errors="coerce").fillna(0.0)
            if float(ms.max()) > 0.0:
                tider = tider + pd.to_timedelta(ms, unit="ms")
    if tider is None or tider.isna().all():
        tider = pd.to_datetime(df[tid_kolonne], format="%d.%m.%Y %H:%M:%S",
                               errors="coerce")
        if tider.isna().all():
            tider = pd.to_datetime(df[tid_kolonne], errors="coerce",
                                   dayfirst=True)
    df["Tid"] = tider
    # Bare naar noe faktisk maa bort - en ekstra kopi av hele rammen koster
    # hundrevis av megabyte naar filen er stor.
    if not bool(df["Tid"].notna().all()):
        df = df.loc[df["Tid"].notna()].reset_index(drop=True)

    etiketter: dict[str, str] = {}
    kolonner: dict[str, pd.Series] = {}
    if verdikol:
        kilder = [(basis, verdikol[basis]) for basis in verdikol]
    else:
        kilder = [(k, k) for k in df.columns
                  if k not in (tid_kolonne, "Tid", "Date", "Time",
                               "Millisecond", "DaylightSavingTime")]

    for basis, kolonne in kilder:
        serie = df[kolonne]
        if pd.api.types.is_numeric_dtype(serie):
            # Allerede tall fra lesingen - ingen grunn til aa gaa via tekst.
            # (Er typen flyttall, brukes kolonnen som den er - astype(float)
            # kopierer, og det er 8 MB per kanal naar filen er en maaned.)
            verdier = serie if serie.dtype.kind == "f" else serie.astype(float)
        else:
            verdier = pd.to_numeric(
                serie.astype(str).str.replace(" ", "").str.replace(",", "."),
                errors="coerce")
        if verdier.notna().sum() < 2:          # tekstkolonne eller tom
            continue
        # ALOSS betyr at maalingen er tapt. Da skal det staa tomt - ikke null,
        # som ville sett ut som en ekte maaling av null.
        if basis in typekol:
            svak = (df[typekol[basis]].astype(str).str.strip().str.upper()
                    != "A")
            verdier = verdier.where(~svak)
        navn = _normaliser(basis) or basis
        if navn in kolonner:                   # to kolonner normaliserer likt
            navn = f"{navn}_2"
        # -1,0 = "ingen maaling" i den gamle eksporten. Ekte null (pumpen
        # er av) skal staa som null.
        rene = verdier.dropna()
        if (not rene.empty and float(rene.median()) >= 0.0
                and bool((rene == -1.0).any())):
            verdier = verdier.where(verdier != -1.0)
        kolonner[navn] = verdier
        if "[" in basis:                       # enheten staar i overskriften
            etiketter[navn] = basis
        else:
            enhet = ENHETER.get(navn, "")
            etiketter[navn] = f"{basis} [{enhet}]" if enhet else basis

    # Bare de normaliserte kolonnene blir med videre - de raa overskriftene
    # ("Grouttrykk [Bar]") skal ikke bli en ekstra kanal.
    ren = pd.DataFrame({"Tid": df["Tid"].to_numpy()})
    for navn, serie in kolonner.items():
        ren[navn] = serie.to_numpy()

    # Tekstkolonner (pelnummer, metode, anlegg ...) er ikke kurver, men de
    # hoerer i overskriften. De blir med som tekstkolonner i rammen;
    # finn_kanaler hopper over dem fordi de ikke er tall.
    for basis, kolonne in kilder:
        navn = _normaliser(basis) or basis
        if navn in ren.columns:
            continue
        tekst = df[kolonne].astype(str).str.strip()
        tekst = tekst.where(~tekst.isin(["", "nan", "NaN", "None"]))
        if int(tekst.notna().sum()) == 0:
            continue
        ren[navn] = tekst.to_numpy()

    dybde_navn = next((n for n in DYDDE_RAKKEFOLGE if n in kolonner), None)
    if dybde_navn is None:
        raise ValueError(
            "Fant ingen dybdekolonne (forventet 'Dybde_rapp [cm]'). "
            f"Kolonner: {list(kolonner)}")
    ren["dybde"] = ren[dybde_navn]
    # Dybden lagres alltid med positivt tall nedover, uansett hva eksporten
    # gjorde: Acron skriver 'Dybde_rapp' negativ (mot en referansekote) og raa
    # 'Dybde' positiv. Resten av skriptet slipper da aa tenke paa fortegn.
    maalt = ren["dybde"].dropna()
    if not maalt.empty and float(maalt.median()) < 0.0:
        ren["dybde"] = -ren["dybde"]
    ren.attrs["etiketter"] = etiketter
    return ren


def finn_kanaler(df: pd.DataFrame, valg: Sequence[str] | None = None,
                 alle: bool = False) -> list[tuple[str, str, str]]:
    """Kanalene som skal ha egen hoyreakse: (nokkel, etikett, farge).

    Uten ``valg`` blir de fem Acron-kanalene med; har filen ingen av dem (et
    annet anlegg, en annen sensorpakke) blir alle brukbare kanaler med.

    En kanal blir bare med hvis den faktisk er en kurve. Konstant verdi
    (sensoren finnes ikke paa denne riggen - 16 av 45 kanaler i dagseksporten
    ligger slik), rene 0/1-flagg og administrasjonskolonner gaar ut: de gjor
    bare hoyreaksene uleselige. Bruk ``--kanaler`` for aa tvinge dem med.
    """
    etiketter = df.attrs.get("etiketter", {})
    hopp_over = {"Tid", "dybde"} | DYDDE_NAVN      # dybden har venstreaksen
    kanaler: list[tuple[str, str, str]] = []
    brukt: set[str] = set()

    def legg_til(navn: str, farge: str | None) -> None:
        etikett = etiketter.get(navn, navn)
        if navn in KJENTE:
            etikett = KJENTE[navn][0]
            farge = KJENTE[navn][1]
        elif farge is None:
            farge = PALETT[len(kanaler) % len(PALETT)]
        kanaler.append((navn, etikett, farge))
        brukt.add(navn)

    def brukbar(navn: str) -> bool:
        if navn in hopp_over or navn.startswith("_") or navn in brukt:
            return False
        if valg is not None:
            if navn not in valg:
                return False
        elif navn in ADMIN:                       # flagg, ikke kurve
            return False
        if not pd.api.types.is_numeric_dtype(df[navn]):
            return False
        serie = df[navn].dropna()
        if serie.size < 2 or serie.nunique() < 2:
            return False
        if bool(serie.isin([0.0, 1.0]).all()):    # rent 0/1-flagg
            return False
        return True

    if valg is not None:
        rekkefolge = [n for n in valg]
    elif alle:
        rekkefolge = ([n for n in KANALREKKEFOLGE if n in df.columns]
                      + [n for n in df.columns if n not in KANALREKKEFOLGE])
    else:
        kjente = [n for n in KANALREKKEFOLGE if n in df.columns]
        rekkefolge = (kjente if kjente
                      else [n for n in df.columns if n not in KANALREKKEFOLGE])

    for navn in rekkefolge:
        if brukbar(navn):
            legg_til(navn, None)
    return kanaler


def kuttkandidater(df: pd.DataFrame, modus: str | None = None) -> list[str]:
    """Kanalene som kan beskrive naar arbeidet gaar og naar det er slutt.

    Prioritert rekkefolge: grouttrykk forst (200-300 bar under jetting, under
    5 bar naar riggen spyler gjennom eller flytter seg), saa flow. Metoden
    skyver sine egne signaler foran: under en pilotboring staar grouttrykket
    paa null hele tiden, og da beskriver lufta arbeidet.
    """
    forst = KUTT_PER_MODUS.get(str(modus or "").strip().upper(), ())
    kandidater = [navn for navn in forst if navn in df.columns]
    kandidater += [navn for navn in ("grouttrykk", "groutflow",
                                     "groutflow_l_min")
                   if navn in df.columns and navn not in kandidater]
    kandidater += [navn for navn in df.columns
                   if navn not in kandidater and navn not in ("Tid", "dybde")
                   and ("flow" in navn or "trykk" in navn)]
    return kandidater


def velg_kuttvindu(df: pd.DataFrame, *, terskel: float = 5.0,
                   tillatt_hull_s: float = 180.0,
                   min_lengde_s: float = 300.0, modus: str | None = None
                   ) -> tuple[str | None, int, int]:
    """Kanalen og vinduet som beskriver arbeidsperioden.

    Grouttrykket er den beste beskrivelsen naar det er noe der - flow alene
    har utblasninger paa 40-60 l/min baade for og etter pelen, og da blir
    starten av kuttet lagt ti minutter for tidlig, inne i rivingen av forrige
    pel.

    Men det finnes peler der trykket ikke sier noe: pel 1 den 23.09.2026 gaar
    med luft og rotasjon og har 0 bar grouttrykk hele tiden, og i pel 4 viser
    trykket bare et kort utslag. Derfor gaar vi gjennom kandidatene i
    prioritert rekkefolge og tar den forste som gir en sammenhengende periode
    paa minst ``min_lengde_s``. Finner vi ingen saa lang, tar vi den lengste.
    """
    beste: tuple[str, int, int, float] | None = None
    for navn in kuttkandidater(df, modus):
        try:
            i0, i1 = produksjonsvindu(df, terskel=terskel,
                                      tillatt_hull_s=tillatt_hull_s,
                                      kolonne=navn)
        except ValueError:
            continue
        varighet = float((df["Tid"].iloc[i1]
                          - df["Tid"].iloc[i0]).total_seconds())
        if varighet >= min_lengde_s:
            return navn, i0, i1
        if beste is None or varighet > beste[3]:
            beste = (navn, i0, i1, varighet)
    if beste is None:
        return None, 0, len(df) - 1
    return beste[0], beste[1], beste[2]


# ---------------------------------------------------------------------------
# Smarte aksegrenser
# ---------------------------------------------------------------------------


def _pent_opp(x: float) -> float:
    """Minste "pene" tall >= x (1, 2, 2.5, 4, 5, 10 * 10^n)."""
    if x <= 0:
        return 0.0
    e = math.floor(math.log10(x))
    f = x / 10.0 ** e
    for k in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        if f <= k:
            return k * 10.0 ** e
    return 10.0 ** (e + 1)


def _pent_ned(x: float) -> float:
    """Storste "pene" tall <= x (gaar andre veien for negative tall)."""
    if x == 0:
        return 0.0
    fortegn = -1.0 if x < 0 else 1.0
    e = math.floor(math.log10(abs(x)))
    f = abs(x) / 10.0 ** e
    for k in (10.0, 8.0, 6.0, 5.0, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0):
        if f >= k:
            return fortegn * k * 10.0 ** e
    return fortegn * 10.0 ** (e - 1)


def smarte_grenser(df: pd.DataFrame,
                   kanaler: Sequence[tuple[str, str, str]], *,
                   trinn_nedre: float = TRINN_NEDRE,
                   trinn_ovre: float = TRINN_OVRE
                   ) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """Regner ut Y-grenser per kanal ut fra dataene i denne filen.

    For hver kanal maales:

    * ``nivaa``  = p90 - det typiske driftsnivaaet
    * ``stoy``   = 1,48 * MAD - det robuste maalet paa normalsvingningen
      (median-basert, saa den blir ikke bladd opp av en lang periode der
      kanalen staar paa null)
    * ``min/max`` = ytterpunktene, som aksen ALLTID skal romme

    Kanalene sorteres stigende etter nivaa og faar hver sin hoeyde paa arket
    fra ``trinn_nedre`` til ``trinn_ovre``. Den kanalen som ligger lavest i
    verdi havner nederst. Ovregrensen blir den minste som baade setter
    typenivaaet paa kanalens hoeyde og rommer hele datasettet.

    Da skalerer arket seg selv: en kanal med mye sving faar stor akse (og
    dermed plass), en kanal som ligger jevnt paa 2 bar og vandrer +/- 0,1
    faar en akse der 0,1 er et par prosent av hoeyden - normalt uten aa se
    ut som en feil.
    """
    info: list[dict[str, float | str]] = []
    for nokkel, _, _ in kanaler:
        verdier = df[nokkel].to_numpy(dtype=float)
        verdier = verdier[np.isfinite(verdier)]
        if verdier.size < 2:
            continue
        nivaa = float(np.percentile(verdier, 90))
        mad = float(np.median(np.abs(verdier - np.median(verdier))))
        info.append({"navn": nokkel, "min": float(verdier.min()),
                     "max": float(verdier.max()), "nivaa": nivaa,
                     "stoy": 1.4826 * mad})
    if not info:
        return {}, []

    info.sort(key=lambda rad: float(rad["nivaa"]))
    antall = len(info)
    grenser: dict[str, tuple[float, float]] = {}
    forklaring: list[str] = []

    for i, rad in enumerate(info):
        navn = str(rad["navn"])
        nivaa = float(rad["nivaa"])
        minste, storste = float(rad["min"]), float(rad["max"])

        # Kanaler som arbeider ned mot null skal ha null i bunnen; ellers
        # starter aksen like under det laveste vi har maalt.
        spenn = max(storste - minste, abs(nivaa) * 1e-6, 1e-9)
        gulv = 0.0 if minste <= 0.15 * max(storste, 1e-9) else minste - 0.05 * spenn

        maal = (0.5 if antall == 1 else
                trinn_nedre + i * (trinn_ovre - trinn_nedre) / (antall - 1))
        if nivaa <= gulv:                     # kanalen ligger paa null
            hi = gulv + 2.0 * spenn
        else:
            hi = gulv + (nivaa - gulv) / maal
        hi = max(hi, storste)

        lo_pent, hi_pent = _pent_ned(gulv), _pent_opp(hi)
        if hi_pent <= lo_pent:                # rusten sikring
            hi_pent = _pent_opp(lo_pent + spenn)
        grenser[navn] = (lo_pent, hi_pent)
        forklaring.append(
            f"{navn} {lo_pent:g}-{hi_pent:g}  (nivaa {nivaa:g}, "
            f"stoy +-{float(rad['stoy']):g}, maalt {minste:g}..{storste:g})")
    return grenser, forklaring


# ---------------------------------------------------------------------------
# Kutt ved produksjonsslutt
# ---------------------------------------------------------------------------


def produksjonsvindu(df: pd.DataFrame, terskel: float = 5.0,
                     tillatt_hull_s: float = 180.0,
                     kolonne: str | None = None) -> tuple[int, int]:
    """Forste og siste prove i den lengste sammenhengende produksjonsperioden.

    Denne loggen har et kort flow-utbrudd lenge etter at pelen var ferdig. En
    regel som "siste prove over terskelen" ville derfor trukket med alt
    riggflyttingen. Vi velger den perioden som varer lengst sammenhengende,
    med toleranse for korte avbrudd, og uten noe fast klokkeslett.
    """
    kolonne = kolonne or next(iter(kuttkandidater(df)), None)
    if kolonne is None or kolonne not in df.columns:
        raise ValueError("Fant ingen flow-/trykk-kolonne aa styre kuttet etter")

    aktiv = (df[kolonne] > terskel).to_numpy()
    t = df["Tid"]
    grense = pd.Timedelta(seconds=tillatt_hull_s)

    grupper: list[tuple[int, int]] = []
    n = len(df)
    i = 0
    while i < n:
        if not aktiv[i]:
            i += 1
            continue
        start = i
        slutt = i
        j = i
        while j < n:
            if aktiv[j]:
                slutt = j
                j += 1
                continue
            k = j
            while k < n and not aktiv[k]:
                k += 1
            if k < n and (t.iloc[k] - t.iloc[slutt]) <= grense:
                j = k
                continue
            break
        grupper.append((start, slutt))
        i = max(slutt + 1, j + 1)

    if not grupper:
        raise ValueError(f"Ingen prover med {kolonne} > {terskel}")
    return max(grupper, key=lambda g: t.iloc[g[1]] - t.iloc[g[0]])


# ---------------------------------------------------------------------------
# Segmentering
# ---------------------------------------------------------------------------


class _Prefiks:
    """Prefikssummer - minstekvadraters tilpasning blir O(1)."""

    def __init__(self, t: np.ndarray, y: np.ndarray) -> None:
        self.S1 = np.concatenate(([0.0], np.cumsum(t)))
        self.S2 = np.concatenate(([0.0], np.cumsum(t * t)))
        self.Sy = np.concatenate(([0.0], np.cumsum(y)))
        self.Syy = np.concatenate(([0.0], np.cumsum(y * y)))
        self.Sty = np.concatenate(([0.0], np.cumsum(t * y)))

    def sse(self, i0: int, i1: int) -> float:
        k = i1 - i0
        if k < 2:
            return 0.0
        s1 = self.S1[i1] - self.S1[i0]
        s2 = self.S2[i1] - self.S2[i0]
        sy = self.Sy[i1] - self.Sy[i0]
        syy = self.Syy[i1] - self.Syy[i0]
        sty = self.Sty[i1] - self.Sty[i0]
        nevner = k * s2 - s1 * s1
        if nevner <= 0:
            return float(max(0.0, syy - sy * sy / k))
        a = (k * sty - s1 * sy) / nevner
        b = (sy - a * s1) / k
        return float(max(0.0, syy - a * sty - b * sy))

    def rest_std(self, i0: int, i1: int) -> float:
        k = i1 - i0
        if k < 2:
            return 0.0
        return float((self.sse(i0, i1) / k) ** 0.5)

    def stigning(self, i0: int, i1: int) -> float:
        """Stigningstallet for [i0, i1) - ogsaa det i O(1).

        Brukes naar vi leter etter knekker. En egen tilpasning for hvert
        kandidatpunkt gjorde segmenteringen over 30 ganger tregere enn den
        trenger aa vaere.
        """
        k = i1 - i0
        if k < 2:
            return 0.0
        s1 = self.S1[i1] - self.S1[i0]
        s2 = self.S2[i1] - self.S2[i0]
        sy = self.Sy[i1] - self.Sy[i0]
        sty = self.Sty[i1] - self.Sty[i0]
        nevner = k * s2 - s1 * s1
        if nevner <= 0:
            return 0.0
        return float((k * sty - s1 * sy) / nevner)


def _linfit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    k = x.size
    if k < 2:
        return 0.0, 0.0
    s1, s2 = x.sum(), (x * x).sum()
    sy, sxy = y.sum(), (x * y).sum()
    nevner = k * s2 - s1 * s1
    if nevner <= 0:
        return 0.0, 0.0
    a = (k * sxy - s1 * sy) / nevner
    b = (sy - a * s1) / k
    rest = y - (a * x + b)
    ss_rest = float((rest * rest).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_rest / ss_tot if ss_tot > 0 else 1.0
    return float(a), float(r2)


def _glattet(y: np.ndarray, vindu_s: float, steg_s: float = 1.0) -> np.ndarray:
    """Medianfilter over ``vindu_s`` sekunder.

    ``steg_s`` er samplingsintervallet i sekunder - loggen kan ha andre
    intervaller enn ett sekund.
    """
    k = max(3, int(round(vindu_s / max(steg_s, 1e-9))))
    if k % 2 == 0:
        k += 1
    return (pd.Series(np.asarray(y, dtype=float))
            .rolling(k, center=True, min_periods=1).median().to_numpy())


def _slatt_sammen(t: np.ndarray, y: np.ndarray,
                  segmenter: list[tuple[int, int]], *, min_lengde_s: float,
                  tol_cm_min: float,
                  pre: "_Prefiks | None" = None) -> list[tuple[int, int]]:
    """Fjerner grenser der stigningstallet er likt likevel, og slår korte
    biter sammen med naboen de ligner mest paa.

    ``pre`` er prefikssummene for den glattede serien naar de finnes. Da
    koster hvert stigningstall O(1) i stedet for en egen tilpasning - dette
    er den innerste loekka i hele segmenteringen.
    """

    def stigning(bit: tuple[int, int]) -> float:
        if pre is not None:
            return pre.stigning(bit[0], bit[1] + 1) * 60.0
        a, _ = _linfit(t[bit[0]:bit[1] + 1], y[bit[0]:bit[1] + 1])
        return a * 60.0

    segmenter = list(segmenter)
    endret = True
    while endret and len(segmenter) > 1:
        endret = False
        for k in range(1, len(segmenter)):
            if abs(stigning(segmenter[k - 1]) - stigning(segmenter[k])) < tol_cm_min:
                segmenter[k - 1] = (segmenter[k - 1][0], segmenter[k][1])
                segmenter.pop(k)
                endret = True
                break
        if endret:
            continue
        kortest = min(segmenter, key=lambda s: t[s[1]] - t[s[0]])
        if (t[kortest[1]] - t[kortest[0]]) < min_lengde_s:
            k = segmenter.index(kortest)
            naboer = [i for i in (k - 1, k + 1) if 0 <= i < len(segmenter)]
            eg = stigning(kortest)
            nabo = min(naboer, key=lambda i: abs(stigning(segmenter[i]) - eg))
            a, b = min(k, nabo), max(k, nabo)
            segmenter[a] = (segmenter[a][0], segmenter[b][1])
            del segmenter[a + 1:b + 1]
            endret = True
    return segmenter


def finn_segmenter(t: np.ndarray, y: np.ndarray, *, tol_std: float = 0.35,
                   min_lengde_s: float = 60.0, tol_cm_min: float = 1.0,
                   glatt_s: float = 0.0,
                   min_forbedring: float = 0.10) -> list[tuple[int, int]]:
    """Stykkevis lineaer regresjon: ny fase naar restavviket blir for stort.

    ``tol_std`` er grensen fra spesifikasjonen (0,35 cm): en del der
    standardavviket til avvikene fra en rett linje er under ``tol_std``
    regnes som EN rett fase og deles ikke. Er avviket storre, leter vi opp
    det punktet som gir den beste todelingen og deler der - ikke der feilen
    tilfeldigvis passerer grensen.

    Det er hele forskjellen fra referanseutkastet, som gikk framover prove
    for prove og kuttet ved forste prove der avviket passerte grensen. Der
    havner kuttet langt inni den nye fasen: paa denne loggen ble hele
    opptrekket pluss rotasjonsstoppet slaat sammen til "én fase" paa
    4,0 cm/min med R2 = 0,39, mens den egentlige profilen er 6,9 / 0 / 10,9
    / 5,9 cm/min. Den metoden gikk dessuten bare én prove framover
    (``start_seg = i - 1``), saa en logg som svinger litt gir hundrevis av
    nesten identiske "faser".
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    n = t.size
    if n < 3:
        return [(0, max(0, n - 1))]

    if glatt_s > 0:
        steg = float(np.median(np.diff(t))) if n > 1 else 1.0
        brukt = _glattet(y, glatt_s, steg if steg > 0 else 1.0)
    else:
        brukt = y
    pre = _Prefiks(t, brukt)

    def beste_knekk(i0: int, i1: int) -> tuple[float, int] | None:
        """Beste todeling av [i0, i1], eller None hvis delen er rett nok.

        Vi leter opp den todelingen som gir stoerst restavviksgevinst BLANT
        de punktene der farten faktisk skifter. Det er forskjellen fra aa ta
        det beste punktet forst og forkaste det etterpaa: ligger det beste
        punktet midt i et encodersprang, der farten er lik paa begge sider,
        ble hele sonen staaende udelt - og da forsvinner baade
        stigningstallet og inndelingen i soner. Prejeten i G21 ble slik én
        fase paa 4,5 cm/min i stedet for 12,0 / 8,3 / 6,0.
        """
        sse0 = pre.sse(i0, i1 + 1)
        if sse0 <= 0.0 or pre.rest_std(i0, i1 + 1) <= tol_std:
            return None
        krav = sse0 * min_forbedring
        gevinst_best = 0.0
        p_best = None
        for p in range(i0 + 3, i1 - 1):
            gevinst = sse0 - (pre.sse(i0, p) + pre.sse(p, i1 + 1))
            if gevinst <= max(gevinst_best, krav):
                continue                     # ikke bedre enn det vi har
            venstre = pre.stigning(i0, p)
            hoyre = pre.stigning(p, i1 + 1)
            if abs((venstre - hoyre) * 60.0) < tol_cm_min:
                continue                     # samme fart - ikke en ny sone
            gevinst_best, p_best = gevinst, p
        if p_best is None:
            return None
        return float(gevinst_best), p_best

    segmenter: list[tuple[int, int]] = [(0, n - 1)]
    while True:
        beste: tuple[float, int, int, int] | None = None
        for i0, i1 in segmenter:
            treff = beste_knekk(i0, i1)
            if treff is None:
                continue
            gevinst, p = treff
            if beste is None or gevinst > beste[0]:
                beste = (gevinst, p, i0, i1)
        if beste is None:
            break
        _, p, i0, i1 = beste
        segmenter.remove((i0, i1))
        segmenter.append((i0, p - 1))
        segmenter.append((p, i1))

    return _slatt_sammen(t, brukt, sorted(segmenter),
                         min_lengde_s=min_lengde_s, tol_cm_min=tol_cm_min,
                         pre=pre)


def fase_tabell(df: pd.DataFrame, segmenter: Sequence[tuple[int, int]], *,
                min_r2: float = 0.7,
                stopp_cm_min: float = 1.0,
                maks_cm_min: float = 30.0,
                stopp_spenn_cm: float = 2.0,
                stopp_min_s: float = 600.0,
                stopp_med_fart: bool = False) -> list[dict[str, Any]]:
    """Stigningstall (cm/min), R2 og merknad per fase.

    Farten regnes OPPOVER: riggen trekker stanga opp mens den jetter, saa
    dybdetallet synker. Positiv fart betyr at stanga gikk opp.

    En fase faar et stigningstall naar dybden faktisk flytter seg:

    * staar dybden i ro - spennet gjennom fasen er innenfor 2*``stopp_spenn_cm``
      og fasen varer minst ``stopp_min_s`` - merkes den "stopp". Det er den
      samme spenn-regelen :func:`finn_stopp` klipper etter, saa en fase som
      klippes bort ogsaa merkes som stopp og omvendt. En langsom stigning har
      et STORT spenn og blir derfor ikke merket stopp lenger, selv om
      gjennomsnittsfarten er liten - den faar cm/min-tallet sitt.
    * er ``stopp_med_fart`` satt, merkes fasen ogsaa "stopp" naar
      |fart| < ``stopp_cm_min``. Av med vilje: spenn-regelen er primaer.
    * er farten fysisk umulig (> ``maks_cm_min``) merkes fasen "uryddig": da
      har encoderet hoppet, og 80 cm/min er ikke en fart. Riggen selv legger
      seg mellom 4 og 13 cm/min, og setpunktet stanser paa 12.
    * er tilpasningen ellers daarlig (R2 < ``min_r2``) merkes fasen "uryddig",
      men tallet staar der likevel i fasetabellen, med R2 ved siden av, saa det
      gaar an aa se hvor sikkert det er. Merkingen er bare en visningsetikett.
      Om fasen teller med i lengde og snittfart avgjores av :func:`teller_med` -
      det er en egen terskel, og de to skal ikke blandes.
    """
    t = (df["Tid"] - df["Tid"].iloc[0]).dt.total_seconds().to_numpy(dtype=float)
    dybde = df["dybde"].to_numpy(dtype=float)

    rader: list[dict[str, Any]] = []
    for nummer, (i0, i1) in enumerate(segmenter, start=1):
        stigning, r2 = _linfit(t[i0:i1 + 1], dybde[i0:i1 + 1])
        dt = float(t[i1] - t[i0])
        # "10,5 cm/min" skal bety at stanga gikk 10,5 cm oppover i minuttet.
        fart = round(-stigning * 60.0, 2)
        r2_avrundet = round(r2, 4)
        # Spennet gjennom fasen avgjor om den staar stille - den samme regelen
        # finn_stopp klipper etter. En langsom stigning har et stort spenn og
        # skal derfor ikke merkes stopp selv om gjennomsnittsfarten er lav.
        i_fase = dybde[i0:i1 + 1]
        i_fase = i_fase[np.isfinite(i_fase)]
        fase_spenn = float(i_fase.max() - i_fase.min()) if i_fase.size else 0.0
        pause = bool(
            stopp_spenn_cm and float(stopp_spenn_cm) > 0.0
            and fase_spenn <= 2.0 * float(stopp_spenn_cm)
            and dt >= stopp_min_s)
        if stopp_med_fart and abs(fart) < stopp_cm_min:
            pause = True
        if pause:
            merknad = "stopp"
        elif abs(fart) > maks_cm_min:
            merknad = "uryddig"
        elif r2_avrundet < min_r2:
            merknad = "uryddig"
        else:
            merknad = ""
        # Er det hull i dybden (ALOSS), staar det NaN i enden av en fase. Da
        # brukes den forste og den siste maalte verdien i fasen i stedet.
        pene = dybde[i0:i1 + 1]
        pene = pene[np.isfinite(pene)]
        fra_cm = float(pene[0]) if pene.size else float("nan")
        til_cm = float(pene[-1]) if pene.size else float("nan")

        rader.append({
            "fase": nummer,
            "fra": df["Tid"].iloc[i0].strftime("%H:%M:%S"),
            "til": df["Tid"].iloc[i1].strftime("%H:%M:%S"),
            "varighet_s": round(dt, 1),
            # Dybden er positiv nedover (normalisert i les_logg).
            "dybde_fra_cm": round(fra_cm, 1),
            "dybde_til_cm": round(til_cm, 1),
            "lengde_cm": round(fra_cm - til_cm, 1),
            "stigningstall_cm_min": fart,
            "r2": r2_avrundet,
            "merknad": merknad,
        })
    return rader


def teller_med(rad: Mapping[str, Any], min_r2_telling: float) -> bool:
    """Teller denne fasen med i lengde og snittfart?

    To ting maa holde samtidig: fasen er ikke merket (``merknad == ""``), og
    tilpasningen er god nok (``r2 >= min_r2_telling``). Merkingen er en
    visningsetikett som styres av ``min_r2``, ``stopp_cm_min`` og
    ``maks_cm_min``; tellingen har sin egen terskel. De to er forskjellige
    begreper: en fase kan staa i plottet med farten sin og likevel holdes
    utenfor lengden og snittet fordi den svinger for mye.
    """
    return not rad["merknad"] and float(rad["r2"]) >= min_r2_telling


# ---------------------------------------------------------------------------
# Stopp: naar grafen skal klippes og merkes
# ---------------------------------------------------------------------------


def _fartsprofil(dybde: np.ndarray, t: np.ndarray, glatt_s: float) -> np.ndarray:
    """Farten i cm/min per prove. Positiv = stanga gaar OPP.

    Dybden er positiv nedover, saa farten er den negative deriverte av dybden.
    Dybden glattes foerst, saa et encodersprang ikke blir en "bevegelse".
    """
    n = t.size
    if n == 0:
        return np.zeros(0)
    y = np.asarray(dybde, dtype=float)
    if glatt_s and glatt_s > 0 and n >= 3:
        steg = float(np.median(np.diff(t))) if n > 1 else 1.0
        y = _glattet(y, glatt_s, steg if steg > 0 else 1.0)
    fart = np.zeros(n)
    if n > 1:
        dt = np.diff(t)
        dt = np.where(dt > 0, dt, np.nan)
        fart[1:] = -(np.diff(y) / dt) * 60.0
        fart[0] = fart[1]
    return np.where(np.isfinite(fart), fart, 0.0)


def _vindu_fartsprofil(dybde: np.ndarray, t: np.ndarray,
                       vindu_s: float) -> np.ndarray:
    """Farten i cm/min maalt bakover over et vindu paa ``vindu_s`` sekunder.

    Forskjellen fra :func:`_fartsprofil`, som deriverer (glattet) dybde prove
    for prove, er at et enkeltsteg blir utjevnet: 0,1 cm over et vindu paa
    ~60 s er ~0,1 cm/min, ikke 6 cm/min. Uten dette deler en langsom trapp av
    smaa encodersprang en ellers flat periode i mange korte biter som hver
    faller under minstekravet - og stoppen blir aldri klippet ut. Maalt over
    vinduet henger hele den flate perioden sammen, slik operatoren vil ha den.
    """
    n = t.size
    fart = np.zeros(n)
    if n < 2:
        return fart
    steg = float(np.median(np.diff(t))) if n > 1 else 1.0
    steg = steg if steg > 0 else 1.0
    w = max(1, int(round(float(vindu_s) / steg)))
    for i in range(n):
        k = i - w
        if k < 0:
            k = 0
        dt = float(t[i] - t[k])
        if (dt > 0 and np.isfinite(dybde[i]) and np.isfinite(dybde[k])):
            fart[i] = -(dybde[i] - dybde[k]) / dt * 60.0
    return fart


def finn_spenn_stopp(t: np.ndarray, dybde: np.ndarray, *,
                     stopp_min_s: float = 600.0,
                     stopp_spenn_cm: float = 2.0) -> list[tuple[int, int]]:
    """Pauser etter DYBDE-SPENN-regelen: dybden staar i ro.

    Operator-regelen: staar dybden innenfor +/-``stopp_spenn_cm`` i minst
    ``stopp_min_s`` sekunder, er det en pause. Vi leter derfor opp de
    MAKSIMALE intervallene der ``max(dybde) - min(dybde) <= 2*stopp_spenn_cm``
    - ikke der farten er lav. En flat periode er en trapp av encodersprang paa
    0,1 cm, og farten prove-for-prove sier ingenting om hvor dybden er paa vei.

    To pekere med monotonistakk gir lengste vindu som slutter i hver prove i
    O(n). Alle slike vinduer som varer lenge nok dekker til sammen de flate
    partiene; de samles i en bitmaske, deles i sammenhengende biter, og hver
    bit klippes til slutt slik at ingen bit faar storre spenn enn toleransen -
    ellers ville en sammenslaaing gjenskapt nettopp den flate linjen vi vil
    fjerne.
    """
    n = t.size
    if n < 2 or stopp_spenn_cm is None or float(stopp_spenn_cm) <= 0.0:
        return []
    tol = 2.0 * float(stopp_spenn_cm)
    lo: deque[int] = deque()
    hi: deque[int] = deque()
    venstre = 0
    L = np.full(n, -1, dtype=int)
    for r in range(n):
        v = float(dybde[r])
        if not np.isfinite(v):
            lo.clear()
            hi.clear()
            venstre = r + 1
            continue
        while lo and (not np.isfinite(dybde[lo[-1]]) or dybde[lo[-1]] >= v):
            lo.pop()
        lo.append(r)
        while hi and (not np.isfinite(dybde[hi[-1]]) or dybde[hi[-1]] <= v):
            hi.pop()
        hi.append(r)
        while dybde[hi[0]] - dybde[lo[0]] > tol:
            venstre += 1
            while lo and lo[0] < venstre:
                lo.popleft()
            while hi and hi[0] < venstre:
                hi.popleft()
        L[r] = venstre
    # Hvilke prover hoerer til et vindu som er langt nok? Differansematrise,
    # saa merkningen blir O(n) ogsaa naar vinduene er lange.
    merk = np.zeros(n + 1, dtype=np.int64)
    for r in range(n):
        if L[r] >= 0 and (t[r] - t[L[r]]) >= stopp_min_s:
            merk[L[r]] += 1
            merk[r + 1] -= 1
    dekt = np.cumsum(merk[:n]) > 0
    idx = np.flatnonzero(dekt)
    if idx.size == 0:
        return []
    starter = idx[np.r_[True, np.diff(idx) > 1]]
    slutter = idx[np.r_[np.diff(idx) > 1, True]]
    ut: list[tuple[int, int]] = []
    for s0, b0 in zip(starter, slutter):
        s = int(s0)
        b0 = int(b0)
        while s <= b0:
            e = s
            lav = hoey = float(dybde[s])
            while e + 1 <= b0:
                nv = float(dybde[e + 1])
                nlav = min(lav, nv)
                nhoey = max(hoey, nv)
                if nhoey - nlav <= tol:
                    lav, hoey, e = nlav, nhoey, e + 1
                else:
                    break
            if (t[e] - t[s]) >= stopp_min_s:
                ut.append((s, e))
            s = e + 1
    return ut


def del_ved_stopp(segmenter: Sequence[tuple[int, int]],
                  spenn: Sequence[tuple[int, int]]
                  ) -> list[tuple[int, int]]:
    """Klipper fasene i biter rundt pausene.

    En pause skal ikke ligge inne i en fase som teller med: da ville
    staa-tiden blitt regnet som bevegelse. Hver pause blir sin egen bit, og
    den biten faar merknaden 'stopp' i :func:`fase_tabell`.
    """
    grenser = sorted({int(p) for a, b in spenn for p in (a, b + 1)})
    if not grenser:
        return [(int(a), int(b)) for a, b in segmenter]
    ut: list[tuple[int, int]] = []
    for i0, i1 in segmenter:
        i0, i1 = int(i0), int(i1)
        kanter = [i0] + [g for g in grenser if i0 < g <= i1] + [i1 + 1]
        for x, y in zip(kanter, kanter[1:]):
            if y - x >= 2:
                ut.append((x, y - 1))
    return ut


def finn_stopp(bit: pd.DataFrame, *, stopp_spenn_cm: float = 2.0,
               stopp_cm_min: float = 1.0, stopp_min_s: float = 600.0,
               stopp_kanal: str | None = None, stopp_verdi: float | None = None,
               stopp_retning: str = "under", stopp_kombi: str = "eller",
               stopp_med_fart: bool = False,
               glatt_s: float | None = None) -> list[dict[str, Any]]:
    """Periodene der riggen staar stille - kandidater for aksekutt.

    HOVEDKRITERIET er DYBDE-SPENNET (``stopp_spenn_cm``, standard 2,0, altsaa
    +/-2 cm): staar dybden innenfor en tolerance paa 2*2,0 = 4 cm i minst
    ``stopp_min_s`` sekunder, er det en pause, og den klippes ut av x-aksen.
    Det er operatørens regel, og den ser paa hvor dybden ER - ikke paa hvor
    fort den flytter seg. En flat periode er en trapp av encodersprang, og
    farten blir derfor et daarlig maal.

    DE ANDRE KRITERIENE er fortsatt tilgjengelige og kan kombineres:

    * bevegelse: |cm/min| under ``stopp_cm_min`` - bare naar
      ``stopp_med_fart`` er satt (av med vilje: spenn-regelen er primaer).
    * kanal: en navngitt kanal under/over ``stopp_verdi`` (``stopp_kanal`` +
      ``stopp_verdi``), f.eks. grouttrykk under 50 bar.

    ``stopp_kombi`` sier hvordan de AKTIVE kriteriene settes sammen: 'eller'
    (standard) = pause naar ett av dem slaar ut, 'og' = alle maa holde
    samtidig. Staar bare spenn-regelen paa, spiller kombien ingen rolle.

    En stopp maa vare minst ``stopp_min_s`` sekunder (standard 600 - ti
    minutter). Da blir ikke enkeltsamples med sensorfjaer eller et
    encodersprang merket.

    Stoppene NUMMERERES FRA DYPEST TIL GRUNNEST - stopp 1 er den dypeste,
    ikke den forste i tid.
    """
    n = len(bit)
    if n < 3:
        return []
    t = (bit["Tid"] - bit["Tid"].iloc[0]).dt.total_seconds().to_numpy(float)
    dybde = bit["dybde"].to_numpy(dtype=float)

    kilder: list[tuple[str, np.ndarray]] = []
    if stopp_spenn_cm is not None and float(stopp_spenn_cm) > 0.0:
        mask = np.zeros(n, dtype=bool)
        for a, b in finn_spenn_stopp(t, dybde, stopp_min_s=stopp_min_s,
                                     stopp_spenn_cm=float(stopp_spenn_cm)):
            mask[a:b + 1] = True
        kilder.append(("spenn", mask))
    if stopp_med_fart:
        glatt = glatt_s if (glatt_s and glatt_s > 0) else min(
            61.0, max(3.0, 0.03 * float(t[-1] - t[0]) if t.size else 3.0))
        fart = _vindu_fartsprofil(dybde, t, glatt)
        kilder.append(("bevegelse",
                       (np.abs(fart) < stopp_cm_min) & np.isfinite(dybde)))
    if stopp_kanal and stopp_verdi is not None and stopp_kanal in bit.columns:
        v = bit[stopp_kanal].to_numpy(dtype=float)
        if str(stopp_retning).lower() == "over":
            slaar = np.isfinite(v) & (v > float(stopp_verdi))
        else:
            slaar = np.isfinite(v) & (v < float(stopp_verdi))
        kilder.append(("kanal", slaar))
    if not kilder:
        return []

    if str(stopp_kombi).lower() == "og" and len(kilder) > 1:
        stille = np.ones(n, dtype=bool)
        for _, m in kilder:
            stille &= m
    else:
        stille = np.zeros(n, dtype=bool)
        for _, m in kilder:
            stille |= m
    stille &= np.isfinite(dybde)

    stopp: list[dict[str, Any]] = []
    i = 0
    while i < n:
        if not stille[i]:
            i += 1
            continue
        a = i
        while i + 1 < n and stille[i + 1]:
            i += 1
        b = i
        i += 1
        varighet = float(t[b] - t[a])
        if varighet < stopp_min_s:
            continue
        ys = dybde[a:b + 1]
        ys = ys[np.isfinite(ys)]
        if ys.size == 0:
            continue
        grunn = "+".join(navn for navn, m in kilder if bool(np.all(m[a:b + 1])))
        # Medianen av de forste/siste provene, ikke ett enkelt sample: et
        # encodersprang i kanten skal ikke bli "dybden ved stopp".
        k = max(1, min(5, ys.size))
        dybde_stopp = float(np.median(ys[:k]))
        dybde_start = float(np.median(ys[-k:]))
        delta = dybde_start - dybde_stopp        # positiv = gikk NED etterpaa
        stopp.append({
            "a": int(a), "b": int(b),
            "grunn": grunn or "bevegelse",
            "fra_iso": bit["Tid"].iloc[a].isoformat(timespec="seconds"),
            "til_iso": bit["Tid"].iloc[b].isoformat(timespec="seconds"),
            "varighet_s": round(varighet, 1),
            "varighet": varighet_tekst(varighet),
            "dybde_stopp_cm": round(dybde_stopp, 1),
            "dybde_start_cm": round(dybde_start, 1),
            "lengde_cm": round(abs(delta), 1),
            "delta_dybde_cm": round(delta, 1),
        })

    # NUMMERERING: dypest forst. Stopp 1 = stoerste dybde. Fargen foelger nr.
    stopp.sort(key=lambda s: -float(s["dybde_stopp_cm"]))
    for nr, s in enumerate(stopp, start=1):
        s["nr"] = nr
        s["farge"] = STOPP_FARGER[(nr - 1) % len(STOPP_FARGER)]
    return stopp


def _slå_sammen_spenn(spenn: Sequence[tuple[int, int]]
                      ) -> list[tuple[int, int]]:
    """Slaar sammen overlappende/naboe indeksspenn til en ryddig liste."""
    ut: list[tuple[int, int]] = []
    for a, b in sorted((int(a), int(b)) for a, b in spenn):
        if ut and a <= ut[-1][1] + 1:
            ut[-1] = (ut[-1][0], max(ut[-1][1], b))
        else:
            ut.append((a, b))
    return ut


def komprimer_akse(t_rel: np.ndarray, spenn: Sequence[tuple[int, int]]
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fjerner ``spenn`` fra x-aksen og gir tilbake den komprimerte x-en.

    ``spenn`` er indeksintervaller [a, b] som skal bort. Tiden de dekker
    trekkes ut av x-aksen (grafen krymper), men provene er der fortsatt - det
    er bare x-koordinaten deres som skyves sammen. Provene inne i spennet blir
    satt til NaN av den som tegner, saa kurven faar et avbrekk der i stedet
    for en rett strek over.

    Returnerer ``(x, fjern, cum)``: den nye x-en, en maske for hva som er
    fjernet, og hvor mange sekunder som er tatt ut foran hver prove.
    """
    t_rel = np.asarray(t_rel, dtype=float)
    n = t_rel.size
    fjern = np.zeros(n, dtype=bool)
    for a, b in spenn:
        a = max(0, int(a))
        b = min(n - 1, int(b))
        if b >= a:
            fjern[a:b + 1] = True
    if n == 0:
        return t_rel, fjern, np.zeros(0)
    dt = np.diff(t_rel, prepend=t_rel[0])
    dt = np.where(np.isfinite(dt) & (dt > 0), dt, 0.0)
    cum = np.cumsum(np.where(fjern, dt, 0.0))
    return t_rel - cum, fjern, cum


def akse_ticks(x: np.ndarray, fjern: np.ndarray, tider: pd.Series,
               antall: int = 10, *,
               min_avstand_andel: float = 0.085
               ) -> tuple[list[float], list[str]]:
    """Plassering og HH:MM-etikett for haker paa den komprimerte x-aksen.

    Aksen er komprimert (pausene er klippet bort), saa matplotlibs egen
    datolokator ville satt merkene paa feil klokkeslett. Vi velger derfor
    haker paa PENE KLOKKESLETT (5/10/15/... minutter), beholder bare haker
    som lander paa en KEPT prove - en hake kan ikke ligge inne i et kutt - og
    merker dem med klokka si. Helt til slutt fjernes haker som ville blitt
    skrevet oppaa hverandre; den forste og den siste beholdes alltid.

    Dette er et BEVISST valg av lesbarhet framfor jevn avstand: etter kuttene
    kan hakene ikke baade staa jevnt i klokketid og jevnt paa skjermen, og
    operatøren klaget nettopp paa at klokka ikke var lesbar. Vi velger altsaa
    pene klokkeslett og dropper de haka som kolliderer.
    """
    x = np.asarray(x, dtype=float)
    idx = np.flatnonzero(~fjern)
    if idx.size == 0 or x.size == 0:
        return [], []
    sti = idx[np.argsort(x[idx], kind="stable")]
    x_min, x_max = float(x[sti[0]]), float(x[sti[-1]])
    bredde = (x_max - x_min) or 1.0
    tid0, tid1 = tider.iloc[0], tider.iloc[-1]
    total_min = (tid1 - tid0).total_seconds() / 60.0
    if total_min <= 0:
        return [], []
    antall = max(2, int(antall))
    # Steget velges ut fra hvor mye KEPT tid aksen viser - ikke hele
    # hendelsen. Er 100 av 137 minutter klippet bort, blir det faa haker om vi
    # regner fra klokka alene. Naar en kandidat lander inne i et kutt, SNAPPES
    # den til naermeste tegnede prove og merkes med DEN provens klokke, saa
    # haken alltid staar der den sier den staar.
    kept_min = (x_max - x_min) / 60.0
    steg_min = None
    for kandidat in (2, 5, 10, 15, 20, 30, 60, 90, 120, 180, 240, 360, 720):
        if kept_min / kandidat <= antall:
            steg_min = kandidat
            break
    if steg_min is None:
        steg_min = max(1.0, kept_min / antall)

    def naar_kept(i: int) -> int:
        """Naermeste indeks som er tegnet (ikke klippet)."""
        p = int(np.searchsorted(sti, i))
        if p <= 0:
            return int(sti[0])
        if p >= sti.size:
            return int(sti[-1])
        lo, hi = int(sti[p - 1]), int(sti[p])
        return lo if abs(i - lo) <= abs(hi - i) else hi

    t_arr = tider.to_numpy()
    kandidater: list[int] = [int(sti[0]), int(sti[-1])]
    naa = tid0.ceil(f"{int(steg_min)}min")
    while naa <= tid1:
        j = int(np.searchsorted(t_arr, naa.to_datetime64()))
        j = min(max(j, 0), len(tider) - 1)
        if (j > 0 and abs((tider.iloc[j - 1] - naa).total_seconds())
                < abs((tider.iloc[j] - naa).total_seconds())):
            j = j - 1
        kandidater.append(naar_kept(j))
        naa = naa + pd.Timedelta(minutes=steg_min)

    # Fjern dubletter og sorter etter x, saa vi kan luke bort kollisjoner.
    kandidater = sorted(set(kandidater), key=lambda i: (float(x[i]), i))
    pos: list[float] = []
    lab: list[str] = []
    siste = int(sti[-1])
    for i in kandidater:
        xi = float(x[i])
        if pos and (xi - pos[-1]) < min_avstand_andel * bredde:
            if i == siste:                     # siste hake skal alltid med
                pos[-1], lab[-1] = xi, tider.iloc[i].strftime("%H:%M")
            continue
        lab_i = tider.iloc[i].strftime("%H:%M")
        if lab and lab_i == lab[-1]:           # ikke to like klokkeslett
            if i == siste:
                pos[-1], lab[-1] = xi, lab_i
            continue
        pos.append(xi)
        lab.append(lab_i)
    if len(pos) < 2:                           # alltid minst start og slutt
        pos = [x_min, x_max]
        lab = [tid0.strftime("%H:%M"), tid1.strftime("%H:%M")]
    return pos, lab


def stopp_fotnote(stopp: Sequence[Mapping[str, Any]]) -> list[str]:
    """Én tekstlinje per stopp, med alt operatoren ba om."""
    linjer: list[str] = []
    for s in stopp:
        delta = float(s["delta_dybde_cm"])
        retning = "ned" if delta > 0.5 else ("opp" if delta < -0.5 else "side")
        tid_s = str(s["fra_iso"])[11:19]
        tid_e = str(s["til_iso"])[11:19]
        linjer.append(
            f"Stopp {s['nr']}: {s['varighet']}   "
            f"stopp {tid_s} / {float(s['dybde_stopp_cm']):.0f} cm   "
            f"start {tid_e} / {float(s['dybde_start_cm']):.0f} cm   "
            f"lengde {float(s['lengde_cm']):.0f} cm, \u0394 dybde "
            f"{delta:+.0f} cm ({retning})")
    return linjer


# ---------------------------------------------------------------------------
# Plottet
# ---------------------------------------------------------------------------


def lag_plott(df: pd.DataFrame, rader: Sequence[dict[str, Any]],
              segmenter: Sequence[tuple[int, int]],
              kanaler: Sequence[tuple[str, str, str]], utfil: str | Path,
              *, maks_dybde: float | None = None,
              grenser: dict[str, tuple[float, float]] | None = None,
              min_r2_telling: float = 0.9,
              tittel: str = "Acron r\u00e5data - samlet plott med delt Y-akse",
              stopp: Sequence[Mapping[str, Any]] | None = None,
              fjern_uryddig: bool = True,
              stopp_spenn_cm: float = 2.0, stopp_min_s: float = 600.0
              ) -> Path:
    """Ett plott med alle kanaler paa delte Y-akser + klammer under.

    Stoppene OG de 'uryddig' fasene blir KLIPPET UT av x-aksen: tiden deres
    forsvinner, men provene er der fortsatt - de blir bare ikke tegnet der.
    Ved hvert kutt staar det vanlige bruddmerket (to skraa streker over
    aksen), og hver stopp faar sin egen fargede strek. Det er operatorens
    verktoey mot at en lang pause gjoer grafen uleselig.
    """
    stopp = list(stopp or [])
    tider = df["Tid"]
    t_rel = (tider - tider.iloc[0]).dt.total_seconds().to_numpy(dtype=float)

    # Hva skal bort fra x-aksen? Stoppene, og 'uryddig'-fasene helt.
    spenn: list[tuple[int, int]] = [(s["a"], s["b"]) for s in stopp]
    if fjern_uryddig:
        for (i0, i1), rad in zip(segmenter, rader):
            if rad["merknad"] == "uryddig":
                spenn.append((i0, i1))
    spenn = _slå_sammen_spenn(spenn)
    x, fjern, _cum = komprimer_akse(t_rel, spenn)

    def stopp_ved(a: int, b: int) -> Mapping[str, Any] | None:
        """Stoppen et kutt hoerer til - til fargen paa streken."""
        for s0 in stopp:
            if not (s0["b"] < a or s0["a"] > b):
                return s0
        return None

    def klipp(serie: Any) -> np.ndarray:
        y = np.asarray(serie, dtype=float)
        return np.where(fjern, np.nan, y)

    fig = plt.figure(figsize=(16.0, 10.2))
    rutenett = fig.add_gridspec(3, 1, height_ratios=[8.0, 0.95, 2.5],
                                hspace=0.16)
    ax1 = fig.add_subplot(rutenett[0])
    ax_klamme = fig.add_subplot(rutenett[1], sharex=ax1)
    ax_fot = fig.add_subplot(rutenett[2], sharex=ax1)

    # -- venstre akse: dybde, invertert --------------------------------------
    dybde = df["dybde"].to_numpy(dtype=float)
    linjer = list(ax1.plot(x, klipp(dybde), color=FARGE_DYBDE, linewidth=1.5,
                           label="Dybde [cm]", zorder=5))
    pene = dybde[np.isfinite(dybde)]
    topp = maks_dybde if maks_dybde else (
        float(pene.max()) * 1.03 if pene.size else 1.0)
    bunn = 0.0 if (not pene.size or pene.min() >= 0) else float(pene.min())
    ax1.set_ylim(bunn, topp)
    ax1.invert_yaxis()                              # 0 overst, dypest nederst
    ax1.set_ylabel(f"Dybde [cm] (0 \u00f8verst - {topp:.0f} nederst)",
                   fontsize=10, fontweight="bold", color=FARGE_DYBDE)
    ax1.tick_params(axis="y", colors=FARGE_DYBDE, labelsize=8)
    ax1.spines["right"].set_visible(False)
    ax1.grid(True, linestyle=":", alpha=0.45)

    # -- firmalogo: svakt, gjennomsiktig vannmerke bak kurvene --------------
    _tegn_logo_akse(ax1)

    # -- hoyreakser, forskjoevet utover --------------------------------------
    akser: list[Any] = []
    for nokkel, etikett, farge in kanaler:
        akse = ax1.twinx()
        if akser:
            akse.spines["right"].set_position(
                ("outward", AVSTAND_AKSE * len(akser)))
        akse.plot(x, klipp(df[nokkel].to_numpy(dtype=float)), color=farge,
                  alpha=0.85, linewidth=0.8, label=etikett)
        akse.set_ylabel(etikett, color=farge, fontsize=9)
        akse.tick_params(axis="y", colors=farge, labelsize=8)
        if grenser and nokkel in grenser:
            akse.set_ylim(*grenser[nokkel])
        linjer.append(akse.get_lines()[-1])
        akser.append(akse)

    # -- tittel og legend paa én rad ----------------------------------------
    # Tittelen staar i TO blokker: overskriften (pel/metode) paa én linje og
    # fakta-linjen under. Legenden legges klart OVER tittelen, med luft, saa
    # de to ikke skrives oppaa hverandre - det var en feil i forrige utgave.
    start_tekst = tider.iloc[0].strftime("%d.%m.%Y %H:%M")
    slutt_tekst = tider.iloc[-1].strftime("%H:%M")
    ax1.set_title(f"{tittel}\n{start_tekst}-{slutt_tekst}",
                  fontsize=11.5, fontweight="bold", pad=16)
    ax1.legend(linjer, [str(ln.get_label()) for ln in linjer],
               loc="upper center", bbox_to_anchor=(0.5, 1.27),
               ncol=len(linjer), fontsize=7.5, frameon=False,
               borderaxespad=0.0, columnspacing=1.0, handlelength=1.4)

    # -- bruddmerkene: to skraa streker + én farget strek per stopp ----------
    import matplotlib.transforms as mtrans
    blandet = mtrans.blended_transform_factory(ax1.transData, ax1.transAxes)
    spennvidde = float(x[-1] - x[0]) if x.size > 1 else 1.0
    dxx = 0.004 * spennvidde if spennvidde else 1.0
    for a, b in spenn:
        xb = float(x[int(a)])
        s = stopp_ved(a, b)
        farge = str(s["farge"]) if s else "#555555"
        # Én farget loddrett strek - stoppens farge, tydelig mot rutenettet.
        ax1.axvline(x=xb, color=farge, linewidth=1.7,
                    alpha=0.60 if s else 0.30, zorder=8)
        # Det vanlige bruddmerket: to parallelle skraastreker over aksen.
        for dx in (-0.7 * dxx, 0.7 * dxx):
            ax1.plot([xb + dx - 0.6 * dxx, xb + dx + 0.6 * dxx],
                     [-0.045, 0.030], transform=blandet, color="#111111",
                     linewidth=1.7, clip_on=False, zorder=9)
        if s:
            ax1.annotate(f"S{s['nr']}", xy=(xb, 0.015), xycoords=blandet,
                         xytext=(0, 1), textcoords="offset points",
                         color=farge, fontsize=9, fontweight="bold",
                         ha="center", va="bottom", zorder=10)

    # -- produksjonsomraadet: start og stopp tydelig merket ------------------
    for xv, merke, farge in ((x[0], "start", "#2e7d32"),
                             (x[-1], "stopp", "#b71c1c")):
        ax1.axvline(x=xv, color=farge, linewidth=1.3, alpha=0.85, zorder=6)
        ax1.annotate(merke, xy=(xv, 0.5), xycoords=("data", "axes fraction"),
                     xytext=(5 if merke == "start" else -5, 0.0),
                     textcoords="offset points", color=farge, fontsize=8,
                     fontweight="bold", rotation=90, va="center",
                     ha="left" if merke == "start" else "right", zorder=7)

    # -- skillelinjer og klammer --------------------------------------------
    ax_klamme.set_ylim(-1.0, 1.0)
    ax_klamme.set_yticks([])
    for side in ("top", "left", "right", "bottom"):
        ax_klamme.spines[side].set_visible(False)
    ax1.tick_params(labelbottom=False)
    ax_klamme.tick_params(labelbottom=False, bottom=False)

    # Hvor mange rader trengs for at cm/min-etikettene ikke kolliderer? Er
    # fasene brede, holder det med én; er de smale (mye klippet bort), legges
    # etikettene i flere rader, saa hver fasene faar sin egen lesbare verdi.
    _bredder = [(float(x[int(j1)]) - float(x[int(j0)]))
                for j0, j1 in segmenter
                if not (fjern[int(j0)] and fjern[int(j1)])]
    _bredder = [b for b in _bredder if b > 0]
    _andel = (float(np.median(_bredder)) / spennvidde) if _bredder else 1.0
    n_rader = max(1, min(4, int(math.ceil(0.055 / _andel)))) if _andel > 0 else 1
    n_tekst = 0                          # teller tegnede klammer -> fordeles paa radene
    for nummer, (i0, i1) in enumerate(segmenter):
        if fjern[int(i0)] and fjern[int(i1)]:
            continue                    # hele fasen er klippet bort
        x0, x1 = float(x[int(i0)]), float(x[int(i1)])
        if x1 - x0 <= 0:
            continue

        # Skillelinjene tegnes for alle faser vi beholder.
        ax1.axvline(x=x0, color="red", linestyle="--", alpha=0.6,
                    linewidth=1.0)
        if nummer == len(segmenter) - 1:
            ax1.axvline(x=x1, color="red", linestyle="--", alpha=0.6,
                        linewidth=1.0)

        rad = rader[nummer]
        fart = float(rad["stigningstall_cm_min"])
        if rad["merknad"] == "stopp":
            # Ingen bevegelse - her finnes det ikke noe stigningstall.
            innhold = "stopp"
        elif not teller_med(rad, min_r2_telling):
            # Fasen holdes utenfor lengde og snitt. Da skal det ikke staa et
            # cm/min-tall her som ser ut som det gjelder.
            innhold = "\u2014"
        else:
            innhold = f"{fart:.1f}\ncm/min"

        midt = 0.5 * (x0 + x1)
        gap = 0.25 * (x1 - x0)
        if midt - gap > x0:
            ax_klamme.plot([x0, midt - gap], [0.0, 0.0],
                           color="black", linewidth=1.2)
        if midt + gap < x1:
            ax_klamme.plot([midt + gap, x1], [0.0, 0.0],
                           color="black", linewidth=1.2)
        ax_klamme.plot([x0, x0], [-0.3, 0.3], color="black", linewidth=1.2)
        ax_klamme.plot([x1, x1], [-0.3, 0.3], color="black", linewidth=1.2)
        # Etter kuttene ligger fasene tett. Teksten fordeles derfor paa
        # ``n_rader`` rader slik at to naboer ikke skrives oppaa hverandre.
        if n_rader == 1:
            y_lab = 0.0
        else:
            y_lab = 0.62 - (n_tekst % n_rader) * (1.24 / (n_rader - 1))
        n_tekst += 1
        ax_klamme.text(midt, y_lab, innhold, ha="center", va="center",
                       fontsize=7.0, fontweight="bold", linespacing=1.05,
                       bbox=dict(boxstyle="square,pad=0.12", facecolor="white",
                                 edgecolor="none"))

    # -- klokka paa x-aksen: nederst i arket, vannrett og lesbar -------------
    pos, lab = akse_ticks(x, fjern, tider, antall=10)
    ax_fot.set_xticks(pos)
    ax_fot.set_xticklabels(lab)

    # -- fotnote: én farget linje per stopp ----------------------------------
    for side in ("top", "left", "right", "bottom"):
        ax_fot.spines[side].set_visible(False)
    ax_fot.set_yticks([])
    ax_fot.tick_params(axis="x", labelsize=9, length=4, pad=3)
    plt.setp(ax_fot.get_xticklabels(), rotation=0, ha="center")

    # Hvor mye av hendelsen aksen faktisk viser: pausene er klippet bort, saa
    # uten dette tallet ser ikke leseren at en time er fjernet fra midten.
    aktiv_s = float(x[-1] - x[0]) if x.size > 1 else 0.0
    total_s = float(t_rel[-1] - t_rel[0]) if t_rel.size > 1 else 0.0
    pause_s = sum(float(s["varighet_s"]) for s in stopp)
    borte_s = max(0.0, total_s - aktiv_s)
    uryddig_s = max(0.0, borte_s - pause_s)
    hode_fot = (
        "Stopp (nummerert fra dypest til grunnest) \u00b7 "
        f"x-aksen viser {aktiv_s / 60.0:.0f} min aktiv tid av "
        f"{total_s / 60.0:.0f} min ({borte_s / 60.0:.0f} min klippet bort: "
        f"{pause_s / 60.0:.0f} min pause, {uryddig_s / 60.0:.0f} min uryddig)")
    linjer_fot = stopp_fotnote(stopp)
    ax_fot.text(0.0, 0.99, hode_fot, transform=ax_fot.transAxes, fontsize=8,
                fontweight="bold", color="#333", va="top")
    if linjer_fot:
        ncol = 1 if len(linjer_fot) <= 4 else (2 if len(linjer_fot) <= 10
                                               else 3)
        per = int(math.ceil(len(linjer_fot) / ncol))
        steg = min(0.16, 0.62 / max(per, 1))
        for c in range(ncol):
            for r in range(per):
                k = c * per + r
                if k >= len(linjer_fot):
                    break
                s = stopp[k]
                ax_fot.text(c / ncol + 0.004, 0.72 - r * steg, linjer_fot[k],
                            transform=ax_fot.transAxes, fontsize=7.6,
                            color=str(s["farge"]), va="top", ha="left")
    else:
        ax_fot.text(0.0, 0.72, "Ingen stopp over grensen i denne hendelsen.",
                    transform=ax_fot.transAxes, fontsize=8, color="#666",
                    va="top")

    fig.text(0.01, 0.002,
             "Dybde er regnet positivt nedover fra Dybde_rapp; aksen er satt "
             f"til 0 (topp)-{topp:.0f} (bunn). En pause er et tidsrom der "
             f"dybden holder seg innenfor +/-{stopp_spenn_cm:g} cm i minst "
             f"{stopp_min_s / 60.0:g} min; den er klippet ut av x-aksen og "
             "merket med brudd og farget strek. Raa verdier ellers uendret.",
             fontsize=7, color="gray")

    fig.subplots_adjust(left=0.055, right=0.78, top=0.835, bottom=0.075)
    ut = Path(utfil)
    ut.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ut, dpi=300)
    plt.close(fig)
    return ut


# ---------------------------------------------------------------------------
# Interaktiv HTML
# ---------------------------------------------------------------------------

_KONTROLL_HTML = """
<div class="kontroll">
  <div class="knapper">
    <button onclick="window.print()">Skriv ut / lagre som PDF</button>
    <button onclick="nullstill()">Nullstill</button>
    <span class="hint">Skru av/p&aring; kurver med avkryssingsboksene, skriv egne
    tall i min/maks for &aring; endre skalaen p&aring; den enkelte aksen.
    Utskrift g&aring;r til A4 liggende.</span>
  </div>
  <table>
    <tr><th>vis</th><th>kanal</th><th>min</th><th>maks</th></tr>
    __RADER__
  </table>
</div>
"""

_KONTROLL_JS = """
<script>
const KANALER = __KANALER__;
function settSynlig(i) {
  const k = KANALER[i];
  const paa = document.getElementById('vis_' + i).checked;
  Plotly.restyle('plott', {'visible': paa}, [k.trace]);
  const oppdatering = {};
  oppdatering[k.akse + '.visible'] = paa;
  Plotly.relayout('plott', oppdatering);
}
function settSkala(i) {
  const k = KANALER[i];
  const a = parseFloat(document.getElementById('min_' + i).value);
  const b = parseFloat(document.getElementById('max_' + i).value);
  if (!isFinite(a) || !isFinite(b) || a === b) { return; }
  const oppdatering = {};
  oppdatering[k.akse + '.range'] = k.invertert ? [b, a] : [a, b];
  Plotly.relayout('plott', oppdatering);
}
function nullstill() {
  const oppdatering = {};
  KANALER.forEach(function (k, i) {
    document.getElementById('vis_' + i).checked = true;
    document.getElementById('min_' + i).value = k.min;
    document.getElementById('max_' + i).value = k.maks;
    oppdatering[k.akse + '.visible'] = true;
    oppdatering[k.akse + '.range'] = k.invertert ? [k.maks, k.min] : [k.min, k.maks];
  });
  Plotly.restyle('plott', {'visible': true});
  Plotly.relayout('plott', oppdatering);
}
</script>
"""

_KONTROLL_CSS = """
<style>
  body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; background: #fff; }
  .kontroll { padding: 10px 14px; border-bottom: 1px solid #ddd; background: #fafafa; }
  .knapper { margin-bottom: 8px; }
  button { font-size: 13px; padding: 6px 12px; margin-right: 8px; cursor: pointer; }
  .hint { font-size: 12px; color: #555; }
  table { border-collapse: collapse; font-size: 12px; }
  th, td { padding: 2px 10px 2px 0; text-align: left; }
  th { color: #666; font-weight: 600; }
  td input[type=number] { width: 74px; font-size: 12px; padding: 2px 4px; }
  .farge { display: inline-block; width: 10px; height: 10px; margin-right: 6px;
           border-radius: 2px; vertical-align: middle; }
  /* Plottet faar plass til alle hoyreaksene. Paa en smal skjerm ruller det
     sidelengs i stedet for at aksene kryper oppaa hverandre. */
  #plott { min-width: __MINBREDDE__px; }
  @media print {
    @page { size: A4 landscape; margin: 8mm; }
    .kontroll { display: none !important; }
    body { margin: 0; }
    #plott { height: 190mm !important; }
  }
</style>
"""


def bygg_interaktiv_html(df: pd.DataFrame, rader: Sequence[dict[str, Any]],
                         segmenter: Sequence[tuple[int, int]],
                         kanaler: Sequence[tuple[str, str, str]],
                         utfil: str | Path,
                         grenser: dict[str, tuple[float, float]] | None = None,
                         *, maks_dybde: float | None = None,
                         min_r2_telling: float = 0.9,
                         tittel: str = "Acron r\u00e5data - samlet plott "
                                        "med delt Y-akse",
                         cdn: bool = False,
                         stopp: Sequence[Mapping[str, Any]] | None = None,
                         fjern_uryddig: bool = True,
                         stopp_spenn_cm: float = 2.0,
                         stopp_min_s: float = 600.0) -> Path:
    """Skriver en zoombar HTML der hver akse kan skrus av og skaleres selv.

    Samme kutt som PNG-en: stopp og 'uryddig' blir tatt ut av x-aksen og
    merket med brudd og farge. Alt ligger i filen - plotly-biblioteket ogsaa -
    saa den aapner seg paa industripc-en uten internett. Utskrift gaar via
    nettleserens "Skriv ut / lagre som PDF".
    """
    import json

    import plotly.graph_objects as go

    stopp = list(stopp or [])
    tider = df["Tid"]
    t_rel = (tider - tider.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
    spenn: list[tuple[int, int]] = [(s["a"], s["b"]) for s in stopp]
    if fjern_uryddig:
        for (i0, i1), rad in zip(segmenter, rader):
            if rad["merknad"] == "uryddig":
                spenn.append((i0, i1))
    spenn = _slå_sammen_spenn(spenn)
    x, fjern, _cum = komprimer_akse(t_rel, spenn)

    def stopp_ved(a: int, b: int) -> Mapping[str, Any] | None:
        for s0 in stopp:
            if not (s0["b"] < a or s0["a"] > b):
                return s0
        return None

    def klipp(serie: Any) -> list:
        y = np.asarray(serie, dtype=float)
        return np.where(fjern, np.nan, y).tolist()

    dybde = df["dybde"].to_numpy(dtype=float)
    pene = dybde[np.isfinite(dybde)]
    topp = maks_dybde if maks_dybde else (
        float(pene.max()) * 1.03 if pene.size else 1.0)

    fig = go.Figure()
    fig.add_trace(go.Scattergl(x=x.tolist(), y=klipp(dybde), name="Dybde [cm]",
                               line=dict(color=FARGE_DYBDE, width=2),
                               connectgaps=False))
    for i, (nokkel, etikett, farge) in enumerate(kanaler):
        fig.add_trace(go.Scattergl(x=x.tolist(),
                                   y=klipp(df[nokkel].to_numpy(dtype=float)),
                                   name=etikett, yaxis=f"y{i + 2}",
                                   line=dict(color=farge, width=1),
                                   connectgaps=False))

    # -- produksjonsomraadet: start og stopp tydelig merket -------------------
    for xv, tekst, farge in ((x[0], "start", "#2e7d32"),
                             (x[-1], "stopp", "#b71c1c")):
        fig.add_shape(type="line", xref="x", yref="paper", x0=xv, x1=xv,
                      y0=0.0, y1=1.0, line=dict(color=farge, width=1.3))
        fig.add_annotation(x=xv, y=0.99, xref="x", yref="paper", text=tekst,
                           showarrow=False, font=dict(color=farge, size=11),
                           bgcolor="white",
                           xanchor="left" if tekst == "start" else "right")

    # -- klammer nederst i datafeltet (samme som i PNG-en) -------------------
    klamme_y = 0.965 * topp
    hake = 0.020 * topp
    _bredder = [(float(x[int(j1)]) - float(x[int(j0)]))
                for j0, j1 in segmenter
                if not (fjern[int(j0)] and fjern[int(j1)])]
    _bredder = [b for b in _bredder if b > 0]
    _bredde = (float(x[-1] - x[0]) if x.size > 1 else 1.0) or 1.0
    _andel = (float(np.median(_bredder)) / _bredde) if _bredder else 1.0
    n_rader = max(1, min(4, int(math.ceil(0.055 / _andel)))) if _andel > 0 else 1
    n_tekst = 0
    for nummer, (i0, i1) in enumerate(segmenter):
        if fjern[int(i0)] and fjern[int(i1)]:
            continue                    # hele fasen er klippet bort
        rad = rader[nummer]
        fart = float(rad["stigningstall_cm_min"])
        if rad["merknad"] == "stopp":
            tekst = "stopp"
        elif not teller_med(rad, min_r2_telling):
            # Holdes utenfor lengde og snitt - da skal det ikke staa et tall.
            tekst = "\u2014"
        else:
            tekst = f"{fart:.1f} cm/min"
        x0, x1 = float(x[int(i0)]), float(x[int(i1)])
        if x1 <= x0:
            continue
        midt = 0.5 * (x0 + x1)
        gap = 0.25 * (x1 - x0)
        for a, b in ((x0, midt - gap), (midt + gap, x1)):
            if b > a:
                fig.add_shape(type="line", xref="x", yref="y", x0=a, x1=b,
                              y0=klamme_y, y1=klamme_y,
                              line=dict(color="black", width=1.4))
        for xv in (x0, x1):
            fig.add_shape(type="line", xref="x", yref="y", x0=xv, x1=xv,
                          y0=klamme_y - hake, y1=klamme_y + hake,
                          line=dict(color="black", width=1.4))
        # Etikettene fordeles paa flere rader naar fasene er smale, saa to
        # naboer ikke skrives oppaa hverandre (samme som i PNG-en).
        if n_rader == 1:
            y_lab = klamme_y
        else:
            y_lab = klamme_y + (0.5 - (n_tekst % n_rader)
                                / (n_rader - 1)) * 0.055 * topp
        n_tekst += 1
        fig.add_annotation(x=midt, y=y_lab, xref="x", yref="y", text=tekst,
                           showarrow=False, font=dict(color="black", size=11),
                           bgcolor="white")

    # -- bruddene: to skraa streker + én farget strek per stopp --------------
    for a, b in spenn:
        xb = float(x[int(a)])
        s = stopp_ved(a, b)
        farge = str(s["farge"]) if s else "#555555"
        fig.add_shape(type="line", xref="x", yref="paper", x0=xb, x1=xb,
                      y0=0.0, y1=1.0, line=dict(color=farge, width=1.7))
        fig.add_annotation(x=xb, y=-0.045, xref="x", yref="paper", text="//",
                           showarrow=False, font=dict(color="#111", size=14))
        if s:
            fig.add_annotation(x=xb, y=0.02, xref="x", yref="paper",
                               text=f"S{s['nr']}", showarrow=False,
                               font=dict(color=farge, size=11))

    # -- skillelinjer --------------------------------------------------------
    for nummer, (i0, i1) in enumerate(segmenter):
        if fjern[int(i0)] and fjern[int(i1)]:
            continue
        for i in ((i0,) if nummer else (i0, i1)):
            xv = float(x[int(i)])
            fig.add_shape(type="line", xref="x", yref="paper", x0=xv, x1=xv,
                          y0=0.0, y1=1.0,
                          line=dict(color="#d62728", width=1, dash="dash"))

    start_tekst = tider.iloc[0].strftime("%d.%m.%Y %H:%M")
    slutt_tekst = tider.iloc[-1].strftime("%H:%M")
    aktiv_s = float(x[-1] - x[0]) if x.size > 1 else 0.0
    total_s = float(t_rel[-1] - t_rel[0]) if t_rel.size > 1 else 0.0
    pause_s = sum(float(s["varighet_s"]) for s in stopp)
    borte_s = max(0.0, total_s - aktiv_s)
    uryddig_s = max(0.0, borte_s - pause_s)
    # Datafeltet bruker venstre del av arket, resten er plass til at aksene
    # kan staa ved siden av hverandre. Bredden til aksene er fast, saa
    # avstanden mellom dem tilpasser seg antall kanaler.
    antall_kanaler = max(1, len(kanaler))
    # Hver hoyreakse trenger plass til streken, hakene og tallene sine ved
    # siden av naboen. Fem kanaler er den bredden vi hadde (0,28); flere
    # kanaler tar mer, men aldri mer enn 62 % av arket - da blir kurvene for
    # korte. Selve plottet vokser med, saa det er plass.
    BREDDE_AKSER = min(0.62, max(0.28, 0.056 * antall_kanaler))
    BILDEBREDDE = int(660 + 95 * antall_kanaler)
    tick_pos, tick_lab = akse_ticks(x, fjern, tider, antall=10)
    oppsett: dict[str, Any] = dict(
        title=dict(text=f"{tittel.replace(chr(10), '<br>')}"
                        f"<br><sub>{start_tekst}-{slutt_tekst} \u00b7 "
                        f"x-aksen viser {aktiv_s / 60.0:.0f} min aktiv tid "
                        f"av {total_s / 60.0:.0f} min "
                        f"({borte_s / 60.0:.0f} min klippet bort: "
                        f"{pause_s / 60.0:.0f} min pause, "
                        f"{uryddig_s / 60.0:.0f} min uryddig)</sub>",
                   automargin=True, pad=dict(t=34)),
        template="plotly_white",
        height=880,
        width=BILDEBREDDE,
        margin=dict(l=62, r=28.0, t=210, b=68),
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.015, x=0),
        xaxis=dict(domain=[0.0, 1.0 - BREDDE_AKSER], showgrid=True,
                   gridcolor="#e8e8e8",
                   title=dict(text="Klokkeslett (HH:MM)", standoff=6),
                   tickmode="array", tickvals=tick_pos, ticktext=tick_lab,
                   tickangle=0, automargin=True),
        yaxis=dict(title=dict(text=f"Dybde [cm] (0 \u00f8verst - {topp:.0f} "
                                   f"nederst)",
                              font=dict(color=FARGE_DYBDE)),
                   range=[topp, 0.0], tickfont=dict(color=FARGE_DYBDE),
                   showgrid=True, gridcolor="#e8e8e8", zeroline=False),
    )
    # Hele aksen flyttes: 'anchor="free"' + 'position' setter aksestreken,
    # hakene og tallene paa sin egen loddrette linje ute i margen, akkurat
    # som matplotlibs spine.set_position(('outward', 45)). Hakene kan da
    # vaere korte - de rekker ikke inn i naboen.
    for i, (nokkel, etikett, farge) in enumerate(kanaler):
        lav, hoy = (grenser or {}).get(nokkel, (0.0, 1.0))
        oppsett[f"yaxis{i + 2}"] = dict(
            title=dict(text=etikett, font=dict(color=farge), standoff=8),
            tickfont=dict(color=farge, size=10),
            overlaying="y", side="right", anchor="free",
            position=(1.0 - BREDDE_AKSER
                      + BREDDE_AKSER * (i + 0.5) / antall_kanaler),
            ticks="outside", ticklen=5, tickcolor=farge,
            showline=True, linecolor=farge, linewidth=1.4,
            range=[lav, hoy], showgrid=False, zeroline=False,
        )

    # Radene i kontrollpanelet og dataene til JS-en maa ha samme rekkefolge:
    # 0 = dybde (venstre akse), 1..N = kanalene (hoyreaksene).
    data: list[dict[str, Any]] = [{
        "navn": "Dybde [cm]", "akse": "yaxis", "trace": 0, "min": 0.0,
        "maks": float(round(topp)), "farge": FARGE_DYBDE,
        "invertert": True,
    }]
    for i, (nokkel, etikett, farge) in enumerate(kanaler):
        lav, hoy = (grenser or {}).get(nokkel, (0.0, 1.0))
        data.append({"navn": etikett, "akse": f"yaxis{i + 2}", "trace": i + 1,
                     "min": lav, "maks": hoy, "farge": farge,
                     "invertert": False})

    # -- firmalogo: svakt, gjennomsiktig vannmerke bak kurvene --------------
    logo = logo_datauri("image/svg+xml")
    if logo:
        oppsett["images"] = [dict(
            source=logo, xref="paper", yref="paper",
            x=0.5, y=0.5, sizex=0.42, sizey=0.30,
            xanchor="center", yanchor="middle", sizing="contain",
            opacity=FIRMA_LOGO_OPACITY, layer="below",
        )]
    fig.update_layout(**oppsett)

    html = fig.to_html(full_html=True, include_plotlyjs=(not cdn),
                       div_id="plott", config={"responsive": True,
                                               "displaylogo": False})
    html = html.replace("<body>", "<body>"
                        + _KONTROLL_CSS.replace("__MINBREDDE__",
                                                str(BILDEBREDDE))
                        + _KONTROLL_HTML.replace("__RADER__",
                                                 _kontroll_rader(data)))
    hode_stopp = (
        "Stopp - nummerert fra dypest til grunnest (farge = streken i "
        f"plottet) \u00b7 en pause er innenfor +/-{stopp_spenn_cm:g} cm i "
        f"minst {stopp_min_s / 60.0:g} min \u00b7 x-aksen viser "
        f"{aktiv_s / 60.0:.0f} min aktiv tid av {total_s / 60.0:.0f} min "
        f"({borte_s / 60.0:.0f} min klippet bort)")
    html = html.replace("</body>", _FOTNOTE_STIL
                        + _stopp_tabell_html(stopp, hode_stopp)
                        + _KONTROLL_JS
                        .replace("__KANALER__", json.dumps(data)) + "</body>")

    ut = Path(utfil)
    ut.parent.mkdir(parents=True, exist_ok=True)
    ut.write_text(html, encoding="utf-8")
    return ut


def _kontroll_rader(data: Sequence[dict[str, Any]]) -> str:
    """HTML-radene i kontrollpanelet: vis / kanal / min / maks."""
    return "".join(
        f'<tr><td><input type="checkbox" id="vis_{i}" checked '
        f'onchange="settSynlig({i})"></td>'
        f'<td><span class="farge" style="background:{rad["farge"]}"></span>'
        f'{rad["navn"]}</td>'
        f'<td><input type="number" id="min_{i}" value="{rad["min"]:g}" '
        f'step="any" onchange="settSkala({i})"></td>'
        f'<td><input type="number" id="max_{i}" value="{rad["maks"]:g}" '
        f'step="any" onchange="settSkala({i})"></td></tr>'
        for i, rad in enumerate(data))


_FOTNOTE_STIL = """
<style>
  .stopptabell { padding: 6px 14px 18px; font-family: "Segoe UI", Arial,
                 sans-serif; font-size: 12px; }
  .stopptabell h3 { margin: 6px 0 6px; font-size: 13px; }
  .stopptabell table { border-collapse: collapse; }
  .stopptabell th, .stopptabell td { border: 1px solid #ddd;
                                     padding: 3px 9px; text-align: left; }
  .stopptabell th { background: #f4f4f4; font-weight: 600; }
</style>
"""


def _stopp_tabell_html(stopp: Sequence[Mapping[str, Any]],
                       hode: str | None = None) -> str:
    """Fotnoten som HTML-tabell under plottet - én farget rad per stopp.

    Nummereringen gaar fra DYPEST til GRUNNEST (stopp 1 = den dypeste),
    akkurat som paa PNG-en, saa de to visningene sier det samme.
    """
    if hode is None:
        hode = ("Stopp - nummerert fra dypest til grunnest "
                "(farge = streken i plottet)")
    if not stopp:
        return (f'<div class="stopptabell"><h3>{hode}</h3>'
                '<p style="color:#666">Ingen stopp over grensen.</p></div>')
    rader: list[str] = []
    for s in stopp:
        delta = float(s["delta_dybde_cm"])
        retning = "ned" if delta > 0.5 else ("opp" if delta < -0.5 else "side")
        farge = str(s["farge"])
        rader.append(
            f'<tr style="color:{farge};font-weight:600">'
            f'<td>Stopp {s["nr"]}</td>'
            f'<td>{s["varighet"]}</td>'
            f'<td>{str(s["fra_iso"])[11:19]}</td>'
            f'<td>{float(s["dybde_stopp_cm"]):.0f} cm</td>'
            f'<td>{str(s["til_iso"])[11:19]}</td>'
            f'<td>{float(s["dybde_start_cm"]):.0f} cm</td>'
            f'<td>{float(s["lengde_cm"]):.0f} cm</td>'
            f'<td>{delta:+.0f} cm ({retning})</td></tr>')
    return (
        f'<div class="stopptabell"><h3>{hode}</h3><table><tr>'
        '<th>nr</th><th>varighet</th><th>kl. stopp</th><th>dybde stopp</th>'
        '<th>kl. start</th><th>dybde start</th><th>lengde</th>'
        '<th>&Delta; dybde</th></tr>'
        + "".join(rader) + '</table></div>')


# ---------------------------------------------------------------------------
# Oekter: pel og metode fra loggen
# ---------------------------------------------------------------------------


def metode_navn(modus: str) -> str:
    """Riggens metodenavn slik det skrives i rapporten."""
    ren = str(modus).strip()
    return MODUS_NAVN.get(ren.upper(), ren.lower())


def _filnavn_del(tekst: str) -> str:
    """Gjoer en tekst om til noe som kan staa i et filnavn."""
    ren = "".join(t if (t.isalnum() or t == "-") else "_"
                  for t in str(tekst).lower())
    return "_".join(del_ for del_ in ren.split("_") if del_)


def _mappenavn(tekst: str) -> str:
    """Mappenavn som beholder store og smaa bokstaver - pelnavnet er 'G21'."""
    ren = "".join(t if (t.isalnum() or t in "-_") else "_"
                  for t in str(tekst).strip())
    return "_".join(del_ for del_ in ren.split("_") if del_)


def finn_okter(df: pd.DataFrame, min_lengde_s: float = 60.0,
               maks_hull_s: float = LOGG_HULL_S) -> list[dict[str, Any]]:
    """Operasjonene i loggen: hvilken pel, hvilken metode, og hvor.

    Riggen skriver pelnummer og metode (PILOTDRILL / PREJETTING / GROUTING)
    for hver prove. Hver gang en av dem skifter begynner en ny oekt - det er
    den inndelingen rapporten skal ha, ikke en grense gjettet fra flowen.

    Korte biter (under ``min_lengde_s``) hoppes over: de er etterlatenskaper i
    loggen og ikke arbeid.

    Loggen kan romme flere dager - en maaned i én fil. Da staar samme pel og
    samme metode igjen etter natten, men det er to oekter, ikke én paa atten
    timer. Et opphold i loggen lengre enn ``maks_hull_s`` bryter derfor
    oekten, akkurat som et metodskifte gjor.
    """
    if PEL_KOLONNE not in df.columns and MODUS_KOLONNE not in df.columns:
        return []
    tomt = pd.Series("", index=df.index)

    def _ren(kolonne: str) -> pd.Series:
        if kolonne not in df.columns:
            return tomt
        tekst = df[kolonne].astype(str).str.strip()
        return tekst.where(~tekst.isin(["", "nan", "NaN", "None"]), "")

    nokler = list(zip(_ren(PEL_KOLONNE).tolist(),
                      _ren(MODUS_KOLONNE).tolist()))
    t = df["Tid"]
    # Avstanden mellom hver prove, i sekunder. Regnet ut én gang - aa hente
    # to tidsstempler per linje gaar merkbart tregt paa en maaned med data.
    hull = np.diff(t.to_numpy()).astype("timedelta64[s]").astype(float)
    okter: list[dict[str, Any]] = []
    start = 0
    for i in range(1, len(nokler) + 1):
        if i < len(nokler):
            puster = hull[i - 1] > maks_hull_s
            if nokler[i] == nokler[start] and not puster:
                continue
        pel, metode = nokler[start]
        sek = float((t.iloc[i - 1] - t.iloc[start]).total_seconds())
        if pel and sek >= min_lengde_s:
            okter.append({"pel": pel, "modus": metode, "start": start,
                          "slutt": i - 1, "sek": sek})
        start = i
    return okter


def finn_peler(df: pd.DataFrame, min_lengde_s: float = 60.0,
               maks_hull_s: float = SKIFT_HULL_TIMER * 3600.0
               ) -> list[dict[str, Any]]:
    """Pelene i loggen, én oppfoering per pel.

    Metodeflagget fra riggen er ikke til aa stole paa for lengden: glemmer
    operatoren aa bytte rapport, staar forrige metode igjen lenge etter at
    arbeidet er ferdig - og da blir 'prejet' og 'grouting' av ulik lengde for
    samme pel. Derfor slaas alle oektene med samme pelnavn sammen til én pel,
    og lengden paa arbeidet blir regnet fra signalene i stedet.

    Kommer samme pel tilbake mer enn ``maks_hull_s`` senere, er det en ny
    oekt: neste skift, eller en maaned i én fil der pelen gjentas hver dag.
    'Hele produksjonsomraadet' skal ikke spenne over natten.

    ``moduser`` er metodene som er brukt i pelen, i den rekkefolgen de kom.
    """
    pel = ""
    pels: list[dict[str, Any]] = []
    for okt in finn_okter(df, min_lengde_s):
        puster = float("inf")
        if pels and okt["pel"] == pel:
            puster = float(
                (df["Tid"].iloc[okt["start"]]
                 - df["Tid"].iloc[pels[-1]["slutt"]]).total_seconds())
        if pels and okt["pel"] == pel and puster <= maks_hull_s:
            pels[-1]["slutt"] = okt["slutt"]
            pels[-1]["sek"] = float(
                (df["Tid"].iloc[okt["slutt"]]
                 - df["Tid"].iloc[pels[-1]["start"]]).total_seconds())
            pels[-1]["okter"].append(okt)
            if okt["modus"] not in pels[-1]["moduser"]:
                pels[-1]["moduser"].append(okt["modus"])
        else:
            pel = str(okt["pel"])
            pels.append({"pel": pel, "start": okt["start"],
                         "slutt": okt["slutt"], "sek": okt["sek"],
                         "moduser": [okt["modus"]], "okter": [okt]})
    return pels


def start_stopp_vinduer(df: pd.DataFrame, pel: str | None = None,
                        min_lengde_s: float = 30.0) -> list[tuple[int, int]]:
    """Operatørens egne start/stopp-vinduer, som radindekser ``(i0, i1)``.

    Riggen har en kanal der operatøren selv markerer at prosessen gaar:
    1 mens den kjoerer, 0 naar den er slutt. Den er SANNheten om naar arbeidet
    begynte og sluttet - og den ser forbi pausene. Den signalbaserte
    inndelingen stopper ved den foerste stillheten lengre enn ``tillatt_hull_s``,
    og da blir en grouting som er delt i flere runder kuttet ved foerste pause.

    Ett merke = ett sammenhengende strekk med 1-ere. Korte merker (under
    ``min_lengde_s``) og merker uten pelnavn hoppes over - de er stoev i
    loggen, ikke arbeid.

    Uten kanalen i filen (eldre eksporter) returneres en tom liste, og da
    gjelder den gamle inndelingen uendret.
    """
    if STARTSTOPP_KOLONNE not in df.columns:
        return []
    verdier = pd.to_numeric(df[STARTSTOPP_KOLONNE], errors="coerce")
    pae = (verdier == 1.0).to_numpy()
    if not bool(pae.any()):
        return []
    tider = df["Tid"]
    if PEL_KOLONNE in df.columns:
        navn = df[PEL_KOLONNE].astype(str).str.strip()
        navn = navn.where(~navn.isin(["", "nan", "NaN", "None"]), "")
    else:
        navn = pd.Series("", index=df.index)

    ut: list[tuple[int, int]] = []
    n = len(pae)
    i = 0
    while i < n:
        if not pae[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and pae[j + 1]:
            j += 1
        her = str(navn.iloc[i]).strip()
        sek = float((tider.iloc[j] - tider.iloc[i]).total_seconds())
        if (sek >= min_lengde_s and her
                and (pel is None or her == pel)):
            ut.append((i, j))
        i = j + 1
    return ut


def _merke_for_okt(merker: Sequence[tuple[int, int]] | None,
                   i0: int, i1: int,
                   min_lengde_s: float = 60.0) -> tuple[int, int] | None:
    """Start/stopp-merket som hoerer til oekten ``[i0, i1]``.

    Merket maa ligge nesten helt inne i oekten (minst 90 % av sin egen lengde)
    og overlappe den med minst ``min_lengde_s`` sekunder. Da kan ikke ett og
    samme merke bli brukt av to oekter samtidig, og et merke som bare saavidt
    berorer kanten av oekten (der operatøren trykket for neste arbeid) blir
    ikke blandet inn.
    """
    if not merker:
        return None
    best: tuple[int, int] | None = None
    best_del = 0.0
    for m0, m1 in merker:
        lengde = float(m1 - m0)
        if lengde <= 0.0:
            continue
        overlapp = float(min(i1, m1) - max(i0, m0))
        if overlapp < min_lengde_s:
            continue
        del_ = overlapp / lengde
        if del_ >= 0.9 and del_ > best_del:
            best, best_del = (m0, m1), del_
    return best


def produksjonsomrade(df: pd.DataFrame, pel: Mapping[str, Any], *,
                      terskel: float = 5.0,
                      tillatt_hull_s: float = 180.0) -> tuple[int, int]:
    """Fra forste til siste prove i pelen der det faktisk arbeides.

    Hver oekt faar sitt eget vindu, styrt av den kanalen som hoerer til
    metoden: luft og rotasjon naar det bores, grouttrykk naar det jettes. Det
    er ikke til aa komme utenom - under en pilotboring staar grouttrykket paa
    null hele tiden, og i en pilotboring uten luft er det bare rotasjonen som
    viser at riggen gaar.

    Pelens omraade gaar fra starten av det forste til slutten av det siste
    vinduet. En pause midt i pelen, eller et metodeflagg som staar igjen etter
    at arbeidet er ferdig, forskyver da ingenting.
    """
    forste: int | None = None
    siste: int | None = None
    for okt in pel["okter"]:
        del_ = df.iloc[okt["start"]:okt["slutt"] + 1]
        kolonne, i0, i1 = velg_kuttvindu(del_, terskel=terskel,
                                         tillatt_hull_s=tillatt_hull_s,
                                         modus=str(okt["modus"]))
        if kolonne is None:            # ingenting som tyder paa arbeid her
            continue
        a, b = okt["start"] + i0, okt["start"] + i1
        forste = a if forste is None else min(forste, a)
        siste = b if siste is None else max(siste, b)

    # Operatørens merker utvider omraadet. 'velg_kuttvindu' kutter ved den
    # foerste stillheten lengre enn 'tillatt_hull_s'; markerer operatøren at
    # prosessen fortsatte etter den, er resten vaart arbeid ogsaa. Uten dette
    # blir alt etter foerste pause liggende utenfor omraadet og forsvinner.
    # Bare merker inne i pelens eget tidsrom teller: samme pelnavn kan komme
    # tilbake en helt annen dag, og da er det to peler, ikke én.
    for m0, m1 in start_stopp_vinduer(df, pel=str(pel["pel"])):
        if m1 < pel["start"] or m0 > pel["slutt"]:
            continue
        forste = m0 if forste is None else min(forste, m0)
        siste = m1 if siste is None else max(siste, m1)

    if forste is None or siste is None:
        return pel["start"], pel["slutt"]
    return forste, siste


def arbeidsvinduer(df: pd.DataFrame, okter: Sequence[Mapping[str, Any]], *,
                   terskel: float = 5.0, tillatt_hull_s: float = 180.0,
                   min_lengde_s: float = 60.0,
                   grense: tuple[int, int] | None = None,
                   merker: Sequence[tuple[int, int]] | None = None
                   ) -> list[tuple[int, int]]:
    """Arbeidsvinduet for hver sammenhengende arbeidsperiode i ``okter``.

    Oekter som ligger ner hverandre i tid er samme arbeid: riggen deler en
    grouting i to naar operatoren bytter rapport eller logger kort av. De slaas
    derfor sammen for vinduet regnes ut. Er det derimot timer mellom dem, er
    det to forskjellige ting, og da kommer det to vinduer.

    Vinduet selv kommer fra bevegelsen i den retningen metoden hoerer til
    (:func:`klipp_til_bevegelse`), ikke fra aktivitetskanalene. Grouttrykket
    alene mister begynnelsen av et opptrekk - operatoren begynner aa trekke for
    trykket er oppe - mens bevegelsen alltid viser hvor arbeidet begynner. Da
    starter hendelsen paa den dybden oversiktsplottet viser for den, og foer og
    etter (og pauser lengre enn ``tillatt_hull_s``) faller utenfor.
    """
    sortert = sorted(okter, key=lambda o: int(o["start"]))
    bunter: list[list[Mapping[str, Any]]] = []
    for okt in sortert:
        if bunter:
            hull = float((df["Tid"].iloc[int(okt["start"])]
                          - df["Tid"].iloc[int(bunter[-1][-1]["slutt"])]
                          ).total_seconds())
            if hull <= tillatt_hull_s:
                bunter[-1].append(okt)
                continue
        bunter.append([okt])

    vinduer: list[tuple[int, int]] = []
    for bunt in bunter:
        i0, i1 = int(bunt[0]["start"]), int(bunt[-1]["slutt"])
        if grense is not None:
            i0, i1 = max(i0, grense[0]), min(i1, grense[1])
        if i1 - i0 < 30:
            continue
        merke = _merke_for_okt(merker, i0, i1, min_lengde_s)
        if merke is None:
            j0, j1 = klipp_til_bevegelse(df.iloc[i0:i1 + 1],
                                         str(bunt[0]["modus"]))
            j0, j1 = i0 + j0, i0 + j1
        else:
            # Operatøren har markert naar prosessen gikk. Da er det vinduet
            # sannheten - ogsaa naar arbeidet er delt i flere runder med
            # pauser imellom. Vinduet brukes som merket er, ikke klippet til
            # metodeflagget: flagget skifter seinere enn arbeidet begynner,
            # og da ville begynnelsen av pelen falle utenfor.
            j0, j1 = int(merke[0]), int(merke[1])
            if grense is not None:
                j0, j1 = max(j0, grense[0]), min(j1, grense[1])
        vinduer.append((j0, j1))
    return vinduer


def _fall(df: pd.DataFrame, i0: int, i1: int) -> float:
    """Hvor langt dybden flyttet seg over vinduet, i cm. Positivt = nedover."""
    dybde = df["dybde"].to_numpy(dtype=float)
    start = dybde[i0:i0 + 5]
    slutt = dybde[max(i0, i1 - 4):i1 + 1]
    start = start[~np.isnan(start)]
    slutt = slutt[~np.isnan(slutt)]
    if start.size == 0 or slutt.size == 0:
        return 0.0
    return float(np.median(slutt) - np.median(start))


def _flagg(okter: Sequence[Mapping[str, Any]], vindu: tuple[int, int]) -> str:
    """Metoden riggen hadde stilt inn da vinduet begynte."""
    for okt in okter:
        if int(okt["start"]) - 5 <= vindu[0] <= int(okt["slutt"]) + 5:
            return str(okt["modus"])
    return ""


def _pumper(df: pd.DataFrame, i0: int, i1: int) -> bool:
    """Pumpes det grout i vinduet? Uten grout er det ikke jetting.

    Under baade prejet og grouting staar grouttrykket eller groutflowen paa
    nesten hele tiden. Flytter dybden seg oppover uten at det pumpes, er det
    stanga som trekkes ut - ikke produksjon.
    """
    bit = df.iloc[i0:i1 + 1]
    for navn, grense in (("grouttrykk", 5.0), ("groutflow", 5.0)):
        if navn in bit.columns:
            verdier = bit[navn].to_numpy(dtype=float)
            if np.count_nonzero(verdier > grense) >= max(10,
                                                         0.1 * verdier.size):
                return True
    return False


def velg_hendelser(df: pd.DataFrame, okter: Sequence[Mapping[str, Any]], *,
                   grense: tuple[int, int] | None = None,
                   tillatt_hull_s: float = 180.0, min_fall_cm: float = 5.0,
                   min_boring_cm: float = 10.0,
                   merknader: list[str] | None = None
                   ) -> list[dict[str, Any]]:
    """Én pilotboring, én prejet og én grouting - i den rekkefolgen de gjores.

    Metodeflagget fra riggen henger etter: glemmer operatoren aa bytte rapport,
    staar forrige metode igjen mens neste arbeid gjores - 22.09. sto det
    'grouting' mens pelen ble boret, og 'pilotboring' mens den ble jettet.
    Det som ikke lyver, er hva riggen faktisk gjor:

        nedover uten grout   = pilotboring (stanga kjoeres ned)
        oppover med grout    = jetting; forste opptur er prejet, neste grouting
        oppover uten grout   = stanga trekkes ut, ikke produksjon
        stille               = ingenting

    Oektene slaas sammen per metode forst, for det er bare oekter av samme
    metode som hoerer til samme arbeid. Gaar det ikke oppover med grout i det
    hele tatt, blir det ingen rapport - da er pelen bare boret.
    """
    funn: list[tuple[tuple[int, int], float, str]] = []
    merker: list[tuple[int, int]] = []
    if okter:
        a_okt = min(int(o["start"]) for o in okter)
        b_okt = max(int(o["slutt"]) for o in okter)
        merker = [m for m in start_stopp_vinduer(df,
                                                 pel=str(okter[0]["pel"]))
                  if m[1] >= a_okt and m[0] <= b_okt]
    for modus in dict.fromkeys(str(o["modus"]) for o in okter):
        gruppe = [o for o in okter if str(o["modus"]) == modus]
        for vindu in arbeidsvinduer(df, gruppe, grense=grense,
                                    tillatt_hull_s=tillatt_hull_s,
                                    merker=merker):
            funn.append((vindu, _fall(df, vindu[0], vindu[1]), modus))
    funn.sort()

    ned = [f for f in funn if f[1] >= min_boring_cm]
    opp = [f for f in funn
           if f[1] <= -min_fall_cm and _pumper(df, f[0][0], f[0][1])]
    if not opp:
        # Pelen er bare BORET - ingen jetting. Hullet er likevel resultatet,
        # og det skal ha sin egen pilotboring-rapport. Ellers mangler pelen
        # helt i viseren, og ingen kan se hvor langt den ble boret. Det er
        # saerlig viktig naar boringen skjer én dag og jettingen en annen.
        if ned:
            return [{"modus": "PILOTDRILL", "vindu": ned[0][0]}]
        return []

    hendelser: list[dict[str, Any]] = []
    if ned:
        hendelser.append({"modus": "PILOTDRILL", "vindu": ned[0][0]})
    if len(opp) == 1:
        # Bare én opptur: da maa flagget avgjore om det er prejet eller grouting.
        modus = opp[0][2] if opp[0][2] in ("PREJETTING", "GROUTING") \
            else "PREJETTING"
        hendelser.append({"modus": modus, "vindu": opp[0][0]})
    elif len(opp) > 1:
        hendelser.append({"modus": "PREJETTING", "vindu": opp[0][0]})
        hendelser.append({"modus": "GROUTING", "vindu": opp[1][0]})

    if merknader is not None:
        brukt = {tuple(h["vindu"]) for h in hendelser}
        for vindu, fall, flagg in funn:
            tid = (f"{df['Tid'].iloc[vindu[0]]:%H:%M:%S}-"
                   f"{df['Tid'].iloc[vindu[1]]:%H:%M:%S}")
            if tuple(vindu) in brukt:
                if (fall >= min_boring_cm
                        and flagg in ("PREJETTING", "GROUTING")):
                    merknader.append(f"loggen sa {metode_navn(flagg)} {tid}, "
                                     f"men dybden gaar nedover - regnet som "
                                     f"boring")
                elif fall <= -min_fall_cm and flagg == "PILOTDRILL":
                    merknader.append(f"loggen sa pilotboring {tid}, men "
                                     f"dybden gaar oppover - regnet som "
                                     f"jetting")
                continue
            if abs(fall) < min_fall_cm:
                grunn = "flyttet seg ikke"
            elif fall > 0:
                grunn = ("for lite nedover" if fall < min_boring_cm
                         else "etterarbeid")
            elif not _pumper(df, vindu[0], vindu[1]):
                grunn = "ingen grout i perioden"
            else:
                grunn = "en opptur mer enn pelen skal ha"
            merknader.append(
                f"utenom: {tid} ({metode_navn(flagg)}, {abs(fall):.0f} cm "
                f"{'ned' if fall > 0 else 'opp'}, {grunn})")
    return hendelser


def klipp_til_bevegelse(bit: pd.DataFrame, modus: str = "",
                        toleranse_cm: float = 5.0) -> tuple[int, int]:
    """Kutter en oekt ned til den forflytningen den faktisk er.

    En oekt er én passasje: boret gaar ned fra toppen til bunn, eller stanga
    trekkes opp fra bunn til topp. Foer og etter staar riggen i ro, og mellom
    passasjene ligger det en rask inn- og utkjoering som ikke hoerer til
    noen av dem.

    Vi leter derfor opp den stoerste forflytningen i oekten i begge
    retninger, og tar den lengste: opptrekk (hoeyest foerst, lavest etterpaa)
    eller boring (motsatt). Da havner starten der passasjen begynner - baade
    prejeten og groutingen av G21 begynner paa 213 cm, paa bunn - og ikke
    midt i en encodertullefeil slik den forste bevegelsen gjorde.

    Er det ingen forflytning aa snakke om (under ``toleranse_cm``), blir hele
    oekten med. Dybden glattes foerst, saa encodersprang ikke teller.
    """
    y = _glattet(bit["dybde"].to_numpy(dtype=float), 11.0)
    n = int(y.size)
    if n < 3:
        return 0, max(0, n - 1)

    opp = (0.0, 0, n - 1)                  # hoyest foerst, lavest etterpaa
    lav_etter, lav_i = float(y[-1]), n - 1
    for i in range(n - 2, -1, -1):
        verdi = float(y[i])
        if verdi - lav_etter > opp[0]:
            opp = (verdi - lav_etter, i, lav_i)
        if verdi < lav_etter:
            lav_etter, lav_i = verdi, i

    ned = (0.0, 0, n - 1)                  # lavest foerst, hoyest etterpaa
    hoy_etter, hoy_i = float(y[-1]), n - 1
    for i in range(n - 2, -1, -1):
        verdi = float(y[i])
        if hoy_etter - verdi > ned[0]:
            ned = (hoy_etter - verdi, i, hoy_i)
        if verdi > hoy_etter:
            hoy_etter, hoy_i = verdi, i

    # Hvilken vei er arbeidet? Under jetting trekkes stanga opp, under
    # pilotboring gaar den ned. Ligger begge passasjene inne i oekten - og det
    # gjoer de naar stanga kjoeres ned igjen foer groutingen - velger vi den
    # retningen metoden hoerer til, saa lenge den er noenlunde like stor.
    opp_er_arbeid = str(modus).strip().upper() in ("PREJETTING", "GROUTING")
    forst = opp if opp_er_arbeid else ned
    andre = ned if opp_er_arbeid else opp
    if forst[0] > toleranse_cm and forst[0] >= 0.5 * andre[0]:
        i0, i1 = forst[1], forst[2]
    elif andre[0] > toleranse_cm:
        i0, i1 = andre[1], andre[2]
    else:
        return 0, n - 1                    # sto i ro hele oekten
    if i1 - i0 < 30:
        return 0, n - 1
    return i0, i1


def varighet_tekst(sekunder: float) -> str:
    """'8 min' eller '1 t 12 min'."""
    minutter = int(round(sekunder / 60.0))
    if minutter < 90:
        return f"{minutter} min"
    timer, minutter = divmod(minutter, 60)
    return f"{timer} t {minutter} min"


def pel_tittel(df: pd.DataFrame, pel: dict[str, Any]) -> str:
    """Overskriften paa arket: pel, metodene som er brukt, og anleggsdata."""
    metoder = ", ".join(metode_navn(str(m)) for m in pel["moduser"])
    deler = [f"Pel {pel['pel']} - {metoder}"]
    for kolonne, etikett in OKT_OVERSKRIFT:
        if kolonne not in df.columns:
            continue
        verdier = df[kolonne].dropna().astype(str).str.strip()
        verdier = verdier[~verdier.isin(["", "nan", "None"])]
        if verdier.empty:
            continue
        verdi = str(verdier.mode().iloc[0]).strip()
        if verdi:
            deler.append(f"{etikett} {verdi}")
    return " \u00b7 ".join(deler)


def skriv_rapport(periode: pd.DataFrame,
                  kanaler: Sequence[tuple[str, str, str]],
                  grenser: dict[str, tuple[float, float]] | None,
                  args: argparse.Namespace, *, utfil: Path,
                  pel: dict[str, Any] | None = None,
                  omrade: tuple[int, int] | None = None,
                  metode: str | None = None,
                  ferdige: Sequence[tuple[int, int]] | None = None
                  ) -> tuple[Path, Path | None]:
    """Kutter, segmenterer og skriver PNG (+ interaktiv HTML) for én periode.

    ``omrade`` er produksjonsomraadet som indekser i ``periode`` (fra
    :func:`produksjonsomrade`). Er den ikke oppgitt, blir omraadet regnet ut
    fra flowen, slik en enkeltstaaende logg uten pelmetadata blir behandlet.
    """
    if omrade is not None:
        i0 = max(0, int(omrade[0]) - args.buffer_pkt)
        i1 = min(len(periode) - 1, int(omrade[1]) + args.buffer_pkt)
        print(f"  produksjonsomraade {periode['Tid'].iloc[omrade[0]]:%H:%M:%S}-"
              f"{periode['Tid'].iloc[omrade[1]]:%H:%M:%S}")
    else:
        i0, i1 = 0, len(periode) - 1
        if not args.full:
            kolonne, i0, i1 = velg_kuttvindu(periode, terskel=args.terskel,
                                             tillatt_hull_s=args.hull_s)
            if kolonne is None:
                print("  fant ingen flow-/trykk-kolonne - beholder hele "
                      "perioden")
            else:
                i0 = max(0, i0 - args.buffer_pkt)
                i1 = min(len(periode) - 1, i1 + args.buffer_pkt)
                print(f"  arbeid {periode['Tid'].iloc[i0]:%H:%M:%S}-"
                      f"{periode['Tid'].iloc[i1]:%H:%M:%S}"
                      f"  (styrt av {kolonne})")
    vindu = periode.iloc[i0:i1 + 1].reset_index(drop=True)
    # Hvilken prove i ``periode`` hver rad i vinduet kom fra. Trengs naar
    # fasene er regnet ut for hele produksjonen og skal klippes inn her.
    posisjon = np.arange(i0, i1 + 1)

    # Hull i maalingene (ALOSS i dagseksporten) ville gjort tilpasningen
    # meningsloes: én NaN i et intervall gir NaN i alle summene, og da finner
    # segmenteringen ingen knekker i det hele tatt. Provene tas ut - i plottet
    # blir hullet da et avbrekk i stedet for en rett strek over.
    mangler = int(vindu["dybde"].isna().sum())
    if mangler and ferdige is None:
        # Uten ferdige faser maa hullet ut, ellers gir NaN i dybden NaN i
        # alle tilpasninger. Er fasene alt regnet ut for hele
        # produksjonsomraadet, blir hullet staaende: da stemmer indeksene med
        # fasene, og hullet blir et avbrekk i kurven i stedet for en rett
        # strek over.
        print(f"  tar ut {mangler} prover uten dybdemaaling (ALOSS)")
        vindu = vindu.loc[vindu["dybde"].notna()].reset_index(drop=True)
    if len(vindu) < 3:
        print("  for faa prover aa lage noe av - hopper over")
        return utfil, None

    t = (vindu["Tid"]
         - vindu["Tid"].iloc[0]).dt.total_seconds().to_numpy(dtype=float)
    dybde = vindu["dybde"].to_numpy(dtype=float)
    varighet = float(t[-1] - t[0]) if t.size else 0.0
    glatt = 0.0
    if ferdige is not None:
        # Fasene er regnet ut én gang for hele produksjonsomraadet. Her
        # klippes de inn i vinduet, saa delplottet viser de samme fasene som
        # oversikten - seksjonene i en grouting blir ikke slaat sammen bare
        # fordi vinduet er kortere.
        segmenter = []
        for s0, s1 in ferdige:
            treff = np.flatnonzero((posisjon >= s0) & (posisjon <= s1))
            if treff.size >= 2:
                segmenter.append((int(treff[0]), int(treff[-1])))
        if not segmenter:
            segmenter = [(0, max(0, len(vindu) - 1))]
    else:
        # Glattingen maa staa i forhold til hvor lang perioden er: i en
        # 4-minutters fase skal ingenting vaskes bort, men i en 30-minutters
        # oekt maa de korte rykningene i encoderet bort for at de ekte
        # fartsendringene skal komme fram. 3 % av vinduet, 3-61 sekunder.
        glatt = (args.glatt_s if args.glatt_s is not None
                 else min(61.0, max(3.0, 0.03 * varighet)))
        segmenter = finn_segmenter(t, dybde, tol_std=args.tol_std,
                                   min_lengde_s=args.min_lengde_s,
                                   tol_cm_min=args.tol_cm_min, glatt_s=glatt)
    # Stoppene (dybde-spenn og/eller kanal) - grunnlaget for aksekuttet og
    # fotnoten. Regelen staar i finn_stopp, den samme som JSON-en bruker.
    stopp_spenn_cm = getattr(args, "stopp_spenn_cm", 2.0)
    stopp_min_s = getattr(args, "stopp_min_s", 600.0)
    stopp = finn_stopp(vindu, stopp_spenn_cm=stopp_spenn_cm,
                       stopp_cm_min=args.stopp_cm_min,
                       stopp_min_s=stopp_min_s,
                       stopp_kanal=getattr(args, "stopp_kanal", None),
                       stopp_verdi=getattr(args, "stopp_verdi", None),
                       stopp_retning=getattr(args, "stopp_retning", "under"),
                       stopp_kombi=getattr(args, "stopp_kombi", "eller"),
                       stopp_med_fart=getattr(args, "stopp_med_fart", False),
                       glatt_s=(glatt if glatt else args.glatt_s))
    # En pause skal ikke ligge inne i en fase som teller med. Fasene klippes
    # derfor i biter rundt pausene, saa hver pause blir sin egen (klippede)
    # bit og hver bevegelse faar sitt eget cm/min-tall. Da blir lengden og
    # snittfarten regnet over bevegelsen alene - ikke over staa-tiden.
    if stopp:
        segmenter = del_ved_stopp(segmenter,
                                  [(s["a"], s["b"]) for s in stopp])
    rader = fase_tabell(vindu, segmenter, min_r2=args.min_r2,
                        stopp_cm_min=args.stopp_cm_min,
                        maks_cm_min=args.maks_cm_min,
                        stopp_spenn_cm=stopp_spenn_cm,
                        stopp_min_s=stopp_min_s,
                        stopp_med_fart=getattr(args, "stopp_med_fart",
                                               False))
    fjern_uryddig = not getattr(args, "vis_uryddig", False)
    antall_kutt = (len(stopp)
                   + (sum(1 for r in rader if r["merknad"] == "uryddig")
                      if fjern_uryddig else 0))
    if antall_kutt:
        print(f"  {len(stopp)} stopp og {antall_kutt - len(stopp)} "
              f"uryddig-faser klippes ut av x-aksen")
        for s in stopp:
            print(f"    stopp {s['nr']} ({s['farge']}) {s['fra_iso'][11:]}"
                  f"-{s['til_iso'][11:]}  {s['dybde_stopp_cm']:.0f}->"
                  f"{s['dybde_start_cm']:.0f} cm  {s['varighet']}"
                  f"  grunn={s['grunn']}")
    hode = f"  {varighet / 60.0:.1f} min"
    if glatt:
        hode += f", medianfilter {glatt:.0f} s"
    print(f"{hode}, {len(rader)} faser:")
    print(f"    {'#':>3} {'fra':>9} {'til':>9} {'sek':>6} {'cm':>7} "
          f"{'cm/min':>8} {'R2':>7}  merknad")
    for rad in rader:
        print(f"    {rad['fase']:>3} {rad['fra']:>9} {rad['til']:>9} "
              f"{rad['varighet_s']:>6.0f} {rad['lengde_cm']:>7.1f} "
              f"{rad['stigningstall_cm_min']:>8.2f} {rad['r2']:>7.4f}"
              f"  {rad['merknad']}")

    # -- overskrift: pel, metode, start/stopp, varighet og snittfarten -------
    tittel: str | None = None
    if pel is not None:
        fakta = [f"start {vindu['Tid'].iloc[0]:%H:%M:%S}",
                 f"stopp {vindu['Tid'].iloc[-1]:%H:%M:%S}",
                 varighet_tekst(varighet)]
        # Gjennomsnittet regnes over fasene som er jevn bevegelse - stopp og
        # encodersprang holdes utenfor. Vektes med tiden i hver fase, saa en
        # lang fase teller mer enn en kort. Det er dette tallet som svarer paa
        # "hvor fort gikk det i denne sesjonen".
        # Farten hoerer til hendelsen. I en pel med baade boring og grouting
        # gaar bevegelsen begge veier, og ett gjennomsnitt av det ville vaere
        # et tal som ikke betyr noe.
        vis_fart = metode is not None or len(pel["moduser"]) == 1
        # Bare fasene som teller med (samme regel som JSON-en). Regelen staar
        # i :func:`teller_med`, saa plottet og JSON-en aldri viser hvert sitt
        # tall for lengde og snittfart.
        gyldige = [rad for rad in rader
                   if teller_med(rad, args.min_r2_telling)]
        tellet_s = sum(float(rad["varighet_s"]) for rad in gyldige)
        alle_s = sum(float(rad["varighet_s"]) for rad in rader)
        utelatt_pst = 0.0
        if vis_fart and gyldige and tellet_s > 0:
            lengde = sum(float(rad["lengde_cm"]) for rad in gyldige)
            snitt = sum(float(rad["stigningstall_cm_min"])
                        * float(rad["varighet_s"])
                        for rad in gyldige) / tellet_s
            # Samme avrunding som JSON-en (én desimal), men uten '.0' naar
            # tallet er helt - da er lengden i overskriften bokstavelig talt
            # det samme tallet som i JSON-en.
            fakta.append(f"{round(abs(lengde), 1):g} cm")
            fakta.append(f"snitt {abs(snitt):.1f} cm/min "
                         f"{'opp' if snitt > 0 else 'ned'}")
            # Andelen av fasetiden som holdes utenfor (samme base som JSON-en).
            if alle_s > 0:
                utelatt_pst = round(
                    (alle_s - tellet_s) / alle_s * 100.0, 1)
        elif vis_fart and varighet > 0:
            # Urolig boring: er hver fase merket 'uryddig', finnes det ingen
            # jevn bevegelse aa regne snittet av. Da er hele forflytningen
            # over vinduet det aerligste svaret som finnes - den bygger paa
            # hele hendelsen, ikke et utvalg, og utelatt er derfor null.
            y = vindu["dybde"].to_numpy(dtype=float)
            flyttet = float(y[-1] - y[0]) if y.size > 1 else 0.0
            if abs(flyttet) > 0.5:
                fakta.append(f"{round(abs(flyttet), 1):g} cm")
                fakta.append(f"snitt {abs(flyttet) / varighet * 60:.1f} "
                             f"cm/min {'ned' if flyttet > 0 else 'opp'}")
        if vis_fart:
            # Operatoren skal se at tallet bygger paa et utvalg av hendelsen og
            # ikke hele. Staar det 0,0 %, er hele hendelsen talt med.
            fakta.append(f"utelatt {utelatt_pst:.1f} % av tiden")
        if metode:
            # Hendelsesplott: overskriften navngir hendelsen, ikke alle
            # metodene som er brukt i pelen.
            deler = [f"Pel {pel['pel']} - {metode_navn(str(metode))}"]
            deler += pel_tittel(periode, pel).split(" \u00b7 ")[1:]
            navn = " \u00b7 ".join(deler)
        else:
            navn = pel_tittel(periode, pel)
        tittel = navn + "\n" + " \u00b7 ".join(fakta)
        print(f"  {' \u00b7 '.join(fakta)}")

    ekstra: dict[str, Any] = {"tittel": tittel} if tittel else {}
    utfil.parent.mkdir(parents=True, exist_ok=True)
    bilde = lag_plott(vindu, rader, segmenter, kanaler, utfil,
                      maks_dybde=args.maks_dybde, grenser=grenser or None,
                      min_r2_telling=args.min_r2_telling, stopp=stopp,
                      fjern_uryddig=fjern_uryddig,
                      stopp_spenn_cm=stopp_spenn_cm,
                      stopp_min_s=stopp_min_s, **ekstra)
    side: Path | None = None
    if not args.ingen_html:
        # --html gjelder bare naar det skrives én rapport; skriver vi mange,
        # ville alle skrevet over den samme filen.
        # --html navngir den ene rapporten naar loggen ikke har pelmetadata.
        # Skrives det flere plott, folger HTML-en PNG-navnet.
        sti = (Path(args.html) if (args.html and pel is None)
               else Path(utfil).with_suffix(".html"))
        side = bygg_interaktiv_html(vindu, rader, segmenter, kanaler, sti,
                                    grenser or None,
                                    maks_dybde=args.maks_dybde,
                                    min_r2_telling=args.min_r2_telling,
                                    cdn=args.html_cdn, stopp=stopp,
                                    fjern_uryddig=fjern_uryddig,
                                    stopp_spenn_cm=stopp_spenn_cm,
                                    stopp_min_s=stopp_min_s, **ekstra)
    return bilde, side


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="regenerer_acron_plott",
        description="Alle kanaler i ett plott med delt Y-akse, kuttet ved "
                    "produksjonsslutt, med klammer for stigningstall.")
    parser.add_argument("fil", help="eksport (.txt/.csv) i Acron-format")
    parser.add_argument("--ut", "-o", default=None,
                        help="filnavn for plottet. Standard: "
                             "dato_pel_metode.png")
    parser.add_argument("--terskel", type=float, default=5.0,
                        help="flow over denne verdien = produksjon (5.0)")
    parser.add_argument("--hull-s", type=float, default=180.0,
                        help="saa lange avbrudd som ikke bryter perioden (180 s)")
    parser.add_argument("--tol-std", type=float, default=0.35,
                        help="restavvik som avslutter en fase (0.35 cm)")
    parser.add_argument("--min-lengde-s", type=float, default=60.0,
                        help="korteste fase vi beholder (60 s)")
    parser.add_argument("--skift-hull", type=float, default=SKIFT_HULL_TIMER,
                        metavar="TIMER",
                        help="kommer samme pel tilbake senere enn dette, er "
                             "det en ny oekt og ikke samme produksjonsomraade "
                             f"({SKIFT_HULL_TIMER:g} t). 0 slaar sammen alt "
                             "med samme pelnavn, uansett hvor langt fra "
                             "hverandre oektene ligger")
    parser.add_argument("--tol-cm-min", type=float, default=1.0,
                        help="hvor mye stigningstallet maa endre seg (1.0)")
    parser.add_argument("--glatt-s", type=float, default=None,
                        help="medianfilter foran segmenteringen, i sekunder. "
                             "Standard er tilpasset lengden paa perioden "
                             "(3-61 s). 0 gir raa data")
    parser.add_argument("--maks-cm-min", type=float, default=30.0,
                        help="fart over dette er et encodersprang og ikke en "
                             "fart - fasen merkes 'uryddig' (30)")
    parser.add_argument("--min-r2", type=float, default=0.7,
                        help="under denne tilpasningen merkes fasen 'uryddig' "
                             "og farten tegnes med merknaden ved siden av "
                             "(0.7). Styrer bare merkelappen, ikke tellingen")
    parser.add_argument("--min-r2-telling", type=float, default=0.9,
                        help="faser under denne tilpasningen holdes utenfor "
                             "lengde og snittfart, selv om de ellers ikke er "
                             "merket. Egen terskel for hva som telles (0.9)")
    parser.add_argument("--stopp-spenn-cm", type=float, default=2.0,
                        metavar="CM",
                        help="HOVEDKRITERIET. Dybden staar stille naar "
                             "spennet (maks-min) gjennom tidsrommet er "
                             "innenfor +/-CM, altsaa 2*CM totalt, i minst "
                             "--stopp-min-s sekunder (standard 2.0 = +/-2 cm "
                             "= 4 cm spenn). 0 slaar kriteriet av")
    parser.add_argument("--stopp-med-fart", action="store_true",
                        help="bruk OGSAA farts-kriteriet (|cm/min| under "
                             "--stopp-cm-min) sammen med spenn-kriteriet. Av "
                             "som standard - spenn-regelen er primaer")
    parser.add_argument("--stopp-cm-min", type=float, default=1.0,
                        help="farts-kriteriet: |cm/min| under denne verdien. "
                             "Gjelder bare naar --stopp-med-fart er satt (1.0)")
    parser.add_argument("--stopp-min-s", type=float, default=600.0,
                        help="korteste stopp som merkes og klippes ut av "
                             "x-aksen (600 = 10 min; kortere pauser er "
                             "ikke stopp)")
    parser.add_argument("--stopp-kanal", default=None,
                        help="kanal som viser stopp, f.eks. grouttrykk")
    parser.add_argument("--stopp-verdi", type=float, default=None,
                        help="grensen for --stopp-kanal (f.eks. 50)")
    parser.add_argument("--stopp-retning", choices=STOPP_RETNINGER,
                        default="under",
                        help="stopp naar kanalen er under/over grensen "
                             "(under)")
    parser.add_argument("--stopp-kombi", choices=STOPP_KOMBIER,
                        default="eller",
                        help="hvordan de aktive kriteriene settes sammen naar "
                             "flere er i bruk: 'eller' (standard) = pause naar "
                             "ett av dem slaar ut, 'og' = alle maa holde")
    parser.add_argument("--vis-uryddig", action="store_true",
                        help="behold 'uryddig'-fasene i plottet. Standard er "
                             "aa fjerne dem helt fra x-aksen")
    parser.add_argument("--maks-dybde", type=float, default=None,
                        help="sett dybdeaksen til 0..denne verdien")
    parser.add_argument("--akse", action="append", default=None,
                        metavar="KANAL=MAKS",
                        help="overstyr ovre grense for en kanal, f.eks. "
                             "--akse grouttrykk=500 (kan gjentas)")
    parser.add_argument("--smarte-akser", action="store_true",
                        help="regn aksegrensene fra dataene i filen i stedet "
                             "for de faste (0-400, 0-7, ...)")
    parser.add_argument("--auto-akser", action="store_true",
                        help="la matplotlib skala hoyreaksene helt fritt")
    parser.add_argument("--html", default=None,
                        help="filnavn for den interaktive HTML-en "
                             "(standard: samme navn som --ut, men .html)")
    parser.add_argument("--ingen-html", action="store_true",
                        help="lag bare PNG, ikke den interaktive HTML-en")
    parser.add_argument("--html-cdn", action="store_true",
                        help="hent plotly fra internett i stedet for aa bygge "
                             "det inn (krever nett, men liten fil)")
    parser.add_argument("--pel", "--okt", dest="pel", type=int, default=None,
                        help="hvilken pel som skal plottes (1 = den forste). "
                             "Lista over pelene skrives ut for kjoering")
    parser.add_argument("--alle-peler", "--alle-okter", dest="alle_peler",
                        action="store_true",
                        help="skriv ett plott for hver pel i filen")
    parser.add_argument("--mappe", default=None,
                        help="mappe aa legge --alle-peler i (standard: her)")
    parser.add_argument("--flat", "--en-mappe", dest="flat",
                        action="store_true",
                        help="legg alle hendelsene rett i --mappe, nummerert i "
                             "produksjonsrekkefolge, saa de kan blaas gjennom "
                             "uten aa bytte mappe")
    parser.add_argument("--kanaler", default=None, metavar="A,B,...",
                        help="tegn disse kanalene i stedet for standardvalget "
                             "(grouttrykk,lufttrykk,rotasjonshastighet,"
                             "groutflow,luftflow)")
    parser.add_argument("--alle-kanaler", action="store_true",
                        help="ta med alle brukbare kanaler i filen, ikke bare "
                             "de fem Acron viser")
    parser.add_argument("--buffer-pkt", type=int, default=20,
                        help="prover vi beholder for/etter produksjonen (20)")
    parser.add_argument("--hver-okt", action="store_true",
                        help="ett plott per oekt i loggen. Standard er én "
                             "pilotboring, én prejet og én grouting per pel - "
                             "oekter som hoerer til samme arbeid slaas sammen")
    parser.add_argument("--start-for", type=float, default=300.0, metavar="SEK",
                        help="prejet og grouting begynner saa mange sekunder "
                             "for den forste seksjonen med stigningstall, og "
                             "slutter naar den siste er slutt (300 = 5 min)")
    parser.add_argument("--full", action="store_true",
                        help="ikke kutt etter produksjonsslutt")
    args = parser.parse_args(argv)
    if args.stopp_kanal:
        # Operatoren skriver 'Grouttrykk' - kolonnen heter 'grouttrykk'.
        args.stopp_kanal = _normaliser(args.stopp_kanal)

    df = les_logg(args.fil)
    valg = (([_normaliser(n) for n in args.kanaler.split(",") if n.strip()])
            if args.kanaler else None)
    kanaler = finn_kanaler(df, valg=valg, alle=args.alle_kanaler)
    print(f"Leste {len(df)} prover: {df['Tid'].iloc[0]} - {df['Tid'].iloc[-1]}")
    print(f"Kanaler: {', '.join(n for n, _, _ in kanaler)}")
    if valg:
        mangler = [n for n in valg if n not in {k[0] for k in kanaler}]
        if mangler:
            parser.error(f"Fant ikke {mangler} i filen. Tilgjengelige "
                         f"kanaler: {sorted(df.columns)}")

    # -- hvilke peler ligger i filen? ---------------------------------------
    # Pelnummeret og metoden staar i loggen. Metoden kan ikke brukes som
    # lengde - glemmer operatoren aa bytte rapport, staar den forrige metoden
    # igjen lenge etter at arbeidet er ferdig, og da blir 'prejet' og
    # 'grouting' av ulik lengde for samme pel. Produksjonsomraadet blir derfor
    # regnet ut fra signalene, ikke fra metodeflagget.
    skift_hull = args.skift_hull * 3600.0
    pelene = finn_peler(df, maks_hull_s=(skift_hull if skift_hull > 0.0
                                         else float("inf")))
    plan: list[dict[str, Any]] = []
    hoppet: list[str] = []
    for pel in pelene:
        # Forst hele produksjonsomraadet for pelen ...
        a, b = produksjonsomrade(df, pel)
        linje: dict[str, Any] = {"pel": pel, "hele": (a, b), "okter": []}

        # Saa hendelsene: én pilotboring, én prejet og én grouting - ikke et
        # delplott for hver gang metodeflagget skiftet, og ikke delplott for
        # arbeid som ikke er produksjon. Gaar det ikke oppover i det hele tatt,
        # er pelen bare boret, og da er det ingenting aa rapportere.
        merknader: list[str] = []
        if args.hver_okt:
            hendelser = []
            her_merker = start_stopp_vinduer(df, pel=str(pel["pel"]))
            for okt in pel["okter"]:
                for vindu in arbeidsvinduer(df, [okt], grense=(a, b),
                                            tillatt_hull_s=args.hull_s,
                                            merker=her_merker):
                    hendelser.append({"modus": str(okt["modus"]),
                                      "vindu": vindu})
        else:
            hendelser = velg_hendelser(df, pel["okter"], grense=(a, b),
                                       tillatt_hull_s=args.hull_s,
                                       merknader=merknader)
        if not hendelser:
            start = df["Tid"].iloc[int(pel["start"])]
            hoppet.append(f"{pel['pel']} {start:%d.%m}")
            continue
        for merknad in merknader:
            print(f"        ({merknad})")

        # Fasene regnes ut én gang for hele produksjonsomraadet, og klippes
        # inn i hvert delplott. Da viser delplottet de samme fasene som
        # oversikten, og seksjonene i en grouting blir ikke slaat sammen selv
        # om vinduet er kortere. Prover uten dybdemaaling holdes utenfor.
        bit = df.iloc[a:b + 1]
        brukt = np.flatnonzero(bit["dybde"].notna().to_numpy())
        ren_bit = bit.iloc[brukt]
        t_bit = (ren_bit["Tid"]
                 - ren_bit["Tid"].iloc[0]).dt.total_seconds().to_numpy(float)
        sek_bit = float(t_bit[-1] - t_bit[0]) if t_bit.size else 0.0
        linje["ferdige"] = [
            (int(brukt[s0]) + a, int(brukt[s1]) + a)
            for s0, s1 in finn_segmenter(
                t_bit, ren_bit["dybde"].to_numpy(dtype=float),
                tol_std=args.tol_std, min_lengde_s=args.min_lengde_s,
                tol_cm_min=args.tol_cm_min,
                glatt_s=(args.glatt_s if args.glatt_s is not None
                         else min(61.0, max(3.0, 0.03 * sek_bit))))]

        # Prejet og grouting skal vise hva som skjer rett for opptrekket
        # begynner. Vinduet deres er der stigningen er - det er derfor det
        # begynner og slutter der det gjor - og det utvides derfor bakover med
        # ``--start-for`` sekunder (5 min). Pauser inne i vinduet blir med:
        # de kan vaere lange, men de hoerer til samme opptrekk.
        #
        # Har riggen operatørens start/stopp-signal, faller forlopet bort: da
        # er det operatøren som definerer vinduet, og fem paalagte minutter
        # foran ville lagt til tid der riggen ennaa ikke har begynt.
        for hendelse in hendelser:
            if hendelse["modus"] not in ("PREJETTING", "GROUTING"):
                continue
            h0, h1 = hendelse["vindu"]
            if STARTSTOPP_KOLONNE in df.columns:
                continue
            # buffer_pkt trekkes fra her og legges til igjen av skriv_rapport
            # naar den kutter - da begynner plottet der vi sier det skal.
            forste = int(df["Tid"].searchsorted(
                df["Tid"].iloc[h0] - pd.Timedelta(seconds=args.start_for)))
            ny0 = max(a, forste + args.buffer_pkt)
            ny1 = min(b, h1 - args.buffer_pkt)
            if ny1 - ny0 >= 30:
                hendelse["vindu"] = (ny0, ny1)

        linje["okter"] = hendelser
        plan.append(linje)

    # Hvor rapportene skal ligge. Rommer filen flere dager - riggen kan
    # eksportere en hel uke i én fil - legges dagen forst, saa pelen. Da blir
    # en maaned med eksport til aa finne fram i, og samme pel kan gjores om
    # igjen neste dag uten at noe skrives over. Er samme pel gjort to ganger
    # samme dag, skilles de med klokkeslettet.
    flerDager = len(set(df["Tid"].dt.date)) > 1
    antall: dict[tuple[str, str], int] = {}
    for linje in plan:
        a, _ = linje["hele"]
        start = df["Tid"].iloc[a]
        nokkel = (f"{start:%Y-%m-%d}", _mappenavn(str(linje["pel"]["pel"])))
        antall[nokkel] = antall.get(nokkel, 0) + 1
    brukte: set[str] = set()
    for linje in plan:
        a, _ = linje["hele"]
        start = df["Tid"].iloc[a]
        navn = _mappenavn(str(linje["pel"]["pel"]))
        if antall[(f"{start:%Y-%m-%d}", navn)] > 1:
            navn = f"{navn}_{start:%H%M}"
        if flerDager:
            navn = f"{start:%Y-%m-%d}/{navn}"
        while navn in brukte:                  # to oekter, samme minutt
            navn += "_"
        brukte.add(navn)
        linje["mappe_navn"] = navn

    print(f"\n{len(pelene)} peler i filen, {len(plan)} av dem skal skrives:")
    if hoppet:
        unike = list(dict.fromkeys(hoppet))       # samme pel hver dag
        print(f"  hopper over {', '.join(unike)} - bare pilotboring, "
              f"ingen prejet eller grouting")
    for nr, linje in enumerate(plan, start=1):
        pel = linje["pel"]
        a, b = linje["hele"]
        metoder = ", ".join(metode_navn(str(m)) for m in pel["moduser"])
        sek = float((df["Tid"].iloc[b] - df["Tid"].iloc[a]).total_seconds())
        print(f"  {nr:2d}  {str(pel['pel']):>4s}  {metoder:<32s}"
              f"  produksjon {df['Tid'].iloc[a]:%H:%M:%S}-"
              f"{df['Tid'].iloc[b]:%H:%M:%S}  {varighet_tekst(sek)}")
        for nummer, okt in enumerate(linje["okter"], start=1):
            u, v = okt["vindu"]
            lengde = varighet_tekst(
                float((df["Tid"].iloc[v] - df["Tid"].iloc[u]).total_seconds()))
            print(f"        {nummer}. {metode_navn(okt['modus']):<12s}"
                  f" {df['Tid'].iloc[u]:%H:%M:%S}-{df['Tid'].iloc[v]:%H:%M:%S}"
                  f"  ({lengde})  fra {df['dybde'].iloc[u]:.0f} til "
                  f"{df['dybde'].iloc[v]:.0f} cm")

    # -- Y-akser: regnet fra hele filen, saa alle oektene faar like akser ----
    grenser: dict[str, tuple[float, float]] = {}
    if args.smarte_akser:
        grenser, forklaring = smarte_grenser(df, kanaler)
        print("\nY-akser regnet fra dataene (--smarte-akser):")
        for tekstlinje in forklaring:
            print(f"  {tekstlinje}")
    elif not args.auto_akser:
        # Fast skala: samme akser i hver rapport, saa plottene kan
        # sammenlignes fra oekt til oekt og fra pel til pel.
        grenser = {navn: FASTE_GRENSER[navn] for navn, _, _ in kanaler
                   if navn in FASTE_GRENSER}
        ukjente = [k for k in kanaler if k[0] not in FASTE_GRENSER]
        if ukjente:
            ekstra, _ = smarte_grenser(df, ukjente)
            grenser.update(ekstra)
        print("\nY-akser (faste):")
        for navn, (lav, hoy) in grenser.items():
            print(f"  {navn} {lav:g}-{hoy:g}")
    for oppgitt in args.akse or []:
        navn, _, verdi = oppgitt.partition("=")
        navn = _normaliser(navn)
        if navn not in {k[0] for k in kanaler}:
            parser.error(f"Ukjent kanal '{navn}'. Velg blant "
                         f"{[k[0] for k in kanaler]}")
        grenser[navn] = (_pent_ned(0.0), _pent_opp(float(verdi)))

    # -- hva skal skrives? ---------------------------------------------------
    if args.alle_peler and not plan:
        parser.error("Fant ingen pel/metode i loggen aa dele opp etter. "
                     "Bruk --full for aa tegne hele filen i ett plott.")
    valgte: list[dict[str, Any] | None] = []
    if args.alle_peler:
        valgte = list(plan)
    elif args.pel is not None:
        if not plan:
            parser.error("Fant ingen pel/metode i loggen aa dele opp etter.")
        if not 1 <= args.pel <= len(plan):
            parser.error(f"--pel maa vaere mellom 1 og {len(plan)}")
        valgte = [plan[args.pel - 1]]
    elif plan:
        print("\nSkriver pel 1 - velg en annen med --pel N, "
              "eller alle med --alle-peler")
        valgte = [plan[0]]
    else:
        valgte = [None]

    dato = df["Tid"].iloc[0].strftime("%Y%m%d")
    mappe = Path(args.mappe) if args.mappe else Path(".")

    rekkefolge = 0
    for oppslag in valgte:
        if oppslag is None:
            # Logg uten pelmetadata: ett plott av hele perioden.
            ut = (Path(args.ut) if args.ut
                  else mappe / f"{dato}_hele_loggen.png")
            print("\n=== hele loggen ===")
            bilde, side = skriv_rapport(df, kanaler, grenser, args, utfil=ut)
            print(f"  plott: {bilde}")
            if side:
                print(f"  interaktiv: {side}")
            continue

        pel = oppslag["pel"]
        print(f"\n=== {pel_tittel(df, pel)} ===")

        # Alt i én mappe, nummerert i produksjonsrekkefolge. Da kan plottene
        # blaas gjennom i filviseren uten aa bytte mappe underveis, og
        # nummeret viser rekkefolgen arbeidet ble gjort i.
        if args.flat:
            for okt in oppslag["okter"]:
                u, _v = okt["vindu"]
                rekkefolge += 1
                ut = mappe / (
                    f"{rekkefolge:02d}_{df['Tid'].iloc[u]:%Y-%m-%d}_"
                    f"{_mappenavn(str(pel['pel']))}_"
                    f"{_filnavn_del(metode_navn(okt['modus']))}.png")
                bilde, side = skriv_rapport(
                    df, kanaler, grenser, args, utfil=ut, pel=pel,
                    omrade=okt["vindu"], metode=okt["modus"],
                    ferdige=oppslag["ferdige"])
                print(f"  plott: {bilde}")
                if side:
                    print(f"  interaktiv: {side}")
            continue

        katalog = mappe / str(oppslag["mappe_navn"])
        katalog.mkdir(parents=True, exist_ok=True)
        print(f"  mappe: {katalog}")

        # Hele produksjonen forst - det er den rapporten pelen skal ha. Har
        # pelen bare én hendelse, er den og hele produksjonen samme vindu, og
        # da skrives det bare ett plott.
        if len(oppslag["okter"]) > 1:
            bilde, side = skriv_rapport(
                df, kanaler, grenser, args,
                utfil=katalog / "0_hele_produksjonen.png", pel=pel,
                omrade=oppslag["hele"], ferdige=oppslag["ferdige"])
            print(f"  plott: {bilde}")
        else:
            print("  (bare én hendelse - hele produksjonen er samme vindu)")

        # Saa hver hendelse for seg: pilotboring, prejet, grouting.
        for nummer, okt in enumerate(oppslag["okter"], start=1):
            ut = (katalog
                  / f"{nummer}_{_filnavn_del(metode_navn(okt['modus']))}.png")
            bilde, side = skriv_rapport(df, kanaler, grenser, args, utfil=ut,
                                        pel=pel, omrade=okt["vindu"],
                                        metode=okt["modus"],
                                        ferdige=oppslag["ferdige"])
            print(f"  plott: {bilde}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
