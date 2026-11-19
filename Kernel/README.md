# Kernel 插件贡献指南

本目录用于收录 CuckooInterface 的 **Kernel（运行时内核）**实现。

CuckooInterface 是面向电教场景、运行于 Windows 的插件运行时与宿主管理平台。Kernel 位于插件体系的底层，负责提供具体语言或脚本环境，并加载、执行与管理对应的 Base / Active 插件。

## Kernel 的职责

Kernel 主要负责：

- 提供一种插件运行时，例如 Python、Lua 或其他语言环境。
- 实现 CuckooInterface 定义的 Kernel ABI，并通过宿主注入的 `CuckooHostAPI` 与 Core 交互。
- 加载插件、生成插件描述信息、触发事件回调，并处理插件卸载。
- 管理运行时初始化、主循环和关闭等生命周期。
- 按需提供运行时状态、设置面板和操作接口。

Kernel 与 Base / Active 不同：**Kernel 是运行插件的运行时实现；Base 和 Active 是由 Kernel 加载的具体功能插件。**

## 现有参考实现

建议在开发前先阅读主仓库中的实现和接口：

- [CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)
- [Kernel ABI：cuckoo_kernel.h](https://github.com/LobbyChen/CuckooInterface/blob/master/plugins/cuckoo_kernel.h)
- [插件描述结构：cuckoo_plugin.h](https://github.com/LobbyChen/CuckooInterface/blob/master/plugins/cuckoo_plugin.h)
- [PythonKernel](https://github.com/LobbyChen/CuckooInterface/tree/master/implement/Kernel/PythonKernel)
- [LuaKernel](https://github.com/LobbyChen/CuckooInterface/tree/master/implement/Kernel/LuaKernel)

当前主仓库包含 PythonKernel 和 LuaKernel 两种参考实现。Kernel ABI 仍可能演进，开发时请以主仓库当前接口为准。

## 贡献方式

欢迎通过 Pull Request（PR）提交新的 Kernel。

请在 PR 中创建一个独立目录，目录名使用有辨识度的名称，并以 `Kernel` 结尾。例如：

```text
Kernel/
└── ExampleKernel/
    ├── README.md
    ├── META-INF.json
    ├── src/
    ├── build.*
    └── ...
```

以上仅为建议的源码组织方式；可根据所使用的语言和构建系统调整，但请确保文档能够说明如何构建和使用。

## 元数据要求

Kernel 的 `META-INF.json` 至少应提供以下信息：

| 字段 | 说明 |
| --- | --- |
| `name` | Kernel 显示名称 |
| `id` | 全局唯一标识，建议使用反向域名格式 |
| `type` | 固定为 `10`，表示 Kernel |
| `version` | Kernel 版本 |
| `description` | 功能简介 |
| `runtime_type` | 运行时类型标识，例如 `python` 或 `lua` |
| `tag` | 可选标签数组 |

参考示例：

```json
{
  "name": "Example Kernel",
  "id": "com.example.kernel",
  "type": 10,
  "version": "1.0.0",
  "description": "Example runtime kernel",
  "runtime_type": "example",
  "tag": ["kernel", "example"]
}
```

## 实现与兼容性

提交前请检查：

- 正确导出 `get_cuckoo_kernel_interface`，并返回有效的 `CuckooKernelInterface`。
- 正确实现运行时初始化、插件加载、回调分发、插件卸载和运行时关闭等必要生命周期。
- 使用宿主提供的 API 进行日志、事件、配置等宿主交互，不要假定宿主内部实现细节。
- 如果实现 Runtime Control Plane，请说明状态、设置和操作接口的用途及 JSON 格式。
- 明确运行所需的系统环境、依赖项、构建工具和目标架构。
- 对加载失败、插件异常和资源释放等情况进行妥善处理。

## PR 内容要求

请在插件目录中附带中文 README，至少说明：

1. Kernel 的用途、支持的语言或运行时。
2. 支持的 CuckooInterface / ABI 版本或兼容性说明。
3. 构建环境、依赖和完整构建步骤。
4. 安装、配置和使用方式。
5. 已知限制及需要用户额外安装的运行时。

PR 描述中请概述实现思路、测试环境和验证结果。请勿提交编译产物、缓存、个人配置或密钥。

---
如需了解插件体系整体设计，请先阅读[主仓库 README](https://github.com/LobbyChen/CuckooInterface/blob/master/readme.md)。
