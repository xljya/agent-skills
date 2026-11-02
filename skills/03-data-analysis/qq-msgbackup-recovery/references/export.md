# 从 SQLite 到离线聊天网页

解密工具打印每个库的表名。选择同时有 `filecontext`、`msg_3_<对方账号>`、`res_3_<对方账号>` 的索引库。将它和本批次所有含 `resfile` 的资源库放在同一目录。脚本目前验证的是这套私聊 schema。同一索引库可含多个私聊表，按用户选择逐个导出。群聊或不同表结构需另外验证。

## 导出与播放

沿用解密步骤中的 PowerShell 变量，指定实际的索引库名和私聊表。用 64 位 MinGW-w64 GCC 编译媒体 DLL，位数须与运行 `media.py` 的 Python 一致。语音转码使用 `silk-python` 提供的 `pysilk` 模块。

```powershell
$catalog = Join-Path $work 'plain\<索引库文件名>.sqlite'
$view = Join-Path $work 'viewer'
$map = Join-Path $work 'media-map.json'
$cipher = Join-Path $work 'media_cipher.dll'
gcc -shared -O2 "$scripts\media_cipher.c" -o $cipher
if ($LASTEXITCODE -ne 0) { throw '媒体 DLL 编译失败' }
python -m pip install silk-python==0.2.9
python "$scripts\media.py" --catalog $catalog --source $source --out $view --map $map --cipher $cipher
if ($LASTEXITCODE -ne 0) { throw '媒体导出失败' }

$owner = Read-Host '备份所属的 QQ 号'
$table = Read-Host '输入目标私聊表全名'
python "$scripts\render.py" --catalog $catalog --map $map --out $view --self $owner --table $table
```

可在同一次 `render.py` 调用末尾加以下参数，然后再执行。它们均为可选项。

| 参数 | 指向的本机目录 | 用途 |
|---|---|---|
| `--faces` | `nt_qq\global\nt_data\Emoji\emoji-resource` | 按编号取 `sysface_res\apng\s<编号>.png`，其次取静态图 |
| `--default-faces` | 安装版本的 `resources\app\resource\default-emojis` | 补齐客户端的静态系统表情 |
| `--cache` | 备份所属账号的 `nt_qq\nt_data` | 检查 Ptt、Pic、Video、Emoji，仅复制实际内容 MD5 匹配且格式符合消息种类的缓存 |

`media.py` 每份索引库运行一次，使用新的网页目录；`render.py` 对该库的每个目标表运行一次。网页名为 `msg_3_<对方账号>.html`。查看器以北京时间显示完整日期和时间，可按月份筛选、搜索正文或引用，支持点图放大、点击语音气泡及内嵌视频播放。

## 数据匹配规则

- `filecontext.dbfileResid` 指向分片的 `resfile.resId`，从 `filedata` 读实际内容。内嵌缩略图与原图的 MD5 可以不同，保留原始字节和数据库关联，并计算资源本身的内容哈希。
- 外置资源按 `filename` 在该批次查找唯一文件。已测试的大文件格式用 `filekey` 对首、尾各 512 KiB 的小端 32 位字执行 XXTEA 逆运算。长度不符、区块重叠或布局未知的文件单独计数。外置文件与元数据 MD5 不符时默认不进入网页。要人工复核，首次运行 `media.py` 时加 `--review <私人候选目录>` 保存候选字节，使用解码器检查完整音视频并记录坏帧。文件头可读或播放器能启动都不足以认定完整。
- 按文件内容识别 JPEG、PNG/APNG、GIF、WebP、MP4、MP3 或 SILK。保留原始 SILK，另转为 24 kHz 单声道 16 位 PCM WAV 供浏览器播放。网页所需文件按内容 SHA-256 命名。
- 消息从 `extensionData` 的 protobuf 路径 `5 → 40800` 逐元素解析，`45002` 是类型，`45101` 是正文，`45406` 可携带原资源的 16 字节 MD5，`47601` 是系统表情编号。通话的 `48157` 或 `48153` 是状态或时长文字，不代表存在通话录音。
- 资源表通过 `msgSeq + msgRandom` 以及可用的 `extraData.msgTime` 匹配。优先使用元素自身的哈希；避免把相同序号下另一条消息的附件挂过来。资源缺失和未知消息类型均保留占位。不同版本和不同备份不会具有相同覆盖率。

## 验收和打包

1. 对每个目标表用 `SELECT count(*), min(msgTime), max(msgTime) FROM "<已核对的表名>"` 对照导出行数和日期范围。区分消息条数、消息元素数和唯一媒体文件数。
2. 在浏览器打开 HTML，抽查跨日分页、搜索、图片打开与关闭、表情、语音的播放和暂停、视频时间轴前进。动态资源是否缺失以原备份和校验结果为准。
3. 只把选定会话的网页放在本次网页目录中。运行下方命令收集这些网页及其引用的附件，检查唯一消息 ID、ZIP 的 CRC 和压缩包内网页内容。解压至新目录后离线打开 HTML。数据库、密钥和待复核候选不在包内。

```powershell
python "$scripts\package.py" $view (Join-Path $work 'QQ聊天记录-网页和媒体.zip')
```
