using System.Buffers.Binary;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public static class PhysicalPlanningChecks
{
    public static string Run()
    {
        var events=new List<string>();
        void Require(bool value,string name){if(!value)throw new IOException(name);events.Add(name);}
        void Refuse(Action action,string name){try{action();}catch(Exception e)when(e is IOException or InvalidOperationException){events.Add(name);return;}throw new IOException("Accepted: "+name);}
        const long gib=1073741824,mib=1048576;
        var json=PartitionInventory.ExampleJson;var gap=DiskPlanning.FreeSpaces(json).Single();
        var selection=new PartitionSelection(json,false,gap.Disk,gap.Start,64*gib);
        var parts=PreparedDisk.Roles.Select((name,i)=>new PreparedPartition(i+1,name,
            Guid.Parse(i==0?"c12a7328-f81f-11d2-ba4b-00a0c93ec93b":"ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"),Guid.NewGuid(),mib+i*8*gib,8*gib,0)).ToArray();
        var image=new PreparedDisk(Guid.NewGuid(),80*gib,parts);
        var plan=PhysicalInstallation.Plan(selection,InstallationTargetKind.InternalShared,image);
        Require(plan.Added[0].Offset==gap.Start && plan.Added[^1].Offset+plan.Added[^1].Size==gap.Start+64*gib,"only-selected-gap");
        Require(plan.Added.Select(p=>p.Id).SequenceEqual(parts.Select(p=>p.Id)),"boot-reference-GUIDs-preserved");
        Require(plan.Added.All(p=>plan.Preserved.All(q=>!PhysicalInstallation.Overlap(p.Offset,p.Size,q.Offset,q.Size))),"existing-partitions-protected");
        var legacyJson=JsonSerializer.Serialize(new {selection.Snapshot,selection.Example,selection.Disk,selection.Start,selection.Capacity});
        var legacySelection=JsonSerializer.Deserialize<PartitionSelection>(legacyJson)!;
        Require(!legacySelection.AlignRight && legacySelection.Target().Start==gap.Start,"legacy-selection-without-placement-keeps-left");
        var rightSelection=selection with {AlignRight=true};var rightTarget=rightSelection.Target();
        Require(rightTarget.Start==gap.Start+gap.Size-selection.Capacity && rightTarget.Start% mib==0 && rightTarget.Start+rightTarget.Size==gap.Start+gap.Size,"right-target-ends-at-exact-gap-boundary");
        Require(JsonSerializer.Deserialize<PartitionSelection>(JsonSerializer.Serialize(rightSelection))==rightSelection,"right-placement-survives-request-and-recovery-serialization");
        var rightAfter=PartitionInventory.After(rightSelection);var rightNew=rightAfter.Where(p=>p.Action=="new").ToArray();
        Require(rightNew.Length==8 && rightNew[0].Start==rightTarget.Start && rightNew[^1].Start+rightNew[^1].Size==gap.Start+gap.Size,"right-preview-contains-all-eight-steamos-partitions");
        Require(rightAfter.Any(p=>p.Action=="free" && p.Start==gap.Start && p.Size==gap.Size-selection.Capacity),"right-preview-shows-left-unallocated-remainder");
        Require(rightNew.Single(p=>p.Name=="home").Size==(long)(39.625*gib),"right-64g-retains-home-capacity");
        var rightPlan=PhysicalInstallation.Plan(rightSelection,InstallationTargetKind.InternalShared,image);
        Require(rightPlan.Preserved.SequenceEqual(plan.Preserved) && rightPlan.Added[0].Offset==rightTarget.Start && rightPlan.Added[^1].Offset+rightPlan.Added[^1].Size==gap.Start+gap.Size,"right-physical-plan-protects-existing-and-uses-reservation");
        var rightNative=PhysicalGptChecks.Native(rightPlan);var rightEncoded=PhysicalInstallation.EncodeAppend(rightNative,rightPlan);
        PhysicalInstallation.RequireLayout(rightPlan,NativeMediaDevice.ParseLayout(rightEncoded,rightTarget.DiskSize),true);events.Add("right-native-encoding-and-full-layout-check");
        Refuse(()=>PhysicalInstallation.EncodeAppend(rightNative,rightPlan with {Added=rightPlan.Added.Select((p,i)=>i==0?p with {Offset=gap.Start}:p).ToArray()}),"right-native-rejects-write-in-unused-left-region");
        var rightFormat=RemainingSpaceFormat.Plan(rightSelection);
        Require(rightFormat.Start==gap.Start && rightFormat.Size==gap.Size-selection.Capacity && rightFormat.Start+rightFormat.Size==rightTarget.Start,"right-format-plan-uses-only-left-remainder");
        var rightRequest=new RemainingFormatRequest(rightSelection with {Example=true},"en-US");
        var rightFormatted=RemainingSpaceFormat.Simulate(rightRequest);
        RemainingSpaceFormat.ValidateFormattedSnapshot(rightFormatted,true,rightRequest);events.Add("right-formatted-snapshot-validates-preserved-reservation");
        Refuse(()=>(rightRequest.Selection with {Snapshot=rightFormatted}).Target(),"right-format-does-not-reuse-now-occupied-original-gap-start");
        Require((rightRequest.Selection with {Snapshot=rightFormatted,Start=rightTarget.Start}).Target().Start==rightTarget.Start,"right-format-rebinds-selection-to-preserved-gap");
        Require((selection with {AlignRight=true,Capacity=gap.Size}).Target().Start==gap.Start,"right-all-space-equals-left");
        Refuse(()=>RemainingSpaceFormat.Plan(selection with {AlignRight=true,Capacity=gap.Size}),"right-all-space-has-no-ntfs-remainder");
        Refuse(()=>PhysicalInstallation.Plan(selection with {Capacity=100*gib},InstallationTargetKind.InternalShared,image),"64g-image-cannot-silently-install-as-100g");
        foreach (var capacity in new[] {100*gib, gap.Size})
        {
            var expanded = image with {Size=capacity+16*gib, Partitions=parts.Select(p=>p.Name=="home"?p with {Size=p.Size+capacity-64*gib}:p).ToArray()};
            var larger = PhysicalInstallation.Plan(selection with {Capacity=capacity},InstallationTargetKind.InternalShared,expanded);
            Require(larger.Required==capacity && larger.Added[^1].Offset+larger.Added[^1].Size==gap.Start+capacity,"physical-capacity-matches-selection-"+capacity);
            Require(larger.Preserved.SequenceEqual(plan.Preserved),"larger-plan-preserves-existing-partitions-"+capacity);
        }
        Refuse(()=>PhysicalInstallation.Plan(selection with{Example=true},InstallationTargetKind.InternalShared,image),"example-refused");
        Refuse(()=>PhysicalInstallation.Plan(selection with{Start=mib},InstallationTargetKind.InternalShared,image),"existing-partition-refused");
        Refuse(()=>PhysicalInstallation.Plan(selection,InstallationTargetKind.ExternalDisk,image),"internal-disk-refused-as-external");
        var duplicate=image with{Partitions=parts.Select((p,i)=>i==0?p with{Id=plan.Preserved[0].Id}:p).ToArray()};
        Refuse(()=>PhysicalInstallation.Plan(selection,InstallationTargetKind.InternalShared,duplicate),"duplicate-existing-partuuid-refused");
        var before=new NativeLayout(1,plan.DiskId,plan.Preserved);PhysicalInstallation.RequireLayout(plan,before,false);events.Add("original-layout-accepted");
        Refuse(()=>PhysicalInstallation.RequireLayout(plan,before with{DiskId=Guid.NewGuid()},false),"changed-disk-refused");
        Refuse(()=>PhysicalInstallation.RequireLayout(plan,before with{Partitions=plan.Preserved[..^1]},false),"missing-protected-partition-refused");
        var native=PhysicalGptChecks.Native(plan);
        var appended=PhysicalInstallation.EncodeAppend(native,plan);
        Require(native.AsSpan(48).SequenceEqual(appended.AsSpan(48,native.Length-48)),"native-existing-entry-bytes-preserved");
        var esp=plan.Added[0];var option=FirmwareBoot.LoadOption(esp);
        var pathLength=BinaryPrimitives.ReadUInt16LittleEndian(option.AsSpan(4));var start=option.Length-pathLength;
        Require(new Guid(option.AsSpan(start+24,16))==esp.Id && BinaryPrimitives.ReadUInt64LittleEndian(option.AsSpan(start+8))==(ulong)(esp.Offset/512),"UEFI-partition-identity-and-offset");
        Require(option[^4]==0x7f && option[^3]==0xff && option[^2]==4,"UEFI-device-path-terminated");
        events.AddRange(PhysicalGptChecks.Run());
        return JsonSerializer.Serialize(new{passed=true,events,scope="Pure planning and firmware serialization; no disk or firmware mutation"},new JsonSerializerOptions{WriteIndented=true});
    }
}
