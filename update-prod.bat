@echo off
echo ============================================
echo   Khaled-Jewelery Production Update
echo ============================================
cd /d "C:\Khaled-Jewelery"

echo.
echo [1/4] Logging into GitHub Registry...
set GH_TOKEN=YOUR_TOKEN_HERE
echo %GH_TOKEN% | docker login ghcr.io -u asaalabbadi2-web --password-stdin
if %ERRORLEVEL% neq 0 (
    echo ERROR: Docker login failed!
    pause & exit /b 1
)

echo.
echo [2/4] Pulling latest images from GitHub...
docker compose -f docker-compose.prod.images.yml --env-file .env.production pull
if %ERRORLEVEL% neq 0 (
    echo ERROR: Pull failed!
    pause & exit /b 1
)

echo.
echo [3/4] Restarting all services (including scheduler)...
docker compose -f docker-compose.prod.images.yml --env-file .env.production up -d --force-recreate
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to start services!
    pause & exit /b 1
)

echo.
echo [4/4] Verifying scheduler started correctly...
timeout /t 5 /nobreak > nul
docker logs yasargold-scheduler --tail=15

echo.
echo ============================================
echo   Update Complete!
echo ============================================
pause
