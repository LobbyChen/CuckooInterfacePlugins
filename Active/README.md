# Active 插件贡献指南

本目录用于收录 CuckooInterface 的 **Active（应用层）插件**。

Active 插件主要负责消费事件并执行具体业务逻辑，例如响应平台事件、执行自动化操作，或将多个基础能力组合成完整功能。

## Active 插件的工作方式

典型事件流如下：

```text
Base 插件 -- 发布事件 --> EventBus -- 分发事件 --> Active 插件回调
```

Active 插件通过 `META-INF.json` 的 `listeners` 字段声明要订阅的事件，并在插件入口代码中注册对应回调。

**注意：Active 订阅的事件必须由某个已加载的 Base 插件提供。** 事件名称应与 Base 声明的名称完全一致。

## 开发入口与参考资料

主仓库当前提供以下开发资料：

- [Python SDK 文档](https://github.com/LobbyChen/CuckooInterface/blob/master/implement/Kernel/PythonKernel/sdk/cuckoo_sdk/sdk.md)
- [Python Active 示例](https://github.com/LobbyChen/CuckooInterface/tree/master/implement/Kernel/PythonKernel/sample_plugin/PythonActiveDemo)
- [Lua Kernel 与 Lua SDK 说明](https://github.com/LobbyChen/CuckooInterface/blob/master/implement/Kernel/LuaKernel/README.md)
- [CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)

Python SDK 提供事件订阅、事件发布、日志和插件配置等能力。Lua Kernel 也提供相应接口。使用其他 Kernel 时，请遵循该 Kernel 的 SDK 文档。

## 贡献方式

欢迎通过 Pull Request（PR）贡献 Active 插件。

请在 PR 中创建一个独立的插件文件夹，名称清晰且以 `Active` 结尾。例如：

```text
Active/
└── ExampleActive/
    ├── README.md
    ├── META-INF.json
    ├── main.py
    └── ...
```

上例以 Python 插件为例；Lua 或其他运行时插件可根据对应 Kernel 的入口约定调整文件结构。

## 插件元数据

每个 Active 插件都应提供 `META-INF.json`。关键字段如下：

| 字段 | 说明 |
| --- | --- |
| `name` | 插件显示名称 |
| `id` | 插件唯一标识，建议使用反向域名格式 |
| `type` | 固定为 `30`，表示 Active |
| `version` | 插件版本，建议遵循语义化版本 |
| `description` | 插件功能简介 |
| `runtime_type` | 对应 Kernel 的运行时标识，例如 `python` |
| `listeners` | 本插件订阅的事件名称数组 |
| `tag` | 可选标签数组 |

Python Active 插件元数据示例：

```json
{
  "name": "ExampleActive",
  "id": "com.example.active",
  "type": 30,
  "version": "1.0.0",
  "description": "响应示例事件",
  "runtime_type": "python",
  "tag": ["example"],
  "listeners": ["example.event"]
}
```

## Python 示例

安装或配置好 Python SDK 后，可以使用 `@on_event` 注册事件回调：

```python
import json
from cuckoo_sdk import on_event, log_info, log_error

@on_event("example.event")
def handle_example(payload: str) -> None:
    try:
        data = json.loads(payload)
        log_info(f"收到事件：{data}")
    except (json.JSONDecodeError, TypeError) as exc:
        log_error(f"事件载荷解析失败：{exc}")
```

回调收到的 `payload` 是 JSON 字符串。事件名称必须在 `META-INF.json` 的 `listeners` 数组中声明，并且应由 Base 插件提供。

## 打包与使用

插件源码目录应包含元数据、入口代码及运行所需资源。按照对应 Kernel 的要求组织并打包插件；主程序运行时会从用户插件目录加载插件包：

- Active 插件包：放入 CuckooInterface 的 `user/Active/` 目录。
- Core 会扫描并解压插件，根据 `runtime_type` 找到匹配的 Kernel，再由 Kernel 加载和执行插件。

具体打包格式和入口文件约定请以所使用 Kernel 的 SDK 文档为准。

## PR 检查清单

- [ ] 插件目录名以 `Active` 结尾，例如 `ExampleActive`。
- [ ] 包含完整且有效的 `META-INF.json`，其中 `type` 为 `30`。
- [ ] `id` 唯一，`runtime_type` 与目标 Kernel 一致。
- [ ] 所有订阅事件均在 `listeners` 中声明。
- [ ] 订阅的事件已由某个 Base 插件提供，名称完全匹配。
- [ ] 附带中文 README，说明功能、依赖、配置、安装和使用方法。
- [ ] 已在对应 Kernel 环境中完成基本测试。

请在 PR 描述中说明插件用途、依赖环境、所需 Base 事件、测试方式和已知限制。不要提交密钥、个人配置或无关构建产物。

---
插件体系和 SDK 的详细说明请参阅[CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)。
