"""Henter Plant1 Pro-eksporten fra Gmail, dekoder, deler og plotter.

Dette er kontor-PC-siden av JETLOGG-704-kjeden, samlet i EEN inngang. Alt
kjeden trenger ligger i denne mappen (rigg_kontor\\), saa den kan kjores for
haand eller fra Task Scheduler uten aa vite noe om prosjektet rundt.

    python hent_og_plott.py                 hele kjeden
    python hent_og_plott.py --test          provetur: viser, endrer ingenting
    python hent_og_plott.py --bare-hent     stopp etter henting
    python hent_og_plott.py --slett-arbeid  tom arbeid\\ til slutt
    python hent_og_plott.py --fra-zip FIL   kjor dekod/plot paa en lokal zip
                                            (til proving, uten e-post)

KJEDEN
------
1. Henter vedlegget fra Gmail (IMAP over SSL, imap.gmail.com:993) og lagrer
   det i hentet\\. Samme oppskrift som tools\\hent_epost_vedlegg.py.
2. Pakker zippen ut i arbeid\\ og finner CSV-en.
3. Kjorer eksporter_hendelser.py (UENDRET) -> hendelser som JSON.
4. Deler den kombinerte JSON-en i én fil per hendelse under json\\.
5. Kjorer regenerer_acron_plott.py (UENDRET) -> PNG per pel/metode.
6. Flater ut og doper om plottene til plot\\<dato>_<pel>_<metode>.png.
7. Skriver json\\index.json - listen hendelsesviseren bygger menyen fra -
   og JS-tvillingane index.js / <navn>.js ved sida av JSON-en (reserve for
   file://, der nettlesaren blokkerer fetch). Alt skrives til slutt, av det
   som FAKTISK ligger i json\\.

MAPPER
------
    json\\    <dato>_<pel>_<metode>.json  + _alle_<dato>.json
    plot\\    <dato>_<pel>_<metode>.png   + <dato>_<pel>_hele.png
    hentet\\  de mottatte .zip-filene
    arbeid\\  midlertidig utpakking (kan tommes)
    behandlet_epost.txt         Message-ID-er vi har hentet
    behandlet_filer.txt         innholdsnoekler for eksporter vi har behandlet
    logg_hent.txt               logg med én sammendragslinje per kjoring

IDEMPOTENS - melding, eksport og \\Seen
---------------------------------------
Samme EKSPORT skal aldri dekodes og plottes to ganger, uansett hvor mange
meldinger som bærer den. Vi bruker tre uavhengige merker:

* \\Seen settes i Gmail forst ETTER at filen er lagret. Det virker ogsaa om
  den lokale loggen skulle forsvinne.
* behandlet_epost.txt (én Message-ID per linje) husker hvilke MELDINGER vi har
  hentet - saa postkassen ikke skannes paa nytt for hver kjoring.
* behandlet_filer.txt husker hvilke EKSPORTER vi har behandlet, noklet paa
  SHA-256 av vedleggsbyttene (én linje per eksport: noekkel, storrelse, navn).
  To meldinger med samme vedlegg men ULIKE Message-ID-er blir derfor fanget
  opp som duplikat: den andre verken dekodes eller plottes.

Message-ID alene er ikke nok, og \\Seen alene er ikke nok heller. En melding
kan ha blitt aapnet i nettleseren og dermed vaere "sett" uten at vedlegget
noen gang ble lagret; og to meldinger kan bære NOEYAKTIG samme eksport med
hver sin Message-ID. Vi leser derfor Message-ID fra hodet forst og hopper over
alt som staar i loggen - uavhengig av \\Seen - og regner i tillegg
innholdsnoekkelen for hvert vedlegg for vi lagrer det. Er noekkelen alt
behandlet, logges det som DUPLIKAT og telles for seg; kjoringen feiler ikke.

STORRE VERSJON VINNER
---------------------
Samme pel/dato/metode skal bare finnes EN gang i json\\ og plot\\. Eksporten er
et glidende vindu: kjorer jobben klokka 08:17, dekker den fra 08:17 i gaar til
08:17 i dag. En boring som fortsatt paagikk ved vinduskanten blir derfor KUTTET
i den ene eksporten, og kommer i sin helhet i den neste - med samme dato, pel
og metode.

Den gamle regelen ("overskriv aldri") la den andre ved siden av den forste som
<navn>_1.json, og da sto samme pel og metode to ganger i nedtrekkslista. Den er
naa snudd: den STORRE versjonen vinner, den ufullstendige blir erstattet, og en
gammel <navn>_1 ryddes bort. <navn>_2 og hoyere er derimot ekte, egne hendelser
(to hendelser med samme pel/metode i EN eksport) og blir staende.

Storrelse og ikke tidspunkt, fordi vinduet ogsaa bestemmer hvor detektoren
begynner aa lete: flytter vinduets START seg, kan samme pel/dato/metode bli en
helt annen og KORTERE hendelse - en oekt som laa innenfor det gamle vinduet
faller utenfor det nye. Da beholder vi den vi har, og sier fra i loggen.

Den raa zippen i hentet\\ bevarer vi som for (overskriv=False): den er beviset
fra riggen, og en ny eksport med samme navn blir <navn>_1.zip der.

SIKKERHET
---------
Ingenting fra et vedlegg blir kjort eller aapnet. En zip pakkes bare ut som
data, og bare hvis alle oppforingene er vanlige filer med trygge navn (ingen
`..`, ingen absolutte stier, ingen kataloger) - det stenger "zip-slip". En CSV
blir aldri kjort, bare sendt videre som data til verktoyene.

FEILING
-------
Skriptet feiler HOYT. Det gir ikke null uten aa ha gjort noe:
* klarte vi ikke koble til eller logge inn -> feilkode 1
* fant vi et vedlegg vi ikke klarte aa lagre -> feilkode 1
* feilet dekodingen, eller ble det null hendelser -> feilkode 1
* feilet plottingen, eller ble det null plott -> feilkode 1
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import imaplib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path, PurePosixPath

# -- stier: alt regnes fra denne mappen (rigg_kontor) ------------------------
HER = Path(__file__).resolve().parent
HENTET = HER / "hentet"
ARBEID = HER / "arbeid"
JSONMAPPE = HER / "json"
PLOTMAPPE = HER / "plot"
# Grafene hoerer hjemme paa nettstedet, i den levende viseren som blir laga
# av hendelses-JSON-en. Vi skriver derfor INGEN PNG-er lokalt med mindre
# --plott blir gitt. Skal noe ut paa papir, skrives det fra viseren (Ctrl+P):
# den gir liggende A4 og hele pelen.
SKRIV_LOKALE_PLOTT = False
BEHANDLET = HER / "behandlet_epost.txt"
BEHANDLET_FILER = HER / "behandlet_filer.txt"
LOGGFIL = HER / "logg_hent.txt"
CRED = HER / "epost.cred"
EKSPORTER = HER / "eksporter_hendelser.py"
PLOTTER = HER / "regenerer_acron_plott.py"

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Vedlegg vi leter etter. Navnet er noekkelen - IKKE emnet.
ZIP_MONSTER = "plant1_pro_*.zip"
CSV_MONSTER = "plant1*.csv"

# Metodenavnene eksporter_hendelser.py skriver. De holdes uendret.
METODER = ("pilotboring", "prejet", "grouting")

MAKS_UTPAKKET_BYTE = 200 * 1024 * 1024     # vern mot zip-bomber
DATO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MND = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------
class Logg:
    """Samler linjer til loggfilen og skriver korte meldinger til skjermen."""

    def __init__(self, stille: bool = False) -> None:
        self.linjer: list[str] = []
        self.stille = stille

    def info(self, melding: str, *a) -> None:
        tekst = melding % a if a else melding
        self.linjer.append(tekst)
        if not self.stille:
            print(tekst)

    def vis(self, melding: str, *a) -> None:
        """Viktig nok til aa vises ogsaa i stille modus."""
        tekst = melding % a if a else melding
        self.linjer.append(tekst)
        print(tekst)

    def advarsel(self, melding: str, *a) -> None:
        tekst = "ADVARSEL: " + (melding % a if a else melding)
        self.linjer.append(tekst)
        print(tekst, file=sys.stderr)

    def feil(self, melding: str, *a) -> None:
        tekst = "FEIL: " + (melding % a if a else melding)
        self.linjer.append(tekst)
        print(tekst, file=sys.stderr)

    def skriv_fil(self, sti: Path) -> None:
        try:
            sti.parent.mkdir(parents=True, exist_ok=True)
            with sti.open("a", encoding="utf-8", newline="\r\n") as f:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for linje in self.linjer:
                    f.write(f"{ts} {linje}\n")
        except OSError as e:
            print(f"FEIL: kunne ikke skrive loggfil \"{sti}\": {e}",
                  file=sys.stderr)


# ---------------------------------------------------------------------------
#  Små hjelpere
# ---------------------------------------------------------------------------
def imap_dato(d: datetime) -> str:
    """IMAP-dato, f.eks. 02-Oct-2026. Bygges for haand saa den ikke er
    avhengig av spraakinnstillingene paa maskinen."""
    return f"{d.day:02d}-{MND[d.month - 1]}-{d.year}"


def trygg_del(tekst: str) -> str:
    """Gjor en tekst trygg som del av et filnavn (beholder A-Za-z0-9, - og _)."""
    ren = "".join(t if (t.isalnum() or t in "-_") else "_"
                  for t in str(tekst).strip())
    return "_".join(d for d in ren.split("_") if d) or "ukjent"


def unik_sti(mappe: Path, navn: str, logg: "Logg | None" = None,
             hva: str = "fil") -> Path:
    """Sti som ikke skriver over noe: legger paa _2, _3 ... ved kollisjon.

    Kollisjonen logges naar en ``logg`` er gitt, saa et navn som alt finnes
    fra for ikke blir byttet ut i stillhet.
    """
    sti = mappe / navn
    if not sti.exists():
        return sti
    stem, suf = sti.stem, sti.suffix
    i = 2
    while True:
        kandidat = mappe / f"{stem}_{i}{suf}"
        if not kandidat.exists():
            if logg is not None:
                logg.advarsel("%s \"%s\" fantes fra for - skriver %s i "
                              "stedet for aa overskrive", hva, navn,
                              kandidat.name)
            return kandidat
        i += 1


def les_noekler(sti: Path) -> set[str]:
    """Innholdsnoeklene i behandlet_filer.txt (forste felt per linje)."""
    ut: set[str] = set()
    if not sti.exists():
        return ut
    for linje in sti.read_text(encoding="utf-8", errors="replace").splitlines():
        linje = linje.strip()
        if linje:
            ut.add(linje.split("\t", 1)[0])
    return ut


def skriv_noekler(sti: Path, linjer: list[str], logg: "Logg") -> None:
    """Legger innholdsnoekler til behandlet_filer.txt (én linje per eksport)."""
    try:
        sti.parent.mkdir(parents=True, exist_ok=True)
        with sti.open("a", encoding="utf-8", newline="\r\n") as f:
            for linje in linjer:
                f.write(linje + "\n")
        logg.info("  skrev %d innholdsnoekkel/-(er) til %s",
                  len(linjer), sti.name)
    except OSError as e:
        logg.feil("kunne ikke skrive \"%s\": %s", sti, e)


def innholdsnoekkel(data: bytes) -> str:
    """SHA-256 av vedleggsbyttene - identifiserer EKSPORTEN, ikke meldingen."""
    return hashlib.sha256(data).hexdigest()


def noekkel_linje(navn: str, data: bytes) -> str:
    """Linjen som lagres i behandlet_filer.txt: noekkel, storrelse, navn."""
    return f"{innholdsnoekkel(data)}\t{len(data)}\t{Path(navn).name}"


def rydd_1_tvilling(maal: Path, logg: "Logg", hva: str) -> int:
    """Fjerner en gammel ``<navn>_1`` - rest etter den gamle "aldri overskriv"-
    regelen - og JS-tvillingen dens.

    ``_1`` blir ALDRI laga av den nye koden, og heller ikke av
    ``brukt_navn``-omdopingen lenger ned (den starter paa ``_2``). En fil som
    heter ``<navn>_1`` er derfor per definisjon en ELDRE utgave av samme
    pel/dato/metode. ``_2``, ``_3`` ... kan derimot vaere en ekte, egen hendelse
    og blir staende. Returnerer antall filer som ble fjernet.
    """
    stamme = maal.stem + "_1"
    fjernet = 0
    for ende in (maal.suffix, ".js"):
        tvilling = maal.with_name(stamme + ende)
        if not tvilling.exists():
            continue
        try:
            tvilling.unlink()
            fjernet += 1
            logg.info("  ryddet eldre %s \"%s\" (gammel _1-variant)", hva,
                      tvilling.name)
        except OSError as e:
            logg.advarsel("kunne ikke slette \"%s\": %s", tvilling.name, e)
    return fjernet


def _dekning(data: bytes) -> tuple[float, float] | None:
    """Hvor mye en hendelses-JSON dekker: (sekunder, cm forflytning).

    Returnerer ``None`` for alt som ikke er en hendelses-JSON. PNG, zip og den
    kombinerte ``_alle_``-fila har ikke disse feltene, og for dem gjelder
    byte-regelen som for.
    """
    try:
        d = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict) or "start" not in d or "stopp" not in d:
        return None
    try:
        start = datetime.fromisoformat(str(d["start"]))
        stopp = datetime.fromisoformat(str(d["stopp"]))
        flyttet = abs(float(d["dybde_til_cm"]) - float(d["dybde_fra_cm"]))
    except (TypeError, ValueError, KeyError):
        return None
    return ((stopp - start).total_seconds(), flyttet)


def _skriv_bytes(maal: Path, data: bytes, logg: "Logg", hva: str,
                 overskriv: bool) -> tuple[Path, bool]:
    """Kjernen bak ``skriv_unik`` og ``lagre_bytes``.

    ``overskriv=False`` er den gamle, forsiktige regelen: finnes navnet med et
    ANNET innhold, legges det nye ved siden av med ``_1``, ``_2`` ... og det
    varsles. Ingenting gaar tapt, men samme pel/dato/metode kan da staa flere
    ganger.

    ``overskriv=True`` er regelen brukeren har bestemt: DEN SOM DEKKER MEST
    VINNER. For en hendelses-JSON maales det i TID og DYBDE - hvor lenge
    hendelsen varte og hvor langt den flyttet seg - ikke i byte:

      * Dekker den nye minst like mye som den som ligger der, skrives navnet
        om, og en gammel ``_1``-variant av SAMME navn ryddes bort. Det skal
        bare finnes EN fil per pel/dato/metode.
      * Dekker den nye MINDRE - kortere tid eller mindre forflytning - blir
        den gamle liggende, og det logges tydelig med BEHOLDER.

    Begrunnelsen:

    * ``_1`` blir ikke lenger laga i det hele tatt naar vi overskriver, og
      ``brukt_navn``-omdopingen lenger ned bruker ``_2``, ``_3`` ... - aldri
      ``_1``. En ``_1``-fil er derfor alltid en eldre utgave, aldri en egen
      hendelse.
    * En eksport som dekker samme dag paa nytt (glidende vindu) inneholder MER
      av samme pel/metode, og skal erstatte den ufullstendige - ikke legges ved
      siden av den.
    * Men vinduet bestemmer ogsaa hvor detektoren begynner aa lete. Flytter
      vinduets START seg (1 dogn -> 4 dogn), kan samme pel/dato/metode bli til
      en HELT ANNEN og KORTERE hendelse. Da ville "nyeste vinner" byttet bort
      en full boring mot en liten en. Derfor er det DEKNINGEN som avgjor, ikke
      tidspunktet.
    * Byte-telling ble provd forst, men den stanset ogsaa RETTELSER: retter vi
      noe som gjoer fila et par byte kortere, ble rettelsen aldri tatt i bruk.
      Dekningen er det vi faktisk bryr oss om, og da slipper rettelsen gjennom.

    For alt annet enn hendelses-JSON (PNG, zip, ``_alle_``) gjelder fortsatt
    byte-regelen: den nye maa vaere stoerre.

    Returnerer ``(sti, ny_skrevet)``. Samme innhold skrives aldri om.
    """
    if not maal.exists():
        maal.parent.mkdir(parents=True, exist_ok=True)
        maal.write_bytes(data)
        return maal, True
    gammelt = maal.read_bytes()
    if gammelt == data:
        logg.info("  uendret: %s fins allerede med samme innhold - "
                  "skriver ikke", maal.name)
        return maal, False
    if overskriv:
        gammel_d = _dekning(gammelt)
        ny_d = _dekning(data)
        if gammel_d is not None and ny_d is not None:
            if ny_d[0] < gammel_d[0] or ny_d[1] < gammel_d[1]:
                logg.info("  BEHOLDER: %s dekker MINDRE enn den vi har "
                          "(%d min / %.0f cm mot %d min / %.0f cm) - bytter "
                          "ikke bort den", maal.name, ny_d[0] / 60, ny_d[1],
                          gammel_d[0] / 60, gammel_d[1])
                return maal, False
            maal.write_bytes(data)
            ryddet = rydd_1_tvilling(maal, logg, hva)
            logg.info("  NY VINNER: %s dekker minst like mye som den vi hadde "
                      "(%d min / %.0f cm mot %d min / %.0f cm)%s",
                      maal.name, ny_d[0] / 60, ny_d[1],
                      gammel_d[0] / 60, gammel_d[1],
                      f" - ryddet {ryddet} gammel _1-variant" if ryddet else "")
            return maal, True
        if len(data) <= len(gammelt):
            logg.info("  BEHOLDER: %s har nyere innhold, men bare %d byte mot "
                      "%d - ikke stoerre, bytter ikke bort den vi har",
                      maal.name, len(data), len(gammelt))
            return maal, False
        maal.write_bytes(data)
        ryddet = rydd_1_tvilling(maal, logg, hva)
        logg.info("  STORRE VINNER: %s fantes med mindre innhold (%d -> %d "
                  "byte)%s", maal.name, len(gammelt), len(data),
                  f" - ryddet {ryddet} gammel _1-variant" if ryddet else "")
        return maal, True
    i = 1
    while True:
        kandidat = maal.with_name(f"{maal.stem}_{i}{maal.suffix}")
        if not kandidat.exists():
            kandidat.write_bytes(data)
            logg.advarsel("%s \"%s\" fantes med ANNET innhold - skrev %s i "
                          "stedet for aa overskrive", hva, maal.name,
                          kandidat.name)
            return kandidat, True
        if kandidat.read_bytes() == data:
            logg.info("  %s \"%s\" fantes med annet innhold - bruker %s "
                      "(samme innhold)", hva, maal.name, kandidat.name)
            return kandidat, False
        i += 1


def skriv_unik(maal: Path, data: bytes, logg: "Logg", hva: str = "fil",
               overskriv: bool = True) -> tuple[Path, bool]:
    """Skriver ``data`` til ``maal``. Se ``_skriv_bytes``.

    Standard er ``overskriv=True``: den STORRE versjonen av samme pel/dato/
    metode vinner, saa en ufullstendig eksport blir erstattet av en fullere -
    ikke en duplikat - mens en nyere men mindre utgave aldri faar bytte bort
    den vi har. Bruk ``overskriv=False`` der historikk skal bevares.
    """
    return _skriv_bytes(maal, data, logg, hva, overskriv)


def les_cred(sti: Path) -> dict[str, str]:
    """Leser NOKKEL=verdi fra epost.cred. `#` er kommentar. Ingen hemmelighet
    skrives ut noe sted."""
    verdier: dict[str, str] = {}
    tekst = sti.read_text(encoding="utf-8", errors="replace")
    for linje in tekst.splitlines():
        linje = linje.strip()
        if not linje or linje.startswith("#") or "=" not in linje:
            continue
        noekkel, verdi = linje.split("=", 1)
        verdier[noekkel.strip().upper()] = verdi.strip()
    return verdier


# ---------------------------------------------------------------------------
#  BODYSTRUCTURE - finn vedleggsnavn uten aa laste ned innholdet
# ---------------------------------------------------------------------------
def les_imap_liste(raa: bytes) -> list:
    """Leser en IMAP-parentesliste (BODYSTRUCTURE) om til nestede lister.

    Vi vil ha navnene paa vedleggene, og BODYSTRUCTURE inneholder dem som
    `"NAME" "filnavn"` og `"FILENAME" "filnavn"`. Ved aa lese strukturen i
    stedet for hele meldingen unngaar vi aa laste ned innholdet i meldinger
    som ikke har noe vedlegg.
    """
    i = 0
    n = len(raa)

    def hopp_ws() -> None:
        nonlocal i
        while i < n and raa[i:i + 1] in b" \r\n\t":
            i += 1

    def les_verdi():
        nonlocal i
        hopp_ws()
        if i >= n:
            return None
        c = raa[i:i + 1]
        if c == b"(":
            i += 1
            liste: list = []
            while True:
                hopp_ws()
                if i >= n:
                    break
                if raa[i:i + 1] == b")":
                    i += 1
                    break
                liste.append(les_verdi())
            return liste
        if c == b'"':
            i += 1
            buf = bytearray()
            while i < n:
                tegn = raa[i:i + 1]
                if tegn == b"\\":
                    buf += raa[i + 1:i + 2]
                    i += 2
                    continue
                if tegn == b'"':
                    i += 1
                    break
                buf += tegn
                i += 1
            return bytes(buf)
        if c == b"{":
            j = raa.find(b"}", i)
            if j < 0:
                i = n
                return b""
            lengde = int(raa[i + 1:j])
            i = j + 1
            if raa[i:i + 2] == b"\r\n":
                i += 2
            elif raa[i:i + 1] in (b"\r", b"\n"):
                i += 1
            verdi = raa[i:i + lengde]
            i += lengde
            return verdi
        start = i
        while i < n and raa[i:i + 1] not in b" ()":
            i += 1
        atom = raa[start:i]
        if atom.upper() == b"NIL":
            return None
        return atom

    verdier: list = []
    while True:
        hopp_ws()
        if i >= n:
            break
        verdier.append(les_verdi())
    return verdier


def _plukk_filnavn(obj, ut: list) -> None:
    """Gaar gjennom strukturen og plukker ut NAME/FILENAME-parametere."""
    if isinstance(obj, (list, tuple)):
        if len(obj) == 2 and isinstance(obj[0], bytes) and isinstance(
                obj[1], (bytes, type(None))):
            noekkel = obj[0].upper()
            if noekkel in (b"NAME", b"FILENAME") and obj[1]:
                ut.append(obj[1])
        for del_ in obj:
            _plukk_filnavn(del_, ut)


def vedleggsnavn_i_struktur(raa: bytes | tuple | list) -> list[str]:
    """Alle vedleggs-/del-navn som BODYSTRUCTURE melder om."""
    if isinstance(raa, (tuple, list)):
        tre: list = list(raa)
    else:
        tre = les_imap_liste(raa)
    funn: list[bytes] = []
    _plukk_filnavn(tre, funn)
    navn: list[str] = []
    for b in funn:
        if not isinstance(b, bytes):
            continue
        try:
            tekst = b.decode("utf-8")
        except UnicodeDecodeError:
            tekst = b.decode("latin-1", "replace")
        navn.append(tekst)
    return navn


def er_vedlegg_vi_vil_ha(navn: str) -> bool:
    """Vedleggsnavnet er noekkelen - ikke emnet. Godtar zippen riggen sender,
    og en ukpakket csv i tilfelle riggen en gang bytter."""
    l = navn.strip().lower()
    return (fnmatch.fnmatch(l, ZIP_MONSTER) or fnmatch.fnmatch(l, CSV_MONSTER))


# ---------------------------------------------------------------------------
#  Lagring og utpakking med zip-slip-vern
# ---------------------------------------------------------------------------
def lagre_bytes(maal: Path, data: bytes, logg: Logg,
                overskriv: bool = True) -> tuple[Path, bool]:
    """Skriver data til maal. Se ``_skriv_bytes`` for reglene.

    Standard ``overskriv=True`` (stoerste vinner), likt ``skriv_unik``. Brukes
    bl.a. for vedleggs-zipen i hentet\\, der vi bevarer historikken med vilje og
    derfor sender ``overskriv=False``.
    """
    return _skriv_bytes(maal, data, logg, "fil", overskriv)


def pakk_ut_zip(zipdata: bytes, maal_mappe: Path, logg: Logg,
                bare_csv: bool = True) -> list[Path]:
    """Pakker ut fra zippen. Alt annet enn vanlige filer med trygt navn
    avvises (zip-slip). Ingenting kjores eller aapnes."""
    maal_mappe.mkdir(parents=True, exist_ok=True)
    skrevet: list[Path] = []
    with zipfile.ZipFile(BytesIO(zipdata)) as z:
        for info in z.infolist():
            navn = info.filename
            if info.is_dir():
                logg.info("  hopper over mappe i zip: %s", navn)
                continue
            p = PurePosixPath(navn.replace("\\", "/"))
            if p.is_absolute() or any(d == ".." for d in p.parts):
                logg.advarsel("avviser utrygg sti i zip (zip-slip): %s", navn)
                continue
            if info.file_size > MAKS_UTPAKKET_BYTE:
                logg.advarsel("%s er uventet stor (%d byte) - avviser",
                              navn, info.file_size)
                continue
            basenavn = p.name
            if bare_csv and not basenavn.lower().endswith(".csv"):
                logg.info("  hopper over fil i zip som ikke er en csv: %s",
                          basenavn)
                continue
            with z.open(info) as f:
                innhold = f.read()
            sti, _ny = lagre_bytes(maal_mappe / basenavn, innhold, logg)
            skrevet.append(sti)
    return skrevet


# ---------------------------------------------------------------------------
#  Trinn 2-6: dekod, del json, plott, flat ut
# ---------------------------------------------------------------------------
def kjor_verktoy(kommando: list, logg: Logg, cwd: Path) -> int:
    """Kjorer et av de uendrede verktoyene og speiler utskriften i loggen."""
    logg.info("  $ %s", " ".join(str(k) for k in kommando))
    miljo = dict(os.environ)
    miljo["PYTHONIOENCODING"] = "utf-8"
    miljo["PYTHONUTF8"] = "1"
    try:
        svar = subprocess.run([str(k) for k in kommando], cwd=str(cwd),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=miljo)
    except OSError as e:
        logg.feil("kunne ikke starte verktoyet: %s", e)
        return 1
    for linje in (svar.stdout or "").splitlines():
        logg.info("    %s", linje)
    for linje in (svar.stderr or "").splitlines():
        logg.info("    ! %s", linje)
    return int(svar.returncode)


def finn_csv(mappe: Path) -> Path | None:
    """CSV-en i arbeidsmappen. Plant1-navnet foretrekkes, ellers hvilken som."""
    kandidater = sorted(mappe.glob("*.csv"))
    if not kandidater:
        return None
    for sti in kandidater:
        if fnmatch.fnmatch(sti.name.lower(), CSV_MONSTER):
            return sti
    return kandidater[0]


def flat_plottnavn(png: Path, rot: Path, pel_dato: dict[str, str],
                   reserve_dato: str) -> tuple[str, str]:
    """(dato, nytt filnavn) for et plott fra plotterens egen mappestruktur.

    Plotteren skriver `<mappe>/<pel>/<nr>_<metode>.png`, og naar loggen rommer
    flere dager `<mappe>/<dato>/<pel>/...`. Vi leser dato og pel ut av stien og
    metoden ut av filnavnet, og lager `<dato>_<pel>_<metode>.png`.
    """
    deler = png.relative_to(rot).parts
    fil = deler[-1]
    pel = trygg_del(deler[-2]) if len(deler) >= 2 else "ukjent"

    dato = ""
    for del_ in deler[:-2]:
        if DATO_RE.match(del_):
            dato = del_
    if not dato:
        dato = pel_dato.get(deler[-2], "") if len(deler) >= 2 else ""
    if not dato:
        dato = reserve_dato

    stem = fil[:-4] if fil.lower().endswith(".png") else fil
    rest = stem.split("_", 1)[1] if "_" in stem else stem
    if rest == "hele_produksjonen":
        metode = "hele"
    else:
        metode = trygg_del(rest)
    return dato, f"{dato}_{pel}_{metode}.png"


# ---------------------------------------------------------------------------
#  index.json - listen hendelsesviseren bygger nedtrekksmenyen fra
# ---------------------------------------------------------------------------
def les_indeksoppforing(sti: Path, logg: Logg) -> dict | None:
    """Leser pel/metode/dato og nokkeltall fra én hendelses-JSON.

    Den kombinerte ``_alle_``-filen faar en egen oppforing med antall
    hendelser i stedet for pel/metode. Returnerer ``None`` hvis filen ikke
    lar seg lese, saa én odelagt fil ikke velter hele listen.
    """
    try:
        with sti.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logg.advarsel("kunne ikke lese \"%s\" til index.json: %s",
                      sti.name, e)
        return None
    if sti.name.lower().startswith("_alle_"):
        return {"fil": sti.name, "kombinert": True,
                "dato": str(data.get("fra", ""))[:10] or None,
                "antall": len(data.get("hendelser") or [])}
    # ``dybde_fra_cm``/``dybde_til_cm`` blir med ut hit fordi viseren regner
    # ut hvor lang PELEN er fra dem: den tar den dypeste og den grunneste
    # dybden over ALLE hendelsene med samme pelnavn, og tegner alle grafene
    # for den pelen med samme akse. Da ser en med én gang om en prejet eller
    # grouting stoppet for pelen var ferdig - uten dem ble hver graf skalert
    # til sitt eget lille utsnitt og sa at alt var i orden.
    return {"fil": sti.name, "kombinert": False,
            "pel": data.get("pel"), "metode": data.get("metode"),
            "dato": data.get("dato"), "lengde_cm": data.get("lengde_cm"),
            "uferdig": bool(data.get("uferdig")),
            "dybde_fra_cm": data.get("dybde_fra_cm"),
            "dybde_til_cm": data.get("dybde_til_cm"),
            "snitt_cm_min": data.get("snitt_cm_min"),
            "stopp": len(data.get("stopp_perioder") or []),
            "varighet": data.get("varighet")}


def _skriv_js_tvillingar(jsonmappe: Path, logg: Logg) -> None:
    """Skriv index.js og <navn>.js ved sida av hendelses-JSON-en.

    Reservelosning for ``file://``, der nettlesaren blokkerer ``fetch`` men
    tillèt ein vanleg ``<script src>``. Selve skrivinga ligg i
    ``eksporter_hendelser.skriv_js_tvillinger``, slik at JSON og JS alltid
    blir laga av same kode og ikkje kan gli fra kvarandre. Importen er
    verna, saa ein manglande avhengigheit ikkje velter heile kjeden.
    """
    try:
        sys.path.insert(0, str(HER))
        import eksporter_hendelser as eks
    except Exception as e:                                # pragma: no cover
        logg.advarsel("hoppar over js-tvillingar (%s)", e)
        return
    try:
        eks.skriv_js_tvillinger(jsonmappe, logg)
    except Exception as e:                                # pragma: no cover
        logg.advarsel("kunne ikke skrive js-tvillingar (%s)", e)


# Hvor lenge det kan vaere stille foer vi sier fra i loggen. En ny eksport
# kommer normalt hvert 15.-30. minutt mens riggen gaar; to timer uten noe er
# verdt en linje.
STILLHET_VARSEL_TIMER = 2.0


def skriv_stillhetsvarsel(logg: Logg) -> None:
    """Sier fra hvor gammelt det nyeste vedlegget i hentet\\ er.

    *hentet=0* hvert kvarter betyr som regel at riggen eller senderen ikke har
    sendt noe - ikke at vi staar fast. Uten denne linjen maa operatoren gjette,
    og lete etter feil paa feil maskin.
    """
    if not HENTET.exists():
        logg.advarsel("mappen \"%s\" finnes ikke", HENTET)
        return
    nyeste: tuple[float, Path] | None = None
    for fil in HENTET.glob("plant1*"):
        try:
            t = fil.stat().st_mtime
        except OSError:
            continue
        if nyeste is None or t > nyeste[0]:
            nyeste = (t, fil)
    if nyeste is None:
        logg.advarsel("stille: har aldri mottatt noe vedlegg i \"%s\"", HENTET)
        return
    t, fil = nyeste
    alder = (datetime.now().timestamp() - t) / 3600.0
    naar = datetime.fromtimestamp(t).strftime("%d.%m %H:%M")
    if alder >= STILLHET_VARSEL_TIMER:
        logg.advarsel("stille i %.1f time(r) - nyeste vedlegg er \"%s\" fra "
                      "%s. Sjekk senderen paa Win7 (logg_sendt.txt) og "
                      "acron-jobben paa XP. Ingenting mangler her.",
                      alder, fil.name, naar)
    else:
        logg.info("nyeste vedlegg: \"%s\" fra %s (%.0f min siden)",
                  fil.name, naar, alder * 60.0)


def skriv_indeks(jsonmappe: Path, logg: Logg,
                 hadde_hendelser: bool = True) -> Path | None:
    """Skriver/overskriver index.json ut fra hendelses-JSON-ene i mappen.

    Viseren kan ikke lese katalogen sin selv, saa denne listen er dens eneste
    oversikt. Den skal alltid gjenspeile det som FAKTISK ligger i mappen.

    Ga kjoringen null hendelser, skriver vi ingenting: en tom eller gammel
    liste ville lurt operatoren. Vi sier fra i loggen i stedet.
    """
    if not hadde_hendelser:
        logg.info("ingen hendelser i denne kjoringen - skriver ikke "
                  "index.json (ville blitt tom/utdatert)")
        return None
    if not jsonmappe.exists():
        logg.advarsel("mappen \"%s\" finnes ikke - skriver ikke index.json",
                      jsonmappe)
        return None
    filer = sorted(p for p in jsonmappe.glob("*.json")
                   if p.name.lower() != "index.json")
    if not filer:
        logg.advarsel("fant ingen hendelses-JSON i \"%s\" - skriver ikke "
                      "index.json", jsonmappe)
        return None
    per = [p for p in filer if not p.name.lower().startswith("_alle_")]
    kombi = [p for p in filer if p.name.lower().startswith("_alle_")]
    hendelser: list[dict] = []
    for p in per + kombi:                       # kombinerte helt til slutt
        opp = les_indeksoppforing(p, logg)
        if opp is not None:
            hendelser.append(opp)
    if not hendelser:
        logg.advarsel("ingen lesbare hendelses-JSON i \"%s\" - skriver ikke "
                      "index.json", jsonmappe)
        return None
    innhold = {"generert": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
               "antall": len(hendelser), "hendelser": hendelser}
    sti = jsonmappe / "index.json"
    try:
        sti.write_text(json.dumps(innhold, ensure_ascii=False, indent=2)
                       + "\n", encoding="utf-8")
    except OSError as e:
        logg.feil("kunne ikke skrive \"%s\": %s", sti, e)
        return None
    logg.info("  index.json: %d oppforing(er), %d byte",
              len(hendelser), sti.stat().st_size)
    # JS-tvillingane blir laga av det som no ligg i mappa, med same kode
    # som JSON-en, saa dei ikkje kan kome i utakt.
    _skriv_js_tvillingar(jsonmappe, logg)
    return sti


def behandle_csv(csv: Path, arbeid: Path, logg: Logg) -> dict:
    """Trinn 3-6 for én CSV. Returnerer tellinger og eventuelle feil."""
    utfall = {"arbeid": arbeid, "hendelser": 0, "json": 0, "plott": 0,
              "feil": [], "hendelser_liste": []}
    arbeid.mkdir(parents=True, exist_ok=True)
    kombinert = arbeid / "hendelser.json"

    # -- trinn 3: dekod (eksporter_hendelser.py, UENDRET) --------------------
    if not EKSPORTER.exists():
        utfall["feil"].append(f"finner ikke {EKSPORTER.name}")
        logg.feil("finner ikke verktoyet \"%s\"", EKSPORTER)
        return utfall
    if not PLOTTER.exists():
        utfall["feil"].append(f"finner ikke {PLOTTER.name}")
        logg.feil("finner ikke verktoyet \"%s\"", PLOTTER)
        return utfall

    logg.info("dekoder hendelser: %s", csv.name)
    rc = kjor_verktoy([sys.executable, EKSPORTER, csv, "--ut", kombinert],
                      logg, HER)
    if rc != 0 or not kombinert.exists():
        utfall["feil"].append("eksporter_hendelser.py feilet")
        logg.feil("dekodingen feilet (feilkode %d) for %s", rc, csv.name)
        return utfall

    try:
        data = json.loads(kombinert.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        utfall["feil"].append(f"kunne ikke lese hendelses-JSON: {e}")
        logg.feil("kunne ikke lese \"%s\": %s", kombinert, e)
        return utfall

    hendelser = data.get("hendelser") or []
    utfall["hendelser"] = len(hendelser)
    utfall["hendelser_liste"] = hendelser
    eksport_dato = (str(data.get("fra", ""))[:10]) or \
        datetime.now().strftime("%Y-%m-%d")

    if not hendelser:
        utfall["feil"].append("eksporten ga null hendelser")
        logg.feil("eksporten \"%s\" ga NULL hendelser - ingenting aa dele "
                  "eller plotte", csv.name)
        return utfall

    # -- trinn 4: én JSON per hendelse + den kombinerte ----------------------
    JSONMAPPE.mkdir(parents=True, exist_ok=True)
    try:
        alle_data = kombinert.read_bytes()
    except OSError as e:
        utfall["feil"].append(f"kunne ikke lese hendelses-JSON: {e}")
        logg.feil("kunne ikke lese \"%s\": %s", kombinert, e)
        return utfall
    alle_sti, _ny = skriv_unik(JSONMAPPE / f"_alle_{eksport_dato}.json",
                               alle_data, logg, "kombinert json")
    logg.info("  kombinert: %s", alle_sti.name)

    brukt_navn: set[str] = set()
    for h in hendelser:
        dato = trygg_del(str(h.get("dato") or eksport_dato))
        pel = trygg_del(str(h.get("pel") or "ukjent"))
        metode = trygg_del(str(h.get("metode") or "ukjent").lower())
        if metode not in METODER:
            logg.advarsel("ukjent metode \"%s\" for pel %s - beholder navnet",
                          metode, pel)
        navn = f"{dato}_{pel}_{metode}.json"
        if navn in brukt_navn:            # to hendelser, samme navn
            stamme = Path(navn).stem
            i = 2
            while f"{stamme}_{i}.json" in brukt_navn:
                i += 1
            navn = f"{stamme}_{i}.json"
        brukt_navn.add(navn)
        innhold = (json.dumps(h, ensure_ascii=False, indent=2)
                   + "\n").encode("utf-8")
        sti, _ny = skriv_unik(JSONMAPPE / navn, innhold, logg, "json")
        utfall["json"] += 1
        logg.info("  json: %s", sti.name)

    # -- trinn 5 og 6: lokal PNG-fil (bare naar --plott blir gitt) ----------
    # Grafene hoerer hjemme paa nettstedet. Viseren der tegner dem levende fra
    # hendelses-JSON-en, med hele pelens dybdeakse, pausene merket og stigning
    # for hver fase - og den kan skrives ut. En PNG i plot\\ blir en ekstra
    # kopi som kan bli staaende og vise et gammelt vindu. Derfor er dette
    # av som standard.
    if not SKRIV_LOKALE_PLOTT:
        logg.info("lokal PNG hoppet over - grafene ligger paa nettstedet "
                  "(bruk --plott for aa lage PNG her ogsaa)")
        return utfall

    plot_ut = arbeid / "plott"
    logg.info("plotter: %s", csv.name)
    rc = kjor_verktoy([sys.executable, PLOTTER, csv, "--alle-peler",
                       "--mappe", plot_ut, "--ingen-html"], logg, HER)
    if rc != 0:
        utfall["feil"].append("regenerer_acron_plott.py feilet")
        logg.feil("plottingen feilet (feilkode %d) for %s", rc, csv.name)
        return utfall

    pnger = sorted(plot_ut.rglob("*.png")) if plot_ut.exists() else []
    if not pnger:
        utfall["feil"].append("plotteren skrev ingen PNG")
        logg.feil("plotteren skrev ingen PNG for %s", csv.name)
        return utfall

    # -- trinn 6: flat ut og dop om -----------------------------------------
    PLOTMAPPE.mkdir(parents=True, exist_ok=True)
    pel_dato: dict[str, str] = {}
    for h in hendelser:
        pel_dato.setdefault(str(h.get("pel") or ""),
                            str(h.get("dato") or eksport_dato))
    for png in pnger:
        _dato, navn = flat_plottnavn(png, plot_ut, pel_dato, eksport_dato)
        try:
            bilde_data = png.read_bytes()
        except OSError as e:
            logg.advarsel("kunne ikke lese plottet \"%s\": %s", png, e)
            continue
        sti, _ny = skriv_unik(PLOTMAPPE / navn, bilde_data, logg, "plott")
        utfall["plott"] += 1
        logg.info("  plott: %s", sti.name)

    if utfall["plott"] == 0:
        utfall["feil"].append("ingen plott ble lagt i plot\\")
        logg.feil("ingen plott havnet i \"%s\"", PLOTMAPPE)
    return utfall


def kjor_kjede(fil: Path, logg: Logg) -> dict:
    """Trinn 2-6 for en mottatt zip eller csv. Skriver i json\\ og plot\\."""
    arbeid = ARBEID / trygg_del(fil.stem)
    if arbeid.exists():
        shutil.rmtree(arbeid, ignore_errors=True)
    arbeid.mkdir(parents=True, exist_ok=True)

    if fil.suffix.lower() == ".zip":
        logg.info("pakker ut: %s", fil.name)
        try:
            csv_er = pakk_ut_zip(fil.read_bytes(), arbeid, logg, bare_csv=True)
        except (OSError, zipfile.BadZipFile) as e:
            logg.feil("kunne ikke pakke ut \"%s\": %s", fil.name, e)
            return {"arbeid": arbeid, "hendelser": 0, "json": 0, "plott": 0,
                    "feil": [f"utpakking feilet: {e}"], "hendelser_liste": []}
        logg.info("  pakket ut %d fil(er)", len(csv_er))
        csv = finn_csv(arbeid)
    else:
        csv = fil

    if csv is None or not csv.exists():
        logg.feil("fant ingen CSV i \"%s\"", fil.name)
        return {"arbeid": arbeid, "hendelser": 0, "json": 0, "plott": 0,
                "feil": ["fant ingen CSV i vedlegget"],
                "hendelser_liste": []}

    return behandle_csv(csv, arbeid, logg)


# ---------------------------------------------------------------------------
#  Trinn 1: henting fra Gmail
# ---------------------------------------------------------------------------
def hent_fra_gmail(logg: Logg, args) -> dict:
    """Henter nye vedlegg til hentet\\.

    Idempotent paa tre nivaaer: \\Seen i Gmail, behandlet_epost.txt (Message-ID)
    og behandlet_filer.txt (SHA-256 av vedleggsbyttene). Er eksporten alt
    behandlet - ogsaa naar meldingen har ny Message-ID - blir den logget som
    DUPLIKAT og verken dekodet eller plottet.
    """
    utfall = {"funnet": 0, "nye": 0, "hentet": 0, "ferdig": 0, "feil": 0,
              "duplikater": 0, "filer": [], "nokler": {},
              "duplikat_linjer": [], "feilet": False, "koble_feil": False}

    try:
        cred = les_cred(CRED)
    except PermissionError:
        logg.feil("kunne ikke lese \"%s\" (tilgang nektet). Filen er "
                  "ACL-sperret - kjor fra en konto som har lov, eller utvid "
                  "ACL-en (se LES_MEG_KONTOR.txt).", CRED)
        utfall["feilet"] = True
        utfall["koble_feil"] = True
        return utfall
    except OSError as e:
        logg.feil("kunne ikke lese \"%s\": %s", CRED, e)
        utfall["feilet"] = True
        utfall["koble_feil"] = True
        return utfall

    bruker = cred.get("SMTP_USER") or cred.get("IMAP_USER")
    noekkel = cred.get("SMTP_KEY") or cred.get("IMAP_KEY") or cred.get("SMTP_PASS")
    if not bruker or not noekkel:
        logg.feil("SMTP_USER eller SMTP_KEY mangler i \"%s\"", CRED)
        utfall["feilet"] = True
        utfall["koble_feil"] = True
        return utfall

    behandlet: set[str] = set()
    if BEHANDLET.exists():
        for linje in BEHANDLET.read_text(encoding="utf-8",
                                         errors="replace").splitlines():
            linje = linje.strip()
            if linje:
                behandlet.add(linje)
    # Innholdsnoekler for eksporter som alt er dekodet og plottet. Denne
    # fanger opp samme eksport sendt i en NY melding (ny Message-ID).
    behandlet_filer = les_noekler(BEHANDLET_FILER)
    denne_kjoringen: set[str] = set()          # noekler tatt imot i denne runden

    logg.info("starter %s", "provetur" if args.test else "henting")
    logg.info("  konto    : %s", bruker)
    logg.info("  mappe    : %s", HENTET)
    logg.info("  vedlegg  : %s  (og %s)", ZIP_MONSTER, CSV_MONSTER)
    logg.info("  behandlet: %d Message-ID(er), %d eksportnoekkel/-(er)",
              len(behandlet), len(behandlet_filer))
    logg.info("  sok      : SINCE %s",
              imap_dato(datetime.now() - timedelta(days=args.siden_dager)))
    logg.info("  nokkel   : <satt> (skrives aldri ut)")

    kontekst = ssl.create_default_context()
    try:
        m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=kontekst)
    except OSError as e:
        logg.feil("kunne ikke koble til %s:%d: %s", IMAP_HOST, IMAP_PORT, e)
        utfall["feilet"] = True
        utfall["koble_feil"] = True
        return utfall

    nye_uider: list = []
    nye_mid: list[str] = []
    try:
        typ, svar = m.login(bruker, noekkel)
        if typ != "OK":
            logg.feil("innlogging feilet: %s", svar)
            utfall["feilet"] = True
            utfall["koble_feil"] = True
            return utfall
        logg.info("  innlogget OK")

        # -- LESERETT (EXAMINE): endrer ingen flagg under soket -------------
        typ, data = m.select("INBOX", readonly=True)
        if typ != "OK":
            logg.feil("kunne ikke aapne INBOX: %s", data)
            utfall["feilet"] = True
            utfall["koble_feil"] = True
            return utfall

        kriterier = ["SINCE",
                     imap_dato(datetime.now() - timedelta(days=args.siden_dager))]
        if args.fra:
            kriterier += ["FROM", f'"{args.fra}"']
        typ, svar = m.uid("search", None, f"({' '.join(kriterier)})")
        if typ != "OK":
            logg.feil("SEARCH feilet: %s", svar)
            utfall["feilet"] = True
            return utfall
        uider = svar[0].split() if svar and svar[0] else []
        logg.info("  SEARCH fant %d kandidat(er)", len(uider))

        for uid in uider:
            typ, strukt = m.uid("fetch", uid, "(BODYSTRUCTURE)")
            if typ != "OK" or not strukt or not strukt[0]:
                continue
            raa = strukt[0]
            if isinstance(raa, tuple):
                raa = raa[0] if raa and isinstance(raa[0], bytes) else b""
            navn = vedleggsnavn_i_struktur(raa)
            treff = [n for n in navn if er_vedlegg_vi_vil_ha(n)]
            if not treff:
                continue
            utfall["funnet"] += 1

            typ, hode = m.uid(
                "fetch", uid,
                "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT DATE FROM)])")
            mid = ""
            emne = ""
            if typ == "OK" and hode and hode[0] and len(hode[0]) > 1:
                msg = BytesParser(policy=policy.default).parsebytes(hode[0][1])
                mid = (msg.get("Message-ID") or "").strip()
                emne = str(msg.get("Subject") or "").strip()
            if not mid:
                raa_id = f"{emne}|{','.join(sorted(treff))}".encode()
                mid = "uten-id:" + hashlib.sha256(raa_id).hexdigest()[:20]

            if mid in behandlet:
                logg.info("  hopper over (allerede behandlet): %s", mid)
                utfall["ferdig"] += 1
                continue

            utfall["nye"] += 1
            if args.test:
                logg.vis("  VILLE HENTET: %s  vedlegg: %s  emne=%r",
                         mid, ", ".join(treff), emne)
                utfall["hentet"] += 1
                continue

            if utfall["hentet"] >= args.maks:
                logg.advarsel("naadde --maks %d denne runden - resten tas "
                              "neste gang", args.maks)
                break

            typ, full = m.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not full or not full[0] or len(full[0]) < 2:
                logg.feil("kunne ikke hente meldingen %s", mid)
                utfall["feil"] += 1
                continue
            melding = BytesParser(policy=policy.default).parsebytes(full[0][1])

            HENTET.mkdir(parents=True, exist_ok=True)
            lagret_noe = False
            duplikat_her = False
            for del_ in melding.walk():
                fn = del_.get_filename()
                if not fn:
                    continue
                fn = fn.strip()
                if not er_vedlegg_vi_vil_ha(fn):
                    continue
                innhold = del_.get_payload(decode=True)
                if not isinstance(innhold, bytes):
                    logg.advarsel("vedlegget %s kunne ikke leses som bytes",
                                  fn)
                    continue
                logg.info("  henter vedlegg %s (%d byte)", fn, len(innhold))
                noekkel = innholdsnoekkel(innhold)
                kort = noekkel[:12]
                # -- innholdsnoekkel: samme EKSPORT skal aldri dekodes og
                # plottes to ganger, uansett hvor mange meldinger som bærer
                # den. Vi sjekker baade loggen fra tidligere kjoringer og det
                # vi alt har tatt imot i denne runden.
                if noekkel in behandlet_filer:
                    duplikat_her = True
                    utfall["duplikater"] += 1
                    utfall["duplikat_linjer"].append(
                        f"DUPLIKAT (tidligere behandlet) {Path(fn).name} "
                        f"sha256={kort} melding={mid}")
                    logg.vis("  DUPLIKAT: %s (sha256 %s, %d byte) er alt "
                             "behandlet - hopper over dekod/plott",
                             Path(fn).name, kort, len(innhold))
                    continue
                if noekkel in denne_kjoringen:
                    duplikat_her = True
                    utfall["duplikater"] += 1
                    utfall["duplikat_linjer"].append(
                        f"DUPLIKAT (samme kjoring) {Path(fn).name} "
                        f"sha256={kort} melding={mid}")
                    logg.vis("  DUPLIKAT: %s (sha256 %s, %d byte) kom alt "
                             "i denne kjoringen - hopper over dekod/plott",
                             Path(fn).name, kort, len(innhold))
                    continue
                # Arkiverer den raa eksporten. Her bevarer vi historikken med
                # vilje (overskriv=False): en ny eksport med SAMME navn men
                # annet innhold blir <navn>_1.zip, saa eksporten fra riggen
                # aldri forsvinner. De AVLEDEDE filene (json/plot) overskriver
                # vi derimot - det er de som er "pel" i viseren.
                sti, _ny = lagre_bytes(HENTET / Path(fn).name, innhold, logg,
                                       overskriv=False)
                denne_kjoringen.add(noekkel)
                if sti not in utfall["filer"]:
                    utfall["filer"].append(sti)
                utfall["nokler"][str(sti)] = noekkel_linje(Path(fn).name,
                                                          innhold)
                lagret_noe = True
                logg.info("     lagret: %s", sti.name)

            if lagret_noe or duplikat_her:
                behandlet.add(mid)
                nye_uider.append(uid)
                nye_mid.append(mid)
                if lagret_noe:
                    utfall["hentet"] += 1
                logg.info("  ferdig med %s", mid)
            else:
                logg.advarsel("vedlegg annonsert, men ingenting ble lagret: %s",
                              mid)

        # -- \\Seen settes til slutt, i LESESKRIV-okt. Aldri under soket. ----
        if nye_uider and not args.test:
            typ, _ = m.select("INBOX")          # read-write
            if typ == "OK":
                for uid in nye_uider:
                    m.uid("store", uid, "+FLAGS", "\\Seen")
                logg.info("  satte \\Seen paa %d melding(er)", len(nye_uider))
            else:
                logg.advarsel("kunne ikke aapne INBOX leseskriv - \\Seen ble "
                              "ikke satt (den lokale loggen hindrer dobbeltkjor)")

    except imaplib.IMAP4.error as e:
        logg.feil("IMAP-feil: %s", e)
        utfall["feil"] += 1
        utfall["feilet"] = True
    finally:
        try:
            m.logout()
        except Exception:                                        # noqa: BLE001
            pass

    # -- behandlet-logg skrives bare ETTER at filene er lagret --------------
    if nye_mid and not args.test:
        try:
            BEHANDLET.parent.mkdir(parents=True, exist_ok=True)
            with BEHANDLET.open("a", encoding="utf-8", newline="\r\n") as f:
                for mid in nye_mid:
                    f.write(mid + "\n")
            logg.info("  skrev %d Message-ID(er) til %s", len(nye_mid),
                      BEHANDLET.name)
        except OSError as e:
            logg.feil("kunne ikke skrive \"%s\": %s", BEHANDLET, e)
            utfall["feil"] += 1

    # -- duplikater: logges tydelig, men er ikke en feil ---------------------
    if utfall["duplikater"]:
        logg.info("  %d duplikat(er) hoppet over - fantes i "
                  "behandlet_filer.txt eller kom flere ganger i samme "
                  "kjoring", utfall["duplikater"])

    # -- et vedlegg som ble annonsert, men aldri lagret = feil --------------
    # (Et duplikat er ikke en feil: eksporten er alt behandlet.)
    if (not args.test and utfall["nye"] > 0 and utfall["hentet"] == 0
            and utfall["feil"] == 0 and utfall["duplikater"] == 0):
        logg.feil("%d melding(er) med vedlegg ble funnet, men ingen ble "
                  "lagret", utfall["nye"])
        utfall["feilet"] = True
    return utfall


# ---------------------------------------------------------------------------
#  Argparse
# ---------------------------------------------------------------------------
def normaliser_argv(argv: list[str]) -> list[str]:
    """/test -> --test, slik at baade Windows- og Unix-stil virker."""
    ut: list[str] = []
    for a in argv:
        if len(a) > 1 and a[0] == "/" and ":" not in a[:3]:
            ut.append("--" + a[1:])
        else:
            ut.append(a)
    return ut


def bygg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hent_og_plott",
        description="Hent Plant1 Pro-eksporten fra Gmail, dekod, del og plott.")
    p.add_argument("--test", "--provetur", dest="test",
                   action="store_true",
                   help="provetur: vis hva som VILLE blitt hentet - hent "
                        "ingenting, endre ingenting, skriv ingenting")
    p.add_argument("--bare-hent", dest="bare_hent",
                   action="store_true",
                   help="stopp etter hentingen - hopp over dekod og plott")
    p.add_argument("--slett-arbeid", dest="slett_arbeid",
                   action="store_true",
                   help="tom arbeid\\ naar kjeden er ferdig")
    p.add_argument("--plott", dest="plott", action="store_true",
                   help="lag PNG-er i plot\\ ogsaa. Standard er NEI: grafene "
                        "ligger paa nettstedet, og en lokal PNG blir bare en "
                        "ekstra kopi som kan bli staaende og vise feil vindu")
    p.add_argument("--json-dir", dest="json_dir", default=str(JSONMAPPE),
                   metavar="STI",
                   help="mappen hendelses-JSON (og index) skrives til. Standard "
                        "er json\\ ved siden av scriptet; GitHub Actions peker "
                        "den paa nettsteds-repoets data\\")
    p.add_argument("--fra-zip", dest="fra_zip", default=None, metavar="FIL",
                   help="kjor dekod/plot/del paa en lokal zip i stedet for "
                        "Gmail (til proving - roerer ikke postkassen)")
    p.add_argument("--siden-dager", type=int, default=30, metavar="DAGER",
                   help="SEARCH SINCE: meldinger fra og med saa mange dager "
                        "tilbake (30)")
    p.add_argument("--fra", default=None,
                   help="valgfritt: begrens SEARCH til denne avsenderen")
    p.add_argument("--maks", type=int, default=50,
                   help="hoyeste antall nye meldinger aa behandle i en runde")
    p.add_argument("--still", dest="stille", action="store_true",
                   help="stille: bare advarsler/feil til skjerm "
                        "(for Task Scheduler)")
    return p


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    global SKRIV_LOKALE_PLOTT, JSONMAPPE
    args = bygg_parser().parse_args(normaliser_argv(
        list(sys.argv[1:] if argv is None else argv)))
    # -- hvor hendelses-JSON-ene havner. Standard er json\ ved siden av
    #    scriptet (kontor-PC-en). GitHub Actions peker den paa data\ i
    #    nettsteds-repoet, saa data\ blir EN kilde til sannhet og ingenting
    #    dupliseres.
    JSONMAPPE = Path(args.json_dir).resolve()
    SKRIV_LOKALE_PLOTT = bool(args.plott)
    logg = Logg(stille=args.stille)

    for mappe in ((HENTET, ARBEID, JSONMAPPE) if not SKRIV_LOKALE_PLOTT
                  else (HENTET, ARBEID, JSONMAPPE, PLOTMAPPE)):
        mappe.mkdir(parents=True, exist_ok=True)

    if args.test:
        logg.vis("== PROVETUR (--test): ingenting blir skrevet eller merket ==")

    try:
        # -- lokal zip: dekod/plot-halvdelen uten aa roere postkassen -------
        if args.fra_zip:
            zip_sti = Path(args.fra_zip)
            if not zip_sti.exists():
                logg.feil("finner ikke \"%s\"", zip_sti)
                logg.skriv_fil(LOGGFIL)
                return 1
            logg.info("lokal zip: %s", zip_sti)
            utfall = kjor_kjede(zip_sti, logg)
            if not args.test:
                skriv_indeks(JSONMAPPE, logg, utfall["hendelser"] > 0)
            if args.slett_arbeid:
                shutil.rmtree(utfall["arbeid"], ignore_errors=True)
            feilet = bool(utfall["feil"])
            logg.vis("SAMMENDRAG: hentet=0, duplikater=0, pakket_ut=-, "
                     "hendelser=%d, json=%d, plott=%d, feilet=%d",
                     utfall["hendelser"], utfall["json"], utfall["plott"],
                     len(utfall["feil"]))
            if not args.test:
                logg.skriv_fil(LOGGFIL)
            return 1 if feilet else 0

        # -- trinn 1: hent fra Gmail ---------------------------------------
        hent = hent_fra_gmail(logg, args)

        if args.test:
            logg.vis("SAMMENDRAG (provetur): ville hentet=%d, funnet=%d, "
                     "allerede behandlet=%d, feilet=%d",
                     hent["hentet"], hent["funnet"], hent["ferdig"],
                     hent["feil"])
            return 1 if hent["koble_feil"] else 0

        if hent["koble_feil"]:
            logg.skriv_fil(LOGGFIL)
            return 1

        if args.bare_hent:
            logg.vis("SAMMENDRAG: hentet=%d, duplikater=%d, pakket_ut=0, "
                     "hendelser=0, json=0, plott=0, feilet=%d",
                     hent["hentet"], hent["duplikater"], hent["feil"])
            logg.skriv_fil(LOGGFIL)
            return 1 if (hent["feilet"] or hent["feil"]) else 0

        # -- trinn 2-6: dekod, del, plott for hvert nye vedlegg ------------
        arbeider: list[Path] = []
        hendelser = json_skrevet = plott_skrevet = 0
        feil = hent["feil"]
        pakket_ut = 0
        nye_filnokler: list[str] = []
        for fil in hent["filer"]:
            logg.info("behandler %s", fil.name)
            utfall = kjor_kjede(fil, logg)
            arbeider.append(utfall["arbeid"])
            hendelser += utfall["hendelser"]
            json_skrevet += utfall["json"]
            plott_skrevet += utfall["plott"]
            pakket_ut += (1 if fil.suffix.lower() == ".zip" else 0)
            feil += len(utfall["feil"])
            # Innholdsnoekkelen fores bare naar kjeden gikk gjennom: da er
            # eksporten faktisk dekodet og plottet, og skal aldri gjores om.
            if not utfall["feil"]:
                noekkel = hent["nokler"].get(str(fil))
                if noekkel:
                    nye_filnokler.append(noekkel)
        if nye_filnokler and not args.test:
            skriv_noekler(BEHANDLET_FILER, nye_filnokler, logg)

        # -- index.json: alltid til slutt, av det som ligger i json\ ---------
        if not args.test:
            skriv_indeks(JSONMAPPE, logg, hendelser > 0)

        if args.slett_arbeid:
            for a in arbeider:
                shutil.rmtree(a, ignore_errors=True)
            shutil.rmtree(ARBEID, ignore_errors=True)

        logg.vis("SAMMENDRAG: hentet=%d, duplikater=%d, pakket_ut=%d, "
                 "hendelser=%d, json=%d, plott=%d, feilet=%d",
                 hent["hentet"], hent["duplikater"], pakket_ut, hendelser,
                 json_skrevet, plott_skrevet, feil)

        if hent["hentet"] == 0:
            if hent["duplikater"]:
                logg.info("ingen nye vedlegg denne runden - %d duplikat(er) "
                          "ble hoppet over", hent["duplikater"])
            else:
                logg.info("ingen nye vedlegg denne runden")
            # Si fra naar det har vaert stille lenge. Uten dette ser en
            # "hentet=0" hver 15. minutt og vet ikke om det er vi som staar
            # fast eller riggen som ikke har sendt noe. Det siste er vanligst:
            # da staar det en alder her, og det er ingenting aa rette her.
            skriv_stillhetsvarsel(logg)

        logg.skriv_fil(LOGGFIL)
        return 1 if feil else 0

    except KeyboardInterrupt:                                    # pragma: no cover
        logg.feil("avbrutt av bruker")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
