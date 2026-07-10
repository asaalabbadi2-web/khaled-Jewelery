# apply_av133_adjustment.ps1

Invoke-WebRequest "https://raw.githubusercontent.com/asaalabbadi2-web/khaled-jewelery/main/backend/apply_av133_adjustment.py" -OutFile "$env:TEMP\apply_av133_adjustment.py"
docker cp "$env:TEMP\apply_av133_adjustment.py" yasargold-backend:/app/backend/apply_av133_adjustment.py
docker exec yasargold-backend python backend/apply_av133_adjustment.py 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
