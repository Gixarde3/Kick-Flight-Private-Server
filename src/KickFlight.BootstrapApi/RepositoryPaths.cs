namespace KickFlight.BootstrapApi;

public static class RepositoryPaths
{
    /// <summary>
    /// Set when the server runs outside a checkout - a container has no solution file, so the upward walk
    /// below would throw on every master load and every catalog lookup. The value is the directory the
    /// repository-relative paths in configuration are resolved against.
    /// </summary>
    public const string RootOverrideVariable = "KF_REPO_ROOT";

    public static string FindRoot(string startingPath)
    {
        var configured = Environment.GetEnvironmentVariable(RootOverrideVariable);
        if (!string.IsNullOrWhiteSpace(configured))
        {
            var resolved = Path.GetFullPath(configured);
            if (Directory.Exists(resolved)) return resolved;
            throw new DirectoryNotFoundException(
                $"{RootOverrideVariable} points at '{resolved}', which does not exist.");
        }

        foreach (var candidate in new[] { startingPath, Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            var directory = new DirectoryInfo(Path.GetFullPath(candidate));
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "KickFlight.PrivateServer.sln"))) return directory.FullName;
                directory = directory.Parent;
            }
        }
        throw new DirectoryNotFoundException("Could not locate KickFlight.PrivateServer.sln.");
    }

    public static string Resolve(string configuredPath, string startingPath) => Path.IsPathRooted(configuredPath)
        ? configuredPath
        : Path.GetFullPath(Path.Combine(FindRoot(startingPath), configuredPath));
}
