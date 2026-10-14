using System.IO;

namespace OxpInstaller;

internal static class SecretInputChecks
{
    internal static async Task<string> RunAsync()
    {
        const string prefix = "Handshake-r-中文-42!";
        var secret = prefix + new string('x', 255 - System.Text.Encoding.UTF8.GetByteCount(prefix));
        var transcript = await Backend.GuestAsync("secret-input-check", null, false,
            _ => { }, CancellationToken.None, secureInput: secret);
        if (!transcript.Contains("OXP_SECRET_CHECK=passed"))
            throw new IOException("Guest did not receive the complete secret.");
        if (!transcript.Contains("OXP_TASK_PERMISSIONS=passed"))
            throw new IOException("Password input changed subsequent task permissions.");
        if (transcript.Contains(secret) || transcript.Contains(Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(secret))))
            throw new IOException("Secret leaked to guest console.");
        var withoutPassword = await Backend.GuestAsync("secret-input-check", null, false,
            _ => { }, CancellationToken.None);
        if (!withoutPassword.Contains("OXP_TASK_PERMISSIONS=passed") || withoutPassword.Contains("OXP_SECRET_CHECK=passed"))
            throw new IOException("Task permissions differ without password input.");
        return "SECRET_INPUT_CHECK=passed (real QEMU with/without password; private secret/state; unprivileged access to task-created 755 directories and 644 files; no console disclosure)";
    }
}
