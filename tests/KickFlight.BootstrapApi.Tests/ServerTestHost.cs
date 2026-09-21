using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

// The server writes one session JSON per user under <content root>/data/users. Without an explicit content root the
// test host inherits src/KickFlight.BootstrapApi, so every run rewrites the tracked save 1000003.json and adds a new
// file per generated uuid. Pointing the host at the (git-ignored) test output directory keeps test sessions out of
// the tracked src/ tree; config still resolves because RepositoryPaths.FindRoot walks up to the .sln.
public sealed class ServerTestHostFixture : IDisposable
{
    public ServerTestHostFixture()
    {
        Factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder => builder.UseContentRoot(AppContext.BaseDirectory));
    }

    public WebApplicationFactory<Program> Factory { get; }

    public void Dispose() => Factory.Dispose();
}
