@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "from app_paths import ROOT, ensure_app_path; ensure_app_path(); from dashboard_server import open_predictions_dashboard; print(open_predictions_dashboard(ROOT))"
pause