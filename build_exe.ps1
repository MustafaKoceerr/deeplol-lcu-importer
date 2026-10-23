$ErrorActionPreference = "Stop"

Write-Host "Installing PyInstaller..."
python -m pip install pyinstaller

Write-Host "Building DeepLoL-LCU-Importer.exe..."
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "DeepLoL-LCU-Importer" `
    --collect-all customtkinter `
    main.py

Write-Host "Build completed: dist\DeepLoL-LCU-Importer.exe"
