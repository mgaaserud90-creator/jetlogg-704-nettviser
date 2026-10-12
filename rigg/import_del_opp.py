"""import_del_opp.py - last opp en STOR ACRON-eksport i biter.

Deler eksporten i biter paa --dager dogn (standard 20), dekoder hver bit med
hent_og_plott.py og skriver hendelsene til <repo>\\data\\, og pusher til slutt.
Med standardinnstillingene kan du ta 200 dogn eller mer i EN kommando.

ENKEL BRUK
    Legg zip-en i denne mappen (rigg\\) og kjoer:
        import_del_opp.bat
    eller dra zip-en inn paa .bat-fila. Da finner skriptet den nyeste
    zip-en (eller csv-en) i mappa selv. Du kan ogsaa gi stien:

        import_del_opp.bat "C:\\sti\\stor.zip"
        import_del_opp.bat "C:\\sti\\stor.zip" --dager 15
        import_del_opp.bat "C:\\sti\\stor.zip" --test      ikke commit/push

Csv-en STROEMMES: den lastes aldri helt inn i minnet, og kilden pakkes ikke ut
som en stor fil. Hver bit blir en liten midlertidig zip som dekodes og slettes
med en gang. Utpakket csv havner i rigg\\arbeid\\ og fjernes av --slett-arbeid.

KILDEN ROERES IKKE.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HER = Path(__file__).resolve().parent
REPO_STD = Path(r"C:\Users\PC\Desktop\nettsted")


def _csv_navn(z: zipfile.ZipFile) -> str:
    navn = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if not navn:
        raise SystemExit("fant ingen CSV i zippen")
    return navn[0]


def _finn_kilde(her: Path) -> Path:
    """Nyeste zip (eller csv) ved siden av skriptet, naar ingen sti er gitt."""
    kandidater = [p for p in her.glob("*.zip")] + [p for p in her.glob("*.csv")]
    kandidater = [p for p in kandidater if p.is_file()]
    if not kandidater:
        raise SystemExit(
            "ingen zip (eller csv) funnet i \"%s\".\n"
            "  Legg eksporten der og kjoer paa nytt, eller gi stien:\n"
            "      import_del_opp.bat \"C:\\sti\\fil.zip\"" % her)
    kandidater.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if len(kandidater) > 1:
        print("MERK: %d filer i mappa - bruker den nyeste:" % len(kandidater))
        for p in kandidater[:5]:
            print("   %s" % p.name)
    return kandidater[0]


def _bit_til_zip(csv_sti: Path, zip_sti: Path) -> None:
    with zipfile.ZipFile(zip_sti, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(csv_sti, csv_sti.name)


def _dekod(bit_zip: Path, json_dir: Path) -> int:
    kommando = [sys.executable, str(HER / "hent_og_plott.py"),
                "--still", "--json-dir", str(json_dir),
                "--fra-zip", str(bit_zip), "--slett-arbeid"]
    print("   $ %s" % " ".join(kommando))
    return subprocess.run(kommando, cwd=str(HER)).returncode


def _git(repo: Path, *argumenter: str) -> int:
    print("   $ git -C %s %s" % (repo, " ".join(argumenter)))
    return subprocess.run(["git", "-C", str(repo)] + list(argumenter)).returncode


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="import_del_opp",
        description="Del en stor ACRON-eksport i biter, dekod og publiser.")
    p.add_argument("kilde", nargs="?", default=None,
                   help="zip (eller csv) - utelatt: nyeste i rigg\\-mappa")
    p.add_argument("--dager", type=int, default=20, help="dogn per bit (20)")
    p.add_argument("--repo", default=str(REPO_STD),
                   help="nettsteds-repoet (standard: %s)" % REPO_STD)
    p.add_argument("--json-dir", default=None,
                   help="hvor hendelses-JSON skrives (standard: <repo>\\data)")
    p.add_argument("--test", action="store_true",
                   help="dekod til en midlertidig mappe og ikke commit/push")
    a = p.parse_args(argv)

    kilde = Path(a.kilde) if a.kilde else _finn_kilde(HER)
    if not kilde.exists():
        raise SystemExit("finner ikke \"%s\"" % kilde)

    repo = Path(a.repo)
    if a.test and a.json_dir is None:
        json_dir = Path(tempfile.mkdtemp(prefix="jetlogg_test_"))
    else:
        json_dir = Path(a.json_dir) if a.json_dir else (repo / "data")
    json_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(" JETLOGG - import av stor eksport i biter")
    print("=" * 70)
    print(" kilde     : %s" % kilde)
    print(" bit-storrelse: %d dogn" % a.dager)
    print(" json-dir  : %s" % json_dir)
    print(" modus     : %s" % ("TEST - ingen commit/push" if a.test
                               else "dekod og push til %s" % repo))
    print("=" * 70)

    tmp = Path(tempfile.mkdtemp(prefix="jetlogg_import_"))
    biter: list = []
    linjer = 0
    bit_nr = 0
    ut = None
    dager_naa: list = []
    sti_bit = None
    hode_linje = ""

    def ny_bit():
        nonlocal bit_nr, ut, dager_naa, sti_bit
        bit_nr += 1
        sti_bit = tmp / ("bit_%03d.csv" % bit_nr)
        ut = sti_bit.open("w", encoding="utf-8", newline="\n")
        ut.write(hode_linje)
        dager_naa = []

    def lukk_bit():
        nonlocal ut
        if ut is None or not dager_naa:
            return
        ut.close()
        ut = None
        bit_zip = sti_bit.with_suffix(".zip")
        print("\n=== bit %d: %s .. %s  (%d dogn) ==="
              % (bit_nr, dager_naa[0], dager_naa[-1], len(dager_naa)))
        _bit_til_zip(sti_bit, bit_zip)
        rc = _dekod(bit_zip, json_dir)
        biter.append((bit_nr, dager_naa[0], dager_naa[-1], len(dager_naa), rc))
        sti_bit.unlink(missing_ok=True)
        bit_zip.unlink(missing_ok=True)

    z = None
    try:
        if kilde.suffix.lower() == ".csv":
            raa = kilde.open("rb")
            navn = kilde.name
        else:
            z = zipfile.ZipFile(kilde)
            navn = _csv_navn(z)
            raa = z.open(navn)
        try:
            tekst = io.TextIOWrapper(raa, encoding="utf-8",
                                     errors="replace", newline="")
            hode_linje = tekst.readline()
            if not hode_linje.endswith("\n"):
                hode_linje += "\n"
            kol = hode_linje.rstrip("\r\n").split(";")
            if "Date" not in kol:
                raise SystemExit("finner ikke kolonnen 'Date' i eksporten")
            i_dato = kol.index("Date")
            ny_bit()
            for linje in tekst:
                d = linje.split(";")
                if len(d) <= i_dato:
                    continue
                v = d[i_dato].strip()
                if not v or v == "Date":
                    continue
                if v not in dager_naa:
                    if len(dager_naa) >= a.dager:
                        lukk_bit()
                        ny_bit()
                    dager_naa.append(v)
                ut.write(linje if linje.endswith("\n") else linje + "\n")
                linjer += 1
            lukk_bit()
        finally:
            try:
                raa.close()
            except Exception:                                    # noqa: BLE001
                pass
    finally:
        if ut is not None:
            ut.close()
        if z is not None:
            z.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # -- sikkerhet: ingen utpakket csv skal ligge igjen --------------------
    arbeid = HER / "arbeid"
    for r in (sorted(arbeid.rglob("*.csv")) if arbeid.exists() else []):
        try:
            r.unlink()
            print("ryddet rest: %s" % r)
        except OSError:
            pass
    if arbeid.exists():
        shutil.rmtree(arbeid, ignore_errors=True)

    feilet = [b for b in biter if b[4] != 0]
    print("\n=== SAMMENDRAG ===")
    for nr, f, s, nd, rc in biter:
        print("   bit %-3d %s .. %s  %2d dogn  rc=%d" % (nr, f, s, nd, rc))
    print("   datalinjer lest: %d" % linjer)
    print("   biter: %d, feilet: %d" % (len(biter), len(feilet)))

    if a.test:
        print("\n--test: dekodet til %s - ingenting committet" % json_dir)
        return 1 if feilet else 0

    if feilet:
        print("\nFEIL i %d bit(er) - committer ingenting." % len(feilet))
        return 1

    print("\n=== PUSHER ===")
    _git(repo, "add", "-A", "--", "data")
    if _git(repo, "diff", "--cached", "--quiet") != 0:
        _git(repo, "commit", "-m",
             "Import: eldre/svaere data i %d biter (%s .. %s)"
             % (len(biter), biter[0][1], biter[-1][2]))
    else:
        print("   ingenting nytt aa committe - data/ var i takt")
    if _git(repo, "push") != 0:
        _git(repo, "pull", "--rebase", "--autostash")
        _git(repo, "push")
    print("\nOK: %d bit(er) behandlet og pushet." % len(biter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
