# Base 插件贡献指南

本目录用于收录 CuckooInterface 的 **Base（基础能力）插件**。

Base 插件主要负责向 CuckooInterface 提供基础功能和事件，是平台能力与事件的提供者。它可以监控设备或进程、提供基础服务，并通过 EventBus 向其他插件发布事件。

## Base 插件的工作方式

典型事件流如下：

```text
Base 插件 -- emit_event() --> EventBus --> Active 插件
```

Base 插件需要在 `META-INF.json` 的 `events` 字段中声明自己提供的事件。运行时通过 SDK 或对应 Kernel 提供的接口发布事件。

**注意：事件名称需要全局唯一。** Active 插件只能订阅已由 Base 插件提供并注册的事件。

## 开发入口与参考资料

Base / Active 插件由 Kernel 加载执行。主仓库当前提供：

- [Python SDK 文档](https://github.com/LobbyChen/CuckooInterface/blob/master/implement/Kernel/PythonKernel/sdk/cuckoo_sdk/sdk.md)
- [Python Base 示例](https://github.com/LobbyChen/CuckooInterface/tree/master/implement/Kernel/PythonKernel/sample_plugin/PythonBaseDemo)
- [Lua Kernel 与 Lua SDK 说明](https://github.com/LobbyChen/CuckooInterface/blob/master/implement/Kernel/LuaKernel/README.md)
- [CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)

Python SDK 提供事件发布、日志和插件配置等能力。Lua Kernel 也提供对应的 SDK 接口。使用其他 Kernel 时，请以该 Kernel 提供的 SDK 和文档为准。

## 贡献方式

欢迎通过 Pull Request（PR）贡献 Base 插件。

请在 PR 中创建一个独立的插件文件夹，名称清晰且以 `Base` 结尾。例如：

```text
Base/
└── ExampleBase/
    ├── README.md
    ├── META-INF.json
    ├── main.py
    └── ...
```

上例以 Python 插件为例；如果使用 Lua 或其他运行时，请按对应 Kernel 的入口文件和项目结构组织。

## 插件元数据

每个 Base 插件都应提供 `META-INF.json`。关键字段如下：

| 字段 | 说明 |
| --- | --- |
| `name` | 插件显示名称 |
| `id` | 插件唯一标识，建议使用反向域名格式 |
| `type` | 固定为 `42`，表示 Base |
| `version` | 插件版本，建议遵循语义化版本 |
| `description` | 插件功能简介 |
| `runtime_type` | 对应 Kernel 的运行时标识，例如 `python` |
| `events` | 本插件提供的事件名称数组 |
| `tag` | 可选标签数组 |

Python Base 插件元数据示例：

```json
{
  "name": "ExampleBase",
  "id": "com.example.base",
  "type": 42,
  "version": "1.0.0",
  "description": "提供示例事件",
  "runtime_type": "python",
  "tag": ["example"],
  "events": ["example.event"]
}
```

## Python 示例

安装或配置好 Python SDK 后，可以通过 `emit_event` 发布已声明的事件：

```python
from cuckoo_sdk import emit_event, log_info

def main():
    log_info("ExampleBase 已加载")
    emit_event("example.event", {"message": "Hello CuckooInterface"})

main()
```

事件名称必须同时出现在 `META-INF.json` 的 `events` 数组中，否则事件不会按预期分发。

## 打包与使用

插件源码目录应包含元数据、入口代码及运行所需资源。按照对应 Kernel 的要求组织并打包插件；主程序运行时会从用户插件目录加载插件包：

- Base 插件包：放入 CuckooInterface 的 `user/Base/` 目录。
- 插件运行时会由 Core 扫描、解压，并根据 `runtime_type` 选择匹配的 Kernel。

具体打包格式和入口文件约定请以所使用 Kernel 的 SDK 文档为准。

## PR 检查清单

- [ ] 插件目录名以 `Base` 结尾，例如 `ExampleBase`。
- [ ] 包含完整且有效的 `META-INF.json`，其中 `type` 为 `42`。
- [ ] `id` 唯一，`runtime_type` 与目标 Kernel 一致。
- [ ] 所有发布事件均在 `events` 中声明，事件名清晰且唯一。
- [ ] 附带中文 README，说明功能、依赖、配置、安装和使用方法。
- [ ] 已在对应 Kernel 环境中完成基本测试。

请在 PR 描述中说明插件用途、依赖环境、测试方式和已知限制。不要提交密钥、个人配置或无关构建产物。

---
插件体系和 SDK 的详细说明请参阅[CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)。
