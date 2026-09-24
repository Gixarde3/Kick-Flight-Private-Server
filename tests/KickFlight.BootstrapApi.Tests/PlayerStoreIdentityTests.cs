using KickFlight.BootstrapApi.PlayerStore;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

// The JSON store allocates an id as one past the highest it can see in its directory, and it only sees a save
// file once someone has written one. Two stores over the same directory would therefore both read the same
// directory before either writes and hand the same id to two different devices, so two players would share one
// save file - each overwriting the other's inventory, name and rank.
//
// That is not hypothetical: IClassFixture gives the suite one host per test class, so ShopGachaTests and
// HarnessTests run two stores side by side over one data/users directory, which is what made
// ShopGachaTests.Disc_draw_grants_a_disc_and_spends_one_ticket fail roughly one run in four with a
// KeyNotFoundException while reading a save file that belonged to another test.
public sealed class PlayerStoreIdentityTests : IDisposable
{
    private readonly string _directory =
        Path.Combine(Path.GetTempPath(), "kf-store-" + Guid.NewGuid().ToString("N")[..12]);

    private JsonPlayerStore NewStore() =>
        new(NullLogger<JsonPlayerStore>.Instance, new TestEnvironment(_directory));

    [Fact]
    public void Two_stores_over_one_directory_never_issue_the_same_id()
    {
        // Both are built before either resolves anything, which is the state that makes the collision possible.
        var first = NewStore();
        var second = NewStore();

        var a = first.ResolvePlayerId("device-a");
        var b = second.ResolvePlayerId("device-b");

        Assert.NotEqual(a, b);
    }

    [Fact]
    public void Many_stores_over_one_directory_still_hand_out_distinct_ids()
    {
        var stores = Enumerable.Range(0, 8).Select(_ => NewStore()).ToList();

        var ids = stores.Select((store, index) => store.ResolvePlayerId($"device-{index}")).ToList();

        Assert.Equal(ids.Count, ids.Distinct().Count());
    }

    [Fact]
    public void Concurrent_stores_preserve_every_identity_after_reload()
    {
        const int deviceCount = 64;
        var stores = Enumerable.Range(0, deviceCount).Select(_ => NewStore()).ToArray();
        var playerIds = new long[deviceCount];

        Parallel.For(0, deviceCount, index =>
            playerIds[index] = stores[index].ResolvePlayerId($"parallel-device-{index}"));

        Assert.Equal(deviceCount, playerIds.Distinct().Count());

        var reloaded = NewStore();
        for (var index = 0; index < deviceCount; index++)
        {
            Assert.Equal(playerIds[index], reloaded.ResolvePlayerId($"parallel-device-{index}"));
        }
    }

    [Fact]
    public void The_same_device_keeps_its_id_across_stores_and_restarts()
    {
        var id = NewStore().ResolvePlayerId("device-stable");

        // A second store is what a server restart looks like to this store: a fresh instance over the same
        // directory, with only the identity index to remember what it decided.
        Assert.Equal(id, NewStore().ResolvePlayerId("device-stable"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory)) Directory.Delete(_directory, recursive: true);
    }

    private sealed class TestEnvironment(string contentRoot) : IWebHostEnvironment
    {
        public string ApplicationName { get; set; } = "tests";
        public string ContentRootPath { get; set; } = contentRoot;
        public string EnvironmentName { get; set; } = "Test";
        public string WebRootPath { get; set; } = contentRoot;
        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
        public IFileProvider WebRootFileProvider { get; set; } = new NullFileProvider();
    }
}
