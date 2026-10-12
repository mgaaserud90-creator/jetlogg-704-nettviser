"""vindu.py - les dato-omfanget i en ACRON-eksport (zip eller csv).

Kan brukes baade som modul og som kommandolinje:

    py -3 rigg/vindu.py <zip-eller-csv> [--maks-dager N]

Skriver forste dato, siste dato og antall dogn. Med --maks-dager gir den
utgangskode 1 hvis vinduet er stoerre enn N, slik at en importjobb kan stoppe
FOER den bruker minutter og minne paa noe den ikke skal ha.

Fila stroemmes - hele csv-en lastes aldri inn i minnet.
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from datetime import datetime
from pathlib import Path


def _stroem(sti: Path):
    """Tekststroem over csv-en, enten den ligger i en zip eller som fil."""
    sti = Path(sti)
    if sti.suffix.lower() == ".zip":
        z = zipfile.ZipFile(sti)
        navn = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not navn:
            raise SystemExit("fant ingen CSV i \"%s\"" % sti)
        raa = z.open(navn[0])
    else:
        raa = sti.open("rb")
    return io.TextIOWrapper(raa, encoding="utf-8", errors="replace")


def les_vindu(sti: Path):
    """(forste, siste, antall_dogn) ut fra kolonnen Date (dd.mm.yyyy)."""
    tekst = _stroem(Path(sti))
    hode = tekst.readline()
    kol = hode.rstrip("\r\n").split(";")
    if "Date" not in kol:
        raise SystemExit("finner ikke kolonnen 'Date' i \"%s\"" % sti)
    i_dato = kol.index("Date")
    forste = siste = None
    for linje in tekst:
        d = linje.split(";")
        if len(d) <= i_dato:
            continue
        v = d[i_dato].strip()
        if not v or v == "Date":
            continue
        if forste is None:
            forste = v
        siste = v
    if forste is None:
        raise SystemExit("fant ingen datalinjer i \"%s\"" % sti)
    f = datetime.strptime(forste, "%d.%m.%Y")
    s = datetime.strptime(siste, "%d.%m.%Y")
    return f, s, (s - f).days + 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vindu")
    p.add_argument("sti", help="zip eller csv med ACRON-eksport")
    p.add_argument("--maks-dager", type=int, default=0,
                   help="stopp med kode 1 hvis vinduet er stoerre enn dette "
                        "(0 = ingen grense)")
    a = p.parse_args(argv)
    f, s, dager = les_vindu(Path(a.sti))
    print("forste : %s" % f.strftime("%d.%m.%Y"))
    print("siste  : %s" % s.strftime("%d.%m.%Y"))
    print("dager  : %d" % dager)
    if a.maks_dager and dager > a.maks_dager:
        print("FEIL: vinduet er %d dogn, grensen er %d. Del eksporten opp."
              % (dager, a.maks_dager), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
