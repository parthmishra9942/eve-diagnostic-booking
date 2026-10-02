# One-click runner for EVE Diagnostic Booking Service
$Host.UI.RawUI.WindowTitle = "EVE Healthcare Diagnostic Service"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "         EVE HEALTHCARE DIAGNOSTIC BOOKING BACKEND          " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan

Write-Host "`n[Step 1/3] Ensuring database schema and seed data..." -ForegroundColor Yellow
python -m scripts.seed

Write-Host "`n[Step 2/3] Opening Interactive API Documentation in browser..." -ForegroundColor Yellow
Start-Process "http://127.0.0.1:8000/docs"

Write-Host "`n[Step 3/3] Starting FastAPI Server on http://127.0.0.1:8000..." -ForegroundColor Green
Write-Host "Press Ctrl + C in this terminal window to stop the server.`n" -ForegroundColor DarkGray

uvicorn app.main:app --reload --port 8000
