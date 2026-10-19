using System.Buffers.Binary;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace OxpInstaller;

internal static class Ext4HomeCopyChecks
{
    internal static async Task<string> RunAsync()
    {
        const long mib = 1048576, homeSize = 12 * mib, sourceStart = mib, targetStart = 2 * mib;
        var events = new List<string>();
        var directory = Path.Combine(InstallationController.Work, "home-copy-native-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        using var source = new FileStream(Path.Combine(directory, "source.bin"), FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None);
        using var target = new FileStream(Path.Combine(directory, "target.bin"), FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None);
        source.SetLength(sourceStart + homeSize); target.SetLength(targetStart + homeSize + mib);
        var seed = new byte[mib]; Array.Fill(seed, (byte)0xa7);
        for (long offset = 0; offset < target.Length; offset += seed.Length) target.Write(seed);
        target.Flush(true);
        var home = new PreparedPartition(8, "home", Guid.NewGuid(), Guid.NewGuid(), sourceStart, homeSize, 0);
        var super = new byte[1024];
        BinaryPrimitives.WriteUInt32LittleEndian(super.AsSpan(4), (uint)(homeSize / 4096));
        BinaryPrimitives.WriteUInt32LittleEndian(super.AsSpan(24), 2);
        BinaryPrimitives.WriteUInt16LittleEndian(super.AsSpan(56), 0xef53);
        BinaryPrimitives.WriteUInt16LittleEndian(super.AsSpan(58), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(super.AsSpan(96), 0x40);
        for (var i = 0; i < 16; i++) super[104 + i] = (byte)i;
        source.Position = sourceStart + 1024; source.Write(super);
        source.Position = sourceStart + 4 * mib + 111; source.WriteByte(0x69); source.Flush(true);
        var definition = new JsonObject
        {
            ["block_count"] = homeSize / 4096, ["block_size"] = 4096, ["features"] = new JsonArray("extent"),
            ["fs_uuid"] = "00010203-0405-0607-0809-0a0b0c0d0e0f", ["mode"] = "ext4-used-v1",
            ["partition_id"] = home.Id.ToString(), ["partition_offset"] = sourceStart, ["partition_size"] = homeSize,
            ["ranges"] = new JsonArray(new JsonArray(0L, 8192L), new JsonArray(4 * mib, 4 * mib + 4096)),
            ["schema"] = 1, ["used_bytes"] = 8192 + 4 * mib + 4096
        };
        string Marker(JsonObject value) => "OXP_HOME_COPY_PLAN=" + value.ToJsonString() + "\n";
        Ext4HomeCopyPlan Parse(JsonObject value) => Ext4HomeCopyPlan.FromTranscript(Marker(value), source, home);
        var plan = Parse(definition);
        if (plan.Profile.Digest != Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(definition.ToJsonString())))
            || Parse(definition).Profile != plan.Profile) throw new IOException("Home plan digest is unstable.");
        events.Add("deterministic-exact-plan-digest-and-rfc-uuid");
        void Refuse(Action action, string name)
        {
            try { action(); } catch (IOException) { events.Add(name); return; }
            throw new IOException("Accepted: " + name);
        }
        void Mutate(string name, Action<JsonObject> change)
        {
            var copy = (JsonObject)definition.DeepClone(); change(copy); Refuse(() => Parse(copy), name);
        }
        Refuse(() => Ext4HomeCopyPlan.FromTranscript(Marker(definition) + Marker(definition), source, home), "duplicate-marker-refused");
        Refuse(() => Ext4HomeCopyPlan.FromTranscript("", source, home), "missing-marker-refused");
        Mutate("unknown-schema-refused", value => value["schema"] = 2);
        Mutate("unknown-mode-refused", value => value["mode"] = "sparse-file-holes");
        Mutate("wrong-partition-refused", value => value["partition_id"] = Guid.NewGuid().ToString());
        Mutate("wrong-offset-refused", value => value["partition_offset"] = sourceStart + 512);
        Mutate("wrong-size-refused", value => value["partition_size"] = homeSize + 4096);
        Mutate("wrong-fs-uuid-refused", value => value["fs_uuid"] = Guid.NewGuid().ToString());
        Mutate("wrong-block-count-refused", value => value["block_count"] = homeSize / 4096 - 1);
        Mutate("wrong-accounting-refused", value => value["used_bytes"] = homeSize);
        Mutate("missing-field-refused", value => value.Remove("ranges"));
        Mutate("unknown-field-refused", value => value["surprise"] = true);
        Mutate("overlap-refused", value => value["ranges"] = new JsonArray(new JsonArray(0L, 8192L), new JsonArray(4096L, 4096L)));
        Mutate("out-of-bounds-refused", value => value["ranges"] = new JsonArray(new JsonArray(0L, 8192L), new JsonArray(homeSize - 4096, 8192L)));
        Mutate("unaligned-refused", value => value["ranges"] = new JsonArray(new JsonArray(0L, 8193L)));
        Mutate("full-mode-cannot-skip-free-ranges", value => value["mode"] = "full");
        Mutate("unsorted-features-refused", value => value["features"] = new JsonArray("metadata_csum", "extent"));
        var duplicate = Marker(definition).Replace("\"schema\":1", "\"schema\":1,\"schema\":1");
        Refuse(() => Ext4HomeCopyPlan.FromTranscript(duplicate, source, home), "duplicate-field-refused");
        source.Position = sourceStart + 1024 + 58; source.WriteByte(0); source.Flush();
        Refuse(() => Parse(definition), "dirty-superblock-refused");
        source.Position = sourceStart + 1024 + 58; source.WriteByte(1); source.Flush();

        var progress = new List<MediaProgress>();
        await PartitionDeployment.CopyRangesAsync(source, target, sourceStart, targetStart, homeSize, target.Length, plan.Ranges, progress.Add, CancellationToken.None);
        if (progress[^1].Written != plan.UsedBytes || progress[^1].Verified != plan.UsedBytes || progress.Any(p => p.Total != plan.UsedBytes))
            throw new IOException("Home copy progress counts logical partition size instead of selected bytes.");
        events.Add("write-readback-progress-uses-actual-bytes");
        byte At(long offset) { target.Position = offset; return (byte)target.ReadByte(); }
        if (At(targetStart + 8191) != 0 || At(targetStart + 8 * mib + 4095) != 0 || At(targetStart + 4 * mib + 111) != 0x69)
            throw new IOException("Allocated zero or nonzero data was not copied.");
        events.Add("allocated-zero-blocks-overwrite-nonzero-target-and-cross-buffer-boundary");
        if (At(targetStart + 2 * mib) != 0xa7 || At(targetStart + homeSize - 1) != 0xa7
            || At(targetStart - 1) != 0xa7 || At(targetStart + homeSize) != 0xa7)
            throw new IOException("Home copy altered omitted or protected bytes.");
        events.Add("free-data-and-protected-surroundings-remain-untouched");
        target.Position = targetStart + 2 * mib; target.WriteByte(0x55); target.Flush();
        await PartitionDeployment.CompareRangesAsync(source, target, sourceStart, targetStart, homeSize, target.Length, plan.Ranges, _ => { }, CancellationToken.None);
        events.Add("resume-accepts-only-free-data-difference");
        target.Position = targetStart + 8 * mib + 4095; target.WriteByte(0x55); target.Flush();
        var mismatch = false;
        try { await PartitionDeployment.CompareRangesAsync(source, target, sourceStart, targetStart, homeSize, target.Length, plan.Ranges, _ => { }, CancellationToken.None); }
        catch (CompletedRangeMismatchException error) { mismatch = error.Message.Contains((8 * mib + 4095).ToString()); }
        if (!mismatch) throw new IOException("Allocated data corruption was accepted on resume.");
        events.Add("resume-rejects-exact-late-allocated-byte-corruption");
        target.Position = targetStart; target.WriteByte(0xa7); target.Flush();
        using var cancel = new CancellationTokenSource(); cancel.Cancel(); var cancelled = false;
        try { await PartitionDeployment.CopyRangesAsync(source, target, sourceStart, targetStart, homeSize, target.Length, plan.Ranges, _ => { }, cancel.Token); }
        catch (OperationCanceledException) { cancelled = true; }
        if (!cancelled || At(targetStart) != 0xa7) throw new IOException("Cancelled home copy performed a content write.");
        events.Add("cancelled-before-first-content-write");
        var invalid = new[] { new CopyExtent(0, 4096), new CopyExtent(homeSize - 4096, 8192) }; var refused = false;
        try { await PartitionDeployment.CopyRangesAsync(source, target, sourceStart, targetStart, homeSize, target.Length, invalid, _ => { }, CancellationToken.None); }
        catch (IOException) { refused = true; }
        if (!refused || At(targetStart) != 0xa7) throw new IOException("Invalid later extent allowed an earlier write.");
        events.Add("all-extents-validated-before-first-write");
        await PartitionDeployment.CopyRangeAsync(source, target, sourceStart, targetStart, homeSize, target.Length, _ => { }, CancellationToken.None);
        if (At(targetStart + 2 * mib) != 0) throw new IOException("Legacy full copy changed behavior.");
        target.Position = targetStart + 2 * mib; target.WriteByte(0x55); target.Flush();
        mismatch = false;
        try { await PhysicalInstallation.CompareCompletedAsync(source, target, sourceStart, targetStart, homeSize, CancellationToken.None); }
        catch (CompletedRangeMismatchException) { mismatch = true; }
        if (!mismatch) throw new IOException("Legacy recovery stopped verifying free data.");
        events.Add("legacy-full-copy-and-recovery-preserve-complete-byte-semantics");
        var full = (JsonObject)definition.DeepClone(); full["mode"] = "full"; full["ranges"] = new JsonArray(new JsonArray(0L, homeSize)); full["used_bytes"] = homeSize;
        if (Parse(full).UsedBytes != homeSize) throw new IOException("Valid full fallback rejected.");
        events.Add("explicit-full-fallback-accepted");
        var snapshot = PartitionInventory.ExampleJson; var gap = DiskPlanning.FreeSpaces(snapshot).Single();
        var selection = new PartitionSelection(snapshot, false, gap.Disk, gap.Start, 64 * 1024 * mib);
        var parts = PreparedDisk.Roles.Select((name, i) => new PreparedPartition(i + 1, name,
            Guid.Parse("EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"), Guid.NewGuid(), mib + i * 8 * 1024 * mib, 8 * 1024 * mib, 0)).ToArray();
        var layout = new PreparedDisk(Guid.NewGuid(), 80 * 1024 * mib, parts);
        var physical = PhysicalInstallation.Plan(selection, InstallationTargetKind.InternalShared, layout);
        var identity = new MediaSource("fixture.img", layout.Size, 1, 1, 1, layout.Id);
        var native = new NativeDiskInfo(gap.Disk, gap.DiskSize, 512, 17, "", "", "", false);
        var legacy = new PhysicalRecoveryState(1, "incomplete", native, physical, identity, PreparedDisk.Roles[..7], "interrupted");
        PhysicalInstallation.ValidateRecovery(legacy, identity, physical, layout);
        var bound = legacy with { Schema = 2, HomeCopy = plan.Profile };
        var restored = JsonSerializer.Deserialize<PhysicalRecoveryState>(JsonSerializer.Serialize(bound))!;
        PhysicalInstallation.ValidateRecovery(restored, identity, physical, layout, plan.Profile);
        events.Add("legacy-and-new-recovery-journal-roundtrip");
        Refuse(() => PhysicalInstallation.ValidateRecovery(legacy, identity, physical, layout, plan.Profile), "legacy-cannot-acquire-optimized-contract");
        Refuse(() => PhysicalInstallation.ValidateRecovery(legacy with { HomeCopy = plan.Profile }, identity, physical, layout), "legacy-profile-injection-refused");
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound, identity, physical, layout), "new-recovery-cannot-lose-profile");
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound with { HomeCopy = null }, identity, physical, layout, plan.Profile), "new-recovery-missing-profile-refused");
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound, identity, physical, layout, plan.Profile with { Digest = new string('a', 64) }), "changed-plan-digest-refused");
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound, identity, physical, layout, plan.Profile with { Mode = "full" }), "changed-copy-mode-refused");
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound with { Schema = 3 }, identity, physical, layout, plan.Profile), "unknown-recovery-schema-refused");
        var invalidProfile = plan.Profile with { Mode = "future-mode" };
        Refuse(() => PhysicalInstallation.ValidateRecovery(bound with { HomeCopy = invalidProfile }, identity, physical, layout, invalidProfile), "unknown-profile-version-refused");
        var job = new PartitionJob(2, Guid.NewGuid().ToString("N"), "reviewed-physical-range", physical.Kind, identity, PhysicalPlan: physical, HomeCopy: plan.Profile);
        if (JsonSerializer.Deserialize<PartitionJob>(JsonSerializer.Serialize(job))!.HomeCopy != plan.Profile
            || JsonSerializer.Deserialize<PartitionJob>("{\"Schema\":1}")!.HomeCopy != null)
            throw new IOException("Job profile serialization broke legacy compatibility.");
        events.Add("new-job-profile-roundtrip-and-absent-legacy-field");
        var result = JsonSerializer.Serialize(new { passed = true, events, scope = "Native plan validation and bounded copy/readback/recovery on ordinary files prefilled with nonzero data; synthetic superblock only, no filesystem acceptance or physical disk writes." }, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(Path.Combine(directory, "result.json"), result); return result;
    }
}
