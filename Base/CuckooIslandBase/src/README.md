# CuckooIslandBridge（桥接插件源码）

注入到 ClassIsland 的小插件，职责只有一个：
把 `../island-bridge/bridge/notifications.jsonl` 里的新行读出来，用 ClassIsland 的提醒系统显示。

编译产物会被复制到上一层的 `island-bridge/`，由 Python 插件在注入时原样复制进 ClassIsland。

## 文件

| 文件 | 作用 |
| --- | --- |
| `Plugin.cs` | `[PluginEntrance]` + `PluginBase`，注册提醒提供方 |
| `CuckooNotificationProvider.cs` | `NotificationProviderBase` + `[NotificationProviderInfo]`，轮询队列并弹提醒 |
| `manifest.yml` | ClassIsland 插件清单（`apiVersion: 2.0.0.0`） |
| `CuckooIslandBridge.csproj` | net8.0 类库，引用 ClassIsland 程序集（`Private=false`，不复制） |

## 构建

```powershell
# 推荐：在上层目录执行，自动同步产物并打包
../build.ps1 -ClassIslandDir "D:\Apps\ClassIsland"

# 只编译
dotnet build CuckooIslandBridge.csproj -c Release -p:ClassIslandDir="D:\Apps\ClassIsland\app-2.1.0.1-0"
```

`ClassIslandDir` 指向包含 `ClassIsland.Core.dll` 的目录（安装根目录下的 `app-x.y.z`）。

## 队列格式

`<插件目录>/bridge/notifications.jsonl`，每行一个 JSON 对象：

```json
{"id":"1794766074326","ts":1794766074,"title":"上课 · 语文","message":"第 3/15 节 08:20 - 09:00","duration":8}
```

- `title`：提醒遮罩文字；
- `message`：提醒正文，可为空；
- `duration`：显示时长（秒），限制在 2–120，默认 6；
- 插件启动时把读取偏移定位到文件末尾，**不补发历史提醒**。

## 注意事项

- 队列路径由 `Assembly.Location` 推导，**不要**把 DLL 单独挪出插件目录；
- `NotificationProviderInfo` 的 GUID 固定为 `8D1F0A7C-5B2E-4E4A-9C1D-6A3B7E2F4C90`，改动会导致用户设置失效；
- 与 ClassIsland 2.1.0 的 `ClassIsland.Core.dll` 编译通过；更低版本可能缺少 `NotificationRequest` 相关成员。
