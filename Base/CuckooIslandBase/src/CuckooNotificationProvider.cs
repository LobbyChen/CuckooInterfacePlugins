using System.Text;
using System.Text.Json;
using ClassIsland.Core.Abstractions.Services.NotificationProviders;
using ClassIsland.Core.Attributes;
using ClassIsland.Core.Models.Notification;
using Microsoft.Extensions.Hosting;

namespace CuckooIslandBridge;

/// <summary>
/// 读取 CuckooInterface 侧写入的提醒队列，转成 ClassIsland 提醒。
///
/// 队列文件：&lt;插件目录&gt;/bridge/notifications.jsonl
/// 每行一个 JSON 对象：
///   { "id": "唯一 id", "ts": 1700000000, "title": "标题",
///     "message": "正文（可选）", "duration": 6, "level": "info" }
/// 采用「追加 + 偏移量」方式读取，不依赖命名管道，跨进程且对 ClassIsland 无侵入。
/// </summary>
[NotificationProviderInfo(
    "8D1F0A7C-5B2E-4E4A-9C1D-6A3B7E2F4C90",
    "CuckooInterface 联动",
    "\uE8F2",
    "接收 CuckooInterface 插件平台推送的事件，并以提醒的形式显示。")]
public class CuckooNotificationProvider : NotificationProviderBase, IHostedService
{
    private const int PollIntervalMs = 700;
    private const int MaxLinesPerPoll = 8;
    private const double DefaultDurationSeconds = 6;

    private readonly object _gate = new();
    private CancellationTokenSource? _cts;
    private Task? _worker;
    private long _offset;
    private bool _primed;

    private static string BridgeDirectory =>
        Path.Combine(Path.GetDirectoryName(typeof(Plugin).Assembly.Location)!, "bridge");

    private static string QueuePath => Path.Combine(BridgeDirectory, "notifications.jsonl");

    // ClassIsland 的 AddNotificationProvider 会把该类型注册为 IHostedService，
    // 这里显式实现接口，避免与基类里同一签名的方法冲突。
    Task IHostedService.StartAsync(CancellationToken cancellationToken) => StartBridgeAsync(cancellationToken);

    Task IHostedService.StopAsync(CancellationToken cancellationToken) => StopBridgeAsync(cancellationToken);

    private Task StartBridgeAsync(CancellationToken cancellationToken)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _worker = Task.Run(() => LoopAsync(_cts.Token), CancellationToken.None);
        return Task.CompletedTask;
    }

    private async Task StopBridgeAsync(CancellationToken cancellationToken)
    {
        _cts?.Cancel();
        if (_worker is not null)
        {
            try
            {
                await _worker.WaitAsync(TimeSpan.FromSeconds(3), cancellationToken);
            }
            catch (Exception)
            {
                // 退出阶段忽略超时/取消。
            }
        }

        _cts?.Dispose();
        _cts = null;
        _worker = null;
    }

    private async Task LoopAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            try
            {
                var lines = ReadPendingLines();
                foreach (var line in lines)
                {
                    if (token.IsCancellationRequested)
                    {
                        break;
                    }

                    if (TryParse(line, out var title, out var message, out var duration))
                    {
                        await ShowAsync(title, message, duration);
                    }
                }
            }
            catch (Exception)
            {
                // 队列文件被占用/删除属于正常情况，等待下一轮。
            }

            try
            {
                await Task.Delay(PollIntervalMs, token);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
    }

    private async Task ShowAsync(string title, string message, double durationSeconds)
    {
        var duration = TimeSpan.FromSeconds(Math.Clamp(durationSeconds, 2, 120));

        var request = new NotificationRequest
        {
            MaskContent = new NotificationContent(title)
            {
                Duration = duration,
                SpeechContent = title,
                IsSpeechEnabled = false
            },
            OverlayContent = string.IsNullOrWhiteSpace(message)
                ? null
                : new NotificationContent(message)
                {
                    Duration = duration,
                    SpeechContent = message,
                    IsSpeechEnabled = false
                }
        };

        await ShowNotificationAsync(request);
    }

    private List<string> ReadPendingLines()
    {
        var result = new List<string>(MaxLinesPerPoll);
        var path = QueuePath;
        if (!File.Exists(path))
        {
            lock (_gate)
            {
                _offset = 0;
                _primed = false;
            }
            return result;
        }

        lock (_gate)
        {
            using var stream = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);

            if (!_primed)
            {
                // 首次启动时跳过历史提醒，避免 ClassIsland 刚启动就被旧事件刷屏。
                _offset = stream.Length;
                _primed = true;
                return result;
            }

            if (stream.Length < _offset)
            {
                _offset = 0;
            }

            if (stream.Length == _offset)
            {
                return result;
            }

            stream.Seek(_offset, SeekOrigin.Begin);
            // 限制单轮读取量，并且只推进到已消费的完整行末尾。
            var available = (int)Math.Min(stream.Length - _offset, 1024 * 1024);
            var buffer = new byte[available];
            var read = stream.Read(buffer, 0, buffer.Length);
            var lineStart = 0;
            var consumed = 0;

            for (var i = 0; i < read; i++)
            {
                if (buffer[i] != (byte)'\n')
                {
                    continue;
                }

                var line = Encoding.UTF8.GetString(buffer, lineStart, i - lineStart);
                var trimmed = line.Trim('\r', ' ', '\t');
                if (trimmed.Length > 0)
                {
                    result.Add(trimmed);
                }

                lineStart = i + 1;
                consumed = lineStart;
                if (result.Count >= MaxLinesPerPoll)
                {
                    break;
                }
            }

            // 未遇到换行的尾部可能只是尚未写完的 JSON，留给下一轮继续读取。
            _offset += consumed;
        }

        return result;
    }

    private static bool TryParse(string line, out string title, out string message, out double duration)
    {
        title = string.Empty;
        message = string.Empty;
        duration = DefaultDurationSeconds;

        try
        {
            using var document = JsonDocument.Parse(line);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            title = ReadString(root, "title");
            message = ReadString(root, "message");

            if (root.TryGetProperty("duration", out var durationElement) &&
                durationElement.ValueKind == JsonValueKind.Number)
            {
                duration = durationElement.GetDouble();
            }

            return title.Length > 0 || message.Length > 0;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string ReadString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var element) || element.ValueKind != JsonValueKind.String)
        {
            return string.Empty;
        }

        return element.GetString()?.Trim() ?? string.Empty;
    }
}
