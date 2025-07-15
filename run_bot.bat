@echo off
echo Activating virtual environment...
call dc_env\Scripts\activate.bat


echo Starting the Discord bot...
python app.py

echo Bot has stopped. Press any key to close...
pause
