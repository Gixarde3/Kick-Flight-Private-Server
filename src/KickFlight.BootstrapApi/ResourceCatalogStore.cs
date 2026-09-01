using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace KickFlight.BootstrapApi;

public sealed class ResourceCatalogDocument
{
    public int SchemaVersion { get; init; } = 1;
    public List<ResourceDefinition> Resources { get; init; } = [];
}

public sealed class ResourceDefinition
{
    public required string Id { get; init; }
    public bool Enabled { get; init; } = true;
    public string Host { get; init; } = "kickflight-resource-api.grenge.jp";
    public required string RequestPath { get; init; }
    public required string LogicalName { get; init; }
    public string Description { get; init; } = "";
    public required string SourcePath { get; init; }
    public string ContentType { get; init; } = "application/octet-stream";
    public required string Sha256 { get; init; }
}

public sealed record ResolvedResource(ResourceDefinition Definition, string SourceFile);
public sealed record ResourceCatalogSnapshot(IReadOnlyList<ResolvedResource> Resources, IReadOnlyList<string> Errors);

public sealed class ResourceCatalogStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private readonly HarnessOptions _options;
    private readonly IWebHostEnvironment _environment;
    private readonly ILogger<ResourceCatalogStore> _logger;
    private readonly object _gate = new();
    private ResourceCatalogSnapshot? _snapshot;
    private string? _fingerprint;

    public ResourceCatalogStore(
        IOptions<HarnessOptions> options,
        IWebHostEnvironment environment,
        ILogger<ResourceCatalogStore> logger)
    {
        _options = options.Value;
        _environment = environment;
        _logger = logger;
    }

    public ResolvedResource? Match(string host, string path) => GetSnapshot().Resources.FirstOrDefault(resource =>
        resource.Definition.Enabled &&
        string.Equals(FixtureStore.NormalizeHost(resource.Definition.Host), FixtureStore.NormalizeHost(host), StringComparison.OrdinalIgnoreCase) &&
        string.Equals(FixtureStore.NormalizePath(resource.Definition.RequestPath), FixtureStore.NormalizePath(path), StringComparison.Ordinal));

    public ResolvedResource? MatchDirect(string path)
    {
        var matches = GetSnapshot().Resources.Where(resource =>
            resource.Definition.Enabled &&
            string.Equals(FixtureStore.NormalizePath(resource.Definition.RequestPath), FixtureStore.NormalizePath(path), StringComparison.Ordinal))
            .Take(2).ToArray();
        return matches.Length == 1 ? matches[0] : null;
    }

    public ResourceCatalogSnapshot GetSnapshot()
    {
        var catalogPath = RepositoryPaths.Resolve(_options.ResourceCatalogPath, _environment.ContentRootPath);
        var fingerprint = File.Exists(catalogPath)
            ? $"{catalogPath}:{File.GetLastWriteTimeUtc(catalogPath).Ticks}:{new FileInfo(catalogPath).Length}"
            : $"{catalogPath}:missing";
        if (_snapshot is not null && fingerprint == _fingerprint) return _snapshot;

        lock (_gate)
        {
            if (_snapshot is not null && fingerprint == _fingerprint) return _snapshot;
            var resources = new List<ResolvedResource>();
            var errors = new List<string>();
            try
            {
                if (!File.Exists(catalogPath)) throw new FileNotFoundException("Resource catalog was not found.", catalogPath);
                var document = JsonSerializer.Deserialize<ResourceCatalogDocument>(File.ReadAllText(catalogPath), JsonOptions)
                    ?? throw new InvalidDataException("The resource catalog was empty.");
                if (document.SchemaVersion != 1) throw new InvalidDataException($"Unsupported resource catalog schema {document.SchemaVersion}.");
                foreach (var definition in document.Resources)
                {
                    try
                    {
                        resources.Add(ResolveAndValidate(definition));
                    }
                    catch (Exception exception)
                    {
                        errors.Add($"{definition.Id}: {exception.Message}");
                    }
                }
            }
            catch (Exception exception)
            {
                errors.Add($"{Path.GetFileName(catalogPath)}: {exception.Message}");
            }

            var duplicates = resources.Where(resource => resource.Definition.Enabled)
                .GroupBy(resource => $"{FixtureStore.NormalizeHost(resource.Definition.Host)}|{FixtureStore.NormalizePath(resource.Definition.RequestPath)}")
                .Where(group => group.Count() > 1)
                .Select(group => group.Key);
            errors.AddRange(duplicates.Select(duplicate => $"Duplicate enabled resource route: {duplicate}"));
            _snapshot = new ResourceCatalogSnapshot(resources, errors);
            _fingerprint = fingerprint;
            _logger.LogInformation("Loaded {ResourceCount} local resources with {ErrorCount} errors", resources.Count, errors.Count);
            return _snapshot;
        }
    }

    private ResolvedResource ResolveAndValidate(ResourceDefinition definition)
    {
        if (string.IsNullOrWhiteSpace(definition.Id)) throw new InvalidDataException("id is required.");
        if (string.IsNullOrWhiteSpace(definition.Host)) throw new InvalidDataException("host is required.");
        if (string.IsNullOrWhiteSpace(definition.RequestPath) || !definition.RequestPath.StartsWith('/'))
            throw new InvalidDataException("requestPath must start with '/'.");
        if (string.IsNullOrWhiteSpace(definition.LogicalName)) throw new InvalidDataException("logicalName is required.");
        if (string.IsNullOrWhiteSpace(definition.SourcePath)) throw new InvalidDataException("sourcePath is required.");
        if (definition.Sha256.Length != 64 || !definition.Sha256.All(Uri.IsHexDigit))
            throw new InvalidDataException("sha256 must contain 64 hexadecimal characters.");

        var sourceFile = RepositoryPaths.Resolve(definition.SourcePath, _environment.ContentRootPath);
        if (!File.Exists(sourceFile)) throw new FileNotFoundException("Source file was not found.", sourceFile);
        using var stream = File.OpenRead(sourceFile);
        var actualHash = Convert.ToHexString(SHA256.HashData(stream));
        if (!string.Equals(actualHash, definition.Sha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"SHA-256 mismatch; expected {definition.Sha256}, got {actualHash}.");
        return new ResolvedResource(definition, sourceFile);
    }
}
