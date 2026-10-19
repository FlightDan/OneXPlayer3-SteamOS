using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;
public partial class App : Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Length > 0 && e.Args[0] == "--format-remaining-helper")
        {
            try { if (e.Args.Length != 2) throw new ArgumentException("Expected formatting request"); Shutdown(await RemainingSpaceFormat.ExecuteHelperAsync(e.Args[1])); }
            catch { Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--delete-partition-helper")
        {
            try { if (e.Args.Length != 2) throw new ArgumentException("Expected deletion request"); Shutdown(await PartitionDeletion.ExecuteHelperAsync(e.Args[1])); }
            catch { Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--partition-helper")
        {
            try
            {
                Shutdown(await InstallationLog.CaptureHelperAsync(async () =>
                {
                    if (e.Args.Length != 2) throw new ArgumentException("Expected partition job");
                    return await InstallationController.ExecuteHelperAsync(e.Args[1]);
                }));
            }
            catch { Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--usb-review-helper")
        {
            try { if (e.Args.Length != 2) throw new ArgumentException("Expected read-only USB job path"); Shutdown(await UsbNativeReview.ExecuteAsync(e.Args[1])); }
            catch { Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--media-helper")
        {
            try { if (e.Args.Length != 2) throw new ArgumentException("Expected media job path"); Shutdown(await MediaHelper.ExecuteAsync(e.Args[1])); }
            catch { Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--cli")
        {
            var log = new System.Text.StringBuilder();
            var resultFile = Path.Combine(Backend.Root, "logs/native-cli-result.txt");
            Directory.CreateDirectory(Path.GetDirectoryName(resultFile)!);
            try
            {
                if (e.Args.Length == 2 && e.Args[1] == "native-volume-checks") { log.AppendLine(NativeVolumeChecks.Run()); }
                else if (e.Args.Length == 2 && e.Args[1] == "process-checks") { log.AppendLine(await ProcessChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "installer-restart-checks") { log.AppendLine(await InstallerRestartChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "desktop-reboot-checks") { log.AppendLine(SteamOSDesktopChecks.Run()); }
                else if (e.Args.Length is 2 or 3 && e.Args[1] == "installation-progress-checks") { log.AppendLine(InstallationProgressChecks.Run(e.Args.Length == 3 ? e.Args[2] : null)); }
                else if (e.Args.Length == 2 && e.Args[1] == "official-system-progress-checks") { log.AppendLine(await OfficialSystemProgressChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "physical-recovery-checks") { log.AppendLine(await PhysicalRecoveryChecks.RunAsync()); }
                else if (e.Args.Length == 3 && e.Args[1] == "resume-physical")
                {
                    var recoveryLog = Path.Combine(InstallationController.Work,"physical-resume-"+Guid.NewGuid().ToString("N")+".log");
                    using var writer = new StreamWriter(new FileStream(recoveryLog,FileMode.CreateNew,FileAccess.Write,FileShare.Read)) { AutoFlush=true };
                    log.AppendLine("RECOVERY_LOG="+recoveryLog);
                    log.AppendLine("RECOVERED="+await InstallationController.ResumePhysicalAsync(e.Args[2],text=>writer.WriteLine(text),CancellationToken.None));
                }
                else if (e.Args.Length == 3 && e.Args[1] == "reviewed-install") { log.AppendLine("INSTALL_SESSION=" + await ReviewedInstallationCli.RunAsync(e.Args[2])); }
                else if (e.Args.Length == 2 && e.Args[1] == "capacity-checks") { log.AppendLine(await PreparedCapacityChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "workspace-checks") { log.AppendLine(await WorkspaceChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "installation-log-checks")
                {
                    var proof = Path.Combine(Backend.Root, "logs", "installation-log-checks-" + Guid.NewGuid().ToString("N"));
                    Directory.CreateDirectory(proof);
                    log.AppendLine(System.Text.Json.JsonSerializer.Serialize(new { passed = true, directory = proof, results = await InstallationLogChecks.RunAsync(proof) }));
                }
                else if (e.Args.Length == 2 && e.Args[1] == "secret-input-checks") { log.AppendLine(await SecretInputChecks.RunAsync()); }
                else if (e.Args.Length == 2 && e.Args[1] == "runtime-permission-checks") { log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"permissions\"}")); }
                else if (e.Args.Length == 2 && e.Args[1] == "startup-integration-checks") { log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"startup\"}")); }
                else if (e.Args.Length == 3 && e.Args[1] == "slot-switch-checks") { log.AppendLine(await Backend.GuestAsync("integration-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"slot-switch\"}")); }
                else if (e.Args.Length == 2 && e.Args[1] == "workspace-path") { log.AppendLine(InstallerWorkspace.DirectoryPath); }
                else if (e.Args.Length == 3 && e.Args[1] == "prepare-accepted-3.10") log.AppendLine("ACCEPTED_SOURCE="+await OfficialSystem.CheckPreparationAsync(e.Args[2],text=>log.AppendLine(text),CancellationToken.None));
                else if (e.Args.Length == 2 && e.Args[1] == "physical-gpt-native-checks") log.AppendLine("GPT_NATIVE_CHECK="+await PhysicalInstallation.CheckSparseGptOwnedAsync());
                else if (e.Args.Length == 2 && e.Args[1] == "physical-planning-checks") { var proof=PhysicalPlanningChecks.Run(); await File.WriteAllTextAsync(Path.Combine(Backend.Root,"logs/physical-planning-checks.json"),proof);log.AppendLine(proof); }
                else if (e.Args.Length == 3 && e.Args[1] == "physical-adapter-check") log.AppendLine("PHYSICAL_ADAPTER="+await PhysicalInstallation.CheckOwnedAsync(e.Args[2],text=>log.AppendLine(text),CancellationToken.None));
                else if (e.Args.Length == 3 && e.Args[1] == "physical-readiness") log.AppendLine(await Backend.GuestAsync("physical-readiness",e.Args[2],false,text=>log.Append(text),CancellationToken.None));
                else if (e.Args.Length == 4 && e.Args[1] == "upgrade-source") log.AppendLine(await Backend.GuestAsync("upgrade-source",e.Args[2],true,text=>log.Append(text),CancellationToken.None,updateRoot:e.Args[3]));
                else if (e.Args.Length == 3 && e.Args[1] == "inspect") log.AppendLine(await Backend.GuestAsync("inspect",e.Args[2],false,text=>log.Append(text),CancellationToken.None));
                else if (e.Args.Length == 2 && e.Args[1] == "component-outcome-checks") log.AppendLine(ComponentOutcomeChecks.Run());
                else if (e.Args.Length == 2 && e.Args[1] == "shared-storage-checks") log.AppendLine(SharedStorageChecks.Run());
                else if (e.Args.Length == 2 && e.Args[1] == "shared-storage-linux-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"shared-storage\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "desktop-language-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"desktop-language\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "maintenance-tool-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"maintenance-tool\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "log-spam-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"log-spam\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "home-ownership-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"home-ownership\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "component-skip-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None, selection: "{\"checks\":\"nonfatal\"}"));
                else if (e.Args.Length == 2 && e.Args[1] == "integration-checks") log.AppendLine(await Backend.GuestAsync("integration-check", null, false, text => log.Append(text), CancellationToken.None));
                else if (e.Args.Length == 2 && e.Args[1] == "integration-delta-checks") log.AppendLine(await Backend.GuestAsync("integration-delta-check", null, false, text => log.Append(text), CancellationToken.None));
                else if (e.Args.Length == 4 && e.Args[1] == "integration-image") log.AppendLine(await Backend.GuestAsync("integration", e.Args[2], true, text => log.Append(text), CancellationToken.None, selection: await File.ReadAllTextAsync(e.Args[3])));
                else if (e.Args.Length == 4 && e.Args[1] == "integration-verify") log.AppendLine(await Backend.GuestAsync("integration-verify", e.Args[2], false, text => log.Append(text), CancellationToken.None, selection: await File.ReadAllTextAsync(e.Args[3])));
                else if (e.Args.Length == 4 && e.Args[1] == "refind-image") log.AppendLine(await Backend.GuestAsync("refind-image", e.Args[2], true, text => log.Append(text), CancellationToken.None, selection: await File.ReadAllTextAsync(e.Args[3])));
                else if (e.Args.Length == 4 && e.Args[1] == "refind-boot") log.AppendLine("REFIND_BOOT="+await VirtualBoot.RefindImageAsync(e.Args[2],e.Args[3]=="windows-probe",e.Args[3]=="manual",text=>log.Append(text),CancellationToken.None));
                else if (e.Args.Length == 3 && e.Args[1] == "integration-boot") log.AppendLine("INTEGRATION_BOOT=" + await VirtualBoot.IntegratedImageAsync(e.Args[2], text => log.Append(text), CancellationToken.None));
                else if (e.Args.Length == 3 && e.Args[1] == "installation-controller-checks") log.AppendLine(await InstallationChecks.RunAsync(e.Args[2]));
                else if (e.Args.Length == 3 && e.Args[1] == "full-virtual-workflow-checks") log.AppendLine(await FullVirtualWorkflowChecks.RunAsync(e.Args[2]));
                else if (e.Args[1] == "native-partition-recovery-fixture" && e.Args.Length == 4)
                    log.AppendLine("RECOVERY_SESSION=" + await PartitionDeploymentChecks.RecoverySessionAsync(e.Args[2], Enum.Parse<InstallationTargetKind>(e.Args[3])));
                else if (e.Args[1] == "aria2-checks" && e.Args.Length == 2)
                    log.AppendLine("ARIA2_CHECKS=" + await AriaDownloadChecks.RunAsync());
                else if (e.Args[1] == "aria2-official-checks" && e.Args.Length == 2)
                    log.AppendLine("ARIA2_OFFICIAL_CHECKS=" + await AriaDownloadChecks.OfficialAsync());
                else if (e.Args[1] == "aria2-probe" && e.Args.Length == 3)
                    log.AppendLine(System.Text.Json.JsonSerializer.Serialize(await AriaDownload.ProbeAsync(e.Args[2], CancellationToken.None)));
                else if (e.Args[1] == "native-partition-recovery-checks" && e.Args.Length == 2)
                    log.AppendLine("RECOVERY_CHECKS=" + await PartitionDeploymentChecks.RecoveryAsync(text => log.AppendLine(text)));
                else if (e.Args[1] == "native-partition-crash" && e.Args.Length == 5)
                    await PartitionDeploymentChecks.CrashWriterAsync(e.Args[2], e.Args[3], Enum.Parse<InstallationTargetKind>(e.Args[4]));
                else if (e.Args[1] == "native-partition-checks" && e.Args.Length == 2)
                    log.AppendLine("PARTITION_CHECKS=" + await PartitionDeploymentChecks.RunAsync(text => log.AppendLine(text)));
                else if (e.Args[1] == "native-partition-deploy" && e.Args.Length == 4)
                {
                    var kind = e.Args[3] switch { "internal" => InstallationTargetKind.InternalShared, "external" => InstallationTargetKind.ExternalDisk,
                        _ => throw new ArgumentException("Expected internal or external target kind") };
                    log.AppendLine("PARTITION_PROOF=" + await PartitionDeploymentChecks.FullAsync(e.Args[2], kind, text => { lock (log) log.AppendLine(text); }, CancellationToken.None));
                }
                else if (e.Args[1] == "native-partition-stage" && e.Args.Length == 4)
                {
                    var kind = e.Args[3] switch { "internal" => InstallationTargetKind.InternalShared, "external" => InstallationTargetKind.ExternalDisk,
                        _ => throw new ArgumentException("Expected internal or external target kind") };
                    log.AppendLine("PARTITION_PROOF=" + await PartitionDeploymentChecks.PreparedAsync(e.Args[2], kind, text => { lock (log) log.AppendLine(text); }, CancellationToken.None));
                }

                else if (e.Args[1] == "native-vhd-smoke") log.AppendLine("VHD_SMOKE=" + MediaWriterChecks.NativeVhdSmoke());
                else if (e.Args[1] == "native-media-write" && e.Args.Length is 3 or 4)
                    { if (e.Args.Length == 4 && e.Args[3] != "cancel") throw new ArgumentException("Expected cancel or no mode"); log.AppendLine("NATIVE_MEDIA=" + await MediaWriterChecks.FullWriteAsync(e.Args[2], e.Args.Length == 4 && e.Args[3] == "cancel")); }
                else if (e.Args[1] == "native-written-vhd-boot" && e.Args.Length == 3) log.AppendLine("WRITTEN_VHD_BOOT=" + await VirtualBoot.WrittenVhdAsync(e.Args[2], text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] == "native-media-guards" && e.Args.Length == 3) log.AppendLine("MEDIA_GUARDS=" + await MediaWriterChecks.HelperGuardsAsync(e.Args[2]));
                else if (e.Args[1] == "native-media-source-change") log.AppendLine("NATIVE_MEDIA=" + await MediaWriterChecks.ChangedSourceAsync());
                else if (e.Args[1] == "native-binding-checks" && e.Args.Length == 3) log.AppendLine("NATIVE_BINDING=" + await NativeBindingChecks.RunAsync(e.Args[2]));
                else if (e.Args[1] == "native-media-faults" && e.Args.Length == 3) log.AppendLine("MEDIA_FAULTS=" + await MediaFaultChecks.RunAsync(e.Args[2]));
                else if (e.Args[1] == "native-volume-write" && e.Args.Length == 3) log.AppendLine("VOLUME_WRITE=" + await VolumeLockChecks.WriteAsync(e.Args[2]));
                else if (e.Args[1] == "native-volume-locks") log.AppendLine("VOLUME_LOCKS=" + await VolumeLockChecks.RunAsync());
                else if (e.Args[1] == "usb-plan-checks") log.AppendLine(UsbPlanningChecks.Run());
                else if (e.Args[1] == "usb-inventory" && e.Args.Length == 3) log.AppendLine(System.Text.Json.JsonSerializer.Serialize(await UsbMediaPlanning.ReadAsync(e.Args[2], CancellationToken.None)));
                else if (e.Args[1] == "disk-inventory" && e.Args.Length == 2) log.AppendLine(await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, CancellationToken.None));
                else if (e.Args[1] == "plan-checks") log.AppendLine(PlanningChecks.Run());
                else if (e.Args[1] == "partition-picker-checks") log.AppendLine(PartitionPickerChecks.Run(e.Args.Length > 2 ? e.Args[2] : null));
                else if (e.Args[1] == "handoff-roundtrip") log.AppendLine("HANDOFF=" + await Backend.CheckHandoffAsync(text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] == "virtual-install-media" && e.Args.Length == 3)
                    log.AppendLine("INSTALL_SESSION=" + await Backend.CheckHandoffAsync(text => log.Append(text), CancellationToken.None, e.Args[2]));
                else if (e.Args[1] == "virtual-intent-interrupt" && e.Args.Length == 4)
                    log.AppendLine("INTENT_RECOVERY=" + await Backend.CheckIntentInterruptionAsync(e.Args[2], e.Args[3], text => { lock (log) log.Append(text); }, CancellationToken.None));
                else if (e.Args[1] == "virtual-journal-check" && e.Args.Length == 4)
                {
                    Backend.VerifyFixture(e.Args[3]);
                    var selection = await File.ReadAllTextAsync(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(e.Args[3]))!, "windows-selection.json"));
                    var overlay = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None, "isolated journal migration check");
                    await Backend.GuestAsync("journal-migration-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, selection, overlay);
                    await File.WriteAllTextAsync(Path.Combine(Path.GetDirectoryName(overlay)!, "journal-result.json"),
                        System.Text.Json.JsonSerializer.Serialize(new { passed = true, overlay,
                            scope = "Real legacy UUID descriptor migration verified against each live filesystem, mismatch rejection without journal overwrite and existing EFI/NTFS/home preservation; isolated overlay, no root copy or Windows OS" }));
                    log.AppendLine("JOURNAL_FIXTURE=" + overlay);
                }
                else if (e.Args[1] == "handoff-checks" && e.Args.Length == 3)
                {
                    await using var destination = new FileStream(Path.GetFullPath(e.Args[2]), FileMode.CreateNew, FileAccess.Write);
                    await System.Text.Json.JsonSerializer.SerializeAsync(destination, PlanningChecks.HandoffFixture());
                    log.AppendLine("Native Windows planner exported the synthetic Linux handoff fixture.");
                }
                else if (e.Args[1] == "cancel-check")
                {
                    using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(1));
                    try { await Backend.GuestAsync("smoke", null, false, text => log.Append(text), cancel.Token); throw new Exception("Cancellation was not observed"); }
                    catch (OperationCanceledException) { log.AppendLine("Cancellation reached the owned QEMU process and preserved its log."); }
                }
                else if (e.Args[1] == "smoke") await Backend.GuestAsync("smoke", null, false, text => log.Append(text), CancellationToken.None);
                else if (e.Args[1] == "verify" && e.Args.Length == 3) await Backend.GuestAsync("verify", e.Args[2], false, text => log.Append(text), CancellationToken.None);
                else if (e.Args[1] == "virtual-create") log.AppendLine("FIXTURE=" + await Backend.CreateFixtureAsync(text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] == "virtual-deploy" && e.Args.Length == 4) await Backend.GuestAsync("deployment-test", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: e.Args[3]);
                else if (e.Args[1] == "virtual-boot" && e.Args.Length == 3) log.AppendLine("BOOT=" + await VirtualBoot.RunAsync(e.Args[2], text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] == "virtual-interrupt-check" && e.Args.Length == 4)
                {
                    var overlay = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None);
                    var reached = false;
                    using var interrupt = new CancellationTokenSource();
                    try
                    {
                        await Backend.GuestAsync("deployment-interrupt", e.Args[2], false, text =>
                        {
                            lock (log)
                            {
                                log.Append(text);
                                if (!reached && log.ToString().Contains("OXP_DEPLOY_HARDSTOP=configure-A:root-writable", StringComparison.Ordinal))
                                { reached = true; interrupt.Cancel(); }
                            }
                        }, interrupt.Token, fixture: overlay);
                        throw new InvalidOperationException("未观察到预定中断边界。");
                    }
                    catch (OperationCanceledException) when (reached)
                    { log.AppendLine("Owned QEMU was abruptly terminated at the writable-root boundary; no guest cleanup ran."); }
                    await Backend.GuestAsync("deployment-recovery", e.Args[2], false, text => { lock (log) log.Append(text); }, CancellationToken.None, fixture: overlay);
                    await File.WriteAllTextAsync(Path.Combine(Path.GetDirectoryName(overlay)!, "hard-stop-result.json"),
                        System.Text.Json.JsonSerializer.Serialize(new { passed = true, reached, overlay, backing = Path.GetFullPath(e.Args[3]),
                            scope = "Real QEMU termination at a synced writable-root configuration boundary and disk-journal recovery; not arbitrary power-loss or physical acceptance" }));
                    log.AppendLine("INTERRUPT_FIXTURE=" + overlay);
                }
                else if (e.Args[1] == "virtual-firstboot-verify" && e.Args.Length == 4)
                    await Backend.GuestAsync("firstboot-verify", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: e.Args[3]);
                else if (e.Args[1] == "virtual-firstboot" && e.Args.Length == 4)
                {
                    var staged = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None, "isolated firstboot staging");
                    await Backend.GuestAsync("firstboot-prepare", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: staged);
                    log.AppendLine("FIRSTBOOT_STAGED=" + staged);
                    var boot = await VirtualBoot.RunAsync(staged, text => log.Append(text), CancellationToken.None);
                    var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "firstboot-proof-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
                    var verification = Path.Combine(directory, "windows-fixture.qcow2");
                    var parent = Path.Combine(boot, "boot.qcow2");
                    using (var input = new FileStream(parent, FileMode.Open, FileAccess.Read, FileShare.Read))
                    {
                        var header = new byte[32]; input.ReadExactly(header);
                        if (!header.AsSpan(0, 4).SequenceEqual(new byte[] { 0x51, 0x46, 0x49, 0xfb })
                            || System.Buffers.Binary.BinaryPrimitives.ReadUInt64BigEndian(header.AsSpan(24, 8)) != 80UL * 1024 * 1024 * 1024)
                            throw new IOException("Known firstboot parent is not the expected 80GiB QCOW2.");
                    }
                    // The stopped boot was already validated. Explicit size avoids
                    // qemu-img reopening a deeply concatenated Windows backing path.
                    // The independent read-only VM must still open the complete graph.
                    await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-u", "-f", "qcow2", "-F", "qcow2", "-b", Path.GetRelativePath(directory, parent), verification, "80G"], text => log.Append(text), CancellationToken.None);
                    await File.WriteAllTextAsync(Path.ChangeExtension(verification, ".fixture.json"), System.Text.Json.JsonSerializer.Serialize(new { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024, purpose = "isolated firstboot readonly result proof" }));
                    await Backend.GuestAsync("firstboot-verify", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: verification);
                    await File.WriteAllTextAsync(Path.Combine(directory, "result.json"), System.Text.Json.JsonSerializer.Serialize(new { passed = true, staged, boot, verification, scope = "Real root-owned firstboot via systemd on owned SteamOS 3.8 UEFI overlay; compatibility refusal before HDR configuration, new boot ID/run count, private state and Windows sentinel/root protection. No positive OXP3 HDR install, Steam frontend/plugin activation or physical disk proof." }));
                    log.AppendLine("FIRSTBOOT_PROOF=" + directory);
                }
                else if (e.Args[1] == "virtual-component-install" && e.Args.Length == 4)
                {
                    var seed = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None, "isolated component install seed");
                    File.Copy(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(e.Args[3]))!, "windows-selection.json"), Path.Combine(Path.GetDirectoryName(seed)!, "windows-selection.json"));
                    var state = await Backend.CreateStateDiskAsync(seed, text => log.Append(text), CancellationToken.None);
                    await Backend.GuestAsync("ui-bootstrap-seed", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: seed, stateDisk: state);
                    var ui = await VirtualBoot.UiAsync(e.Args[2], seed, true, text => log.Append(text), CancellationToken.None);
                    using var value = System.Text.Json.JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(ui, "result.json")));
                    var installed = value.RootElement.GetProperty("target").GetString()!;
                    await Backend.GuestAsync("ui-installed-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: installed);
                    var boot = await VirtualBoot.RunAsync(installed, text => log.Append(text), CancellationToken.None);
                    var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "component-install-proof-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
                    var proof = Path.Combine(directory, "windows-fixture.qcow2");
                    await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-u", "-f", "qcow2", "-F", "qcow2", "-b", Path.GetRelativePath(directory, Path.Combine(boot, "boot.qcow2")), proof, "80G"], text => log.Append(text), CancellationToken.None);
                    File.Copy(Path.ChangeExtension(installed, ".fixture.json"), Path.ChangeExtension(proof, ".fixture.json"));
                    await Backend.GuestAsync("ui-installed-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: proof);
                    log.AppendLine("COMPONENT_INSTALL_UI=" + ui); log.AppendLine("COMPONENT_INSTALL_BOOT=" + boot); log.AppendLine("COMPONENT_INSTALL_PROOF=" + proof);
                }
                else if (e.Args[1] == "virtual-shared-state" && e.Args.Length == 4)
                {
                    var overlay = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None, "isolated shared A-B component state");
                    await Backend.GuestAsync("shared-state-test", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: overlay);
                    log.AppendLine("SHARED_FIXTURE=" + overlay);
                }
                else if (e.Args[1] == "virtual-hdr" && e.Args.Length == 4)
                {
                    var overlay = await Backend.CreateFixtureOverlayAsync(e.Args[3], text => log.Append(text), CancellationToken.None, "isolated HDR configuration lifecycle");
                    await Backend.GuestAsync("hdr-test", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: overlay);
                    log.AppendLine("HDR_FIXTURE=" + overlay);
                }
                else if (e.Args[1] == "virtual-plugins" && e.Args.Length == 4) await Backend.GuestAsync("plugin-test", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: e.Args[3]);
                else if (e.Args[1] == "preview-boot" && e.Args.Length == 3) log.AppendLine("BOOT=" + await VirtualBoot.PreviewAsync(e.Args[2], text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] is "ui-boot-check" or "ui-install-check" && e.Args.Length == 4)
                    log.AppendLine("UI_BOOT=" + await VirtualBoot.UiAsync(e.Args[2], e.Args[3], e.Args[1] == "ui-install-check", text => log.Append(text), CancellationToken.None));
                else if (e.Args[1] == "ui-resume-check" && e.Args.Length == 4)
                    log.AppendLine("UI_BOOT=" + await VirtualBoot.UiAsync(e.Args[2], e.Args[3], true, text => log.Append(text), CancellationToken.None, resume: true));
                else if (e.Args[1] == "ui-cancel-check" && e.Args.Length == 4)
                    log.AppendLine("UI_BOOT=" + await VirtualBoot.UiAsync(e.Args[2], e.Args[3], true, text => log.Append(text), CancellationToken.None, cancel: true));
                else if (e.Args[1] == "ui-installed-verify" && e.Args.Length == 4)
                    await Backend.GuestAsync("ui-installed-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: e.Args[3]);
                else if (e.Args[1] == "ui-cancelled-verify" && e.Args.Length == 4)
                    await Backend.GuestAsync("ui-cancelled-check", e.Args[2], false, text => log.Append(text), CancellationToken.None, fixture: e.Args[3]);
                else if (e.Args[1] == "refine-preview" && e.Args.Length == 3) await Backend.GuestAsync("refine-preview", e.Args[2], true, text => log.Append(text), CancellationToken.None);
                else if (e.Args[1] == "refresh-hdr-resources" && e.Args.Length == 3)
                    await Backend.GuestAsync("refine-preview", e.Args[2], true, text => log.Append(text), CancellationToken.None,
                        System.Text.Json.JsonSerializer.Serialize(new { resources = new[] { "waydroid", "oxp3-controls", "hdr" } }));
                else if (e.Args[1] == "refresh-preview-resources" && e.Args.Length == 3)
                    await Backend.GuestAsync("refine-preview", e.Args[2], true, text => log.Append(text), CancellationToken.None,
                        System.Text.Json.JsonSerializer.Serialize(new { resources = new[] { "waydroid", "oxp3-controls" } }));
                else if (e.Args[1] is "build" or "build-waydroid" or "build-resources" && e.Args.Length == 4)
                {
                    await Backend.CopyImageAsync(e.Args[2], e.Args[3], CancellationToken.None);
                    var resources = e.Args[1] == "build-resources" ? new[] { "waydroid", "oxp3-controls" } : e.Args[1] == "build-waydroid" ? new[] { "waydroid" } : [];
                    var selection = resources.Length == 0 ? null : System.Text.Json.JsonSerializer.Serialize(DiskPlanning.Preview(null, resources));
                    await Backend.GuestAsync("build", e.Args[3], true, text => log.Append(text), CancellationToken.None, selection);
                }
                else throw new ArgumentException("Unknown CLI task");
                await File.WriteAllTextAsync(resultFile, log + "\nNATIVE_CLI_RESULT=passed\n"); Shutdown(0);
            }
            catch (Exception error) { await File.WriteAllTextAsync(resultFile, log + "\n" + error); Shutdown(1); }
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--render-ui") System.Windows.Media.RenderOptions.ProcessRenderMode = System.Windows.Interop.RenderMode.SoftwareOnly;
        var rehearsal = e.Args.Length > 0 && e.Args[0] is "--rehearsal" or "--shared-storage-ui-checks" or "--wizard-checks" or "--wizard-resume" or "--wizard-run-prepared" or "--wizard-run-image" or "--wizard-cancel-prepared";
        var window = new MainWindow(rehearsal);
        MainWindow = window;
        if (e.Args.Length == 1 && e.Args[0] == "--shared-storage-ui-checks")
        {
            var result = Path.Combine(Backend.Root, "logs/shared-storage-ui-checks.json");
            try { await File.WriteAllTextAsync(result, SharedStorageChecks.RunUi(window)); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--boot-setup-checks")
        {
            Directory.CreateDirectory(Path.Combine(Backend.Root, "logs"));
            try { var proof = BootSetupChecks.Run(window); await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/boot-setup-checks-result.txt"), proof); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/boot-setup-checks-result.txt"), error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--installation-result-checks")
        {
            var result = Path.Combine(Backend.Root, "logs/installation-result-checks.json");
            Directory.CreateDirectory(Path.GetDirectoryName(result)!);
            try { await File.WriteAllTextAsync(result, InstallationResultChecks.Run(window)); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 2 && e.Args[0] == "--official-local-import-checks")
        {
            var result = Path.Combine(Backend.Root, "logs/official-local-import-checks.json");
            Directory.CreateDirectory(Path.GetDirectoryName(result)!);
            try { await File.WriteAllTextAsync(result, await OfficialSystemProgressChecks.RunImportUiAsync(window, e.Args[1])); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 2 && e.Args[0] == "--official-local-bundle-checks")
        {
            var result = Path.Combine(Backend.Root, "logs/official-local-bundle-checks.json");
            try { await File.WriteAllTextAsync(result, await OfficialSystemProgressChecks.RunLocalBundleAsync(window, e.Args[1])); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--official-download-ui-checks")
        {
            Directory.CreateDirectory(Path.Combine(Backend.Root, "logs"));
            var result = Path.Combine(Backend.Root, "logs/official-download-ui-checks.json");
            try { await File.WriteAllTextAsync(result, await OfficialSystemProgressChecks.RunUiAsync(window)); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--touch-checks")
        {
            Directory.CreateDirectory(Path.Combine(Backend.Root, "logs"));
            try { var proof = TouchLayoutChecks.Run(window); await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/touch-checks-result.txt"), proof); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/touch-checks-result.txt"), error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--options-checks")
        {
            Directory.CreateDirectory(Path.Combine(Backend.Root, "logs"));
            try { await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/options-checks.json"), OptionsChecks.Run(window)); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/options-checks.json"), error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 2 && e.Args[0] == "--wizard-physical-navigation-checks")
        {
            var result = Path.Combine(Backend.Root, "logs/wizard-physical-navigation-checks.json");
            try { await File.WriteAllTextAsync(result, WizardChecks.RunPhysicalNavigation(window, e.Args[1])); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(result, error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length == 2 && e.Args[0] == "--wizard-checks")
        {
            try { var proof = WizardChecks.Run(window, e.Args[1]); await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/wizard-checks-result.txt"), proof); Shutdown(0); }
            catch (Exception error) { await File.WriteAllTextAsync(Path.Combine(Backend.Root, "logs/wizard-checks-result.txt"), error.ToString()); Shutdown(1); }
            return;
        }
        if (e.Args.Length is 2 or 3 or 5 && e.Args[0] == "--render-ui")
        {
            if (e.Args.Length >= 3) window.PreviewStep(int.Parse(e.Args[2]));
            var width = e.Args.Length == 5 ? int.Parse(e.Args[3]) : 1060;
            var height = e.Args.Length == 5 ? int.Parse(e.Args[4]) : 790;
            if (width < 640 || width > 2000 || height < 360 || height > 2000) throw new ArgumentException("Invalid capture size");
            window.WindowState = WindowState.Normal; window.Width = width; window.Height = height; window.ShowActivated = false; window.Show();
            await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
            var content = (FrameworkElement)window.Content;
            content.Measure(new Size(width, height)); content.Arrange(new Rect(0, 0, width, height)); content.UpdateLayout();
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            var background = new DrawingVisual();
            using (var context = background.RenderOpen()) context.DrawRectangle(window.Background, null, new Rect(0, 0, width, height));
            bitmap.Render(background); bitmap.Render(content);
            var pixels = new byte[width * height * 4]; bitmap.CopyPixels(pixels, width * 4, 0);
            if (!pixels.Where((_, index) => index % 4 == 3).Any(alpha => alpha != 0))
            {
                await File.WriteAllTextAsync(Path.GetFullPath(e.Args[1]) + ".diagnostics.json",
                    System.Text.Json.JsonSerializer.Serialize(new {
                        content.IsVisible, content.ActualWidth, content.ActualHeight, failure = "WPF layout capture is empty" }));
                Shutdown(1); return;
            }
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using var stream = File.Create(Path.GetFullPath(e.Args[1])); encoder.Save(stream);
            Shutdown(); return;
        }
        if (e.Args.Length == 2 && e.Args[0] == "--wizard-resume")
        {
            MediaSource.Ordinary(e.Args[1], InstallationController.Work);
            var selected = System.Text.Json.JsonSerializer.Deserialize<InstallationSession>(await File.ReadAllTextAsync(e.Args[1])) ?? throw new IOException("Missing session");
            window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
            await window.ResumeAsync(selected);
            Shutdown(window.CompletedSession?.Status == "complete" ? 0 : 1); return;
        }
        if (e.Args.Length == 3 && e.Args[0] is "--wizard-run-prepared" or "--wizard-run-image" or "--wizard-cancel-prepared")
        {
            var kind = e.Args[2] switch { "internal" => InstallationTargetKind.InternalShared, "external" => InstallationTargetKind.ExternalDisk, _ => throw new ArgumentException("Expected kind") };
            window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
            window.CloseOnFirstWriteForCheck = e.Args[0] == "--wizard-cancel-prepared";
            await window.StartAsync(new(kind, e.Args[1], e.Args[0] != "--wizard-run-image"));
            Shutdown(window.CompletedSession?.Status == (e.Args[0] == "--wizard-cancel-prepared" ? "cancelled" : "complete") ? 0 : 1); return;
        }
        window.Show();
    }
}








