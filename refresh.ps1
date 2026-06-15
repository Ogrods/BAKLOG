Set-Location -Path "$PSScriptRoot"
$env:PYTHONPATH = "$PSScriptRoot"
$log = ".\refresh.log"
Clear-Content -Path $log -ErrorAction SilentlyContinue
python fetchers/fetch_games.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_gog.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_psn.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_epic.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_xbox.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_battlenet.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_ubisoft.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_nintendo.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_humble.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_ea.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_amazon.py --only-new 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_itch.py --only-new --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python enrichers/enrich_steam_reviews.py --stores itch 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_wishlist.py --skip-hltb 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_psn_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_ubisoft_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_nintendo_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_humble_wishlist.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_itad.py 2>&1 | Tee-Object -FilePath $log -Append
python fetchers/fetch_free_claims.py 2>&1 | Tee-Object -FilePath $log -Append
python enrichers/enrich_cross_store_images.py 2>&1 | Tee-Object -FilePath $log -Append
