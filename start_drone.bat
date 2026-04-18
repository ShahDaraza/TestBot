@echo off
powershell -Command "Invoke-WebRequest -Uri 'https://your-github-link.com/python2.py' -OutFile 'C:\Users\%USERNAME%\drone.py'"
python C:\Users\%USERNAME%\drone.py