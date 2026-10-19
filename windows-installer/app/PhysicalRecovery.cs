using System.IO;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record PhysicalRecoveryState(int Schema, string Phase, NativeDiskInfo Device, PhysicalPlan Plan, MediaSource Source, string[] Completed, string? Error, HomeCopyProfile? HomeCopy = null);
internal sealed class CompletedRangeMismatchException(long offset) : IOException("Completed partition differs at exact byte " + offset + ".");

public static partial class PhysicalInstallation
{
    internal static string[] RecoveryPrefix(string[] completed, ISet<string> restore)
    {
        if (!completed.SequenceEqual(PreparedDisk.Roles.Take(completed.Length)) || restore.Any(r => r is not ("efi-A" or "efi-B") || !completed.Contains(r)))
            throw new IOException("Only the newly installed FAT boot slots may be restored during recovery.");
        return completed.TakeWhile(r => !restore.Contains(r)).ToArray();
    }
    internal static void ValidateRecovery(PhysicalRecoveryState state, MediaSource source, PhysicalPlan plan, PreparedDisk layout, HomeCopyProfile? homeCopy = null)
    {
        if (state.Schema is not (1 or 2) || state.Schema == 1 && (state.HomeCopy != null || homeCopy != null)
            || state.Schema == 2 && (state.HomeCopy == null || homeCopy == null || state.HomeCopy != homeCopy)
            || state.Phase is not ("incomplete" or "partitions-created" or "registering-boot")
            && !PreparedDisk.Roles.Any(r => state.Phase == "writing-" + r || state.Phase == "verified-" + r))
            throw new IOException("This physical journal cannot be resumed.");
        state.HomeCopy?.Validate();
        var expected = Plan(plan.Selection, plan.Kind, layout);
        bool Same(PhysicalPlan p) => p.Selection == plan.Selection && p.Kind == plan.Kind && p.DiskId == expected.DiskId
            && p.MakeDefaultBoot == plan.MakeDefaultBoot && (!p.MakeDefaultBoot || p.Kind == InstallationTargetKind.InternalShared)
            && p.Required == expected.Required && p.Preserved.SequenceEqual(expected.Preserved) && p.Added.SequenceEqual(expected.Added);
        if (state.Source != source || !Same(state.Plan) || !Same(plan)) throw new IOException("Recovery source or reviewed plan changed.");
        if (state.Completed == null || state.Completed.Length > PreparedDisk.Roles.Length
            || !state.Completed.SequenceEqual(PreparedDisk.Roles.Take(state.Completed.Length))) throw new IOException("Recovery requires an ordered completed prefix.");
        RequireDevice(plan,state.Device);
    }

    internal static async Task CompareCompletedAsync(FileStream source, FileStream target, long sourceOffset, long targetOffset, long length, CancellationToken token)
    {
        if (sourceOffset < 0 || targetOffset < 1048576 || length <= 0 || sourceOffset % 512 != 0 || targetOffset % 512 != 0 || length % 512 != 0 || length > source.Length-sourceOffset)
            throw new IOException("Invalid completed partition comparison range.");
        source.Position=sourceOffset;target.Position=targetOffset;
        var a=new byte[4*1024*1024];var b=new byte[a.Length];
        for(long offset=0;offset<length;)
        {
            token.ThrowIfCancellationRequested();var count=(int)Math.Min(a.Length,length-offset);
            await source.ReadExactlyAsync(a.AsMemory(0,count),token);await target.ReadExactlyAsync(b.AsMemory(0,count),token);
            if(!a.AsSpan(0,count).SequenceEqual(b.AsSpan(0,count)))
            {
                var first=0;while(first<count && a[first]==b[first])first++;
                throw new CompletedRangeMismatchException(offset+first);
            }
            offset+=count;
        }
    }
}

public static partial class InstallationController
{
    // Explicit recovery entry. Never constructs a new plan from the now-occupied gap.
    public static async Task<string> ResumePhysicalAsync(string sessionPath, Action<string> log, CancellationToken token)
        => await WithInstallationLogAsync("physical-resume", log, trace => ResumePhysicalCoreAsync(sessionPath, trace.Write, token));

    private static async Task<string> ResumePhysicalCoreAsync(string sessionPath, Action<string> log, CancellationToken token)
    {
        if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("Physical recovery requires administrator access.");
        sessionPath=Path.GetFullPath(sessionPath);MediaSource.Ordinary(sessionPath,Work);
        if(Path.GetFileName(sessionPath)!="session.json" || new FileInfo(sessionPath).Length>65536)throw new IOException("Invalid session path.");
        var state=JsonSerializer.Deserialize<InstallationSession>(File.ReadAllText(sessionPath))??throw new IOException("Missing session.");
        if(state.Schema!=1 || !state.Physical || state.Status is not ("failed" or "cancelled") || !Regex.IsMatch(state.Id,"^[0-9a-f]{32}$")
            || !string.Equals(Path.GetDirectoryName(sessionPath),SessionDirectory(state),StringComparison.OrdinalIgnoreCase)
            || state.Deployment==null || !Regex.IsMatch(Path.GetFileName(state.Deployment),"^partition-deploy-[0-9a-f]{32}$"))throw new IOException("Not an interrupted physical session.");
        using var lease=LeaseSession(SessionDirectory(state));
        var journal=Path.Combine(state.Deployment,"physical-state.json");MediaSource.Ordinary(journal,Work);
        if(new FileInfo(journal).Length>1024*1024)throw new IOException("Oversized physical journal.");
        var recovery=JsonSerializer.Deserialize<PhysicalRecoveryState>(File.ReadAllText(journal),new JsonSerializerOptions{PropertyNameCaseInsensitive=true})??throw new IOException("Missing physical journal.");
        if(state.Kind!=recovery.Plan.Kind || state.MakeDefaultBoot!=recovery.Plan.MakeDefaultBoot)throw new IOException("Recovery target kind or boot choice changed.");
        var jobPath=Path.Combine(state.Deployment,"partition-job.json");MediaSource.Ordinary(jobPath,Work);
        if(new FileInfo(jobPath).Length>65536)throw new IOException("Oversized original job.");
        var job=JsonSerializer.Deserialize<PartitionJob>(File.ReadAllText(jobPath))??throw new IOException("Missing original job.");
        if(job.Schema is not (1 or 2) || job.Schema != recovery.Schema || job.Schema == 1 && job.HomeCopy != null || job.Schema == 2 && job.HomeCopy == null
            || job.Scope!="reviewed-physical-range" || job.PhysicalPlan==null || job.Kind!=state.Kind
            || "partition-deploy-"+job.Nonce!=Path.GetFileName(state.Deployment) || job.Source!=recovery.Source)throw new IOException("Original reviewed job differs from recovery journal.");
        // The deployment journal carries the source handle identity and original reviewed range.
        using var source=new PreparedDiskImage(recovery.Source.Path);
        PhysicalInstallation.ValidateRecovery(recovery,source.Identity,job.PhysicalPlan,source.Layout,job.HomeCopy);
        if(MediaSpace.Query(Work,16*PartitionInventory.MiB).Available<8ul*PartitionInventory.GiB)throw new IOException("Recovery requires at least 8 GiB of free workspace.");
        File.Copy(sessionPath,sessionPath+".before-physical-resume-"+Guid.NewGuid().ToString("N")+".json",false);
        try
        {
            state=state with{Status="running",Stage="recovering",Error=null,UpdatedUtc=DateTime.UtcNow};Save(sessionPath,state);
            await PhysicalInstallation.ApplyAsync(source,recovery.Plan,state.Deployment,log,token,resume:true,homeCopy:job.HomeCopy);
            var desktop = SteamOSDesktop.Install(state.Kind, state.Deployment, log, state.Options?.InstallerLanguage ?? InstallerI18n.Language);
            state = state with { DesktopRebootScript = desktop.Path, DesktopRebootWarning = desktop.Warning };
            state=state with{Status="awaiting-device-boot",Stage="awaiting-device-boot",UpdatedUtc=DateTime.UtcNow};Save(sessionPath,state);
            log("INSTALL_STATUS=awaiting-device-boot");return state.Deployment;
        }
        catch(Exception error)
        {
            state=state with{Status=error is OperationCanceledException?"cancelled":"failed",Error=error.Message,UpdatedUtc=DateTime.UtcNow};Save(sessionPath,state);throw;
        }
    }
}
