@echo off
where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo Failed to install PyInstaller. Exiting.
        exit /b 1
    )
)

pyinstaller --onefile --windowed ^
    --icon="%CD%\assets\foxmidi.ico" ^
    --add-data "%CD%\assets;assets" ^
    --paths "%CD%\src" ^
    --workpath build\cache\build ^
    --specpath build\cache ^
    --distpath release ^
    --name FoxMIDI ^
    --hidden-import=rtmidi ^
    --hidden-import=mido.backends.rtmidi ^
    --hidden-import=mido.backends.rtmidi_python ^
    --collect-all=rtmidi ^
    main.py

if %errorlevel% neq 0 exit /b %errorlevel%
echo Done. release\FoxMIDI.exe ready.
pause