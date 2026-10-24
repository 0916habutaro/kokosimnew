@echo off
chcp 65001 >nul
rem ココシミュNew の EXE を作る（PyInstaller、kokosimnew.spec）。
rem できたもの: dist\kokosimnew\kokosimnew.exe
rem セーブは %LOCALAPPDATA%\KokosimNew\saves に置かれる。
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm kokosimnew.spec || goto :error
echo.
echo できました: dist\kokosimnew\kokosimnew.exe
exit /b 0
:error
echo EXE を作れませんでした。上のエラーを確認してください。
exit /b 1
