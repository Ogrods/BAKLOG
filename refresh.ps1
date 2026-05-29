Set-Location -Path "$PSScriptRoot"
$log = ".\refresh.log"
python fetch_games.py 2>&1 | Tee-Object -FilePath $log
python fetch_gog.py 2>&1 | Tee-Object -FilePath $log -Append
