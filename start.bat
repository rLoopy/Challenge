@echo off
echo.
echo ====================================
echo    BOT DISCORD - DEFI FITNESS
echo ====================================
echo.

REM Vérifier si .env existe
if not exist .env (
    echo [ERREUR] Fichier .env manquant!
    echo.
    echo 1. Copie config-example.env en .env
    echo 2. Edite .env et ajoute ton token Discord
    echo.
    pause
    exit /b 1
)

REM Vérifier si les dépendances sont installées
python -c "import discord" 2>nul
if errorlevel 1 (
    echo [INFO] Installation des dependances...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERREUR] Echec de l'installation
        pause
        exit /b 1
    )
)

echo [INFO] Demarrage du bot...
echo.
python bot.py

pause



