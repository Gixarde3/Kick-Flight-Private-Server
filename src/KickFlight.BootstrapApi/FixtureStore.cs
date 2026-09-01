using System.Text.Json;
using Microsoft.Extensions.Options;

namespace KickFlight.BootstrapApi;

public sealed class FixtureStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private readonly HarnessOptions _options;
    private readonly IWebHostEnvironment _environment;
    private readonly ILogger<FixtureStore> _logger;
    private readonly object _gate = new();
    private FixtureSnapshot? _snapshot;
    private string? _fingerprint;

    public FixtureStore(IOptions<HarnessOptions> options, IWebHostEnvironment environment, ILogger<FixtureStore> logger)
    {
        _options = options.Value;
        _environment = environment;
        _logger = logger;
    }

    public FixtureDefinition? Match(string host, string method, string path) => GetSnapshot().Fixtures.FirstOrDefault(f =>
        f.Enabled && string.Equals(NormalizeHost(f.Host), NormalizeHost(host), StringComparison.OrdinalIgnoreCase) &&
        string.Equals(f.Method, method, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(NormalizePath(f.Path), NormalizePath(path), StringComparison.Ordinal));

    public FixtureDefinition? MatchDirect(string method, string path)
    {
        var matches = GetSnapshot().Fixtures.Where(f =>
            f.Enabled && string.Equals(f.Method, method, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(NormalizePath(f.Path), NormalizePath(path), StringComparison.Ordinal)).Take(2).ToArray();
        return matches.Length == 1 ? matches[0] : null;
    }

    public FixtureSnapshot GetSnapshot()
    {
        var directory = ResolveDirectory(_options.FixtureDirectory);
        var files = Directory.Exists(directory)
            ? Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories).OrderBy(x => x, StringComparer.OrdinalIgnoreCase).ToArray()
            : Array.Empty<string>();
        var fingerprint = string.Join('|', files.Select(f => $"{f}:{File.GetLastWriteTimeUtc(f).Ticks}:{new FileInfo(f).Length}"));
        if (_snapshot is not null && fingerprint == _fingerprint) return _snapshot;

        lock (_gate)
        {
            if (_snapshot is not null && fingerprint == _fingerprint) return _snapshot;
            var fixtures = new List<FixtureDefinition>();
            var errors = new List<string>();
            foreach (var file in files)
            {
                try
                {
                    var fixture = JsonSerializer.Deserialize<FixtureDefinition>(File.ReadAllText(file), JsonOptions)
                        ?? throw new InvalidDataException("The fixture was empty.");
                    fixture.SourceFile = file;
                    Validate(fixture);
                    fixtures.Add(fixture);
                }
                catch (Exception exception)
                {
                    errors.Add($"{Path.GetFileName(file)}: {exception.Message}");
                }
            }

            var duplicates = fixtures.Where(f => f.Enabled).GroupBy(f => $"{NormalizeHost(f.Host)}|{f.Method.ToUpperInvariant()}|{NormalizePath(f.Path)}")
                .Where(g => g.Count() > 1).Select(g => g.Key);
            errors.AddRange(duplicates.Select(d => $"Duplicate enabled fixture route: {d}"));
            _snapshot = new FixtureSnapshot(fixtures, errors);
            _fingerprint = fingerprint;
            _logger.LogInformation("Loaded {FixtureCount} local fixtures with {ErrorCount} errors", fixtures.Count, errors.Count);
            return _snapshot;
        }
    }

    public static string NormalizeHost(string host) => host.Trim().TrimEnd('.').ToLowerInvariant();
    public static string NormalizePath(string path) => "/" + path.Trim().TrimStart('/');

    private string ResolveDirectory(string configured) => RepositoryPaths.Resolve(configured, _environment.ContentRootPath);

    private static void Validate(FixtureDefinition fixture)
    {
        if (string.IsNullOrWhiteSpace(fixture.Id)) throw new InvalidDataException("id is required.");
        if (string.IsNullOrWhiteSpace(fixture.Host)) throw new InvalidDataException("host is required.");
        if (string.IsNullOrWhiteSpace(fixture.Method)) throw new InvalidDataException("method is required.");
        if (string.IsNullOrWhiteSpace(fixture.Path)) throw new InvalidDataException("path is required.");
        if (fixture.StatusCode is < 100 or > 599) throw new InvalidDataException("statusCode must be between 100 and 599.");
        _ = fixture.GetBodyBytes();
    }
}
