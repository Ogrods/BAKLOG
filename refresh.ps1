Set-Location -Path "$PSScriptRoot"
$log = ".\refresh.log"
python fetch_games.py 2>&1 | Tee-Object -FilePath $log
python fetch_gog.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_psn.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_epic.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_amazon.py --only-new 2>&1 | Tee-Object -FilePath $log -Append
python fetch_wishlist.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_itad.py 2>&1 | Tee-Object -FilePath $log -Append
python enrich_cross_store_images.py 2>&1 | Tee-Object -FilePath $log -Append
