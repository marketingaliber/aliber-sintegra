@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Aliber SINTEGRA 2.5 - gerando o programa .exe
echo ============================================
echo.
py --version >nul 2>&1
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python pelo site python.org
  echo e marque a opcao "Add python.exe to PATH" na instalacao.
  pause
  exit /b 1
)
echo [1/2] Instalando o empacotador (PyInstaller) e o gerador de Excel (openpyxl)...
py -m pip install --upgrade pyinstaller openpyxl
echo.
echo [2/2] Montando o AliberSintegra.exe (leva 1 a 2 minutos)...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name AliberSintegra --icon icone.ico --add-data "icone.ico;." --hidden-import relatorio_excel --hidden-import versoes --collect-submodules openpyxl app.py
if errorlevel 1 (
  echo.
  echo Deu erro ao montar o programa. Tire um print desta tela e mande para o Claude.
  pause
  exit /b 1
)
copy /y dist\AliberSintegra.exe AliberSintegra.exe >nul
echo.
echo PRONTO! O programa esta em:
echo   %cd%\AliberSintegra.exe
echo.
echo Esse unico arquivo e o que voce copia para o computador do cliente.
pause
