using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Text.Json;

namespace OxpInstaller;

internal static class PhysicalGptChecks
{
    internal static byte[] Native(PhysicalPlan plan, NativePartition[]? records=null)
    {
        records ??= plan.Preserved;
        var bytes=new byte[48+144*records.Length];
        BinaryPrimitives.WriteUInt32LittleEndian(bytes,1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4),(uint)records.Length);
        plan.DiskId.TryWriteBytes(bytes.AsSpan(8));
        BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(24),1048576);
        BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(32),plan.Selection.Target().DiskSize-2097152);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(40),128);
        for(var i=0;i<records.Length;i++)
        {
            var p=records[i];var at=48+i*144;
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(at),1);
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(at+8),p.Offset);
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(at+16),p.Size);
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(at+24),(uint)p.Number);
            Guid.Parse(p.Type).TryWriteBytes(bytes.AsSpan(at+32));p.Id.TryWriteBytes(bytes.AsSpan(at+48));
            BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(at+64),0x8000000000000001);
            Encoding.Unicode.GetBytes("保留分区 "+p.Number).CopyTo(bytes,at+72);
        }
        return bytes;
    }

    internal static PhysicalPlan SparsePlan()
    {
        const long mib=1048576,gib=1073741824;
        var numbers=new[]{1,2,3,15,16};
        var offsets=new[]{mib,65*mib,129*mib,400*gib,410*gib};
        var basic=Guid.Parse("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7");
        var json=JsonSerializer.Serialize(new[]{new{number=0,model="Sparse OEM fixture",size=512*gib,bus="NVMe",style="GPT",guid=Guid.NewGuid(),sectorSize=512,isBoot=true,isSystem=true,isOffline=false,isReadOnly=false,
            partitions=numbers.Select((n,i)=>new{number=n,guid=Guid.NewGuid(),offset=offsets[i],size=64*mib,gptType=basic,type="Basic",filesystem="",letter="",label="OEM",isBoot=false,free=0})}});
        var gap=DiskPlanning.FreeSpaces(json).First();
        var parts=PreparedDisk.Roles.Select((name,i)=>new PreparedPartition(i+1,name,basic,Guid.NewGuid(),mib+i*8*gib,8*gib,0)).ToArray();
        return PhysicalInstallation.Plan(new(json,false,0,gap.Start,64*gib),InstallationTargetKind.InternalShared,new(Guid.NewGuid(),80*gib,parts));
    }

    internal static string[] Run()
    {
        var events=new List<string>();
        void Require(bool value,string name){if(!value)throw new IOException(name);events.Add(name);}
        void Refuse(Action action,string name){try{action();}catch(IOException){events.Add(name);return;}throw new IOException("Accepted: "+name);}
        var plan=SparsePlan();var native=Native(plan);var saved=native.ToArray();
        var appended=PhysicalInstallation.EncodeAppend(native,plan);
        Require(plan.Preserved.Select(p=>p.Number).SequenceEqual(new[]{1,2,3,15,16}),"g3e-sparse-windows-numbers");
        Require(plan.Added.Select(p=>p.Number).SequenceEqual(Enumerable.Range(4,8)),"new-windows-identifiers-use-free-numbers");
        Require(BitConverter.ToUInt32(appended,4)==13 && appended.Length==48+13*144,"native-record-count-is-five-plus-eight");
        Require(native.SequenceEqual(saved) && native.AsSpan(48).SequenceEqual(appended.AsSpan(48,native.Length-48)),"all-existing-native-record-bytes-preserved");
        Require(new Guid(appended.AsSpan(48+5*144+48,16))==plan.Added[0].Id,"esp-appended-after-fifth-record-not-windows-number-four");
        PhysicalInstallation.RequireLayout(plan,NativeMediaDevice.ParseLayout(appended,plan.Selection.Target().DiskSize),true);
        events.Add("encoded-result-matches-entire-reviewed-layout");
        var reversed=Native(plan,plan.Preserved.Reverse().ToArray());
        var reversedResult=PhysicalInstallation.EncodeAppend(reversed,plan);
        Require(reversed.AsSpan(48).SequenceEqual(reversedResult.AsSpan(48,reversed.Length-48)),"native-array-order-independent-of-number-and-offset");
        var flagged=Native(plan);flagged[48+28]=1;flagged[48+29]=1;flagged[48+4]=37;
        var expected=flagged.ToArray();expected[48+28]=0;
        Require(PhysicalInstallation.EncodeAppend(flagged,plan).AsSpan(48,flagged.Length-48).SequenceEqual(expected.AsSpan(48)),"service-ordinal-name-attributes-preserved-only-rewrite-cleared");
        void BadPlan(PreparedPartition p,string name)=>Refuse(()=>PhysicalInstallation.EncodeAppend(native,plan with{Added=plan.Added.Select((x,i)=>i==0?p:x).ToArray()}),name);
        BadPlan(plan.Added[0] with{Number=15},"existing-number-conflict-refused");
        BadPlan(plan.Added[0] with{Number=plan.Added[1].Number},"duplicate-new-number-refused");
        BadPlan(plan.Added[0] with{Id=plan.Preserved[0].Id},"existing-guid-conflict-refused");
        BadPlan(plan.Added[0] with{Id=plan.Added[1].Id},"duplicate-new-guid-refused");
        BadPlan(plan.Added[0] with{Offset=plan.Preserved[2].Offset},"protected-range-overlap-refused");
        BadPlan(plan.Added[0] with{Offset=plan.Added[1].Offset},"new-range-overlap-refused");
        BadPlan(plan.Added[0] with{Size=long.MaxValue},"overflow-sized-range-refused");
        BadPlan(plan.Added[0] with{Offset=plan.Added[0].Offset+1},"unaligned-range-refused");
        BadPlan(plan.Added[0] with{Offset=plan.Selection.Start+plan.Selection.Capacity},"outside-reviewed-capacity-refused");
        BadPlan(plan.Added[0] with{Id=Guid.Empty},"empty-guid-refused");
        var truncated=native[..^1];Refuse(()=>PhysicalInstallation.EncodeAppend(truncated,plan),"truncated-native-array-refused");
        var full=native.ToArray();BinaryPrimitives.WriteUInt32LittleEndian(full.AsSpan(40),12);
        Refuse(()=>PhysicalInstallation.EncodeAppend(full,plan),"native-max-partition-count-enforced");
        var changed=native.ToArray();Guid.NewGuid().TryWriteBytes(changed.AsSpan(48+48));
        Refuse(()=>PhysicalInstallation.EncodeAppend(changed,plan),"changed-original-guid-refused-before-encoding");
        var duplicate=native.ToArray();native.AsSpan(48+48,16).CopyTo(duplicate.AsSpan(48+144+48));
        Refuse(()=>NativeMediaDevice.ParseLayout(duplicate,plan.Selection.Target().DiskSize),"native-duplicate-guid-refused");
        byte[] Gpt(byte[] records)
        {
            var table=new byte[128*128];
            for(var i=0;i<BitConverter.ToUInt32(records,4);i++)
            {
                var at=48+i*144;var dest=i*128;
                records.AsSpan(at+32,32).CopyTo(table.AsSpan(dest));
                var offset=BitConverter.ToInt64(records,at+8);var size=BitConverter.ToInt64(records,at+16);
                BinaryPrimitives.WriteUInt64LittleEndian(table.AsSpan(dest+32),(ulong)(offset/512));
                BinaryPrimitives.WriteUInt64LittleEndian(table.AsSpan(dest+40),(ulong)((offset+size)/512-1));
                records.AsSpan(at+64,80).CopyTo(table.AsSpan(dest+48));
            }
            return table;
        }
        var oldTable=Gpt(native);var newTable=Gpt(appended);var oldGpt=new PhysicalGpt(oldTable);var newGpt=new PhysicalGpt(newTable);
        oldGpt.RequireNativePrefix(native);newGpt.RequireAppended(oldGpt,5,plan.Added);
        Require(newGpt.ForFirmware(plan.Added[0]).Number==6,"firmware-uses-gpt-slot-not-windows-identifier");
        Refuse(()=>oldGpt.RequireNativePrefix(reversed),"physical-native-to-gpt-slot-mismatch-refused-before-write");
        var hole=oldTable.ToArray();oldTable.AsSpan(4*128,128).CopyTo(hole.AsSpan(14*128));hole.AsSpan(4*128,128).Clear();
        Refuse(()=>new PhysicalGpt(hole).RequireNativePrefix(native),"nonpacked-physical-gpt-refused-before-write");
        var changedOld=newTable.ToArray();changedOld[48]^=1;
        Refuse(()=>new PhysicalGpt(changedOld).RequireAppended(oldGpt,5,plan.Added),"original-gpt-attribute-change-detected-after-append");
        Refuse(()=>new PhysicalGpt(changedOld).RequireSame(newGpt),"gpt-mutation-between-review-and-write-refused");
        var changedNew=newTable.ToArray();changedNew[5*128+48]^=1;
        Refuse(()=>new PhysicalGpt(changedNew).RequireAppended(oldGpt,5,plan.Added),"new-gpt-attribute-change-detected");
        Refuse(()=>newGpt.ForFirmware(plan.Added[0] with{Size=512}),"firmware-range-mismatch-refused");
        var repeated=newTable.ToArray();newTable.AsSpan(5*128,128).CopyTo(repeated.AsSpan(20*128));
        Refuse(()=>new PhysicalGpt(repeated).ForFirmware(plan.Added[0]),"firmware-duplicate-guid-refused");
        return events.ToArray();
    }
}
