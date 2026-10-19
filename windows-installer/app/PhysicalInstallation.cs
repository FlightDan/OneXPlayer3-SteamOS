using System.Buffers.Binary;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

public sealed record PhysicalPlan(PartitionSelection Selection, InstallationTargetKind Kind, Guid DiskId,
    NativePartition[] Preserved, PreparedPartition[] Added, long Required, bool MakeDefaultBoot = false);

public static partial class PhysicalInstallation
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle handle, uint code, byte[]? input, uint length, byte[]? output, uint outputLength, out uint returned, IntPtr overlapped);
    private static void Control(SafeFileHandle handle, uint code, byte[]? input = null)
    {
        if (!DeviceIoControl(handle, code, input, (uint)(input?.Length ?? 0), null, 0, out _, IntPtr.Zero))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Physical installation metadata operation");
    }
    public static PhysicalPlan Plan(PartitionSelection selection, InstallationTargetKind kind, PreparedDisk image)
    {
        if (selection.Example) throw new IOException("示例磁盘不能用于实际安装。 / Example disks cannot be installed.");
        var space = selection.Target();
        using var snapshot = JsonDocument.Parse(selection.Snapshot);
        var disk = snapshot.RootElement.EnumerateArray().Single(d => d.GetProperty("number").GetInt32() == space.Disk);
        var bus = disk.GetProperty("bus").GetString();
        if (kind == InstallationTargetKind.ExternalDisk && (bus is not ("USB" or "SD" or "MMC")
            || disk.GetProperty("isBoot").GetBoolean() || disk.GetProperty("isSystem").GetBoolean()))
            throw new IOException("外部安装必须选择非系统 USB/SD/MMC 设备。 / Select a non-system USB/SD/MMC disk.");
        if (kind == InstallationTargetKind.InternalShared && bus is not ("NVMe" or "SATA"))
            throw new IOException("内置安装必须选择 NVMe/SATA 磁盘。 / Select an NVMe/SATA disk.");
        var identity = space.Identity ?? throw new IOException("Missing GPT identity.");
        var preserved = identity.Partitions.Select(p => new NativePartition(p.Number,p.Offset,p.Size,Guid.Parse(p.Guid),1,p.GptType)).OrderBy(p=>p.Offset).ToArray();
        var source = image.System;
        if (!source.Select(p=>p.Name).SequenceEqual(PreparedDisk.Roles)) throw new IOException("Missing prepared roles.");
        var required = checked(source[^1].Offset + source[^1].Size - source[0].Offset);
        if (required != space.Size) throw new IOException("已准备系统与所选安装容量不一致。 / Prepared system does not match the selected capacity.");
        var numbers = preserved.Select(p=>p.Number).ToHashSet();
        var next = 1;
        var added = source.Select(p => { while(numbers.Contains(next)) next++; if(next>128) throw new IOException("GPT table is full.");
            return p with { Number=next++, Offset=checked(space.Start+p.Offset-source[0].Offset) }; }).ToArray();
        foreach(var p in added)
            if(p.Offset<space.Start || p.Offset+p.Size>space.Start+space.Size || preserved.Any(q=>p.Id==q.Id || Overlap(p.Offset,p.Size,q.Offset,q.Size)))
                throw new IOException("Prepared partition identity/range conflicts with existing data.");
        // A prepared root contains references to these GPT IDs. Keep them while relocating offsets.
        return new(selection,kind,Guid.Parse(identity.DiskGuid),preserved,added,required);
    }
    internal static bool Overlap(long a,long n,long b,long m)=>a<b+m && b<a+n;
    public static void RequireLayout(PhysicalPlan plan, NativeLayout actual, bool appended)
    {
        var expected=plan.Preserved.Concat(appended?plan.Added.Select(p=>p.Native):[]).OrderBy(p=>p.Offset).ToArray();
        if(actual.Style!=1 || actual.DiskId!=plan.DiskId || !actual.Partitions.SequenceEqual(expected))
            throw new IOException("磁盘布局已改变，请重新读取并确认。 / Target layout changed; review again.");
    }
    private static void RequireDevice(PhysicalPlan plan,NativeDiskInfo device,NativeDiskInfo? baseline=null)
    {
        var target=plan.Selection.Target();
        using var snapshot=JsonDocument.Parse(plan.Selection.Snapshot);
        var reviewed=snapshot.RootElement.EnumerateArray().Single(d=>d.GetProperty("number").GetInt32()==device.Number);
        if(reviewed.TryGetProperty("serial",out var serial) && !string.IsNullOrWhiteSpace(serial.GetString())
            && !string.Equals(serial.GetString()!.Trim(),device.Serial,StringComparison.OrdinalIgnoreCase))throw new IOException("Native serial differs from the reviewed target.");
        if(device.Number!=target.Disk || device.Size!=target.DiskSize || device.SectorSize!=512
            || device.Bus is not (7 or 11 or 12 or 17 or 13) || baseline!=null && baseline!=device)
            throw new IOException("Target native identity/capacity/bus changed.");
    }
    internal static byte[] EncodeAppend(byte[] original, PhysicalPlan plan)
    {
        if(original.Length<48 || BitConverter.ToUInt32(original)!=1 || new Guid(original.AsSpan(8,16))!=plan.DiskId)
            throw new IOException("Unexpected GPT header.");
        var count=checked((int)BitConverter.ToUInt32(original,4));
        if(count>128 || original.Length<48+144*count) throw new IOException("Invalid GPT metadata size.");
        var capacity=plan.Selection.Target().DiskSize;
        RequireLayout(plan,NativeMediaDevice.ParseLayout(original,capacity),false);
        var maximum=BitConverter.ToUInt32(original,40);
        var total=checked(count+plan.Added.Length);
        if(maximum==0 || maximum>128 || total>maximum || plan.Added.Length!=PreparedDisk.Roles.Length)
            throw new IOException("Insufficient native GPT entries for the reviewed plan.");
        // PartitionEntry is a packed record array. PartitionNumber is a Windows
        // identifier, not an array index or the on-disk GPT slot (e.g. 1,2,3,15,16).
        // Retain original records in place and append after PartitionCount.
        var result=new byte[48+144*total]; original.AsSpan(0,48+144*count).CopyTo(result);
        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(4),(uint)total);
        for(var i=0;i<count;i++) result[48+144*i+28]=0;
        var first=BitConverter.ToInt64(original,24); var usable=BitConverter.ToInt64(original,32);
        if(first<0 || usable<=0 || first>capacity || usable>capacity-first)
            throw new IOException("Invalid native GPT usable range.");
        var numbers=plan.Preserved.Select(p=>p.Number).ToHashSet();
        var ids=plan.Preserved.Select(p=>p.Id).ToHashSet();
        var ranges=plan.Preserved.Select(p=>(p.Offset,p.Size)).ToList();
        var target=plan.Selection.Target();
        for(var i=0;i<plan.Added.Length;i++)
        {
            var p=plan.Added[i];var at=48+144*(count+i);
            if(p.Number<1 || p.Number>128 || !numbers.Add(p.Number) || p.Id==Guid.Empty || !ids.Add(p.Id)
                || p.Type==Guid.Empty || p.Offset<first || p.Size<=0 || p.Offset>first+usable || p.Size>first+usable-p.Offset
                || p.Offset<target.Start || p.Offset>target.Start+target.Size || p.Size>target.Start+target.Size-p.Offset
                || p.Offset%512!=0 || p.Size%512!=0 || p.Name.Length>36 || p.Name.Contains('\0')
                || p.Name!=PreparedDisk.Roles[i] || ranges.Any(q=>Overlap(p.Offset,p.Size,q.Offset,q.Size)))
                throw new IOException("Invalid or conflicting appended GPT partition: "+p.Name);
            ranges.Add((p.Offset,p.Size));
            BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(at),1);
            BinaryPrimitives.WriteInt64LittleEndian(result.AsSpan(at+8),p.Offset);
            BinaryPrimitives.WriteInt64LittleEndian(result.AsSpan(at+16),p.Size);
            BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(at+24),(uint)p.Number); result[at+28]=1;
            p.Type.TryWriteBytes(result.AsSpan(at+32,16));p.Id.TryWriteBytes(result.AsSpan(at+48,16));
            BinaryPrimitives.WriteUInt64LittleEndian(result.AsSpan(at+64),p.Attributes);
            Encoding.Unicode.GetBytes(p.Name).CopyTo(result,at+72);
        }
        return result;
    }
    private static void CheckSource(FileStream source,PhysicalPlan plan)
    {
        var volume=NativeVolumes.FromOpenFile(source);
        if(volume.Extents.Length!=1 || volume.Extents.Any(e=>e.DiskNumber==plan.Selection.Disk
            && plan.Added.Any(p=>Overlap(e.Offset,e.Size,p.Offset,p.Size)))) throw new IOException("Source overlaps the installation range.");
    }
    public static async Task ApplyAsync(PreparedDiskImage source, PhysicalPlan plan,string directory,Action<string> log,CancellationToken token, bool resume = false, HomeCopyProfile? homeCopy = null)
    {
        if (plan.MakeDefaultBoot && plan.Kind != InstallationTargetKind.InternalShared)
            throw new IOException("External installation cannot change the host boot order.");
        var statePath=Path.Combine(directory,"physical-state.json");
        PhysicalRecoveryState? recovery = null;
        if (resume)
        {
            MediaSource.Ordinary(statePath,InstallationController.Work);
            if(new FileInfo(statePath).Length>1024*1024)throw new IOException("Oversized physical recovery journal.");
            recovery=JsonSerializer.Deserialize<PhysicalRecoveryState>(File.ReadAllText(statePath),new JsonSerializerOptions{PropertyNameCaseInsensitive=true}) ?? throw new IOException("Missing physical recovery journal.");
            ValidateRecovery(recovery,source.Identity,plan,source.Layout,homeCopy);
        }
        homeCopy?.Validate();
        var leasePath=Path.Combine(InstallationController.Work,"physical-"+plan.DiskId.ToString("N")+".lock");MediaSource.Ordinary(leasePath,InstallationController.Work,false);
        using var ownership=new FileStream(leasePath,FileMode.Create,FileAccess.ReadWrite,FileShare.None,4096,FileOptions.DeleteOnClose);
        var readiness = await Backend.GuestAsync("physical-readiness",source.Identity.Path,false,log,token,
            selection: homeCopy == null ? null : Ext4HomeCopyPlan.Selection);
        var homePlan = homeCopy == null ? null : Ext4HomeCopyPlan.FromTranscript(readiness, source);
        if (homePlan != null && homePlan.Profile != homeCopy) throw new IOException("Prepared home copy plan changed after review.");
        if (homePlan != null) log($"HOME_COPY_PROFILE={homePlan.Profile.Mode}:{homePlan.UsedBytes}:{source.Layout.System.Single(p=>p.Name=="home").Size}");
        // All checks precede obtaining a writable handle. This API never erases existing partitions.
        var fresh=await Backend.PowerShellAsync("read-disks.ps1", [],_=>{},token);
        var rebound=plan.Selection with {Snapshot=resume?plan.Selection.Snapshot:fresh};
        var again=Plan(rebound,plan.Kind,source.Layout);
        if(again.DiskId!=plan.DiskId || !again.Preserved.SequenceEqual(plan.Preserved) || !again.Added.SequenceEqual(plan.Added)) throw new IOException("Reviewed disk changed.");
        CheckSource(source.Stream,plan);
        using var metadata=NativeMediaIo.OpenReadOnlyDisk(plan.Selection.Disk);
        var native=NativeMediaDevice.Read(metadata);RequireDevice(plan,native,recovery?.Device);RequireLayout(plan,NativeMediaDevice.ReadLayout(metadata,native.Size),resume);
        var before=NativeMediaIo.Query(metadata,0x70050,1024*1024,48);
        var encoded=resume?null:EncodeAppend(before,plan);
        using var metadataFile=new FileStream(metadata,FileAccess.Read,4096,false);
        var gptBefore=PhysicalGpt.Read(metadataFile,native.Size,plan.DiskId);
        if(!resume)gptBefore.RequireNativePrefix(before);
        // Discovery inspects all Windows volumes. Fail on an existing malformed
        // response before appending GPT entries, not only when acquiring locks.
        NativeVolumes.FindForDisk(native.Number,native.Size);
        log("PHYSICAL_VOLUME_PREFLIGHT=passed");
        if(plan.Kind==InstallationTargetKind.InternalShared)FirmwareBoot.RequireSupported();
        if(File.Exists(statePath)!=resume) throw new IOException("Physical journal requires explicit recovery; new jobs require an unused directory.");
        void Save(string phase,string[] completed,string? error=null)
        {
            using(var file=new FileStream(statePath+".tmp",FileMode.Create,FileAccess.Write,FileShare.None))
            { JsonSerializer.Serialize(file,new {schema=homeCopy == null ? 1 : 2,phase,device=native,plan,source=source.Identity,completed,error,homeCopy});file.Flush(true); }
            File.Move(statePath+".tmp",statePath,true);
        }
        if(!resume) { File.WriteAllBytes(Path.Combine(directory,"gpt-native-before.bin"),before); Save("reviewed",[]); }
        else File.Copy(statePath,statePath+".before-resume-"+Guid.NewGuid().ToString("N")+".json",false);
        token.ThrowIfCancellationRequested();
        var handle=CreateFile(@"\\.\PhysicalDrive"+native.Number,0xc0000000,3,IntPtr.Zero,3,0x80000000,IntPtr.Zero);
        if(handle.IsInvalid){handle.Dispose();throw new Win32Exception(Marshal.GetLastWin32Error(),"Open reviewed target disk");}
        using var raw=new FileStream(handle,FileAccess.ReadWrite,4*1024*1024,false);
        RequireDevice(plan,NativeMediaDevice.Read(handle),native);RequireLayout(plan,NativeMediaDevice.ReadLayout(handle,native.Size),resume);
        CheckSource(source.Stream,plan);source.Recheck();
        if(!resume)
        {
            if(!NativeMediaIo.Query(handle,0x70050,1024*1024,48).SequenceEqual(before))throw new IOException("Native GPT metadata changed before append.");
            PhysicalGpt.Read(raw,native.Size,plan.DiskId).RequireSame(gptBefore);
        }
        var completed=new List<string>(recovery?.Completed??[]);
        try
        {
            if(!resume) { Save("appending",[]);Control(handle,0x7c054,encoded);raw.Flush(true);Control(handle,0x70140); }
            RequireLayout(plan,NativeMediaDevice.ReadLayout(handle,native.Size),true);
            if(!resume)PhysicalGpt.Read(raw,native.Size,plan.DiskId).RequireAppended(gptBefore,(int)BitConverter.ToUInt32(before,4),plan.Added);
            if(!resume)Save("partitions-created",[]);
            using(var locks=PhysicalLocks.Acquire(plan,native,handle,()=>RequireDevice(plan,NativeMediaDevice.Read(handle),native),log,token))
            {
                // Recovery verifies the entire completed prefix before the first write.
                var verifiedBeforeResume=new HashSet<string>();
                var restoreBootSlots=new HashSet<string>();
                foreach(var role in completed)
                {
                    RequireDevice(plan,NativeMediaDevice.Read(handle),native);
                    RequireLayout(plan,NativeMediaDevice.ReadLayout(handle,native.Size),true);source.Recheck();
                    var part=source.Layout.System.Single(p=>p.Name==role);var target=plan.Added.Single(p=>p.Name==role);
                    try
                    {
                        if (part.Name == "home" && homePlan != null)
                            await PartitionDeployment.CompareRangesAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,native.Size,homePlan.Ranges,_=>{},token);
                        else await CompareCompletedAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,token);
                        verifiedBeforeResume.Add(role);log("PHYSICAL_RECOVERY_PREFIX_VERIFIED="+role);
                    }
                    catch(CompletedRangeMismatchException error) when(role is "efi-A" or "efi-B")
                    {
                        // Windows can mount these Basic/FAT volumes and add index metadata
                        // after locks are released. Restore this session's newly-created slot
                        // from the immutable source, then use normal full write/readback.
                        restoreBootSlots.Add(role);log("PHYSICAL_RECOVERY_RESTORE_BOOT="+role+":"+error.Message);
                    }
                }
                completed=RecoveryPrefix(completed.ToArray(),restoreBootSlots).ToList();
                foreach(var destination in plan.Added.Skip(completed.Count).ToArray())
                {
                    token.ThrowIfCancellationRequested();RequireDevice(plan,NativeMediaDevice.Read(handle),native);
                    RequireLayout(plan,NativeMediaDevice.ReadLayout(handle,native.Size),true); source.Recheck();
                    if(verifiedBeforeResume.Contains(destination.Name))
                    {
                        completed.Add(destination.Name);Save("verified-"+destination.Name,completed.ToArray());continue;
                    }
                    var part=source.Layout.System.Single(p=>p.Name==destination.Name);Save("writing-"+part.Name,completed.ToArray());
                    Action<MediaProgress> report = p=>log($"PARTITION_PROGRESS={part.Name}:{p.Stage}:{p.Written}:{p.Verified}:{p.Total}");
                    if (part.Name == "home" && homePlan != null)
                        await PartitionDeployment.CopyRangesAsync(source.Stream,raw,part.Offset,destination.Offset,part.Size,native.Size,homePlan.Ranges,report,token);
                    else await PartitionDeployment.CopyRangeAsync(source.Stream,raw,part.Offset,destination.Offset,part.Size,native.Size,report,token);
                    completed.Add(part.Name);Save("verified-"+part.Name,completed.ToArray());
                }
            }
            token.ThrowIfCancellationRequested();
            RequireLayout(plan,NativeMediaDevice.ReadLayout(handle,native.Size),true);
            Save("registering-boot",completed.ToArray());
            log("PARTITION_PHASE=registering-boot");
            if(plan.Kind==InstallationTargetKind.InternalShared)
                FirmwareBoot.Register(PhysicalGpt.Read(raw,native.Size,plan.DiskId).ForFirmware(plan.Added.Single(p=>p.Name=="esp")),directory,plan.MakeDefaultBoot);
            Save("written-awaiting-device-boot",completed.ToArray());
            log("PHYSICAL_RESULT=written-awaiting-device-boot");
        }
        catch(Exception error){Save("incomplete",completed.ToArray(),error.Message);throw;}
    }
    private sealed class PhysicalLocks:IDisposable
    {
        private readonly List<SafeFileHandle> handles=[];
        public static PhysicalLocks Acquire(PhysicalPlan plan,NativeDiskInfo device,SafeFileHandle disk,Action checkDevice,Action<string>? log=null,CancellationToken token=default)
        {
            var result=new PhysicalLocks();
            try
            {
                var selected=NativeVolumeDiscovery.Wait(
                    ()=>NativeVolumes.FindForDisk(device.Number,device.Size).Where(v=>plan.Added.Any(p=>Overlap(p.Offset,p.Size,v.Extents[0].Offset,v.Extents[0].Size))).ToArray(),
                    volumes=>plan.Added.Take(3).All(p=>volumes.Any(v=>v.Extents[0].Offset==p.Offset && v.Extents[0].Size==p.Size)),
                    ()=>{checkDevice();RequireLayout(plan,NativeMediaDevice.ReadLayout(disk,device.Size),true);},
                    TimeSpan.FromSeconds(15),log,token);
                foreach(var volume in selected)
                {
                    if(!plan.Added.Any(p=>volume.Extents[0].Offset==p.Offset && volume.Extents[0].Size==p.Size))throw new IOException("Overlapping target volume.");
                    var h=CreateFile(volume.Path[..^1],0xc0000000,3,IntPtr.Zero,3,0,IntPtr.Zero);
                    if(h.IsInvalid){h.Dispose();throw new Win32Exception(Marshal.GetLastWin32Error());}
                    try
                    {
                        var waiting=System.Diagnostics.Stopwatch.StartNew();var announced=false;
                        while(true)
                        {
                            token.ThrowIfCancellationRequested();checkDevice();RequireLayout(plan,NativeMediaDevice.ReadLayout(disk,device.Size),true);
                            if(!NativeVolumes.ReadExtents(h,volume.Path).SequenceEqual(volume.Extents))throw new IOException("Volume binding changed.");
                            try{Control(h,0x90018);break;}
                            catch(Win32Exception error) when(error.NativeErrorCode is 5 or 32 && waiting.Elapsed<TimeSpan.FromSeconds(15))
                            {
                                if(!announced){log?.Invoke("PHYSICAL_VOLUME_LOCK=waiting; "+volume.Path);announced=true;}
                                if(token.WaitHandle.WaitOne(100))token.ThrowIfCancellationRequested();
                            }
                        }
                        result.handles.Add(h);h=null!;
                    }
                    finally{h?.Dispose();}
                }
                checkDevice();RequireLayout(plan,NativeMediaDevice.ReadLayout(disk,device.Size),true);
                foreach(var h in result.handles)Control(h,0x90020);
                return result;
            }catch{result.Dispose();throw;}
        }
        public void Dispose()
        {
            Exception? failure=null;
            foreach(var h in handles.AsEnumerable().Reverse())
            {try{Control(h,0x9001c);}catch(Exception error){failure??=error;}finally{h.Dispose();}}
            handles.Clear();if(failure!=null)throw new IOException("Failed to unlock a selected volume; all handles were closed.",failure);
        }
    }
    // Exercises the same native append, lock and bounded-copy operations only on an owned disposable VHD.
    public static async Task<string> CheckOwnedAsync(string imagePath,Action<string> log,CancellationToken token,bool optimizeHome = false)
    {
        using var source=new PreparedDiskImage(imagePath);
        var homePlan = optimizeHome ? Ext4HomeCopyPlan.FromTranscript(
            await Backend.GuestAsync("physical-readiness",imagePath,false,log,token,selection:Ext4HomeCopyPlan.Selection),source) : null;
        if (optimizeHome && homePlan!.Profile.Mode != "ext4-used-v1") throw new IOException("Owned optimized-copy proof requires an optimized ext4 plan.");
        long? freeProbe = null, zeroProbe = null;
        if (homePlan != null)
        {
            var home = source.Layout.System.Single(p => p.Name == "home");
            var block = new byte[4096]; long inspected = 0;
            foreach (var range in homePlan.Ranges)
            {
                for (long at = range.Offset; at < range.Offset + range.Length && inspected < 16 * 1048576; at += block.Length)
                {
                    token.ThrowIfCancellationRequested(); source.Stream.Position = home.Offset + at; source.Stream.ReadExactly(block); inspected += block.Length;
                    if (block.All(value => value == 0)) { zeroProbe = at; break; }
                }
                if (zeroProbe != null || inspected >= 16 * 1048576) break;
            }
            long end = 0;
            foreach (var range in homePlan.Ranges)
            {
                if (range.Offset - end >= 4096) { freeProbe = end; break; }
                end = range.Offset + range.Length;
            }
            if (freeProbe == null && home.Size - end >= 4096) freeProbe = end;
            if (zeroProbe == null || freeProbe == null) throw new IOException("Owned optimized-copy fixture needs an allocated zero block and a filesystem-free block.");
        }
        var directory=Path.Combine(InstallationController.Work,"physical-adapter-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
        const long mib=1048576, gib=1073741824;
        using(var disk=new VirtualMediaDisk(Path.Combine(directory,"media.vhd"),96*gib))
        {
            var protectedParts=new[]{new PreparedPartition(1,"Keep existing data",Guid.Parse("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"),Guid.NewGuid(),mib,64*mib,0x8000000000000000)};
            var initial=new PreparedDisk(Guid.NewGuid(),disk.Size,protectedParts);
            OwnedPartitionLayout.Initialize(disk,initial,protectedParts);
            var preservedPattern=new byte[4*1024*1024];Array.Fill(preservedPattern,(byte)0xa7);
            using(var protectedLocks=PartitionVolumeLocks.Acquire(disk,protectedParts))
            using(var seed=disk.OpenDevice())
            {seed.Position=protectedParts[0].Offset;for(long i=0;i<protectedParts[0].Size;i+=preservedPattern.Length)seed.Write(preservedPattern);seed.Flush(true);}
            using var raw=disk.OpenDevice();var native=NativeMediaDevice.Read(raw.SafeFileHandle);
            var snapshot=JsonSerializer.Serialize(new[]{new{number=native.Number,model="Owned VHD test",size=disk.Size,bus="NVMe",style="GPT",guid=initial.Id,sectorSize=512,isBoot=false,isSystem=false,isOffline=false,isReadOnly=false,
                partitions=protectedParts.Select(p=>new{number=p.Number,guid=p.Id,offset=p.Offset,size=p.Size,gptType=p.Type,type="Basic",filesystem="",letter="",label=p.Name,isBoot=false,free=0})}});
            var gap=DiskPlanning.FreeSpaces(snapshot).Single();
            var selected=new PartitionSelection(snapshot,false,native.Number,gap.Start,64*gib);
            var plan=Plan(selected,InstallationTargetKind.InternalShared,source.Layout);
            var before=NativeMediaIo.Query(raw.SafeFileHandle,0x70050,1024*1024,48);
            var next=EncodeAppend(before,plan);
            if(!before.AsSpan(48,28).SequenceEqual(next.AsSpan(48,28)) || !before.AsSpan(77,115).SequenceEqual(next.AsSpan(77,115)))throw new IOException("Preserved entry changed.");
            RequireLayout(plan,NativeMediaDevice.ReadLayout(raw.SafeFileHandle,disk.Size),false);
            Control(raw.SafeFileHandle,0x7c054,next);raw.Flush(true);Control(raw.SafeFileHandle,0x70140);
            RequireLayout(plan,NativeMediaDevice.ReadLayout(raw.SafeFileHandle,disk.Size),true);
            using(var locks=PhysicalLocks.Acquire(plan,native,raw.SafeFileHandle,()=>{if(disk.BoundDiskNumber()!=native.Number)throw new IOException("Owned VHD binding changed.");}))
            foreach(var target in plan.Added)
            {
                var part=source.Layout.System.Single(p=>p.Name==target.Name);
                source.Recheck();
                if (part.Name == "home" && homePlan != null)
                {
                    var sentinel = new byte[4096]; Array.Fill(sentinel, (byte)0xa7);
                    foreach (var probe in new[] { zeroProbe!.Value, freeProbe!.Value })
                    { raw.Position = target.Offset + probe; raw.Write(sentinel); }
                    raw.Flush(true);
                    await PartitionDeployment.CopyRangesAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,disk.Size,homePlan.Ranges,
                        p=>log($"PARTITION_PROGRESS={part.Name}:{p.Stage}:{p.Written}:{p.Verified}:{p.Total}"),token);
                    var block = new byte[4096]; raw.Position = target.Offset + zeroProbe.Value; raw.ReadExactly(block);
                    if (block.Any(value => value != 0)) throw new IOException("Owned native range copy skipped an allocated zero block.");
                    raw.Position = target.Offset + freeProbe.Value; raw.ReadExactly(block);
                    if (!block.SequenceEqual(sentinel)) throw new IOException("Owned native range copy changed a filesystem-free block.");
                    block = new byte[4096]; block[0] = 0x55;
                    raw.Position = target.Offset + freeProbe.Value; raw.Write(block); raw.Flush(true);
                    await PartitionDeployment.CompareRangesAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,disk.Size,homePlan.Ranges,_=>{},token);
                    raw.Position = target.Offset + zeroProbe.Value; raw.Write(block); raw.Flush(true); var rejected = false;
                    try { await PartitionDeployment.CompareRangesAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,disk.Size,homePlan.Ranges,_=>{},token); }
                    catch (CompletedRangeMismatchException) { rejected = true; }
                    if (!rejected) throw new IOException("Owned native resume accepted allocated-block corruption.");
                    raw.Position = target.Offset + zeroProbe.Value; raw.Write(new byte[4096]); raw.Flush(true);
                    log("PHYSICAL_ADAPTER_HOME_PROBES=allocated-zero-overwritten;free-preserved;resume-validates-allocated-ranges");
                }
                else await PartitionDeployment.CopyRangeAsync(source.Stream,raw,part.Offset,target.Offset,part.Size,disk.Size,_=>{},token);
                log("PHYSICAL_ADAPTER_VERIFIED="+part.Name);
            }
            RequireLayout(plan,NativeMediaDevice.ReadLayout(raw.SafeFileHandle,disk.Size),true);
            var readback=new byte[preservedPattern.Length];raw.Position=protectedParts[0].Offset;
            for(long i=0;i<protectedParts[0].Size;i+=readback.Length){raw.ReadExactly(readback);if(!readback.SequenceEqual(preservedPattern))throw new IOException("Protected partition contents changed.");}
            File.WriteAllText(Path.Combine(directory,"plan.json"),JsonSerializer.Serialize(plan));
        }
        var boot=await VirtualBoot.PhysicalAdapterAsync(Path.Combine(directory,"media.vhd"),log,token);
        File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new {passed=true,boot,homeCopy=homePlan?.Profile,homeUsedBytes=homePlan?.UsedBytes,allocatedZeroProbe=zeroProbe,freeDataProbe=freeProbe,scope="Same native GPT append, selected-volume locking and relocated partition write/readback on an owned VHD; independent UEFI boot. No physical device or host firmware writes."}));
        return directory;
    }
}
