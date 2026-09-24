param (
    [string]$ImagePath = ""
)

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms

    # Load System.Runtime.WindowsRuntime.dll manually
    $null = [System.Reflection.Assembly]::LoadFile("C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Runtime.WindowsRuntime.dll")

    # Load WinRT namespaces
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    
    # Locate reflection helpers for Await
    $getAwaiterMethod = [System.WindowsRuntimeSystemExtensions].GetMethods().Where({ 
        $_.Name -eq 'GetAwaiter' -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
    })[0]

    function Await-Async($AsyncTask, $ResultType) {
        $awaiterGeneric = $getAwaiterMethod.MakeGenericMethod($ResultType)
        $awaiter = $awaiterGeneric.Invoke($null, @($AsyncTask))
        return $awaiter.GetResult()
    }

    $OcrEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $OcrEngine) {
        Write-Error "OCR Engine not available"
        exit 1
    }

    # Load or capture image bytes
    $bytes = $null
    if ($ImagePath -and (Test-Path $ImagePath)) {
        $bytes = [System.IO.File]::ReadAllBytes($ImagePath)
    } else {
        # Take screenshot of primary screen
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bmp)
        $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
        $graphics.Dispose()

        # Convert to bytes
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        $bytes = $ms.ToArray()
        $ms.Dispose()
    }

    # Convert bytes to WinRT RandomAccessStream
    $randomAccessStream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter $randomAccessStream
    $writer.WriteBytes($bytes)
    
    $null = Await-Async ($writer.StoreAsync()) ([System.UInt32])
    $null = Await-Async ($writer.FlushAsync()) ([System.Boolean])
    
    $randomAccessStream.Seek(0)

    # Decode SoftwareBitmap
    $decoder = Await-Async ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($randomAccessStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await-Async ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    # Run OCR
    $ocrResult = Await-Async ($OcrEngine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])

    # Package result as custom object array for JSON output
    $linesJson = @()
    foreach ($line in $ocrResult.Lines) {
        $wordsJson = @()
        foreach ($word in $line.Words) {
            $wordsJson += @{
                text = $word.Text
                x = $word.BoundingRect.X
                y = $word.BoundingRect.Y
                w = $word.BoundingRect.Width
                h = $word.BoundingRect.Height
            }
        }
        $linesJson += @{
            text = $line.Text
            words = $wordsJson
        }
    }

    $output = @{
        status = "success"
        lines = $linesJson
    }

    Write-Output (ConvertTo-Json -InputObject $output -Depth 5)
} catch {
    $err = @{
        status = "error"
        message = $_.Exception.Message
    }
    Write-Output (ConvertTo-Json -InputObject $err)
    exit 1
}
