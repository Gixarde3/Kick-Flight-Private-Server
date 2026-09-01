namespace KickFlight.BootstrapApi;

public static class RepositoryPaths
{
    public static string FindRoot(string startingPath)
    {
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
