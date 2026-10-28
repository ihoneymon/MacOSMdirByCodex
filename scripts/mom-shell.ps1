# Dot-source after installing MOM. Get-Command -CommandType Application avoids recursion.
function m2 {
    $momExecutable = Get-Command m2 -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $momFile = [System.IO.Path]::GetTempFileName()
    try {
        & $momExecutable.Source @args --last-dir-file $momFile
        $momCode = $LASTEXITCODE
        if ($momCode -eq 0) {
            $momTarget = [System.IO.File]::ReadAllText($momFile, [System.Text.Encoding]::UTF8)
            if ($momTarget -and (Test-Path -LiteralPath $momTarget -PathType Container)) {
                Set-Location -LiteralPath $momTarget
            }
        }
        $global:LASTEXITCODE = $momCode
    } finally {
        Remove-Item -LiteralPath $momFile -Force -ErrorAction SilentlyContinue
    }
}
