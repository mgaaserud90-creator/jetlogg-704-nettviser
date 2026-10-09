"""Henter ut hendelsene fra en riggeksport og skriver dem som JSON.

    python tools\\eksporter_hendelser.py <fil.csv> [--ut <fil.json>] [--pen]

Hver hendelse faar naa OGSAA kurvene: hele hendelsesvinduet prove for prove
(tid i sekunder fra hendelsens start, dybde i cm og de maalekanalene plottene
tegner), pluss stoppene med klokke, dybde og lengde. Det er det de fritt-
staaende viserne trenger - en kurve som ikke staar i filen kan ikke tegnes.

Hver pel gir én pilotboring, én prejet
og én grouting, fordi det er det arbeidet pelen bestaar av. Hva som er hva
avgjores av hva riggen faktisk gjor (retningen paa dybden, og om det pumpes
grout), ikke av metodeflagget fra riggen - det henger etter naar operatoren
glemmer aa bytte rapport.

Prejet og grouting begynner fem minutter for opptrekket begynner og slutter
der bevegelsen slutter. Pauser inne i opptrekket blir med, de kan vaere lange.

Reglene er de samme som plottene bruker, i :mod:`regenerer_acron_plott`. Filen
har én oppfoering per hendelse:

    pel, dato                  hvilken pel, og hvilken dag
    metode, modus              'prejet' / 'pilotboring' / 'grouting' og
                               riggens eget navn (PREJETTING osv.)
    start, stopp               ISO-tidspunkt
    varighet_s, varighet       sekunder og '37 min'
    dybde_fra_cm, dybde_til_cm dybden der hendelsen begynner og slutter
    lengde_cm                  summen av seksjonene som teller med - det
                               samme tallet som staar i plottets overskrift
    flyttet_cm                 hele forflytningen over hendelsen
    retning, snitt_cm_min      'opp' eller 'ned', og vektet snittfart
    jevn_bevegelse             hvor mange seksjoner som teller med
    utelatt_pst                hvor stor del av fasetiden (i prosent) som ikke
                               teller med i lengde og snitt
    seksjoner                  hver fase med cm_min, r2 og merknad
    serie                      kurvene for hendelsesvinduet: t_s (sekunder fra
                               hendelsens start), dybde_cm og kanalene med
                               navn/etikett/farge - prove for prove
    stopp_perioder             stoppene, nummerert fra DYPEST til GRUNNEST,
                               med klokke og dybde ved stopp og restart, lengde
                               og delta dybde (fortegn: positiv = ned etterpaa)

Dybden er positiv nedover, slik den er normalisert i :func:`les_logg`.
En seksjon teller med naar den ikke er merket (merknad tom) OG r2 er minst
``--min-r2-telling`` (0.9). Regelen staar i teller_med (rap.teller_med), den
samme som plottet bruker. Seksjoner med merknad 'uryddig' eller 'stopp' har
ogsaa et tall, men det er merket - bruk det bare naar merknaden er tom.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regenerer_acron_plott as rap                              # noqa: E402

# Metodenavnene i JSON-en, i den rekkefolgen arbeidet gjores.
REKKEFOLGE = {"PILOTDRILL": 1, "PREJETTING": 2, "GROUTING": 3}


def skriv_js_tvillinger(jsonmappe, logg=None) -> list[Path]:
    """Skriv JS-tvillingar til hendelses-JSON-ene i ``jsonmappe``.

    Nettlesaren blokkerer ``fetch`` naar sida blir opna som lokal fil
    (``file://``), men ein vanleg ``<script src="...">`` er lovleg. Difor
    skriv vi, i same slengen som ``index.json`` blir skriven:

        index.js          window.JETLOGG_INDEKS = {...};
        <navn>.js         window.JETLOGG_HENDELSE["<navn>.json"] = {...};

    Tvillingane blir laga av det som FAKTISK ligg i mappa, saa dei kan ikkje
    kome i utakt med JSON-en. JSON-skjemaet blir IKKJE endra - vi pakkar
    berre den same JSON-en inn i ein liten JS-innpakning. ``ensure_ascii``
    held filene reine ASCII, saa dei ikkje er avhengige av teiknsett.

    Returnerer stiane som vart skrivne.
    """
    mappe = Path(jsonmappe)
    if not mappe.exists():
        return []
    skrivne: list[Path] = []

    def _skriv(sti: Path, tekst: str) -> None:
        try:
            sti.write_text(tekst, encoding="utf-8")
            skrivne.append(sti)
        except OSError as e:
            if logg is not None:
                logg.advarsel("kunne ikke skrive \"%s\": %s", sti, e)

    indeks_sti = mappe / "index.json"
    if indeks_sti.exists():
        try:
            data = json.loads(indeks_sti.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            if logg is not None:
                logg.advarsel("kunne ikke lese \"%s\": %s", indeks_sti, e)
        else:
            _skriv(mappe / "index.js",
                   "window.JETLOGG_INDEKS = "
                   + json.dumps(data, ensure_ascii=True) + ";\n")

    for p in sorted(mappe.glob("*.json")):
        if p.name.lower() == "index.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            if logg is not None:
                logg.advarsel("kunne ikke lese \"%s\": %s", p, e)
            continue
        _skriv(mappe / (p.stem + ".js"),
               "window.JETLOGG_HENDELSE = window.JETLOGG_HENDELSE || {};\n"
               + "window.JETLOGG_HENDELSE[" + json.dumps(p.name) + "] = "
               + json.dumps(data, ensure_ascii=True) + ";\n")

    if logg is not None and skrivne:
        logg.info("  js-tvillingar: %d fil(er)", len(skrivne))
    return skrivne


def _tall(verdi, desimaler: int = 1) -> float | None:
    """Runder av og gjor NaN/Inf om til null - JSON har ikke NaN."""
    try:
        f = float(verdi)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, desimaler)


def seksjoner(df: pd.DataFrame, vindu: tuple[int, int],
              ferdige: list[tuple[int, int]], args: argparse.Namespace
              ) -> list[dict]:
    """Fasene inne i hendelsen, med stigningstall, R2 og merknad."""
    i0, i1 = vindu
    if i1 - i0 < 2:
        return []
    # Indeksene blir regnet om til vinduet: fase 3 i hele produksjonsomraadet
    # er en annen posisjon naar vi bare ser paa hendelsen.
    posisjon = np.arange(i0, i1 + 1)
    segmenter: list[tuple[int, int]] = []
    for s0, s1 in ferdige:
        treff = np.flatnonzero((posisjon >= s0) & (posisjon <= s1))
        if len(treff) > 1:
            segmenter.append((int(treff[0]), int(treff[-1])))
    if not segmenter:
        return []
    bit = df.iloc[i0:i1 + 1].reset_index(drop=True)
    # Pausene klippes inn i fasene - den SAMME regelen som plottet bruker.
    # Da inneholder ingen fase som teller med staa-tid, og hver bevegelse
    # faar sitt eget cm/min-tall. Regelen staar i rap.finn_stopp og
    # rap.del_ved_stopp, saa JSON-en og plottet aldri kan gli fra hverandre.
    stopp_bit = rap.finn_stopp(
        bit, stopp_spenn_cm=args.stopp_spenn_cm,
        stopp_cm_min=args.stopp_cm_min, stopp_min_s=args.stopp_min_s,
        stopp_med_fart=args.stopp_med_fart, stopp_kanal=args.stopp_kanal,
        stopp_verdi=args.stopp_verdi, stopp_retning=args.stopp_retning,
        stopp_kombi=args.stopp_kombi, glatt_s=args.glatt_s)
    if stopp_bit:
        segmenter = rap.del_ved_stopp(
            segmenter, [(s["a"], s["b"]) for s in stopp_bit])
    rader = rap.fase_tabell(bit, segmenter, min_r2=args.min_r2,
                            stopp_cm_min=args.stopp_cm_min,
                            maks_cm_min=args.maks_cm_min,
                            stopp_spenn_cm=args.stopp_spenn_cm,
                            stopp_min_s=args.stopp_min_s,
                            stopp_med_fart=args.stopp_med_fart)

    ut: list[dict] = []
    for nummer, (rad, (s0, s1)) in enumerate(zip(rader, segmenter), start=1):
        ut.append({
            "nr": nummer,
            "fra": rad["fra"],
            "til": rad["til"],
            "fra_iso": bit["Tid"].iloc[s0].isoformat(timespec="seconds"),
            "til_iso": bit["Tid"].iloc[s1].isoformat(timespec="seconds"),
            "sek": rad["varighet_s"],
            "dybde_fra_cm": rad["dybde_fra_cm"],
            "dybde_til_cm": rad["dybde_til_cm"],
            "lengde_cm": rad["lengde_cm"],
            "cm_min": rad["stigningstall_cm_min"],
            "r2": rad["r2"],
            "merknad": rad["merknad"],
        })
    return ut


def gjennomsnitt(rader: list[dict]) -> float | None:
    """Vektet snittfart over seksjonene som teller med.

    Listen som kommer inn er alt filtrert med teller_med (rap.teller_med), slik
    at regelen finnes paa ett sted.
    """
    tid = sum(float(r["sek"]) for r in rader)
    if not rader or tid <= 0:
        return None
    return round(sum(float(r["cm_min"]) * float(r["sek"]) for r in rader)
                 / tid, 2)


def finn(df: pd.DataFrame, args: argparse.Namespace) -> list[dict]:
    """Alle hendelsene i filen, klar for JSON."""
    skift = args.skift_hull * 3600.0
    pelene = rap.finn_peler(df, maks_hull_s=(skift if skift > 0 else
                                             float("inf")))
    # Kanalene plottene tegner (de fem Acron-kanalene naar de finnes). De
    # samme blir med i serien, saa den frittstaaende viseren tegner noyaktig
    # det PNG-en tegner.
    kanaler = rap.finn_kanaler(df)
    ut: list[dict] = []

    for pel in pelene:
        a, b = rap.produksjonsomrade(df, pel, terskel=args.terskel,
                                     tillatt_hull_s=args.hull_s)
        # Fasene regnes én gang for hele produksjonsomraadet - de samme som
        # plottene viser, saa JSON-en og rapporten sier det samme.
        bit = df.iloc[a:b + 1]
        brukt = np.flatnonzero(bit["dybde"].notna().to_numpy())
        ren = bit.iloc[brukt]
        if len(ren) < 2:
            continue
        t_bit = (ren["Tid"]
                 - ren["Tid"].iloc[0]).dt.total_seconds().to_numpy(float)
        sek_bit = float(t_bit[-1] - t_bit[0])
        ferdige = [(int(brukt[s0]) + a, int(brukt[s1]) + a)
                   for s0, s1 in rap.finn_segmenter(
                       t_bit, ren["dybde"].to_numpy(dtype=float),
                       tol_std=args.tol_std, min_lengde_s=args.min_lengde_s,
                       tol_cm_min=args.tol_cm_min,
                       glatt_s=(args.glatt_s if args.glatt_s is not None
                                else min(61.0, max(3.0, 0.03 * sek_bit))))]

        if args.hver_okt:
            hendelser: list[dict] = []
            her_merker = rap.start_stopp_vinduer(df, pel=str(pel["pel"]))
            for okt in pel["okter"]:
                for vindu in rap.arbeidsvinduer(df, [okt], grense=(a, b),
                                                tillatt_hull_s=args.hull_s,
                                                merker=her_merker):
                    hendelser.append({"modus": str(okt["modus"]),
                                      "vindu": vindu})
        else:
            hendelser = rap.velg_hendelser(df, pel["okter"], grense=(a, b),
                                           tillatt_hull_s=args.hull_s)

        for hendelse in hendelser:
            i0, i1 = hendelse["vindu"]
            # Fem minutter for opptrekket begynner - men bare naar vinduet er
            # funnet fra signalene. Har riggen operatørens start/stopp-signal,
            # definerer operatøren vinduet selv, og da skal ingen forlop
            # legges paa.
            if (hendelse["modus"] in ("PREJETTING", "GROUTING")
                    and rap.STARTSTOPP_KOLONNE not in df.columns):
                i0 = max(a, int(df["Tid"].searchsorted(
                    df["Tid"].iloc[i0]
                    - pd.Timedelta(seconds=args.start_for))))
            if i1 - i0 < 30:
                continue
            rader = seksjoner(df, (i0, i1), ferdige, args)
            if not rader:
                continue
            dybde_fra = float(rader[0]["dybde_fra_cm"])
            dybde_til = float(rader[-1]["dybde_til_cm"])
            sek = float((df["Tid"].iloc[i1]
                         - df["Tid"].iloc[i0]).total_seconds())
            # Lengden og snittfarten regnes bare over seksjonene som teller
            # med: de som ikke er merket, og som har r2 >= min_r2_telling.
            # Regelen staar i rap.teller_med - den samme som plottet bruker -
            # saa JSON-en og plottets overskrift alltid sier det samme tallet.
            # Er det ingen slike seksjoner i det hele tatt (urolig boring),
            # brukes hele forflytningen i stedet.
            gyldige = [r for r in rader
                       if rap.teller_med(r, args.min_r2_telling)]
            tellet_s = sum(float(r["sek"]) for r in gyldige)
            alle_s = sum(float(r["sek"]) for r in rader)
            if gyldige:
                lengde = float(sum(float(r["lengde_cm"]) for r in gyldige))
                snitt = gjennomsnitt(gyldige)
                # Andelen av fasetiden som holdes utenfor. Basen er summen av
                # alle fasene - ikke vinduet - saa tallet beskriver det vi
                # faktisk regner over.
                utelatt_pst = (round((alle_s - tellet_s) / alle_s * 100.0, 1)
                               if alle_s > 0 else 0.0)
            else:
                lengde = float(dybde_fra - dybde_til)
                snitt = (round(lengde / sek * 60.0, 2) if sek > 0 else None)
                # Hele forflytningen er brukt - da er det ikke noe utvalg aa
                # holde utenfor, og utelatt er null.
                utelatt_pst = 0.0
            # -- kurvene for hendelsesvinduet, prove for prove -------------
            bit = df.iloc[i0:i1 + 1]
            tider = bit["Tid"]
            t_s = (tider - tider.iloc[0]).dt.total_seconds().to_numpy(float)
            serie = {
                "t_s": [round(float(v), 1) for v in t_s],
                "dybde_cm": [_tall(v, 1)
                             for v in bit["dybde"].to_numpy(dtype=float)],
                "kanaler": [
                    {"navn": nokkel, "etikett": etikett, "farge": farge,
                     "verdier": [_tall(v, 2)
                                 for v in bit[nokkel].to_numpy(dtype=float)]}
                    for nokkel, etikett, farge in kanaler],
            }
            # -- stoppene: samme regel som plottet tegner og merker --------
            stopp = rap.finn_stopp(
                bit, stopp_spenn_cm=args.stopp_spenn_cm,
                stopp_cm_min=args.stopp_cm_min,
                stopp_min_s=args.stopp_min_s, stopp_kanal=args.stopp_kanal,
                stopp_verdi=args.stopp_verdi,
                stopp_retning=args.stopp_retning,
                stopp_kombi=args.stopp_kombi,
                stopp_med_fart=args.stopp_med_fart, glatt_s=args.glatt_s)
            stopp_ut: list[dict] = []
            for s in stopp:
                rad = {k: v for k, v in s.items() if k not in ("a", "b")}
                rad["fra_s"] = round(float(t_s[int(s["a"])]), 1)
                rad["til_s"] = round(float(t_s[int(s["b"])]), 1)
                stopp_ut.append(rad)
            # -- gikk hendelsen fortsatt da loggen sluttet? -----------------
            # Eksporten er et oyeblikksbilde. Blir den tatt midt i en
            # grouting, stopper dataene der - ikke fordi arbeidet var
            # ferdig, men fordi filen ikke rekker lenger. Det skal staa, saa
            # ingen tror at pelen ble groutet bare halvveis med vilje.
            #
            # Sjekken er: hendelsen slutter ved filens slutt, og operatøren
            # har IKKE kvittert ut med stopp (0). Staar det 1 - eller staar
            # det ingenting fordi maalingen er tapt (ALOSS) - gikk arbeidet
            # fortsatt da eksporten ble tatt. Den siste raden i filen kan
            # vaere en annen pel, saa vi spoer ved hendelsens EGEN slutt.
            uferdig = i1 >= len(df) - 60
            if uferdig and rap.STARTSTOPP_KOLONNE in df.columns:
                slutt = df[rap.STARTSTOPP_KOLONNE].iloc[i1]
                uferdig = not (slutt == 0.0)
            ut.append({
                "pel": str(pel["pel"]),
                "dato": df["Tid"].iloc[i0].strftime("%Y-%m-%d"),
                "modus": hendelse["modus"],
                "metode": rap.metode_navn(hendelse["modus"]),
                "start": df["Tid"].iloc[i0].isoformat(timespec="seconds"),
                "stopp": df["Tid"].iloc[i1].isoformat(timespec="seconds"),
                "uferdig": bool(uferdig),
                "varighet_s": round(sek, 1),
                "varighet": rap.varighet_tekst(sek),
                "dybde_fra_cm": round(dybde_fra, 1),
                "dybde_til_cm": round(dybde_til, 1),
                "lengde_cm": round(abs(lengde), 1),
                "flyttet_cm": round(abs(dybde_til - dybde_fra), 1),
                "retning": "opp" if lengde >= 0 else "ned",
                "snitt_cm_min": snitt,
                "jevn_bevegelse": len(gyldige),
                "utelatt_pst": utelatt_pst,
                "pel_metoder": [rap.metode_navn(str(m))
                                for m in pel["moduser"]],
                "seksjoner": rader,
                "stopp_perioder": stopp_ut,
                "serie": serie,
            })

    ut.sort(key=lambda h: (h["pel"], h["start"]))
    return ut


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eksporter_hendelser",
        description="Skriv hendelsene i en riggeksport som JSON. Bare "
                    "hendelsene - ikke kurvene.")
    parser.add_argument("fil", help="eksport fra riggen (.csv)")
    parser.add_argument("--ut", "-o", default=None,
                        help="hvor JSON-filen skal ligge. Standard: samme navn "
                             "som kilden, men .json")
    parser.add_argument("--start-for", type=float, default=300.0, metavar="SEK",
                        help="prejet og grouting begynner saa mange sekunder "
                             "for opptrekket (300 = 5 min)")
    parser.add_argument("--hver-okt", action="store_true",
                        help="ta med hver oekt i loggen, ikke én per metode")
    parser.add_argument("--skift-hull", type=float,
                        default=rap.SKIFT_HULL_TIMER, metavar="TIMER",
                        help="kommer samme pel tilbake senere enn dette, er "
                             "det en ny oekt (6)")
    parser.add_argument("--terskel", type=float, default=5.0,
                        help="flow over denne verdien = produksjon (5.0)")
    parser.add_argument("--hull-s", type=float, default=180.0,
                        help="saa lange avbrudd som ikke bryter perioden (180)")
    parser.add_argument("--tol-std", type=float, default=0.35)
    parser.add_argument("--min-lengde-s", type=float, default=60.0)
    parser.add_argument("--tol-cm-min", type=float, default=1.0)
    parser.add_argument("--glatt-s", type=float, default=None)
    parser.add_argument("--maks-cm-min", type=float, default=30.0)
    parser.add_argument("--min-r2", type=float, default=0.7,
                        help="under denne tilpasningen merkes fasen 'uryddig' "
                             "(0.7). Styrer bare merkelappen, ikke tellingen")
    parser.add_argument("--min-r2-telling", type=float, default=0.9,
                        help="faser under denne tilpasningen holdes utenfor "
                             "lengde og snittfart, selv om de ellers ikke er "
                             "merket (0.9)")
    parser.add_argument("--stopp-spenn-cm", type=float, default=2.0,
                        metavar="CM",
                        help="HOVEDKRITERIET: dybden staar stille naar spennet "
                             "(maks-min) er innenfor +/-CM, altsaa 2*CM totalt, "
                             "i minst --stopp-min-s sekunder (2.0 = +/-2 cm = "
                             "4 cm spenn). 0 slaar kriteriet av")
    parser.add_argument("--stopp-med-fart", action="store_true",
                        help="bruk OGSAA farts-kriteriet (|cm/min| under "
                             "--stopp-cm-min). Av som standard")
    parser.add_argument("--stopp-cm-min", type=float, default=1.0,
                        help="farts-kriteriet. Gjelder bare med "
                             "--stopp-med-fart (1.0)")
    parser.add_argument("--stopp-min-s", type=float, default=600.0,
                        help="korteste stopp som blir med (600 s = 10 min; "
                             "kortere pauser er ikke stopp)")
    parser.add_argument("--stopp-kanal", default=None,
                        help="kanal som viser stopp, f.eks. Grouttrykk")
    parser.add_argument("--stopp-verdi", type=float, default=None,
                        help="grensen for --stopp-kanal (f.eks. 50)")
    parser.add_argument("--stopp-retning", choices=rap.STOPP_RETNINGER,
                        default="under",
                        help="stopp naar kanalen er under/over grensen "
                             "(under)")
    parser.add_argument("--stopp-kombi", choices=rap.STOPP_KOMBIER,
                        default="eller",
                        help="hvordan de aktive kriteriene settes sammen naar "
                             "flere er i bruk: 'eller' (standard) eller 'og'")
    parser.add_argument("--pen", action="store_true",
                        help="skriv JSON-en med innrykk og norske tegn")
    args = parser.parse_args(argv)
    if args.stopp_kanal:
        # Operatoren skriver 'Grouttrykk' - kolonnen heter 'grouttrykk'.
        args.stopp_kanal = rap._normaliser(args.stopp_kanal)

    kilde = Path(args.fil)
    if not kilde.exists():
        parser.error(f"Finner ikke filen: {kilde}")
    utfil = Path(args.ut) if args.ut else kilde.with_suffix(".json")

    df = rap.les_logg(kilde)
    hendelser = finn(df, args)

    data = {
        "fil": kilde.name,
        "generert": datetime.now().isoformat(timespec="seconds"),
        "prover": len(df),
        "fra": df["Tid"].iloc[0].isoformat(timespec="seconds"),
        "til": df["Tid"].iloc[-1].isoformat(timespec="seconds"),
        "antall_hendelser": len(hendelser),
        "peler": sorted({h["pel"] for h in hendelser}),
        "kanaler": [{"navn": n, "etikett": e, "farge": f}
                    for n, e, f in rap.finn_kanaler(df)],
        "hendelser": hendelser,
    }
    utfil.write_text(json.dumps(data, indent=2 if args.pen else None,
                                ensure_ascii=not args.pen) + "\n",
                     encoding="utf-8")

    print(f"{kilde.name}: {len(hendelser)} hendelser "
          f"({len(data['peler'])} peler)")
    for h in hendelser:
        snitt = f"{h['snitt_cm_min']:.1f} cm/min" if h["snitt_cm_min"] else "-"
        print(f"  {h['pel']:>4s} {h['dato']} {h['metode']:<11s} "
              f"{h['start'][11:]}-{h['stopp'][11:]}  "
              f"{h['lengde_cm']:>6.1f} cm  {h['retning']:<3s} {snitt:>12s}  "
              f"{len(h['seksjoner'])} seksjoner")
    print(f"  skrev {utfil} ({utfil.stat().st_size} byte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
