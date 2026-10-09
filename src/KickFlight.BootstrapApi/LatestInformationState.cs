using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KickFlight.BootstrapApi;

public sealed record LatestInformationSnapshot(string Content, DateTime ChangedAtUtc);

/// <summary>
/// Editable announcements shown by the client's Latest Information WebView. Plain Markdown-like text is persisted
/// under data/latest-information.json and rendered as safe HTML; raw HTML is always escaped.
/// </summary>
public sealed class LatestInformationState
{
    public const int MaximumContentLength = 12000;
    public const string DefaultContent = """
**Bienvenido a Kick-Flight**
Este es un servidor privado de pruebas. El progreso es local y puede reiniciarse sin aviso.

**Tienda y gacha**
La tienda y el gacha todavia no estan disponibles; llegaran en una proxima actualizacion.
""";

    private static readonly JsonSerializerOptions FileJson = new() { WriteIndented = true };
    private static readonly Regex InlinePattern = new(
        @"(?<bold>\*\*(?<boldText>.+?)\*\*)|(?<code>`(?<codeText>[^`]+)`)|(?<url>https?://[^\s<>]+)",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private readonly ILogger<LatestInformationState> _logger;
    private readonly object _lock = new();
    private LatestInformationSnapshot _current;

    public LatestInformationState(ILogger<LatestInformationState> logger, IWebHostEnvironment environment, IConfiguration configuration)
        : this(logger, configuration["LatestInformation:FilePath"] is { Length: > 0 } configured
            ? configured
            : Path.Combine(environment.ContentRootPath, "data", "latest-information.json"))
    {
    }

    public LatestInformationState(ILogger<LatestInformationState> logger, string filePath)
    {
        _logger = logger;
        FilePath = Path.GetFullPath(filePath);
        _current = new LatestInformationSnapshot(DefaultContent, DateTime.UtcNow);
        Load();
    }

    public string FilePath { get; }

    public LatestInformationSnapshot Current
    {
        get { lock (_lock) return _current; }
    }

    public LatestInformationSnapshot Set(string? content)
    {
        var normalized = content ?? "";
        if (normalized.Length > MaximumContentLength)
            throw new ArgumentOutOfRangeException(nameof(content), $"content must be {MaximumContentLength} characters or fewer");

        LatestInformationSnapshot next;
        lock (_lock)
        {
            next = new LatestInformationSnapshot(normalized.Replace("\r\n", "\n").Replace('\r', '\n'), DateTime.UtcNow);
            Save(next);
            _current = next;
        }
        _logger.LogInformation("Latest information updated ({Length} characters)", next.Content.Length);
        return next;
    }

    public string BuildHtml()
    {
        var content = Current.Content;
        var body = RenderContent(content);
        if (body.Length == 0) body = "<p>No hay avisos nuevos.</p>";
        return """
<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Latest Information</title><body style="font-family:sans-serif;padding:24px;max-width:640px;margin:auto;line-height:1.5;color:#222">
<h2>Latest Information</h2>
""" + body + "</body></html>";
    }

    private static string RenderContent(string content)
    {
        var output = new StringBuilder();
        var paragraph = new List<string>();
        var inList = false;
        void CloseParagraph()
        {
            if (paragraph.Count == 0) return;
            output.Append("<p>").Append(string.Join("<br>", paragraph.Select(RenderInline))).Append("</p>");
            paragraph.Clear();
        }
        void CloseList()
        {
            if (!inList) return;
            output.Append("</ul>");
            inList = false;
        }

        foreach (var raw in content.Split('\n'))
        {
            var line = raw.TrimEnd();
            if (string.IsNullOrWhiteSpace(line))
            {
                CloseParagraph();
                CloseList();
                continue;
            }
            var heading = Regex.Match(line, @"^(#{1,3})\s+(.+)$");
            if (heading.Success)
            {
                CloseParagraph();
                CloseList();
                var level = Math.Min(heading.Groups[1].Value.Length + 1, 4);
                output.Append("<h").Append(level).Append('>').Append(RenderInline(heading.Groups[2].Value))
                    .Append("</h").Append(level).Append('>');
                continue;
            }
            var bullet = Regex.Match(line, @"^\s*[-*]\s+(.+)$");
            if (bullet.Success)
            {
                CloseParagraph();
                if (!inList)
                {
                    output.Append("<ul>");
                    inList = true;
                }
                output.Append("<li>").Append(RenderInline(bullet.Groups[1].Value)).Append("</li>");
                continue;
            }
            CloseList();
            paragraph.Add(line);
        }
        CloseParagraph();
        CloseList();
        return output.ToString();
    }

    private static string RenderInline(string text)
    {
        var output = new StringBuilder();
        var last = 0;
        foreach (Match match in InlinePattern.Matches(text))
        {
            output.Append(WebUtility.HtmlEncode(text[last..match.Index]));
            if (match.Groups["bold"].Success)
                output.Append("<strong>").Append(WebUtility.HtmlEncode(match.Groups["boldText"].Value)).Append("</strong>");
            else if (match.Groups["code"].Success)
                output.Append("<code>").Append(WebUtility.HtmlEncode(match.Groups["codeText"].Value)).Append("</code>");
            else
            {
                var url = match.Groups["url"].Value;
                if (Uri.TryCreate(url, UriKind.Absolute, out var parsed) && parsed.Scheme is "http" or "https")
                    output.Append("<a href=\"").Append(WebUtility.HtmlEncode(url))
                        .Append("\" target=\"_blank\" rel=\"noopener noreferrer\">")
                        .Append(WebUtility.HtmlEncode(url)).Append("</a>");
                else output.Append(WebUtility.HtmlEncode(url));
            }
            last = match.Index + match.Length;
        }
        output.Append(WebUtility.HtmlEncode(text[last..]));
        return output.ToString();
    }

    private void Load()
    {
        if (!File.Exists(FilePath)) return;
        try
        {
            var loaded = JsonSerializer.Deserialize<LatestInformationSnapshot>(File.ReadAllText(FilePath), FileJson);
            if (loaded is not null && loaded.Content is { Length: <= MaximumContentLength }) _current = loaded;
            _logger.LogInformation("Loaded latest information from {Path}", FilePath);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning("Could not read latest information state {Path}: {Error}", FilePath, ex.Message);
        }
    }

    private void Save(LatestInformationSnapshot snapshot)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            var temporary = FilePath + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(snapshot, FileJson));
            File.Move(temporary, FilePath, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogError(ex, "Could not persist latest information to {Path}", FilePath);
            throw new InvalidOperationException("Could not persist latest information", ex);
        }
    }
}

/// <summary>GET/POST /admin/latest-information, limited to API loopback callers as for maintenance.</summary>
public static class LatestInformationAdmin
{
    public static IResult Get(HttpContext context, LatestInformationState state) =>
        MaintenanceAdmin.IsLocalAdmin(context) ? Status(state.Current) : Results.NotFound();

    public static async Task<IResult> PostAsync(HttpContext context, LatestInformationState state)
    {
        if (!MaintenanceAdmin.IsLocalAdmin(context)) return Results.NotFound();
        try
        {
            using var document = await JsonDocument.ParseAsync(context.Request.Body);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("content", out var property)
                || property.ValueKind != JsonValueKind.String)
                return Results.BadRequest(new { error = "body must be JSON {content: string}" });
            var content = property.GetString() ?? "";
            if (content.Length > LatestInformationState.MaximumContentLength)
                return Results.BadRequest(new { error = $"content must be {LatestInformationState.MaximumContentLength} characters or fewer" });
            return Status(state.Set(content));
        }
        catch (JsonException ex)
        {
            return Results.BadRequest(new { error = "body must be JSON {content: string}", detail = ex.Message });
        }
        catch (InvalidOperationException)
        {
            return Results.Json(new { error = "could not persist latest information; the previous announcement is still active" },
                statusCode: StatusCodes.Status500InternalServerError);
        }
    }

    private static IResult Status(LatestInformationSnapshot current) => Results.Json(new
    {
        content = current.Content,
        defaultContent = LatestInformationState.DefaultContent,
        changedAtUtc = current.ChangedAtUtc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture)
    });
}
