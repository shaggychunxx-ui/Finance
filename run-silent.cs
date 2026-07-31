// Tiny launcher: start a process with NO console flash.
// Built as a Windows (GUI) subsystem app so the launcher itself never allocates a console.
// Compile: csc /nologo /t:winexe /out:.local\run-silent.exe run-silent.cs
// Usage: run-silent.exe <exe> [args...]
//
// Uses CreateProcess(CREATE_NO_WINDOW) rather than Process.Start so child PowerShell/git
// do not briefly open a terminal under Windows Terminal as the default console host.
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

internal static class Program
{
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;
    private const short SW_HIDE = 0;
    private const int STARTF_USESHOWWINDOW = 0x00000001;
    private const int STARTF_USESTDHANDLES = 0x00000100;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        public int bInheritHandle;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcess(
        string lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFO lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CreatePipe(
        out IntPtr hReadPipe,
        out IntPtr hWritePipe,
        ref SECURITY_ATTRIBUTES lpPipeAttributes,
        int nSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(IntPtr hObject, uint dwMask, uint dwFlags);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(IntPtr hProcess, out uint lpExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadFile(
        IntPtr hFile,
        byte[] lpBuffer,
        uint nNumberOfBytesToRead,
        out uint lpNumberOfBytesRead,
        IntPtr lpOverlapped);

    private const uint HANDLE_FLAG_INHERIT = 0x00000001;
    private const uint INFINITE = 0xFFFFFFFF;

    private static int Main(string[] args)
    {
        if (args == null || args.Length < 1)
            return 1;

        string exe = args[0];
        var cmd = new StringBuilder();
        cmd.Append(QuoteArg(exe));
        for (int i = 1; i < args.Length; i++)
        {
            cmd.Append(' ');
            cmd.Append(QuoteArg(args[i]));
        }

        var sa = new SECURITY_ATTRIBUTES
        {
            nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)),
            bInheritHandle = 1,
            lpSecurityDescriptor = IntPtr.Zero
        };

        IntPtr outRead, outWrite, errRead, errWrite, inRead, inWrite;
        if (!CreatePipe(out outRead, out outWrite, ref sa, 0))
            return 3;
        if (!SetHandleInformation(outRead, HANDLE_FLAG_INHERIT, 0))
            return 3;
        if (!CreatePipe(out errRead, out errWrite, ref sa, 0))
            return 3;
        if (!SetHandleInformation(errRead, HANDLE_FLAG_INHERIT, 0))
            return 3;
        if (!CreatePipe(out inRead, out inWrite, ref sa, 0))
            return 3;
        if (!SetHandleInformation(inWrite, HANDLE_FLAG_INHERIT, 0))
            return 3;

        var si = new STARTUPINFO();
        si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        si.dwFlags = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES;
        si.wShowWindow = SW_HIDE;
        si.hStdOutput = outWrite;
        si.hStdError = errWrite;
        si.hStdInput = inRead;

        PROCESS_INFORMATION pi;
        uint flags = CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT;
        string cwd = Environment.CurrentDirectory;

        bool ok = CreateProcess(
            null,
            cmd,
            IntPtr.Zero,
            IntPtr.Zero,
            true,
            flags,
            IntPtr.Zero,
            cwd,
            ref si,
            out pi);

        // Parent must close write ends so child pipes can EOF
        CloseHandle(outWrite);
        CloseHandle(errWrite);
        CloseHandle(inRead);

        if (!ok)
        {
            CloseHandle(outRead);
            CloseHandle(errRead);
            CloseHandle(inWrite);
            return 3;
        }

        try
        {
            // Drain stdout/stderr so full pipes never deadlock; discard content
            DrainAsync(outRead);
            DrainAsync(errRead);
            CloseHandle(inWrite); // no stdin

            WaitForSingleObject(pi.hProcess, INFINITE);
            uint code;
            if (!GetExitCodeProcess(pi.hProcess, out code))
                return 2;
            return unchecked((int)code);
        }
        finally
        {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            CloseHandle(outRead);
            CloseHandle(errRead);
        }
    }

    private static void DrainAsync(IntPtr h)
    {
        // Simple blocking drain on a background thread
        System.Threading.ThreadPool.QueueUserWorkItem(_ =>
        {
            var buf = new byte[4096];
            uint read;
            while (ReadFile(h, buf, (uint)buf.Length, out read, IntPtr.Zero) && read > 0) { }
        });
    }

    private static string QuoteArg(string a)
    {
        if (string.IsNullOrEmpty(a)) return "\"\"";
        if (a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return a;
        return "\"" + a.Replace("\"", "\\\"") + "\"";
    }
}
