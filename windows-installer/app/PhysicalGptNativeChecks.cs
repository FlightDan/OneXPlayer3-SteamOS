using System.Buffers.Binary;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public static partial class PhysicalInstallation
{
    // Only this new receipted VHD can be mutated. No supplied device number,
    // physical installation, formatting or firmware writes.
    internal static async Task<string> CheckSparseGptOwnedAsync()
    {
        const long mib=1048576,gib=1073741824;
        var directory=Path.Combine(InstallationController.Work,"gpt-sparse-check-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);var path=Path.Combine(directory,"media.vhd");
        var linux=Guid.Parse("0fc63daf-8483-4772-8e79-3d69d8477de4");
        var parts=Enumerable.Range(1,16).Select(n=>new PreparedPartition(n,"Preserved "+n,linux,Guid.NewGuid(),
            n<15?n*2*mib:(n==15?100*gib:102*gib),mib,0x8000000000000000)).ToArray();
        var prepared=new PreparedDisk(Guid.NewGuid(),128*gib,parts);
        var keep=parts.Where(p=>p.Number<=3 || p.Number>=15).ToArray();
        var events=new List<string>();Guid owner;PhysicalPlan plan;
        using(var disk=new VirtualMediaDisk(path,prepared.Size))
        {
            owner=disk.Id;OwnedPartitionLayout.Initialize(disk,prepared,parts);
            using var raw=disk.OpenDevice();
            var original=NativeMediaIo.Query(raw.SafeFileHandle,0x70050,1024*1024,48);
            // Remove only empty fixture records 4..14; Windows retains 15/16.
            var sparse=new byte[48+keep.Length*144];original.AsSpan(0,48).CopyTo(sparse);
            BinaryPrimitives.WriteUInt32LittleEndian(sparse.AsSpan(4),(uint)keep.Length);
            for(var i=0;i<keep.Length;i++)original.AsSpan(48+(keep[i].Number-1)*144,144).CopyTo(sparse.AsSpan(48+i*144));
            Control(raw.SafeFileHandle,0x7c054,sparse);raw.Flush(true);Control(raw.SafeFileHandle,0x70140);
            // Let Windows finish arrival/removal of this newly initialized test
            // disk before seeding protected data. Production partitions preexist.
            await Task.Delay(1500);
            var before=NativeMediaIo.Query(raw.SafeFileHandle,0x70050,1024*1024,48);
            var layout=NativeMediaDevice.ReadLayout(raw.SafeFileHandle,disk.Size);
            if(!layout.Partitions.Select(p=>p.Number).SequenceEqual(new[]{1,2,3,15,16}))throw new IOException("Fixture did not retain sparse Windows partition numbers.");
            var gpt=PhysicalGpt.Read(raw,disk.Size,prepared.Id);gpt.RequireNativePrefix(before);
            events.Add("actual-windows-1-2-3-15-16-with-packed-gpt-1-through-5");
            foreach(var p in keep){raw.Position=p.Offset;var sentinel=new byte[1024*1024];Array.Fill(sentinel,(byte)(p.Number+90));raw.Write(sentinel);}raw.Flush(true);
            foreach(var p in keep){raw.Position=p.Offset;var sentinel=new byte[1024*1024];raw.ReadExactly(sentinel);if(sentinel.Any(b=>b!=p.Number+90))
            {
                using var independent=NativeMediaIo.OpenReadOnlyDisk(disk.BoundDiskNumber());
                using var probe=new FileStream(independent,FileAccess.Read,1,false);probe.Position=p.Offset;var sector=new byte[512];probe.ReadExactly(sector);
                var scan=new List<string>();for(var j=0;j<32;j++){probe.Position=j*mib;var block=new byte[512];probe.ReadExactly(block);if(block[0]!=0)scan.Add(j+":"+block[0]);}
                throw new IOException("Seed sentinel differs before append: "+p.Number+" actual="+Convert.ToHexString(sentinel.AsSpan(0,16))+" independent="+Convert.ToHexString(sector.AsSpan(0,16))+" mismatches="+sentinel.Count(b=>b!=p.Number+90)+" position="+raw.Position+" scan="+string.Join(',',scan));
            }}
            var snapshot=JsonSerializer.Serialize(new[]{new{number=disk.BoundDiskNumber(),model="Owned sparse VHD",size=disk.Size,bus="NVMe",style="GPT",guid=prepared.Id,sectorSize=512,isBoot=false,isSystem=false,isOffline=false,isReadOnly=false,
                partitions=keep.Select(p=>new{number=p.Number,guid=p.Id,offset=p.Offset,size=p.Size,gptType=p.Type,type="Unknown",filesystem="",letter="",label=p.Name,isBoot=false,free=0})}});
            var gap=DiskPlanning.FreeSpaces(snapshot).First();
            var source=PreparedDisk.Roles.Select((name,i)=>new PreparedPartition(i+1,name,i==0?Guid.Parse("c12a7328-f81f-11d2-ba4b-00a0c93ec93b"):
                i<3?Guid.Parse("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"):linux,Guid.NewGuid(),mib+i*8*gib,8*gib,0)).ToArray();
            plan=Plan(new(snapshot,false,disk.BoundDiskNumber(),gap.Start,64*gib),InstallationTargetKind.InternalShared,new(Guid.NewGuid(),80*gib,source));
            var encoded=EncodeAppend(before,plan);
            File.WriteAllBytes(Path.Combine(directory,"native-before.bin"),before);
            File.WriteAllBytes(Path.Combine(directory,"native-encoded.bin"),encoded);
            Control(raw.SafeFileHandle,0x7c054,encoded);raw.Flush(true);Control(raw.SafeFileHandle,0x70140);
            RequireLayout(plan,NativeMediaDevice.ReadLayout(raw.SafeFileHandle,disk.Size),true);
            var after=PhysicalGpt.Read(raw,disk.Size,prepared.Id);after.RequireAppended(gpt,keep.Length,plan.Added);
            events.Add("production-encoder-appends-eight-and-preserves-all-original-gpt-bytes");
            var firmware=after.ForFirmware(plan.Added[0]);
            if(firmware.Number!=6 || plan.Added[0].Number!=4)throw new IOException("Firmware did not use GPT slot 6 instead of Windows number 4.");
            var boot=FirmwareBoot.LoadOption(firmware);var start=boot.Length-BitConverter.ToUInt16(boot,4);
            if(BitConverter.ToUInt32(boot,start+4)!=6)throw new IOException("Wrong firmware HD() partition ordinal.");
            events.Add("firmware-serialization-uses-gpt-slot-six-not-windows-number-four");
            using var locks=PhysicalLocks.Acquire(plan,NativeMediaDevice.Read(raw.SafeFileHandle),raw.SafeFileHandle,
                ()=>{if(disk.BoundDiskNumber()!=plan.Selection.Disk)throw new IOException("Owned VHD binding changed.");});
            events.Add("production-selected-volume-discovery-lock-and-dismount");
            // Exercise the production copy/readback with a final partial block,
            // plus untouched sectors just before and after its selected range.
            var destination=plan.Added[3];var content=new byte[5*1024*1024+512];
            for(var i=0;i<content.Length;i++)content[i]=(byte)(i*29+7);
            var guard=new byte[512];Array.Fill(guard,(byte)0xd3);
            raw.Position=destination.Offset-512;raw.Write(guard);
            raw.Position=destination.Offset+content.Length;raw.Write(guard);raw.Flush(true);
            var sourcePath=Path.Combine(directory,"copy-source.bin");File.WriteAllBytes(sourcePath,content);
            using(var copySource=new FileStream(sourcePath,FileMode.Open,FileAccess.Read,FileShare.Read))
                await PartitionDeployment.CopyRangeAsync(copySource,raw,0,destination.Offset,content.Length,disk.Size,_=>{},CancellationToken.None);
            var readback=new byte[content.Length];raw.Position=destination.Offset;raw.ReadExactly(readback);
            if(!readback.SequenceEqual(content))throw new IOException("Partial-block native copy differs.");
            foreach(var offset in new[]{destination.Offset-512,destination.Offset+content.Length})
            {var sector=new byte[512];raw.Position=offset;raw.ReadExactly(sector);if(!sector.SequenceEqual(guard))throw new IOException("Copy crossed its selected range.");}
            events.Add("native-copy-and-readback-five-mib-plus-one-sector-preserves-both-boundaries");
            foreach(var p in keep){raw.Position=p.Offset;var sentinel=new byte[1024*1024];raw.ReadExactly(sentinel);if(sentinel.Any(b=>b!=p.Number+90))throw new IOException("Preserved data sentinel changed: "+p.Number+" actual="+Convert.ToHexString(sentinel.AsSpan(0,16)));}
            events.Add("all-five-protected-data-sentinels-unchanged");
            File.WriteAllText(Path.Combine(directory,"plan.json"),JsonSerializer.Serialize(plan));
        }
        using(var reopened=VirtualMediaDisk.ReopenOwned(path,prepared.Size,owner))
        using(var raw=reopened.OpenDevice())
        {
            var layout=NativeMediaDevice.ReadLayout(raw.SafeFileHandle,reopened.Size);
            var expected=plan.Preserved.Concat(plan.Added.Select(p=>p.Native)).OrderBy(p=>p.Offset).ToArray();
            if(layout.DiskId!=plan.DiskId || layout.Partitions.Length!=expected.Length
                || layout.Partitions.Any(p=>!expected.Any(q=>q.Id==p.Id && q.Offset==p.Offset && q.Size==p.Size && q.Type==p.Type)))throw new IOException("Reattached GPT identities/ranges changed.");
            foreach(var p in keep){raw.Position=p.Offset;var sentinel=new byte[1024*1024];raw.ReadExactly(sentinel);if(sentinel.Any(b=>b!=p.Number+90))throw new IOException("Reattached preserved sentinel changed.");}
            if(PhysicalGpt.Read(raw,reopened.Size,plan.DiskId).ForFirmware(plan.Added[0]).Number!=6)throw new IOException("Reattached firmware slot changed.");
            events.Add("detach-reattach-preserves-gpt-identities-ranges-data-and-firmware-slot");
        }
        File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new{passed=true,events,scope="Owned disposable VHD only; production native append, original GPT bytes and data, firmware serialization and reattach. No physical disk or firmware mutation."},new JsonSerializerOptions{WriteIndented=true}));
        return directory;
    }
}
