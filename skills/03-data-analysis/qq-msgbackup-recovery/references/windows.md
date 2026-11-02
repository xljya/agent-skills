# Windows 解密手册

已验证的组合是 Windows x64 QQ 9.9.36-53644 的 `wrapper.node` 和经典 QQ 9.7.25.29417 的 x86 `KernelUtil.dll`。手机侧验证过安卓 QQ 9.3.60 系列。备份用当前登录的 QQ 读取；经典组件只供独立的 32 位小程序加载。可从自己取得的对应经典 QQ 安装包解包，保留 `Files\Bin` 内的配套依赖。仓库不附带 QQ 程序或 DLL。

## 准备

使用 Windows PowerShell 7、64 位 Python 3.11+、.NET Framework 4.x 的 32 位 C# 编译器。在 skill 目录打开 PowerShell，把下方的示例路径和进程号换成实际值。私人工作目录应位于备份及 Git 仓库以外，留够数据库副本、临时 rekey 文件和解密结果所需的空间。

```powershell
$scripts = (Resolve-Path -LiteralPath '.\scripts').Path
$source = 'D:\QQ-data\Tencent Files\<账号>\MsgBackup\<本次备份目录>'
$work = 'D:\QQ-recovery\case-01'
$dll = 'D:\ClassicQQ\Files\Bin\KernelUtil.dll'
$wrapper = 'D:\QQ\versions\9.9.36-53644\resources\app\wrapper.node'
python "$scripts\recover.py" prepare $source --work $work
if ($LASTEXITCODE -ne 0) { throw '准备副本失败' }
$helper = Join-Path $work 'Msg0.exe'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
& $csc /nologo /target:exe /platform:x86 "/out:$helper" "$scripts\Msg0.cs"
if ($LASTEXITCODE -ne 0) { throw 'x86 助手编译失败' }
```

`prepare` 递归按文件头识别数据库，并验证源文件与副本的 SHA-256。若有同名库，先缩小到一份备份。若只发现一部分，先检查选择的备份根目录。采集密钥前先确认 QQ 的备份列表能看到目标备份。

## 捕获

```powershell
python -m pip install frida==17.25.1
Get-Process -Name QQ | Select-Object Id, Path
Get-Process -Name QQ | ForEach-Object {
    $q = $_
    $q.Modules | Where-Object ModuleName -eq 'wrapper.node' |
        Select-Object @{Name='ProcessId';Expression={$q.Id}}, FileName
}
$qqProcessId = Read-Host '输入已核对的 QQ 主进程 PID'
python "$scripts\recover.py" capture --work $work --dll $dll --helper $helper --wrapper $wrapper --pid $qqProcessId
```

临时调试可能让 QQ 短暂停顿或退出。看到 `ARMED` 后，请用户在 QQ 重新进入目标备份详情，触发读取；无需实际覆盖手机聊天。限定 180 秒，匹配完成或超时即分离。若只匹配部分文件，保留已有结果，检查 PID、备份批次和是否触发了读取，再决定是否重试。

脚本对两个组件都做 SHA-256 校验，并核对进程内的模块路径和架构。此版本的请求入口 RVA 为 `0x3D7AB76`，响应入口为 `0x3D7B1F2`。只 hook 响应，在成功标志为真时取第 3 个参数所指向的字节向量；接受 16 字节或 32 个 ASCII 十六进制字符。通过本地管道送入 x86 助手，逐库验证 `SELECT count(*) FROM sqlite_master`。成功后写入私人目录 `keys\<容器名>.verified-key`。

指纹不匹配就停止。适配另一版时，需对该版的备份请求、响应调用点、回调参数和容器的测试副本重新验证，然后再增加相应版本支持。不要把这组 RVA 直接套用到另一版。

## 离线解密

```powershell
python "$scripts\recover.py" decrypt --work $work --dll $dll --helper $helper
```

助手在临时副本上用验证过的 16 字节密钥打开库，再以 **16 个零字节**做 rekey。关闭句柄后，检查偏移 0 的扩展头和偏移 1024 的 `SQLite format 3\0`，导出标准 SQLite，再以只读方式运行 `PRAGMA integrity_check`。仅在结果恰为 `ok` 时，将该库交付到 `plain\<容器名>.sqlite`。按列出的表名区分索引库与资源库。已存在的同名结果会停止本次导出；重做时使用新的工作目录。

经典 PCQQ 的 rekey 与扩展头可参阅上游文档。手机 MSG0 的备份回调由随附脚本处理。[QQDecrypt 的经典 PCQQ 说明](https://github.com/QQBackup/QQDecrypt/blob/main/docs/decrypt/extract/PCQQ%20%28Windows%29.md)
