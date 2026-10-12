@echo off
setlocal
rem ===========================================================================
rem  import_del_opp.bat - last opp en STOR ACRON-eksport i biter.
rem
rem  ENKEL BRUK
rem      Legg zip-en i denne mappen og dobbeltklikk paa denne fila - eller
rem      dra zip-en inn paa den. Da finner skriptet filen selv, deler den i
rem      biter paa 20 dogn, dekoder hver bit og PUSHER til nettstedet.
rem
rem      Mer enn en zip i mappen? Den NYESTE brukes (det staar i vinduet).
rem
rem  MED STI
rem      import_del_opp.bat "C:\sti\stor.zip"
rem      import_del_opp.bat "C:\sti\stor.zip" --dager 15
rem      import_del_opp.bat "C:\sti\stor.zip" --test      ingen commit/push
rem
rem  Utpakket csv og midlertidige biter slettes automatisk.
rem  Kilden (zip-en du peker paa) roeres ikke.
rem
rem  Krever: Python 3 med numpy/pandas/matplotlib, og git med innlogging
rem  (Windows Credential Manager) for den brukeren som kjoerer skriptet.
rem ===========================================================================

set "HERE=%~dp0"
if exist "C:\Python314\python.exe" (
  set "PY=C:\Python314\python.exe"
  set "PYARG="
) else (
  set "PY=py"
  set "PYARG=-3"
)

"%PY%" %PYARG% "%HERE%import_del_opp.py" %*
set "RC=%errorlevel%"

echo.
echo (sluttkode %RC%)
if not defined JETLOGG_NOPAUSE pause
exit /b %RC%
