using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class PreparedCapacityChecks
{
    internal static async Task<string> RunAsync()
    {
        var directory = Path.Combine(InstallationController.Work, "capacity-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var original = Path.Combine(directory, "original.img");
        var seed = Path.Combine(directory, "blank.qcow2");
        var events = new List<string>();
        var token = CancellationToken.None;
        await Backend.ProcessAsync(Path.Combine(Backend.Root,"runtime/qemu-min/qemu-img.exe"), ["create","-f","qcow2",seed,"80G"], _=>{},token);
        await RawImageStaging.ConvertAsync(seed,original,_=>{},token);
        await Backend.GuestAsync("capacity-check",original,true,_=>{},token,selection:"{\"mode\":\"create\"}");
        var session = Path.Combine(directory,"session"); Directory.CreateDirectory(session);
        MediaSource identity;
        using (var source = new PreparedDiskImage(original)) identity = source.Identity;
        var same = await PreparedCapacity.ExpandAsync(original,session,64*PartitionInventory.GiB,_=>{},token);
        if(same!=original) throw new IOException("64G unexpectedly copied the matching source.");
        events.Add("64g-existing-layout-kept");
        var expanded = await PreparedCapacity.ExpandAsync(original,session,100*PartitionInventory.GiB,_=>{},token);
        if(expanded==original) throw new IOException("Selected source was modified in place.");
        using(var source=new PreparedDiskImage(original)) if(source.Identity!=identity) throw new IOException("Original source changed.");
        events.Add("selected-source-immutable");
        await Backend.GuestAsync("capacity-check",expanded,true,_=>{},token,selection:JsonSerializer.Serialize(new{mode="verify",capacity=100*PartitionInventory.GiB}));
        events.Add("100g-real-gpt-and-ext4-growth-data-preserved");
        var fractional=100*PartitionInventory.GiB+512*PartitionInventory.MiB;
        await PreparedCapacity.ExpandAsync(expanded,session,fractional,_=>{},token);
        await Backend.GuestAsync("capacity-check",expanded,true,_=>{},token,selection:JsonSerializer.Serialize(new{mode="verify",capacity=fractional}));
        events.Add("fractional-all-space-capacity-gpt-and-ext4-growth");
        File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new {passed=true,events,scope="Actual GPT/ext4 resize in offline QEMU on new sparse fixture, source immutability and data preservation; no host disk writes or physical boot test."},new JsonSerializerOptions{WriteIndented=true}));
        return directory;
    }
}
