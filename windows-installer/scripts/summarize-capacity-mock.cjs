const fs = require('fs');
const path = require('path');
const run = process.argv[2];
if (!run) throw new Error('Pass the exact capacity-mock run directory');
const evidence = path.join(run, 'evidence');
const readJson = p => JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
const GiB = 1024 ** 3;
const measuredStages = readJson(path.join(evidence, 'stages.json'));
const result = readJson(path.join(evidence, 'result.json'));
const context = readJson(path.join(evidence, 'run-context.json'));
const defaultEvidence = context.default_run ? path.join(context.default_run,'evidence') : null;
const preparationStages = defaultEvidence ? readJson(path.join(defaultEvidence,'stages.json')).filter(x=>+x.name.slice(0,2)<5) : [];
const compatibleStages = context.compatible_run ? readJson(path.join(context.compatible_run,'evidence/stages.json')).filter(x=>+x.name.slice(0,2)>=5 && +x.name.slice(0,2)<=10) : [];
const stages = [...preparationStages,...compatibleStages,...measuredStages];
const lines = fs.readFileSync(path.join(evidence, 'events.jsonl'), 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse);
const snapshots = lines.filter(x => x.allocated_bytes !== undefined);
const last = snapshots.at(-1);
const peak = snapshots.reduce((a, b) => b.allocated_bytes > a.allocated_bytes ? b : a);
const peakWork = snapshots.reduce((a, b) => (b.groups.work?.allocated_bytes || 0) > (a.groups.work?.allocated_bytes || 0) ? b : a);
const beforeTarget = readJson(path.join(evidence, 'inventory-12-native-write-and-full-readback-before.json'));
const sharedPreparation = defaultEvidence ? readJson(path.join(defaultEvidence,'inventory-05-sparse-raw-export-before.json')) : null;
const failedDefault = defaultEvidence ? readJson(path.join(defaultEvidence,'inventory-failed.json')) : null;
const usageMeasurementBytes = beforeTarget.files.filter(x=>x.path.startsWith('work'+path.sep)&&x.path.includes('-capacity-usage'+path.sep)).reduce((a,x)=>a+x.allocated_bytes,0);
const normalizedWorkspaceBeforeTarget = beforeTarget.groups.work.allocated_bytes-usageMeasurementBytes+(sharedPreparation?.groups.work?.allocated_bytes||0);
const finalFiles = readJson(path.join(evidence, 'inventory-complete.json')).files;
const media = finalFiles.filter(x => /partition-deploy-[a-f0-9]+[\\/]media\.vhd$/.test(x.path));
const layout = readJson(path.join(evidence, 'partition-layout.json'));
const roles = ['esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home'];
const partitions = layout.Partitions.filter(x => roles.includes(x.Name));
const partitionBytes = partitions.reduce((a, x) => a + x.Size, 0);
const usages = [];
const native = [];
const nativeCompleted = [];
const joinedLog = lines.filter(x=>x.type==='log').map(x=>x.text).join('');
for (const match of joinedLog.matchAll(/OXP_CAPACITY=(\{[^\r\n]+\})/g)) usages.push(JSON.parse(match[1]));
for (const e of lines.filter(x => x.type === 'log')) {
  for(const match of e.text.matchAll(/PARTITION_DEPLOYED=([^\r\n]+)/g)) nativeCompleted.push({role:match[1],seconds:e.seconds});
  for (const match of e.text.matchAll(/PARTITION_PROGRESS=([^:]+):([^:]+):(\d+):(\d+):(\d+)/g)) {
    native.push({seconds: e.seconds, role: match[1], phase: match[2], written: +match[3], verified: +match[4], total: +match[5]});
  }
}
if (result.passed && new Set(usages.map(x=>x.name)).size !== 8) throw new Error('Expected all eight filesystem usage records; inspect retained raw transcript');
const nativeByRole = roles.map(role => {
  const samples = native.filter(x => x.role === role);
  const done=nativeCompleted.find(x=>x.role===role);
  return {role, bytes: partitions.find(x => x.Name === role)?.Size, first_seconds: samples[0]?.seconds, last_seconds: samples.at(-1)?.seconds, completed:!!done,completed_seconds:done?.seconds,samples};
});
const excluded = new Set(['00-recovery-download-default-zip','11-installed-filesystem-usage', '13-independent-uefi-boot']);
const installStages = stages.filter(x => !excluded.has(x.name));
const installSeconds = installStages.reduce((a, x) => a + x.duration_seconds, 0);
const profile = installStages.map(x => ({...x, weight_percent: 100 * x.duration_seconds / installSeconds,
  method: x.name.startsWith('12-') ? 'global bytes written and verified across all eight partitions' : x.name.startsWith('01-') ? 'archive extraction output bytes or format-specific measured baseline' : 'stage baseline with live backend milestones; cap estimated fraction below completion until actual success'}));
const report = {schema: 1, run, passed: result.passed, source_head: fs.readFileSync(path.join(evidence,'source-head.txt'),'utf8').trim(),
  source_snapshot: 'installer/app, guest, components and scripts in this run; source-tracked-diff.patch and source-snapshot-files.json retained',
  allocation_method: 'FILE_STANDARD_INFO.AllocationSize for every ordinary file, includes ReFS 64 KiB allocation units and sparse ranges. Per-file counts are distinct from volume-wide free-space change.',
  recovery_network_download_measured: !!context.recovery_network_download_measured, official_root_network_download_measured: false, context, total_test_seconds: result.seconds,
  cached_install_baseline_seconds: installSeconds, estimated_weights: profile,
  capacity: {target_partition_bytes: partitionBytes, final_filesystem_used_bytes: usages.reduce((a,x)=>a+x.used_bytes,0),
    workspace_before_native_allocated_bytes: normalizedWorkspaceBeforeTarget,
    excluded_extra_usage_measurement_bytes:usageMeasurementBytes,
    workspace_before_native_method: sharedPreparation?'Sum of unchanged preparation workspace before first export plus compatible-profile staging workspace, excluding extra filesystem-usage measurement payloads and failed-default artifacts.':'Observed main workspace allocation before native target creation, excluding extra usage measurement payloads.',
    retained_workspace_peak_allocated_bytes: peakWork.groups.work.allocated_bytes,
    retained_run_peak_allocated_bytes: peak.allocated_bytes,
    retained_run_final_allocated_bytes: last.allocated_bytes,
    mock_target_vhd_allocated_bytes: media.reduce((a,x)=>a+x.allocated_bytes,0),
    final_run_without_mock_target_bytes: last.allocated_bytes-media.reduce((a,x)=>a+x.allocated_bytes,0),
    recovery_archive_bytes: context.recovery_archive_bytes, official_root_cache_bytes: context.rootfs_bytes,
    portable_instrumented_build_allocated_bytes: last.groups.installer?.allocated_bytes||sharedPreparation?.groups.installer?.allocated_bytes||0,
    scope: 'All temporary VM payloads and logs retained. VHD is mock target overhead, not physical-install workspace. Btrfs statvfs usage is filesystem accounting, not a unique-file total.'},
  partition_layout: partitions, filesystem_usage: usages, native_progress: nativeByRole,
  eta_formula: 'T = sum(remaining stage baselines) + remaining_download_bytes / smoothed_download_bytes_per_second + remaining_write_bytes / smoothed_write_bytes_per_second + remaining_verify_bytes / smoothed_verify_bytes_per_second. Use separate rates for write and verify. Exclude device-first-boot from completed installer ETA.',
  progress_formula: 'P = sum(completed stage weights) + current_stage_weight * stage_fraction. For native writes, fraction = (sum(written_by_role) + sum(verified_by_role)) / (2 * sum(partition_bytes)). Keep counters across partition transitions.',
  limits: ['One local run; no percentile or cross-device throughput guarantee.', 'Official 3.10 network restore used cached rootfs.', 'Existing deployment-test includes injected failure and retry; retained as current controller behavior.', 'Physical disk/firmware and handheld first boot not performed.', 'Filesystem usage inspection and independent UEFI boot are verification overhead excluded from installer progress weights.']};
report.native_phase_overhead={scope:'Native stage also creates an owned VHD, seeds synthetic protected Windows ranges and compares them after the eight system copies. Those test-only operations are part of raw mock-stage timing. Physical installation preserves existing Windows ranges without seeding them.',first_role_completed_seconds:nativeCompleted[0]?.seconds,last_role_completed_seconds:nativeCompleted.at(-1)?.seconds};
report.limits.push('VHD may allocate less space for zero-filled ranges; logical 64 GiB write + 64 GiB readback still completed. Use live physical-target speeds for SSD/SD ETA.');
report.build_sdk={existing_shared_path:'C:/steamosmod/windows-installer/runtime/dotnet',logical_bytes:807336133,scope:'Existing shared SDK/runtime used to build; not copied as a full SDK to E. Portable runtime subset is counted in installer allocation.'};
if(defaultEvidence){
  report.default_selection={passed:false,result:readJson(path.join(defaultEvidence,'result.json')),refused_components:readJson(path.join(defaultEvidence,'components.json')).filter(x=>x.status!=='files_installed')};
  report.compatible_profile={passed:result.passed,disabled_repairs:['flathub-ustc'],scope:'Separate supported profile on fresh export of the same immutable latest 3.10 QEMU baseline; production source unchanged.'};
  report.capacity.retained_default_and_compatible_bytes=(failedDefault?.allocated_bytes||0)+last.allocated_bytes;
  report.capacity.retained_shared_preparation_bytes=sharedPreparation.groups.work.allocated_bytes;
  report.capacity.final_run_without_mock_target_bytes=report.capacity.workspace_before_native_allocated_bytes+report.capacity.portable_instrumented_build_allocated_bytes;
  report.capacity.final_run_without_mock_target_method='Normalized successful preparation plus compatible staging; failed-default test artifacts and mock target excluded.';
  report.total_test_seconds=preparationStages.reduce((a,x)=>a+x.duration_seconds,0)+compatibleStages.reduce((a,x)=>a+x.duration_seconds,0)+result.seconds;
  report.limits.push('The actual Chinese default selection is blocked by absent pre-existing Flathub remote. Capacity and supported installation timing combine default ZIP preparation with the separate mirror-off profile, excluding failed default component timing.');
}
if (context.recovery_archive_format === 'zip') {
  report.default_zip = {passed:true,archive_bytes:context.recovery_archive_bytes,download_seconds:stages.find(x=>x.name==='00-recovery-download-default-zip')?.duration_seconds||0,
    extract_seconds:stages.find(x=>x.name==='01-recovery-decompress').duration_seconds,cached_install_estimate_seconds:installSeconds,
    with_measured_recovery_download_estimate_seconds:installSeconds+(stages.find(x=>x.name==='00-recovery-download-default-zip')?.duration_seconds||0),
    estimate_scope:defaultEvidence?'Measured latest default ZIP preparation plus separate mirror-off profile completion; default Chinese selection remains failed. Official 3.10 root cached.':'Actual end-to-end default ZIP download/import and installation mock; official 3.10 root cached.'};
}
const zipPath = path.join(evidence,'default-zip-benchmark.json');
if (fs.existsSync(zipPath)) {
  report.default_zip = readJson(zipPath);
  if (report.default_zip.passed) {
    const bz = stages.find(x=>x.name==='01-recovery-decompress');
    report.default_zip.cached_install_estimate_seconds = installSeconds-bz.duration_seconds+report.default_zip.extract_seconds;
    report.default_zip.with_measured_recovery_download_estimate_seconds = report.default_zip.cached_install_estimate_seconds+report.default_zip.download_seconds;
    report.default_zip.estimate_scope = 'Derived by replacing the main run BZ2 import duration with a separate ZIP import measurement. Official SteamOS 3.10 rootfs remained cached. This is an estimate, not a second end-to-end ZIP installation.';
    const zipStages = installStages.map(x=>({...x,duration_seconds:x.name==='01-recovery-decompress'?report.default_zip.extract_seconds:x.duration_seconds}));
    report.default_zip.estimated_weights = zipStages.map(x=>({name:x.name,duration_seconds:x.duration_seconds,weight_percent:100*x.duration_seconds/report.default_zip.cached_install_estimate_seconds}));
    report.limits.push(report.default_zip.estimate_scope);
  }
}
fs.writeFileSync(path.join(evidence, 'capacity-and-progress-estimates.json'),JSON.stringify(report,null,2));
const fmt = x => (x/GiB).toFixed(2)+' GiB';
const duration = s => `${Math.floor(s/60)}m ${(s%60).toFixed(1)}s`;
const rows = stages.map(x => `${x.name}\t${x.duration_seconds.toFixed(3)}\t${profile.find(p=>p.name===x.name)?.weight_percent.toFixed(2)||'verification-only'}`);
fs.writeFileSync(path.join(evidence,'stage-timings.tsv'), 'stage\tduration_seconds\tinstall_weight_percent\n'+rows.join('\n')+'\n');
const summary = [
  'SteamOS 最新源码容量 / 耗时 mock 实测',
  `目录：${run}`, `结果：${result.passed ? '容量样本通过' : '失败'}`, `固定源码快照：${report.source_head} + 对应未提交修改（随默认方案目录保留）`,
  ...(defaultEvidence?[`默认中文方案：失败（A/B 的 flathub-ustc 均因缺少已有 Flathub remote 拒绝）；失败记录：${context.default_run}`,
    '以下容量和耗时来自仅关闭 flathub-ustc 的独立方案。使用同一最新构建和未修改的预部署基线，未修改生产源码。']:[]),
  `分段成功测试合计：${duration(report.total_test_seconds)}；缓存就绪的安装阶段基线：${duration(installSeconds)}`,
  `目标八分区总容量：${fmt(partitionBytes)}`,
  `文件系统已用合计：${fmt(report.capacity.final_filesystem_used_bytes)}`,
  `原生落盘前成功方案工作空间实际分配：${fmt(report.capacity.workspace_before_native_allocated_bytes)}`,
  `最新落盘阶段及复用工作目录的峰值：${fmt(peak.allocated_bytes)}`,
  `mock 目标 VHD 实际分配：${fmt(report.capacity.mock_target_vhd_allocated_bytes)}`,
  `成功方案扣除 mock 目标 VHD、排除默认失败产物的工作空间+运行程序：${fmt(report.capacity.final_run_without_mock_target_bytes)}`,
  ...(defaultEvidence?[`实际保留默认失败+容量方案全部产物合计：约 ${fmt(report.capacity.retained_default_and_compatible_bytes)}`]:[]),
  `恢复压缩包：${fmt(context.recovery_archive_bytes)}；官方根系统缓存：${fmt(context.rootfs_bytes)}`,
  ...(report.default_zip?.passed ? [`最新默认ZIP：${fmt(report.default_zip.archive_bytes)}；下载 ${duration(report.default_zip.download_seconds)}；解压 ${duration(report.default_zip.extract_seconds)}`,
    `替换为ZIP后的缓存就绪安装推算：${duration(report.default_zip.cached_install_estimate_seconds)}；加本次恢复ZIP下载：${duration(report.default_zip.with_measured_recovery_download_estimate_seconds)}`,
    defaultEvidence?'上项按默认ZIP准备和仅关闭换源的成功安装分段相加，排除默认失败组件轮次；3.10根系统下载仍未计入。':context.recovery_archive_format==='zip'?'本轮直接走默认ZIP的端到端安装mock；3.10根系统下载仍未计入。':'上项按分段测量合成；并非第二次ZIP端到端安装，3.10根系统下载仍未计入。'] : []),
  '', '各阶段（秒 / 安装进度权重%）：', ...rows,
  '', '进度条建议：下载按实际下载字节；解压按当前格式的解压字节或实测基线；写入与读回按全部八分区累计字节，不能每换一个分区重置总进度。',
  'ETA 对写入和读回分别平滑测速；未收到阶段成功事件前不要跳到100%。首次实机启动属于后续验收。',
  '', '本轮使用现有官方3.10根系统缓存，其下载未测；恢复ZIP下载单独记录。单机单次结果不能当作所有设备的耗时。文件系统已用是文件系统自身统计，Btrfs数据/元数据口径见原始记录。',
  '全部源码快照、编译日志、QEMU串口日志、原生写入进度、组件报告、磁盘样本与失败/旧版本记录均保留。',
].join('\r\n');
fs.writeFileSync(path.join(evidence,'REPORT.zh-CN.txt'),summary);
console.log(JSON.stringify({run, passed:result.passed, test_minutes:result.seconds/60, install_minutes:installSeconds/60, capacity:report.capacity},null,2));
