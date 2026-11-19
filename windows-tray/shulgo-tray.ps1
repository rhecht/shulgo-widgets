# ShulGo in the Windows notification area (system tray) — the next minyan near you, at a glance.
#
# For the machines the Electron tray app (../desktop) can't run on: Windows 7 SP1, 8 and 8.1 (and it works on 10/11).
# Nothing to install: PowerShell 2.0+ and .NET 3.5+, both part of Windows 7. Hover the ShulGo icon for the next minyan;
# right-click it for the next few, today's place, "Refresh", "Open ShulGo", "Change place" and "Quit".
#
#   powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File shulgo-tray.ps1
#
# First run: it asks for your town or zip (or "lat,lng"), then links this computer to ShulGo the same way the other
# widgets do — it shows a short code; you type it at shulgo.com/link while signed in. The key it gets is kept in
# %APPDATA%\ShulGo\tray.json (only for you). It asks ShulGo every 15 minutes (fewer requests than a page view), keeps the
# last answer, and counts down between asks; when the network is down it says how old the times are.
#
# Windows 7 needs TLS 1.2 for shulgo.com: install .NET Framework 4.5+ (or the KB3140245 update) if it says "couldn't connect".
# State: written for the brief's P2.6 (2026-11-19); not yet run on a real Windows machine — see ../COMPATIBILITY.md.

$ErrorActionPreference = 'Stop'
$Base     = 'https://shulgo.com'
$Dir      = Join-Path $env:APPDATA 'ShulGo'
$Settings = Join-Path $Dir 'tray.json'
$EveryMin = 15

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Web.Extensions
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch { } # TLS 1.2 where .NET has it
$json = New-Object System.Web.Script.Serialization.JavaScriptSerializer

function Load-Settings {
    if (Test-Path $Settings) { try { return $json.DeserializeObject([IO.File]::ReadAllText($Settings)) } catch { } }
    return @{}
}
function Save-Settings($s) {
    if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Path $Dir | Out-Null }
    [IO.File]::WriteAllText($Settings, $json.Serialize($s))
}
function Web($method, $path, $body, $key) {
    $wc = New-Object Net.WebClient
    $wc.Encoding = [Text.Encoding]::UTF8
    $wc.Headers.Add('User-Agent', 'ShulGo-Windows-Tray/1.0')
    $wc.Headers.Add('Accept', 'application/json')
    if ($key) { $wc.Headers.Add('X-Api-Key', $key) }
    try {
        if ($method -eq 'POST') { $wc.Headers.Add('Content-Type', 'application/json'); $text = $wc.UploadString("$Base$path", 'POST', $json.Serialize($body)) }
        else { $text = $wc.DownloadString("$Base$path") }
        return $json.DeserializeObject($text)
    } catch [Net.WebException] {
        $r = $_.Exception.Response
        if ($r) { try { $sr = New-Object IO.StreamReader($r.GetResponseStream()); return $json.DeserializeObject($sr.ReadToEnd()) } catch { } }
        throw
    }
}
function Ask($title, $prompt, $default) {
    [void][Reflection.Assembly]::LoadWithPartialName('Microsoft.VisualBasic')
    return [Microsoft.VisualBasic.Interaction]::InputBox($prompt, $title, $default)
}

$s = Load-Settings
if (-not $s['place']) {
    $p = Ask 'ShulGo' 'Your town, neighbourhood or zip code (or "lat,lng"):' ''
    if (-not $p) { exit }
    $s['place'] = $p; Save-Settings $s
}
if (-not $s['key']) {
    # Link this computer (RFC 8628, as the other ShulGo widgets do)
    $code = (Web 'POST' '/api/v1/device/code' @{ client_name = 'ShulGo for Windows (tray)'; device_name = $env:COMPUTERNAME } $null)['data']
    [Windows.Forms.MessageBox]::Show("Go to $($code['verification_uri']) (signed in to ShulGo) and type this code:`n`n    $($code['user_code'])`n`nThen press OK here.", 'Link this computer to ShulGo') | Out-Null
    $deadline = (Get-Date).AddSeconds([int]$code['expires_in'])
    while ((Get-Date) -lt $deadline -and -not $s['key']) {
        $t = Web 'POST' '/api/v1/device/token' @{ device_code = $code['device_code'] } $null
        if ($t['data'] -and $t['data']['api_key']) { $s['key'] = $t['data']['api_key']; Save-Settings $s; break }
        $err = if ($t['error']) { $t['error']['code'] } else { '' }
        if ($err -and @('authorization_pending', 'slow_down') -notcontains $err) { [Windows.Forms.MessageBox]::Show("ShulGo didn't link this computer ($err). Start it again to try once more.", 'ShulGo') | Out-Null; exit }
        Start-Sleep -Seconds ([Math]::Max(5, [int]$code['interval']))
    }
    if (-not $s['key']) { exit }
}

# ---- the tray icon ------------------------------------------------------------------------------------------------
$icon = New-Object Windows.Forms.NotifyIcon
$bmp  = New-Object Drawing.Bitmap 16, 16
$g    = [Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = 'AntiAlias'
$g.FillEllipse((New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(29, 78, 216))), 0, 0, 15, 15)
$g.DrawString('S', (New-Object Drawing.Font('Segoe UI', 8, [Drawing.FontStyle]::Bold)), [Drawing.Brushes]::White, 2.5, 0.5)
$icon.Icon    = [Drawing.Icon]::FromHandle($bmp.GetHicon())
$icon.Visible = $true
$icon.Text    = 'ShulGo — loading…'
$menu = New-Object Windows.Forms.ContextMenu
$icon.ContextMenu = $menu
$state = @{ items = @(); label = ''; fetched = $null; error = $null }

function Fetch {
    $q = $s['place']
    $path = if ($q -match '^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$') { "/api/v1/next?lat=$($matches[1])&lng=$($matches[3])&window=240" } else { '/api/v1/next?q=' + [Uri]::EscapeDataString($q) + '&window=240' }
    try {
        $r = Web 'GET' $path $null $s['key']
        if ($r['error']) { $state.error = $r['error']['message']; return }
        $state.items   = @($r['data'] | Where-Object { $_['shul'] -or $_['live'] })
        $state.label   = $r['meta']['location']['label']
        $state.fetched = Get-Date
        $state.error   = $null
        $s['last'] = @{ items = $state.items; label = $state.label; fetched = $state.fetched.ToString('o') }; Save-Settings $s
    } catch {
        $state.error = "Couldn't reach ShulGo"
        if (-not $state.fetched -and $s['last']) { $state.items = @($s['last']['items']); $state.label = $s['last']['label']; $state.fetched = [DateTime]::Parse($s['last']['fetched']) }
    }
}
function Line($m) {
    $mins = [int](([DateTime]::Parse($m['starts_at'])).ToUniversalTime() - (Get-Date).ToUniversalTime()).TotalMinutes
    $when = if ($m['display_time']) { $m['display_time'] } else { $m['local_time'] }
    $tef  = (Get-Culture).TextInfo.ToTitleCase([string]$m['tefillah'])
    $name = if ($m['shul']) { $m['shul']['name'] } else { 'a minyan forming nearby' }
    return @{ text = "$tef $when · $name"; mins = $mins }
}
function Show {
    $now  = (Get-Date).ToUniversalTime()
    $next = @($state.items | Where-Object { ([DateTime]::Parse($_['starts_at'])).ToUniversalTime() -gt $now })
    if ($next.Count -gt 0) {
        $l = Line $next[0]
        $tip = "$($l.text) (in $($l.mins) min)"
    } elseif ($state.fetched) { $tip = 'No minyan in the next few hours nearby' } else { $tip = 'ShulGo — no times yet' }
    if ($state.error -and $state.fetched) { $tip = "$tip · $([int]((Get-Date) - $state.fetched).TotalMinutes) min old" }
    $icon.Text = if ($tip.Length -gt 63) { $tip.Substring(0, 62) + '…' } else { $tip } # (Windows 7 shows 63 characters)
    $menu.MenuItems.Clear()
    $head = $menu.MenuItems.Add("Near $($state.label)"); $head.Enabled = $false
    foreach ($m in ($next | Select-Object -First 6)) { $l = Line $m; $it = $menu.MenuItems.Add("$($l.text)  (in $($l.mins) min)"); $u = if ($m['shul']) { $m['shul']['url'] } else { "$Base/next" }; $it.Tag = $u; $it.add_Click({ param($o) Start-Process $o.Tag }) }
    if ($state.error) { $e = $menu.MenuItems.Add($state.error); $e.Enabled = $false }
    [void]$menu.MenuItems.Add('-')
    [void]$menu.MenuItems.Add('Refresh', { Fetch; Show })
    [void]$menu.MenuItems.Add('Open ShulGo', { Start-Process "$Base/next" })
    [void]$menu.MenuItems.Add('Change place…', { $p = Ask 'ShulGo' 'Your town, neighbourhood or zip code (or "lat,lng"):' $s['place']; if ($p) { $s['place'] = $p; Save-Settings $s; Fetch; Show } })
    [void]$menu.MenuItems.Add('Quit', { $icon.Visible = $false; [Windows.Forms.Application]::Exit() })
}

Fetch; Show
$tick = New-Object Windows.Forms.Timer
$tick.Interval = 60000
$count = 0
$tick.add_Tick({ $script:count++; if ($script:count % $EveryMin -eq 0) { Fetch }; Show }) # the countdown every minute, ShulGo every 15
$tick.Start()
[Windows.Forms.Application]::Run()
