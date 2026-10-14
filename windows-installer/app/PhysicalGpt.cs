using System.Buffers.Binary;
using System.IO;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

// Windows PartitionNumber may survive deletion/recreation and differ from the
// GPT entry ordinal. Firmware's HD() path needs the latter. Bind by GUID/range.
internal sealed class PhysicalGpt(byte[] table)
{
    private readonly byte[] entries=table;
    internal static PhysicalGpt Read(FileStream bound,long capacity,Guid diskId)
    {
        // Use an independent read-only handle with no managed read-ahead: a
        // buffered 512-byte read of the last sector can extend beyond the disk.
        // Do not mix positional reads with the writer's buffered file position.
        var device=NativeMediaDevice.Read(bound.SafeFileHandle);
        using var handle=NativeMediaIo.OpenReadOnlyDisk(device.Number);
        if(device.Size!=capacity || NativeMediaDevice.Read(handle)!=device)throw new IOException("GPT read device binding changed.");
        using var disk=new FileStream(handle,FileAccess.Read,1,false);
        byte[] At(long offset,int size)
        {
            if(offset<0 || offset>capacity || size>capacity-offset)throw new IOException("GPT read outside disk.");
            var bytes=new byte[size];disk.Position=offset;disk.ReadExactly(bytes);
            return bytes;
        }
        var primary=At(512,512);var backup=At(capacity-512,512);
        bool Header(byte[] h,ulong current,ulong other)=>h.AsSpan(0,8).SequenceEqual("EFI PART"u8)
            && BitConverter.ToUInt32(h,12)==92 && BitConverter.ToUInt64(h,24)==current && BitConverter.ToUInt64(h,32)==other
            && new Guid(h.AsSpan(56,16))==diskId && BitConverter.ToUInt32(h,80)==128 && BitConverter.ToUInt32(h,84)==128;
        if(capacity%512!=0 || !Header(primary,1,(ulong)(capacity/512-1)) || !Header(backup,(ulong)(capacity/512-1),1)
            || BitConverter.ToUInt64(primary,72)!=2 || BitConverter.ToUInt64(backup,72)!=(ulong)(capacity/512-33)
            || !primary.AsSpan(40,32).SequenceEqual(backup.AsSpan(40,32)))
            throw new IOException("Unsupported or inconsistent physical GPT headers; refuse layout mutation.");
        var table=At(1024,128*128);
        if(!table.SequenceEqual(At(capacity-33*512,128*128)))throw new IOException("Physical GPT primary/backup entries differ.");
        return new(table);
    }
    private static bool Matches(ReadOnlySpan<byte> entry,Guid type,Guid id,long offset,long size,ulong attributes,string name)
        =>new Guid(entry[..16])==type && new Guid(entry.Slice(16,16))==id
        && offset>=0 && size>0 && offset%512==0 && size%512==0
        && BinaryPrimitives.ReadUInt64LittleEndian(entry[32..])==(ulong)(offset/512)
        && BinaryPrimitives.ReadUInt64LittleEndian(entry[40..])==(ulong)(offset/512+size/512-1)
        && BinaryPrimitives.ReadUInt64LittleEndian(entry[48..])==attributes
        && Encoding.Unicode.GetString(entry[56..]).TrimEnd('\0')==name;

    internal void RequireNativePrefix(byte[] native)
    {
        var count=checked((int)BitConverter.ToUInt32(native,4));
        if(count>128 || native.Length<48+144*count)throw new IOException("Invalid native GPT prefix.");
        for(var i=0;i<128;i++)
        {
            var entry=entries.AsSpan(i*128,128);
            if(i>=count)
            {
                if(entry.ContainsAnyExcept((byte)0))throw new IOException("Non-packed GPT entries require a separate reviewed plan; refuse before writing.");
                continue;
            }
            var at=48+i*144;
            if(!Matches(entry,new Guid(native.AsSpan(at+32,16)),new Guid(native.AsSpan(at+48,16)),
                BitConverter.ToInt64(native,at+8),BitConverter.ToInt64(native,at+16),BitConverter.ToUInt64(native,at+64),
                Encoding.Unicode.GetString(native,at+72,72).TrimEnd('\0')))
                throw new IOException("Native array order differs from on-disk GPT slots; refuse before writing.");
        }
    }
    internal void RequireAppended(PhysicalGpt previous,int originalCount,PreparedPartition[] added)
    {
        if(originalCount<0 || originalCount+added.Length>128
            || !entries.AsSpan(0,originalCount*128).SequenceEqual(previous.entries.AsSpan(0,originalCount*128)))
            throw new IOException("Existing on-disk GPT entries changed after append.");
        for(var i=0;i<added.Length;i++)
        {
            var p=added[i];
            if(!Matches(entries.AsSpan((originalCount+i)*128,128),p.Type,p.Id,p.Offset,p.Size,p.Attributes,p.Name))
                throw new IOException("Appended on-disk GPT identity/range differs: "+p.Name);
        }
        if(entries.AsSpan((originalCount+added.Length)*128).ContainsAnyExcept((byte)0))
            throw new IOException("Unexpected extra on-disk GPT entry after append.");
    }
    internal void RequireSame(PhysicalGpt expected)
    {
        if(!entries.SequenceEqual(expected.entries))throw new IOException("On-disk GPT changed before append.");
    }
    internal PreparedPartition ForFirmware(PreparedPartition partition)
    {
        var matches=Enumerable.Range(0,128).Where(i=>new Guid(entries.AsSpan(i*128+16,16))==partition.Id).ToArray();
        if(matches.Length!=1 || !Matches(entries.AsSpan(matches[0]*128,128),partition.Type,partition.Id,
            partition.Offset,partition.Size,partition.Attributes,partition.Name))throw new IOException("Firmware partition does not match actual GPT.");
        return partition with{Number=matches[0]+1};
    }
}
