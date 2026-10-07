using System.Collections.Concurrent;

namespace KickFlight.BootstrapApi;

/// <summary>
/// Optional per-table override directory for the <c>config/masters_*.json</c> files, so the balance WebUI can
/// persist tuned values outside the checked-in config tree (which the CI deploy overwrites). A file in this
/// directory with the same name as a base master replaces that master entirely; when it is absent the base
/// file, and then the inline fallback, are used as before.
///
/// The directory comes from configuration (<c>Masters:OverrideDir</c> / environment
/// <c>Masters__OverrideDir</c>) and defaults to <c>.local/masters-overrides</c>, resolved against the
/// repository root like every other repo-relative path.
/// </summary>
public sealed class MasterOverrides
{
    public const string ConfigurationKey = "Masters:OverrideDir";
    public const string DefaultRelativeDir = ".local/masters-overrides";

    // LoadJson is called from the singleton's constructor and, for CustomBattleRuleField, once per request;
    // the dictionary keeps the "which were overridden" bookkeeping safe under concurrency.
    private readonly ConcurrentDictionary<string, byte> _applied = new(StringComparer.Ordinal);

    public MasterOverrides(string? configuredDir, string contentRoot)
    {
        Directory = RepositoryPaths.Resolve(
            string.IsNullOrWhiteSpace(configuredDir) ? DefaultRelativeDir : configuredDir, contentRoot);
    }

    /// <summary>Absolute override directory (it need not exist).</summary>
    public string Directory { get; }

    /// <summary>Names of the master files served from the override directory, sorted for a stable log.</summary>
    public IReadOnlyList<string> Applied =>
        _applied.Keys.OrderBy(name => name, StringComparer.Ordinal).ToList();

    /// <summary>The override file that replaces a repository-relative master path, or null when there is none.</summary>
    public string? Find(string relativePath)
    {
        var fileName = Path.GetFileName(relativePath);
        if (!fileName.StartsWith("masters_", StringComparison.Ordinal) ||
            !fileName.EndsWith(".json", StringComparison.Ordinal))
        {
            return null;
        }

        var candidate = Path.Combine(Directory, fileName);
        if (!File.Exists(candidate)) return null;
        _applied.TryAdd(fileName, 0);
        return candidate;
    }

    /// <summary>Override file when present, else the base file, else the inline fallback.</summary>
    public string Read(string contentRoot, string relativePath, string fallback)
    {
        var overridePath = Find(relativePath);
        if (overridePath is not null) return File.ReadAllText(overridePath);

        var resolved = RepositoryPaths.Resolve(relativePath, contentRoot);
        return File.Exists(resolved) ? File.ReadAllText(resolved) : fallback;
    }
}
