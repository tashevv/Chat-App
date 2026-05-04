@echo off

echo Starting server...
start "Chat Server" python server.py

timeout /t 2 > nul

echo Starting client...
start "Chat Client" pythonw client.py

exit
