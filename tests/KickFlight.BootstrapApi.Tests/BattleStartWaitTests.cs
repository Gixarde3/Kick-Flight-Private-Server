using System.Net;
using System.Text;
using System.Text.Json;
using KickFlight.BootstrapApi;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

// The Photon room master only waits for the other humans of a match while home/index serves a positive
// battleStartWaitTime (NormalMatchingJoinBattleRoomState); 0 made it start the battle before a slower human joined.
public sealed class BattleStartWaitTests : IClassFixture<ServerTestHostFixture>
{
    private const string Host = "kickflight-api.grenge.jp";
    private const string SessionKey = "0123456789abcdef0123456789abcdef";
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";

    private readonly WebApplicationFactory<Program> _factory;

    public BattleStartWaitTests(ServerTestHostFixture fixture) => _factory = fixture.Factory;

    [Fact]
    public void Default_wait_covers_a_slow_late_joiner_but_stays_bounded()
    {
        Assert.InRange(BattleMatchmakingService.BattleStartWaitSeconds, 8.0, 15.0);
    }

    [Fact]
    public async Task Home_index_serves_the_master_start_wait()
    {
        var client = _factory.CreateClient();
        var key = Encoding.ASCII.GetBytes(SessionKey);
        var auth = JsonSerializer.Serialize(new { hash = SessionKey, uuid = Guid.NewGuid().ToString("N") });
        var authRequest = new HttpRequestMessage(HttpMethod.Post, "/auth/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(auth), Encoding.ASCII.GetBytes(CommonCode), new byte[16]))
        };
        authRequest.Headers.Host = Host;
        using var authResponse = await client.SendAsync(authRequest);
        Assert.Equal(HttpStatusCode.OK, authResponse.StatusCode);
        client.DefaultRequestHeaders.Add("x-app-access-token", authResponse.Headers.GetValues("x-app-access-token").Single());

        var homeRequest = new HttpRequestMessage(HttpMethod.Post, "/home/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes("{}"), key, new byte[16]))
        };
        homeRequest.Headers.Host = Host;
        using var homeResponse = await client.SendAsync(homeRequest);
        Assert.Equal(HttpStatusCode.OK, homeResponse.StatusCode);
        using var home = JsonDocument.Parse(D2CCodec.Decode(await homeResponse.Content.ReadAsByteArrayAsync(), key));

        Assert.Equal(BattleMatchmakingService.BattleStartWaitSeconds,
            home.RootElement.GetProperty("battleStartWaitTime").GetDouble());
        Assert.True(home.RootElement.GetProperty("battleStartWaitTime").GetDouble() > 0);
    }
}
