Set-Location -Path "$PSScriptRoot"
python fetch_games.py 2>&1 | Tee-Object -FilePath ".\refresh.log"
