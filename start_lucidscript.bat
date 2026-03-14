@echo off

cd /d "C:\Users\dodd6\LucidScript Folder\LucidScript"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate

pip install -r requirements.txt

python -m uvicorn main:app --reload

pause