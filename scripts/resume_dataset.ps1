while ($true) {
    Write-Host "Running build_dataset.py..."
    .venv\Scripts\python scripts\build_dataset.py --years 2025 2026 --sessions FP1 FP2 FP3 Sprint --pause 2.5 *>&1 | Tee-Object -FilePath "temp_build.log"
    
    # Check if the output contains the rate limit warning
    if (Select-String -Path "temp_build.log" -Pattern "F1 API rate limit reached" -Quiet) {
        Write-Host "Rate limit hit. Waiting 45 minutes before trying again..."
        Start-Sleep -Seconds 2700
    } else {
        Write-Host "Finished all possible sessions!"
        Remove-Item "temp_build.log" -ErrorAction SilentlyContinue
        break
    }
}
