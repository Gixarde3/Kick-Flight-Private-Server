namespace KickFlight.BootstrapApi;

public sealed class PhotonServerOptions
{
    public const string SectionName = "PhotonServer";

    public bool Enabled { get; set; } = true;
    public string Host { get; set; } = "10.0.2.2";
    public int MasterServerPort { get; set; } = 5055;
    public int GameServerPort { get; set; } = 5056;
    public int NameServerPort { get; set; } = 5058;
    public string ContainerName { get; set; } = "luxon-server";
    public string RepositoryUrl { get; set; } = "https://github.com/Gixarde3/luxonserver.git";
    public int HealthCheckTimeoutMs { get; set; } = 1500;
}
