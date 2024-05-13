@echo off

set "current_dir=%~dp0"

set "exe_path=%current_dir%.venv\Scripts\python.exe"

set "main_file=%current_dir%main.py"

"%exe_path%" "%main_file%"

pause