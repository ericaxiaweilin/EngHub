@echo off
:: ============================================================
:: IE Module Deployment Script - Windows Version
:: 精益生产IE模块部署脚本（Windows版）
:: ============================================================

setlocal enabledelayedexpansion

:: Configuration (modify as needed)
set PROJECT_DIR=%~dp0
set REPOSITORY_URL=https://github.com/ericaxiaweilin/enghub.git
set BRANCH=main
set DATABASE_NAME=your_mes_db
set DB_USER=postgres
set DB_PASSWORD=your_password

echo ==========================================
echo   IE MODULE DEPLOYMENT SCRIPT - WINDOWS
echo ==========================================
echo.

:: Step 1: Update Git Repository
echo [Step 1] Pulling latest code from git...
cd /d %PROJECT_DIR%
if exist .git\ (
    git fetch origin
    git checkout %BRANCH%
    git pull origin %BRANCH%
    echo Code updated successfully!
) else (
    echo Error: Not a git repository!
    pause
    exit /b 1
)

:: Step 2: Apply Database Migrations
echo.
echo [Step 2] Applying database migrations...

:: Check if psql exists
where psql >nul 2>&1
if %errorlevel% equ 0 (
    echo Found psql client, applying migrations directly...
    
    set MIGRATION_FILES="039_ie_module.sql" "040_ie_extended_module.sql"
    
    for %%f in (%MIGRATION_FILES%) do (
        if exist database\migrations\%%f (
            echo Applying migration: %%f
            psql -U %DB_USER% -d %DATABASE_NAME% -f database\migrations\%%f
            if %errorlevel% equ 0 (
                echo ✓ Applied successfully!
            ) else (
                echo ✗ Failed to apply %%f
            )
        ) else (
            echo Error: Migration file not found: database\margins\%%f
        )
    )
) else (
    echo psql not found. Please check your PATH or use Python method.
    echo Press any key to continue and try Python approach...
    pause
    
    :: Try Python migration runner
    python -c "import sqlalchemy" >nul 2>&1
    if %errorlevel% equ 0 (
        echo Running migration via Python script...
        python run_migrations_py.py
    ) else (
        echo No suitable database connector found. Manual migration required.
        echo Install psycopg2: pip install psycopg2-binary
    )
)

:: Step 3: Restart Application
echo.
echo [Step 3] Restarting MES application...

:: Method 1: Check for PM2
where pm2 >nul 2>&1
if %errorlevel% equ 0 (
    echo PM2 found, restarting application...
    pm2 restart all || pm2 start main.py --name "mes-app"
    echo Application restarted via PM2!
) else (
    echo PM2 not found. Checking other methods...
    
    :: Check for running process
    tasklist /FI "IMAGENAME eq python.exe" | findstr /C:"main.py" >nul
    if %errorlevel% equ 0 (
        echo Found running process, attempting graceful restart...
        taskkill /F /IM python.exe >nul 2>&1
        timeout /t 1 /nobreak >nul
        
        :: Start new process in background
        start "" python main.py
        echo Application started in background.
    ) else (
        echo No running process found. Starting application...
        start "" python main.py
        echo Application started.
    )
)

echo.
echo ==========================================
echo ✅ IE Module Deployment Complete!
echo ==========================================
echo.
echo API Endpoints available at:
echo   Base: http://localhost:8000
echo   Swagger: http://localhost:8000/docs
echo   IE Module API prefix: /api/v1/ie
echo.
pause