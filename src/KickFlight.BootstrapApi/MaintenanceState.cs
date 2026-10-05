using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KickFlight.BootstrapApi;

public enum MaintenanceMode
{
    /// <summary>Normal service.</summary>
    Off,
    /// <summary>Players keep playing; /home/index shows one notice window with the warning text.</summary>
    Warning,
    /// <summary>Every POST except boot and the end of running battles answers 503 (TitleMaintenanceWindow).</summary>
    Hard
}

public sealed record MaintenanceSnapshot(
    [property: JsonConverter(typeof(JsonStringEnumConverter))] MaintenanceMode Mode,
    string Title,
    string Message,
    int NoticeId,
    DateTime ChangedAtUtc);

/// <summary>
/// Server-side maintenance switch, driven only by what the API answers (no client change): Warning adds a
/// userNoticeList entry to /home/index, Hard makes DemoSessionApi answer the client's maintenance error. Set through the
/// loopback-only /admin/maintenance endpoint and persisted to &lt;content root&gt;/data/maintenance.json (next to the JSON
/// player store's data/users) so an API restart keeps it. Maintenance:FilePath overrides the location (tests).
///
/// In Hard mode a diagnostic client build still gets through: the client sends x-app-application-version, and a value
/// ending in Maintenance:BypassVersionSuffix (default "-diag", case-insensitive) is served normally instead of the 503
/// / 401. The gRPC matchmaking path learns the same thing from the ticket's registering /battle/entry request (and,
/// when present, the gRPC metadata of the GetAssignments call itself).
/// </summary>
public sealed class MaintenanceState
{
    public const string DefaultTitle = "Maintenance";
    public const string DefaultWarningMessage =
        "The server will go down for maintenance shortly. Please finish your match.";
    public const string DefaultHardMessage = "The server is under maintenance. Please try again in a few minutes.";
    public const string DefaultBypassVersionSuffix = "-diag";

    private static readonly JsonSerializerOptions FileJson = new() { WriteIndented = true };

    private readonly ILogger<MaintenanceState> _logger;
    private readonly object _lock = new();
    private MaintenanceSnapshot _current = new(MaintenanceMode.Off, "", "", 0, DateTime.UtcNow);

    public MaintenanceState(ILogger<MaintenanceState> logger, IWebHostEnvironment environment, IConfiguration configuration)
        : this(logger, configuration["Maintenance:FilePath"] is { Length: > 0 } configured
            ? configured
            : Path.Combine(environment.ContentRootPath, "data", "maintenance.json"),
            configuration["Maintenance:BypassVersionSuffix"])
    {
    }

    public MaintenanceState(ILogger<MaintenanceState> logger, string filePath, string? bypassVersionSuffix = null)
    {
        _logger = logger;
        FilePath = Path.GetFullPath(filePath);
        BypassVersionSuffix = string.IsNullOrWhiteSpace(bypassVersionSuffix)
            ? DefaultBypassVersionSuffix
            : bypassVersionSuffix.Trim();
        Load();
    }

    public string FilePath { get; }

    /// <summary>Suffix that marks a diagnostic build, e.g. the "-diag" in "2.11.1-diag". Never empty.</summary>
    public string BypassVersionSuffix { get; }

    /// <summary>
    /// True when the client's x-app-application-version ends in the configured DIAG suffix (case-insensitive), i.e. a
    /// diagnostic build allowed through Hard maintenance. A production version such as "2.11.1" never matches.
    /// </summary>
    public bool IsBypassClient(string? clientVersion) =>
        !string.IsNullOrWhiteSpace(clientVersion)
        && clientVersion.Trim().EndsWith(BypassVersionSuffix, StringComparison.OrdinalIgnoreCase);

    /// <summary>Immutable snapshot; read it once per request so mode and text stay consistent.</summary>
    public MaintenanceSnapshot Current
    {
        get { lock (_lock) return _current; }
    }

    /// <summary>
    /// Switches the mode and text. Empty title/message fall back to the defaults for that mode. The notice id only
    /// changes when the warning text (or entering Warning) changes, so the same warning keeps one id.
    /// </summary>
    public MaintenanceSnapshot Set(MaintenanceMode mode, string? title, string? message)
    {
        MaintenanceSnapshot previous, next;
        lock (_lock)
        {
            previous = _current;
            var resolvedTitle = string.IsNullOrWhiteSpace(title) ? DefaultTitle : title.Trim();
            var resolvedMessage = string.IsNullOrWhiteSpace(message)
                ? mode == MaintenanceMode.Hard ? DefaultHardMessage : DefaultWarningMessage
                : message.Trim();
            if (mode == MaintenanceMode.Off)
            {
                resolvedTitle = "";
                resolvedMessage = "";
            }

            var noticeId = previous.NoticeId;
            if (mode == MaintenanceMode.Warning
                && (previous.Mode != MaintenanceMode.Warning || previous.Title != resolvedTitle || previous.Message != resolvedMessage))
            {
                // Unix seconds keeps ids increasing even if the state file is lost with a recreated container.
                noticeId = (int)Math.Max(previous.NoticeId + 1L, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            }

            next = new MaintenanceSnapshot(mode, resolvedTitle, resolvedMessage, noticeId, DateTime.UtcNow);
            _current = next;
            Save(next);
        }

        if (previous.Mode != next.Mode)
        {
            _logger.LogInformation("Maintenance mode {PreviousMode} -> {Mode}: {Title} / {Message}",
                previous.Mode, next.Mode, next.Title, next.Message);
        }
        else
        {
            _logger.LogInformation("Maintenance text updated ({Mode}): {Title} / {Message}", next.Mode, next.Title, next.Message);
        }
        return next;
    }

    /// <summary>The ResponseUserNotice list /home/index sends: one entry in Warning, none otherwise.</summary>
    public object[] BuildUserNoticeList()
    {
        var current = Current;
        if (current.Mode != MaintenanceMode.Warning) return [];
        return
        [
            new
            {
                userNoticeId = current.NoticeId,
                title = current.Title,
                message = current.Message,
                // Same "yyyy-MM-dd HH:mm:ss" wall-clock format as every other datetime the API serves.
                sentDatetime = current.ChangedAtUtc.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
            }
        ];
    }

    /// <summary>Plaintext (not D2C-encrypted) error body the client turns into TitleMaintenanceWindow.</summary>
    public string BuildHardErrorJson()
    {
        var current = Current;
        // "1000" opens the maintenance window; never "1999", which makes the client retry.
        return JsonSerializer.Serialize(new { error = new { code = "1000", title = current.Title, message = current.Message } });
    }

    private void Load()
    {
        if (!File.Exists(FilePath)) return;
        try
        {
            var loaded = JsonSerializer.Deserialize<MaintenanceSnapshot>(File.ReadAllText(FilePath), FileJson);
            if (loaded is null) return;
            _current = loaded with { Title = loaded.Title ?? "", Message = loaded.Message ?? "" };
            _logger.LogInformation("Loaded maintenance mode {Mode} from {Path}", _current.Mode, FilePath);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning("Could not read maintenance state {Path}, starting with Off: {Error}", FilePath, ex.Message);
        }
    }

    private void Save(MaintenanceSnapshot snapshot)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            // Write then rename, so a crash mid-write cannot leave a truncated file that loads as Off.
            var temporary = FilePath + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(snapshot, FileJson));
            File.Move(temporary, FilePath, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // The switch still applies to this process; it only would not survive a restart.
            _logger.LogWarning("Could not persist maintenance state to {Path}: {Error}", FilePath, ex.Message);
        }
    }
}

/// <summary>
/// GET/POST /admin/maintenance. Only for a caller on the API's own loopback with no proxy headers: nginx (the cdn
/// sidecar) adds X-Real-IP / X-Forwarded-For and connects from another container, so nothing from outside gets in.
/// Use it from inside the container:
///   docker exec deploy-api-1 curl -s -X POST http://127.0.0.1:8080/admin/maintenance -d '{"mode":"warning","message":"..."}'
/// Anyone else - and every other /admin path - gets a plain 404.
/// </summary>
public static class MaintenanceAdmin
{
    public static bool IsLocalAdmin(HttpContext context)
    {
        if (context.Request.Headers.ContainsKey("X-Forwarded-For") || context.Request.Headers.ContainsKey("X-Real-IP"))
            return false;
        var remote = context.Connection.RemoteIpAddress;
        return remote is not null && System.Net.IPAddress.IsLoopback(remote.IsIPv4MappedToIPv6 ? remote.MapToIPv4() : remote);
    }

    public static IResult Get(HttpContext context, MaintenanceState maintenance) =>
        IsLocalAdmin(context) ? Status(maintenance.Current) : Results.NotFound();

    public static async Task<IResult> PostAsync(HttpContext context, MaintenanceState maintenance)
    {
        if (!IsLocalAdmin(context)) return Results.NotFound();

        MaintenanceMode mode;
        string? title = null, message = null;
        try
        {
            using var document = await JsonDocument.ParseAsync(context.Request.Body);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("mode", out var modeProperty)
                || !TryParseMode(modeProperty, out mode))
            {
                return Results.BadRequest(new { error = "mode must be off, warning or hard" });
            }
            if (root.TryGetProperty("title", out var titleProperty) && titleProperty.ValueKind == JsonValueKind.String)
                title = titleProperty.GetString();
            if (root.TryGetProperty("message", out var messageProperty) && messageProperty.ValueKind == JsonValueKind.String)
                message = messageProperty.GetString();
        }
        catch (JsonException ex)
        {
            return Results.BadRequest(new { error = "body must be JSON {mode, title, message}", detail = ex.Message });
        }

        return Status(maintenance.Set(mode, title, message));
    }

    private static bool TryParseMode(JsonElement property, out MaintenanceMode mode)
    {
        mode = MaintenanceMode.Off;
        if (property.ValueKind == JsonValueKind.Number && property.TryGetInt32(out var number)
            && Enum.IsDefined(typeof(MaintenanceMode), number))
        {
            mode = (MaintenanceMode)number;
            return true;
        }
        return property.ValueKind == JsonValueKind.String
            && !int.TryParse(property.GetString(), out _)
            && Enum.TryParse(property.GetString(), ignoreCase: true, out mode);
    }

    private static IResult Status(MaintenanceSnapshot current) => Results.Json(new
    {
        mode = current.Mode.ToString().ToLowerInvariant(),
        title = current.Title,
        message = current.Message,
        noticeId = current.NoticeId,
        changedAtUtc = current.ChangedAtUtc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture)
    });
}
