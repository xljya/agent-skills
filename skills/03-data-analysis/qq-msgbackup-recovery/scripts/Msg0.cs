using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

// Build x86. The classic QQ library uses cdecl and UTF-8 SQLite filenames.
class Msg0 {
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Open(byte[] path, out IntPtr db);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Key(IntPtr db, byte[] key, int length);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Exec(IntPtr db, string sql, IntPtr cb, IntPtr ctx, out IntPtr err);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Close(IntPtr db);

    static int Main(string[] args) {
        if (args.Length != 3 || (args[0] != "check" && args[0] != "rekey") || IntPtr.Size != 4) return 2;
        string dll = Path.GetFullPath(args[1]);
        using (var sha = SHA256.Create())
        using (var f = File.OpenRead(dll)) {
            if (BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "") !=
                "B39F79C6CF43A5665DABB587F31784C713FBFDA55EF0EBDD4A51AC1D0A0EC4E9") return 3;
        }
        if (!File.Exists(args[2])) return 4;
        var module = LoadLibraryEx(dll, IntPtr.Zero, 8);
        if (module == IntPtr.Zero) return 5;
        var open = (Open)Marshal.GetDelegateForFunctionPointer(IntPtr.Add(module,222689),typeof(Open));
        var key = (Key)Marshal.GetDelegateForFunctionPointer(IntPtr.Add(module,552643),typeof(Key));
        var exec = (Exec)Marshal.GetDelegateForFunctionPointer(IntPtr.Add(module,219554),typeof(Exec));
        var close = (Close)Marshal.GetDelegateForFunctionPointer(IntPtr.Add(module,219520),typeof(Close));
        var rekey = (Key)Marshal.GetDelegateForFunctionPointer(IntPtr.Add(module,553090),typeof(Key));
        byte[] secret = new byte[16];
        using (var input = new BinaryReader(Console.OpenStandardInput())) {
            secret = input.ReadBytes(16);
            if (secret.Length != 16) return 6;
        }
        IntPtr db, err;
        if (open(System.Text.Encoding.UTF8.GetBytes(Path.GetFullPath(args[2]) + "\0"), out db) != 0) return 7;
        int rc;
        try {
            rc = key(db,secret,16);
            if (rc == 0) rc = exec(db,"SELECT count(*) FROM sqlite_master",IntPtr.Zero,IntPtr.Zero,out err);
            if (rc == 0 && args[0] == "rekey") rc = rekey(db,new byte[16],16);
        } finally { Array.Clear(secret,0,secret.Length); }
        int closeRc = close(db);
        return rc != 0 ? rc : closeRc;
    }
}
