@echo off
echo ============================================================
echo  ZaloPay Stock Intelligence Agent - Setup
echo ============================================================

:: Install dependencies
echo.
echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
pip install vnstock3

:: Create .env from template if not exists
echo.
echo [2/3] Checking .env configuration...
if not exist .env (
    copy .env.template .env
    echo   Created .env from template. PLEASE EDIT .env with your credentials!
) else (
    echo   .env already exists.
)

:: Create required directories
echo.
echo [3/3] Creating directories...
mkdir data 2>nul
mkdir logs 2>nul
mkdir reports 2>nul

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  NEXT STEPS:
echo  1. Edit .env with your Azure AD and SMTP credentials
echo  2. Test the pipeline:   python main.py --test
echo  3. Run once with email: python main.py --once
echo  4. Start scheduler:     python main.py
echo ============================================================
pause
