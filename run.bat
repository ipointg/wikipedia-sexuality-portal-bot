@echo off
set PYWIKIBOT_DIR=C:\Users\Admin
cd /d C:\Users\Admin\wikipedia-sexuality-portal-bot

echo [%date% %time%] START > bot.log

py -u sexuality_portal.py >> bot.log 2>&1

echo. >> bot.log
echo [%date% %time%] EXIT CODE: %ERRORLEVEL% >> bot.log