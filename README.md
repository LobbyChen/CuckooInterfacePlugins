# CuckooInterfacePlugins

**CuckooInterface 的插件与扩展仓库。**

本仓库用于收录 CuckooInterface 的 Kernel、Base 和 Active 插件，欢迎开发者通过 Pull Request（PR）提交插件，与社区共同扩展 CuckooInterface 的能力。

CuckooInterface 主项目：[LobbyChen/CuckooInterface](https://github.com/LobbyChen/CuckooInterface)

## 插件类型

CuckooInterface 的插件体系分为三种类型：

| 类型 | 目录 | 说明 | 元数据类型值 |
| --- | --- | --- | --- |
| Kernel | [Kernel/](./Kernel/) | 运行时内核，为插件提供语言或脚本运行环境，并负责加载和执行 Base / Active 插件 | `10` |
| Base | [Base/](./Base/) | 基础能力插件，提供平台功能并向 EventBus 发布事件 | `42` |
| Active | [Active/](./Active/) | 应用层插件，订阅事件并执行相应的业务逻辑 | `30` |

### 插件之间的关系

通常，Base 插件负责提供能力和发布事件，Active 插件负责订阅事件并响应。Kernel 为它们提供运行时支持。

```text
                  CuckooInterface Core
                          |
                 +--------+--------+
                 |                 |
              Kernel            EventBus
                 |                 |
          +------+-----+           |
          |            |           |
        Base         Active <------+
     发布事件       订阅并处理事件
```

- **Kernel**：运行时层。负责初始化运行环境、加载插件、分发回调以及管理插件生命周期。
- **Base**：基础能力层。可通过 SDK 或对应 Kernel 提供的接口发布事件。
- **Active**：应用逻辑层。通过订阅事件，将基础能力组合成具体功能。

不同 Kernel 的 SDK、入口文件和打包方式可能不同。开发插件时，请以目标 Kernel 的文档为准。

## 仓库结构

```text
CuckooInterfacePlugins/
├── Kernel/
│   └── README.md
├── Base/
│   └── README.md
├── Active/
│   └── README.md
├── LICENSE
└── README.md
```

每种类型的目录都包含独立的贡献指南：

- [Kernel 插件贡献指南](./Kernel/README.md)
- [Base 插件贡献指南](./Base/README.md)
- [Active 插件贡献指南](./Active/README.md)

提交新插件前，请先阅读对应目录中的 README。

## 如何贡献插件

欢迎提交新插件或改进现有插件。所有插件贡献均通过 Pull Request（PR）进行。

### 1. 选择插件类型

根据插件的职责选择对应目录：

- 实现新的语言或脚本运行时：选择 `Kernel`。
- 提供基础服务、设备能力或事件：选择 `Base`。
- 消费事件并实现应用层逻辑：选择 `Active`。

### 2. 创建独立插件目录

请在对应类型目录下创建独立文件夹，目录名称应清晰易懂，并使用类型名称作为后缀：

```text
Kernel/ExampleKernel/
Base/ExampleBase/
Active/ExampleActive/
```

请勿直接将插件源码散放在类型目录根目录中。

### 3. 准备插件文件

每个插件目录应包含自己的说明文档和元数据文件。具体源码结构可根据语言、SDK 和构建系统决定。

建议结构：

```text
Base/
└── ExampleBase/
    ├── README.md
    ├── META-INF.json
    ├── src/
    └── ...
```

其中：

- `README.md`：使用中文介绍插件的用途、功能、依赖、配置、安装和使用方法。
- `META-INF.json`：描述插件名称、唯一 ID、版本、类型、运行时等信息。
- 其他文件：插件源码、资源文件和必要的构建配置。

### 4. 检查元数据

`META-INF.json` 中的 `type` 应与插件目录类型一致：

- Kernel：`10`
- Active：`30`
- Base：`42`

插件 ID 应保持全局唯一，建议采用反向域名格式。Base 插件应在 `events` 中声明提供的事件；Active 插件应在 `listeners` 中声明订阅的事件。

字段要求和示例请参考对应类型的贡献指南及主仓库中的示例插件。

### 5. 提交 Pull Request

完成开发和基本测试后：

1. Fork 本仓库并创建自己的分支。
2. 在正确的类型目录下添加插件文件夹。
3. 确认 README、元数据、依赖说明和必要资源齐全。
4. 在对应 Kernel 环境中完成基本验证。
5. 提交 PR，并在描述中说明插件用途、运行环境、测试方式和已知限制。

PR 应尽量只包含与该插件相关的改动。请勿提交密钥、个人配置、缓存目录或无关的编译产物。

## 开发参考

开始开发前，建议先阅读：

- [CuckooInterface 主仓库](https://github.com/LobbyChen/CuckooInterface)
- [Kernel 插件贡献指南](./Kernel/README.md)
- [Base 插件贡献指南](./Base/README.md)
- [Active 插件贡献指南](./Active/README.md)

主仓库中的 SDK、Kernel 实现和示例插件是了解接口与开发约定的重要参考。若本文档与主仓库当前接口定义存在差异，请以主仓库当前实现和文档为准。

## 许可证

本仓库采用 [MIT License](./LICENSE) 开源。

提交插件时，请确保你拥有所提交代码和资源的必要权利，并在插件自身的 README 中注明其特殊依赖或不同的许可证要求。
