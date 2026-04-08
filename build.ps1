Write-Host "Installing PyInstaller..."
pip install pyinstaller

Write-Host "Setting Playwright Browser Path to Local for Portable Executable..."
$env:PLAYWRIGHT_BROWSERS_PATH="0"
playwright install chromium

Write-Host "Building ICEC Smart Assistant GUI..."
pyinstaller --name "ICEC_Smart_Assistant" `
    --noconsole `
    --onedir `
    --add-data "configs;configs" `
    --add-data "src/icec_bot/static;src/icec_bot/static" `
    --collect-all "playwright_stealth" `
    --collect-all "playwright" `
    --hidden-import "playwright_stealth" `
    --hidden-import "uvicorn" `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols" `
    --hidden-import "uvicorn.protocols.http" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "uvicorn.protocols.http.h11_impl" `
    --hidden-import "uvicorn.protocols.websockets" `
    --hidden-import "uvicorn.protocols.websockets.auto" `
    --hidden-import "uvicorn.protocols.websockets.wsproto_impl" `
    --hidden-import "uvicorn.lifespan" `
    --hidden-import "uvicorn.lifespan.on" `
    --hidden-import "fastapi" `
    --hidden-import "starlette" `
    --hidden-import "starlette.routing" `
    --hidden-import "starlette.responses" `
    --hidden-import "starlette.middleware" `
    --hidden-import "starlette.middleware.cors" `
    --hidden-import "websockets" `
    --hidden-import "anyio._backends._asyncio" `
    --hidden-import "pydantic" `
    --hidden-import "multiprocessing" `
    --hidden-import "pkg_resources" `
    --hidden-import "bs4" `
    --hidden-import "src.icec_bot" `
    --hidden-import "src.icec_bot.app" `
    --hidden-import "src.icec_bot.cli" `
    --hidden-import "src.icec_bot.browser" `
    --hidden-import "src.icec_bot.config" `
    --hidden-import "src.icec_bot.runner" `
    --hidden-import "src.icec_bot.storage" `
    --hidden-import "src.icec_bot.models" `
    --hidden-import "src.icec_bot.logging_utils" `
    --hidden-import "src.icec_bot.gui" `
    main_dashboard.py

Write-Host "=================="
Write-Host "Copying editable configs..."
Copy-Item -Path "configs" -Destination "dist\ICEC_Smart_Assistant\configs" -Recurse -Force

Write-Host "Build Complete!"
Write-Host "You can zip the 'dist\ICEC_Smart_Assistant' folder and distribute it."
Write-Host "Execute 'ICEC_Smart_Assistant.exe' directly inside to start the GUI!"
