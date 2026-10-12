"""import_del_opp.py - last opp en STOR ACRON-eksport i biter.

Deler zippen i biter paa --dager dogn (standard 20), dekoder hver bit med
hent_og_plott.py og skriver hendelsene til <repo>\\data\\, og pusher til slutt.
Med standardinnstillingene kan du ta 200 dogn eller mer i EN kommando.

Csv-en STROEMMES rett fra zippen: den pakkes aldri ut som en stor fil, og den
lastes aldri helt inn i minnet. Hver bit blir en liten csv som kodes til en
midlertidig zip, dekodes, og slettes med en gang. Utpakket csv havner i
rigg\\arbeid\\ og fjernes av --slett-arbeid.

KILDEN ROERES IKKE.

BRUK
    rigg\\import_del_opp.bat "C:\\sti\\stor.zip"
    rigg\\import_del_opp.bat "C:\\sti\\stor.zip" --dager 15
    rigg\\import_del_opp.bat "C:\\sti\\stor.zip" --test          ikke commit/push
    py -3 rigg\\import_del_opp.py "C:\\sti\\stor.zip" --repo C:\\...\\nettsted
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
    p.add_argument("kilde", help="stor zip med ACRON-csv")
    p.add_argument("--dager", type=int, default=20,
                   help="dogn per bit (20)")
    p.add_argument("--repo", default=str(REPO_STD),
                   help="nettsteds-repoet (standard: %s)" % REPO_STD)
    p.add_argument("--json-dir", default=None,
                   help="hvor hendelses-JSON skrives (standard: <repo>\\data)")
    p.add_argument("--test", action="store_true",
                   help="dekod til en midlertidig mappe og ikke commit/push")
    a = p.parse_args(argv)

    kilde = Path(a.kilde)
    if not kilde.exists():
        raise SystemExit("finner ikke \"%s\"" % kilde)

    repo = Path(a.repo)
    if a.test and a.json_dir is None:
        json_dir = Path(tempfile.mkdtemp(prefix="jetlogg_test_"))
    else:
        json_dir = Path(a.json_dir) if a.json_dir else (repo / "data")
    json_dir.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="jetlogg_import_"))
    biter: list = []
    linjer = 0
    bit_nr = 0
    ut = None
    dager_naa: list = []
    sti_bit = None

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

    hode_linje = ""
    try:
        with zipfile.ZipFile(kilde) as z:
            navn = _csv_navn(z)
            info = z.getinfo(navn)
            print("kilde      : %s" % kilde)
            print("csv i zip  : %s (%.1f MB utpakket)"
                  % (navn, info.file_size / 1048576))
            print("bit-storrelse: %d dogn" % a.dager)
            print("json-dir   : %s" % json_dir)
            with z.open(navn) as raa:
                tekst = io.TextIOWrapper(raa, encoding="utf-8",
                                         errors="replace", newline="")
                hode_linje = tekst.readline()
                if not hode_linje.endswith("\n"):
                    hode_linje += "\n"
                kol = hode_linje.rstrip("\r\n").split(";")
                if "Date" not in kol:
                    raise SystemExit("finner ikke kolonnen 'Date' i csv-en")
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
        if ut is not None:
            ut.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # -- sikkerhet: ingen utpakket csv skal ligge igjen -------
    arbeid = HER / "arbeid"
    rest = sorted(arbeid.rglob("*.csv")) if arbeid.exists() else []
    for r in rest:
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

    _git(repo, "add", "-A", "--", "data")
    if _git(repo, "diff", "--cached", "--quiet") != 0:
        _git(repo, "commit", "-m",
             "Import: eldre/svaere data i %d biter (%s .. %s)"
             % (len(biter), biter[0][1], biter[-1][2]))
    else:
        print("   ingenting nytt aa committe")
    if _git(repo, "push") != 0:
        _git(repo, "pull", "--rebase", "--autostash")
        _git(repo, "push")
    print("\nOK: %d bit(er) publisert" % len(biter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
