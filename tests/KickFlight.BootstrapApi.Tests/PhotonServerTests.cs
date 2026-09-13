using KickFlight.BootstrapApi;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class PhotonServerTests
{
    [Fact]
    public void PhotonServerOptions_defaults_point_to_luxonserver()
    {
        var options = new PhotonServerOptions();
        Assert.True(options.Enabled);
        Assert.Equal("10.0.2.2", options.Host);
        Assert.Equal(5055, options.MasterServerPort);
        Assert.Equal(5056, options.GameServerPort);
        Assert.Equal(5058, options.NameServerPort);
        Assert.Equal("luxon-server", options.ContainerName);
        Assert.Equal("https://github.com/Gixarde3/luxonserver.git", options.RepositoryUrl);
    }

    [Fact]
    public async Task PhotonServerManager_initializes_and_reports_status()
    {
        var options = Options.Create(new PhotonServerOptions
        {
            Enabled = true,
            Host = "127.0.0.1",
            MasterServerPort = 5055,
            GameServerPort = 5056,
            NameServerPort = 5058,
            HealthCheckTimeoutMs = 100
        });

        var manager = new PhotonServerManager(options, NullLogger<PhotonServerManager>.Instance);
        var initial = manager.GetStatus();

        Assert.True(initial.Enabled);
        Assert.Equal("https://github.com/Gixarde3/luxonserver.git", initial.RepositoryUrl);

        var checkedStatus = await manager.CheckHealthAsync();
        Assert.NotNull(checkedStatus);
        Assert.Equal(initial.Host, checkedStatus.Host);
    }
}
