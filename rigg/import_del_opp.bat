@echo off
setlocal
rem ===========================================================================
rem  import_del_opp.bat - last opp en STOR ACRON-eksport i biter.
rem
rem  Deler zippen i biter paa 20 dogn (kan endres), dekoder hver bit og
rem  pusher til nettstedet. Taaler filer paa 200 dogn og mer.
rem
rem  BRUK
rem      import_del_opp.bat "C:\sti\stor.zip"
rem      import_del_opp.bat "C:\sti\stor.zip" --dager 15
rem      import_del_opp.bat "C:\sti\stor.zip" --test      (ingen commit/push)
rem
rem  Utpakket csv og midlertidige biter slettes automatisk.
rem  Kilden (zip-en du peker paa) roeres ikke.
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
exit /b %errorlevel%
