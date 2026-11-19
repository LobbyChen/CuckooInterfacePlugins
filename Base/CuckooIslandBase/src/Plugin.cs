using ClassIsland.Core.Abstractions;
using ClassIsland.Core.Attributes;
using ClassIsland.Core.Extensions.Registry;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace CuckooIslandBridge;

/// <summary>
/// ClassIsland 侧桥接插件入口。
/// 只做一件事：注册提醒提供方，让 CuckooInterface 的事件能以 ClassIsland 提醒的形式出现。
/// </summary>
[PluginEntrance]
public class Plugin : PluginBase
{
    public override void Initialize(HostBuilderContext context, IServiceCollection services)
    {
        services.AddNotificationProvider<CuckooNotificationProvider>();
    }
}
