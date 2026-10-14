const fs=require('fs');
const path=require('path');
const run=process.argv[2];
const evidence=path.join(run,'evidence');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const report=read(path.join(evidence,'capacity-and-progress-estimates.json'));
const home=report.filesystem_usage.find(x=>x.name==='home');
const GiB=1024**3;
report.capacity.home_partition_bytes=home.partition_bytes;
report.capacity.home_available_bytes=home.available_bytes;
report.capacity.recommended_fresh_workspace_free_bytes=64*GiB;
report.capacity.recommended_workspace_scope='Single successful fresh sparse-file workflow including recovery ZIP, official root cache, QEMU preparation, one staging image and preserved logs. Excludes failed-run artifacts and mock target VHD. Existing sessions accumulate; non-sparse filesystems need separate full-image checks.';
const config={schema:1,snapshot:report.source_head,profile:'SteamOS 3.10 20260924.1000, zh-CN defaults except flathub-ustc disabled, rEFInd SteamOS/5s, 64 GiB, ReFS sparse workspace',
  default_chinese_selection_passed:false,
  cached_install_baseline_seconds:report.cached_install_baseline_seconds,
  measured_recovery_download_seconds:report.default_zip.download_seconds,
  simplified_stage_weights_percent:{prepare_system:32,components_and_verify:43,refind:3,write_and_verify:22},
  precise_stages:report.estimated_weights.map(x=>({stage:x.name,seconds:x.duration_seconds,weight_percent:x.weight_percent})),
  target_system_bytes:report.capacity.target_partition_bytes,
  native_io_total_bytes:2*report.capacity.target_partition_bytes,
  update_rules:[
    'Download progress is completed/total bytes; ETA uses smoothed live speed. Official-root network restore is a separate unmeasured branch.',
    'Keep write and verification counters per role. Completed PARTITION_DEPLOYED roles count as both fully written and fully verified.',
    'Native stage fraction = (sum(written)+sum(verified))/(2*sum(role_size)); do not reset when a new partition begins.',
    'Use separate smoothed rates for writing and verifying, update remaining time with actual target speed.',
    'For stages without byte counters, use backend milestones and a capped time estimate; only a success event completes the stage.',
    'A component rejection stops the default install progress before target creation. Show a specific refusal, not 100% success.',
    'Physical installation finishes in awaiting-device-boot. UEFI mock boot is validation overhead, not real handheld first-boot timing.'
  ],
  limitations:report.limits};
fs.writeFileSync(path.join(evidence,'progress-bar-calibration.json'),JSON.stringify(config,null,2));
fs.writeFileSync(path.join(evidence,'capacity-and-progress-estimates.json'),JSON.stringify(report,null,2));
const old=fs.readFileSync(path.join(evidence,'REPORT.zh-CN.txt'),'utf8');
const fixed=old.replace(' + 对应未提交修改（随默认方案目录保留）',' + 当时未提交更新（当前 installer 源码和 source-tracked-diff.patch 已保留）');
const extra=[
  '',`home 分区：${(home.partition_bytes/GiB).toFixed(2)} GiB；当前可用：${(home.available_bytes/GiB).toFixed(2)} GiB。不能把64 GiB减去系统已用直接当作游戏可用空间。`,
  '建议单次真实安装准备64 GiB空闲工作空间（当前稀疏文件配置，含压缩镜像/官方根缓存/准备镜像/日志，保留8 GiB余量）；失败/旧任务另占空间。',
  'E盘此次VHD mock的原生预检仍要求160.5 GiB可用，这是开发测试保守检查，不是已测文件实际占用。',
  '', '简化进度权重：准备系统32%，组件安装+核对43%，rEFInd 3%，写入+读回22%。下载按实时字节单列。精确分段权重见progress-bar-calibration.json。',
  '本机安装阶段合成基线约36分钟；加本次恢复ZIP下载约38分钟。官方3.10根系统首次下载、用户确认/UAC等待、主机EFI变更及掌机首启未测。',
  'VHD原生写入+读回约7分58秒，其中含测试盘创建和合成Windows分区保留检查。VHD零区间可少分配空间，SSD/SD应使用目标实际测速更新ETA。',
  '', '数据口径：FILE_STANDARD_INFO.AllocationSize为卷内每文件分配量；不把整个E卷可用空间变化归因于本任务，也不等同于存储池底层物理/共享块数量。',
  `共享开发SDK已存在于C:/steamosmod/windows-installer/runtime/dotnet，逻辑大小约${(report.build_sdk.logical_bytes/GiB).toFixed(2)} GiB，没有把完整SDK复制到E。便携运行库已计入工具目录。`,
  '', '最新原生源码810b096与前期快照的185个生产文本文件比对：仅NativeVolumes.cs和NativeVolumeChecks.cs改变，系统准备与组件代码未变。比较见source-comparison.json。',
  '源码仓库只增加测量脚本，没有修改生产安装逻辑或默认选项。默认中文换源阻断需要另行修复。'
].join('\r\n');
fs.writeFileSync(path.join(evidence,'REPORT.zh-CN.txt'),fixed+'\r\n'+extra+'\r\n');
console.log(JSON.stringify({workspace_gib:report.capacity.workspace_before_native_allocated_bytes/GiB,workspace_with_tool_gib:report.capacity.final_run_without_mock_target_bytes/GiB,target_gib:64,filesystem_used_gib:report.capacity.final_filesystem_used_bytes/GiB,home_available_gib:home.available_bytes/GiB,install_minutes:report.cached_install_baseline_seconds/60,with_zip_download_minutes:report.default_zip.with_measured_recovery_download_estimate_seconds/60,report:path.join(evidence,'REPORT.zh-CN.txt')},null,2));
