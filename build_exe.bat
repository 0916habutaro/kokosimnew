@echo off
chcp 65001 >nul
rem ココシミュNew の EXE を作る（PyInstaller、kokosimnew.spec）。
rem できたもの: dist\kokosimnew\kokosimnew.exe
rem セーブは config\screen\screen_v1.json の save_root（E:\14.koko\kokosim_github\saves）に置かれる。
rem そのドライブがないときは %LOCALAPPDATA%\KokosimNew\saves。
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm kokosimnew.spec || goto :error
echo.
echo できました: dist\kokosimnew\kokosimnew.exe
pause
exit /b 0
:error
echo EXE を作れませんでした。上のエラーを確認してください。
pause
exit /b 1
