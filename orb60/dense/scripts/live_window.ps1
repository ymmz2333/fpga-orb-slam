# Only activate this workspace's viewer for the requested live endpoint.
function Show-Orb60LiveWindow([string]$Root,[int]$Port) {
    $viewerPath=Join-Path $Root 'orb60/viewer/app.py'
    $pathPattern=[regex]::Escape([IO.Path]::GetFullPath($viewerPath))
    $endpointPattern='--dense-live["\s]+127\.0\.0\.1:'+$Port+'(?:["\s]|$)'
    $candidates=Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
    foreach ($candidate in $candidates) {
        $command=([string]$candidate.CommandLine).Replace('/',[string][IO.Path]::DirectorySeparatorChar)
        if ($command -notmatch $pathPattern -or $command -notmatch $endpointPattern) {continue}
        $process=Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
        if (-not $process) {continue}
        if (-not ('Orb60LiveWindow' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class Orb60LiveWindow {
    private delegate bool EnumCallback(IntPtr window, IntPtr data);
    [StructLayout(LayoutKind.Sequential)] public struct Rect {public int Left,Top,Right,Bottom;}
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumCallback callback, IntPtr data);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int limit);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window,out Rect rect);
    public static IntPtr Find(uint process) {
        IntPtr found=IntPtr.Zero;long largest=0;
        EnumWindows((window,data) => {
            uint owner; GetWindowThreadProcessId(window,out owner);
            if(owner!=process)return true;
            var title=new StringBuilder(256);GetWindowText(window,title,256);
            if(!title.ToString().StartsWith("ORB Studio"))return true;
            Rect rect;if(!GetWindowRect(window,out rect))return true;
            long width=rect.Right-rect.Left,height=rect.Bottom-rect.Top;
            // QOpenGLWidget owns hidden 1x1 surfaces with the application title.
            // They are not the main window, even when Windows marks them visible.
            if(width<400||height<250)return true;
            long area=width*height;if(area>largest){largest=area;found=window;}
            return true;
        },IntPtr.Zero);
        return found;
    }
}
'@
        }
        $handle=[Orb60LiveWindow]::Find($candidate.ProcessId)
        if ($handle -eq [IntPtr]::Zero) {continue}
        [void][Orb60LiveWindow]::ShowWindowAsync($handle,9)
        $activated=[Orb60LiveWindow]::SetForegroundWindow($handle)
        return [pscustomobject]@{Found=$true;Activated=$activated;ProcessId=$candidate.ProcessId;Handle=$handle}
    }
    return [pscustomobject]@{Found=$false;Activated=$false;ProcessId=$null}
}
