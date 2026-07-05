# Assign a Windows AppUserModelID to a .lnk shortcut (taskbar icon grouping).
param(
    [Parameter(Mandatory = $true)][string]$ShortcutPath,
    [Parameter(Mandatory = $true)][string]$AppId
)

if (-not (Test-Path $ShortcutPath)) {
    Write-Error "Shortcut not found: $ShortcutPath"
}

if (-not ("ShortcutAppId" -as [type])) {
    Add-Type -Language CSharp @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PropertyKey
{
    public Guid fmtid;
    public uint pid;
}

[StructLayout(LayoutKind.Explicit)]
public struct PropVariant
{
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pointerValue;
}

[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore
{
    void GetCount(out uint cProps);
    void GetAt(uint iProp, out PropertyKey pkey);
    void GetValue(ref PropertyKey key, out PropVariant pv);
    void SetValue(ref PropertyKey key, ref PropVariant pv);
    void Commit();
}

[ComImport, Guid("0000010c-0000-0000-c000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPersist
{
    void GetClassID(out Guid pClassID);
}

[ComImport, Guid("0000010b-0000-0000-c000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPersistFile : IPersist
{
    new void GetClassID(out Guid pClassID);
    void IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, [MarshalAs(UnmanagedType.Bool)] bool fRemember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
}

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
public class CShellLink { }

public static class ShortcutAppId
{
    public static void Set(string shortcutPath, string appId)
    {
        var link = (IPersistFile)new CShellLink();
        const uint STGM_READWRITE = 2;
        link.Load(shortcutPath, STGM_READWRITE);
        var store = (IPropertyStore)link;
        var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        var pv = new PropVariant { vt = 31, pointerValue = Marshal.StringToCoTaskMemUni(appId) };
        try
        {
            store.SetValue(ref key, ref pv);
            store.Commit();
            link.Save(shortcutPath, true);
        }
        finally
        {
            if (pv.pointerValue != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(pv.pointerValue);
            }
        }
    }
}
"@
}

[ShortcutAppId]::Set($ShortcutPath, $AppId)