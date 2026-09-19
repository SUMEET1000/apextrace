while ($true) {
    Write-Host "Running build_dataset.py..."
    .venv\Scripts\python scripts\build_dataset.py --years 2025 2026 --sessions FP1 FP2 FP3 Sprint --pause 2.5 *>&1 | Tee-Object -FilePath "temp_build.log"
    $buildExit = $LASTEXITCODE

    # A rate limit is the one failure worth sitting out: the budget is hourly,
    # and the build resumes from where it stopped.
    if (Select-String -Path "temp_build.log" -Pattern "F1 API rate limit reached" -Quiet) {
        Write-Host "Rate limit hit. Waiting 45 minutes before trying again..."
        Start-Sleep -Seconds 2700
        continue
    }

    # Every other failure is a failure. Matching only the rate-limit phrase
    # sent any other nonzero exit down the success branch, which printed
    # "Finished all possible sessions!", deleted the evidence and exited 0.
    if ($buildExit -ne 0) {
        Write-Host "Build failed with exit code $buildExit. Log kept at temp_build.log."
        exit $buildExit
    }

    Write-Host "Finished all possible sessions!"
    Remove-Item "temp_build.log" -ErrorAction SilentlyContinue
    break
}
