; Instalador do Aliber SINTEGRA 2.3
; Instala para o usuario atual (sem precisar de administrador) em %LOCALAPPDATA%\AliberSintegra,
; com um Python proprio (baixado do python.org na primeira instalacao).

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APP      "Aliber SINTEGRA"
!define VERSAO   "2.4"
!define PYVER    "3.12.10"
!define PYURL    "https://www.python.org/ftp/python/${PYVER}/python-${PYVER}-amd64.exe"
!define UNKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\AliberSintegra"

Name "${APP} ${VERSAO}"
OutFile "Instalar-AliberSintegra-${VERSAO}.exe"
InstallDir "$LOCALAPPDATA\AliberSintegra"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Aliber Informatica"
VIProductVersion "2.4.0.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "CompanyName" "Aliber Informatica"
VIAddVersionKey "FileDescription" "Instalador do ${APP}"
VIAddVersionKey "FileVersion" "${VERSAO}"
VIAddVersionKey "LegalCopyright" "Aliber Informatica"

!define MUI_ICON   "..\icone.ico"
!define MUI_UNICON "..\icone.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar o ${APP} ${VERSAO}"
!define MUI_WELCOMEPAGE_TEXT "Gera o arquivo SINTEGRA direto do banco do PDV+ e envia para a contabilidade.$\r$\n$\r$\nFeche o Aliber SINTEGRA se estiver aberto.$\r$\n$\r$\nNa primeira instalação o instalador baixa o Python (cerca de 25 MB) do site oficial python.org. É preciso estar conectado à internet."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirApp
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o ${APP} agora"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Var PYW

Function AbrirApp
  Exec '"$PYW" "$INSTDIR\app\app.py"'
FunctionEnd

Section "Aliber SINTEGRA" SecApp
  SetOutPath "$INSTDIR\app"
  ; remove versoes antigas do codigo antes de copiar as novas
  Delete "$INSTDIR\app\*.py"
  RMDir /r "$INSTDIR\app\__pycache__"
  File "..\app.py"
  File "..\automatico.py"
  File "..\motor_pdv.py"
  File "..\envio.py"
  File "..\relatorio_excel.py"
  File "..\gerar_sintegra.py"
  File "..\versoes.py"
  File "..\icone.ico"
  File "..\LEIA-ME.txt"
  SetOutPath "$INSTDIR\pacotes"
  File "pacotes\*.whl"

  ; ---------- Python proprio ----------
  ${IfNot} ${FileExists} "$INSTDIR\python\pythonw.exe"
    DetailPrint "Baixando o Python ${PYVER} do python.org (cerca de 25 MB)..."
    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $$ProgressPreference=\"SilentlyContinue\"; Invoke-WebRequest -UseBasicParsing -Uri \"${PYURL}\" -OutFile \"$TEMP\python-aliber.exe\""'
    Pop $0
    ${IfNot} ${FileExists} "$TEMP\python-aliber.exe"
      MessageBox MB_ICONSTOP "Não foi possível baixar o Python. Verifique a internet e rode o instalador de novo." /SD IDOK
      Abort
    ${EndIf}
    DetailPrint "Instalando o Python (pode levar alguns minutos)..."
    ExecWait '"$TEMP\python-aliber.exe" /quiet InstallAllUsers=0 TargetDir="$INSTDIR\python" Include_launcher=0 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Include_dev=0 Shortcuts=0 AssociateFiles=0 PrependPath=0 Include_pip=1 Include_tcltk=1' $0
    Delete "$TEMP\python-aliber.exe"
  ${EndIf}

  StrCpy $PYW "$INSTDIR\python\pythonw.exe"
  ${IfNot} ${FileExists} "$PYW"
    ; O computador ja tinha esse mesmo Python instalado: usa o existente.
    ReadRegStr $1 HKCU "Software\Python\PythonCore\3.12\InstallPath" ""
    ${If} $1 == ""
      ReadRegStr $1 HKLM "Software\Python\PythonCore\3.12\InstallPath" ""
    ${EndIf}
    StrCpy $PYW "$1pythonw.exe"
    ${IfNot} ${FileExists} "$PYW"
      MessageBox MB_ICONSTOP "A instalação do Python não foi concluída. Rode o instalador de novo ou fale com a Aliber Informática." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${GetParent} "$PYW" $2
  DetailPrint "Python em: $2"

  DetailPrint "Instalando o gerador de Excel (openpyxl)..."
  nsExec::ExecToLog '"$2\python.exe" -m pip install --no-index --find-links "$INSTDIR\pacotes" --upgrade --disable-pip-version-check openpyxl'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Falha ao instalar o openpyxl (código $0). Fale com a Aliber Informática." /SD IDOK
    Abort
  ${EndIf}

  ; ---------- atalhos ----------
  CreateShortcut "$DESKTOP\${APP}.lnk" "$PYW" '"$INSTDIR\app\app.py"' "$INSTDIR\app\icone.ico" 0
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$PYW" '"$INSTDIR\app\app.py"' "$INSTDIR\app\icone.ico" 0
  CreateShortcut "$SMPROGRAMS\${APP}\LEIA-ME.lnk" "$INSTDIR\app\LEIA-ME.txt"
  CreateShortcut "$SMPROGRAMS\${APP}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"

  ; Se o envio automatico ja estava ativo (versao anterior), aponta o inicio com o Windows para esta instalacao.
  ReadRegStr $3 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AliberSintegra"
  ${If} $3 != ""
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AliberSintegra" '"$PYW" "$INSTDIR\app\app.py" --automatico'
  ${EndIf}

  ; ---------- desinstalador ----------
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "Aliber Informatica"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\app\icone.ico"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1

  ; Troca de versao pelo tecnico (instalador rodado com /S): reabre o programa no final.
  ${If} ${Silent}
    Exec '"$PYW" "$INSTDIR\app\app.py"'
  ${EndIf}
SectionEnd

Section "Uninstall"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AliberSintegra"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\pacotes"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNKEY}"
  ; As configuracoes e o historico de envios (%APPDATA%\AliberSintegra) e os arquivos gerados sao mantidos.
SectionEnd
