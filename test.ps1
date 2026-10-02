# One-click test runner for EVE Diagnostic Booking Service
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       RUNNING FULL TEST SUITE (42 TESTS)                  " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan

python -m pytest -v
