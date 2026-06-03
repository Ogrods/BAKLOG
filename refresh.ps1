Set-Location -Path "$PSScriptRoot"
$log = ".\refresh.log"
Clear-Content -Path $log -ErrorAction SilentlyContinue
python fetch_games.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_gog.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_psn.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_epic.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_xbox.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_battlenet.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_ubisoft.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_nintendo.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_humble.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_amazon.py --only-new 2>&1 | Tee-Object -FilePath $log -Append
python fetch_itch.py --only-new --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python enrich_steam_reviews.py --stores itch 2>&1 | Tee-Object -FilePath $log -Append
python fetch_wishlist.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetch_psn_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_ubisoft_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_nintendo_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_humble_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetch_itad.py 2>&1 | Tee-Object -FilePath $log -Append
python enrich_cross_store_images.py 2>&1 | Tee-Object -FilePath $log -Append
