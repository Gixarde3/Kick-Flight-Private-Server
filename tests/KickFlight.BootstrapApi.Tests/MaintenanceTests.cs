using System.Net;
using System.Text;
using System.Text.Json;
using Grpc.Core;
using KickFlight.BootstrapApi;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using OpenMatch;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

// A host of its own with its own state file: the switch is persisted, and a Hard left behind in the shared
// <test output>/data/maintenance.json would make every other test class's host answer 503.
public sealed class MaintenanceFixture : IDisposable
{
    public MaintenanceFixture()
    {
        StateFile = Path.Combine(Path.GetTempPath(), $"kf-maintenance-{Guid.NewGuid():N}.json");
        Factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder => builder
            .UseContentRoot(AppContext.BaseDirectory)
            .UseSetting("Maintenance:FilePath", StateFile));
    }

    public WebApplicationFactory<Program> Factory { get; }

    public string StateFile { get; }

    public void Dispose()
    {
        Factory.Dispose();
        File.Delete(StateFile);
    }
}

public sealed class MaintenanceTests : IClassFixture<MaintenanceFixture>, IDisposable
{
    private const string Host = "kickflight-api.grenge.jp";
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";

    private readonly WebApplicationFactory<Program> _factory;

    public MaintenanceTests(MaintenanceFixture fixture)
    {
        _factory = fixture.Factory;
    }

    // Every test starts and ends in normal service.
    public void Dispose() => _factory.Services.GetRequiredService<MaintenanceState>().Set(MaintenanceMode.Off, null, null);

    [Fact]
    public async Task Warning_adds_one_notice_to_home_index_and_off_removes_it()
    {
        var session = await CreateSessionAsync();
        Assert.Empty((await PostAsync(session, "/home/index", null)).GetProperty("userNoticeList").EnumerateArray());

        var status = await AdminAsync("POST", """{"mode":"warning","title":"Heads up","message":"Restart in 10 minutes"}""");
        Assert.Equal(HttpStatusCode.OK, status.StatusCode);
        Assert.Equal("warning", status.Json.GetProperty("mode").GetString());

        var home = await PostAsync(session, "/home/index", null);
        var notice = Assert.Single(home.GetProperty("userNoticeList").EnumerateArray());
        Assert.Equal("Heads up", notice.GetProperty("title").GetString());
        Assert.Equal("Restart in 10 minutes", notice.GetProperty("message").GetString());
        Assert.True(notice.GetProperty("userNoticeId").GetInt32() > 0);
        Assert.Matches(@"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", notice.GetProperty("sentDatetime").GetString());
        // Everything else is the usual home payload.
        Assert.Equal(session.UserId, home.GetProperty("userPlayer").GetProperty("userId").GetString());
        Assert.False(home.GetProperty("appInformationNotificationFlag").GetBoolean());

        await AdminAsync("POST", """{"mode":"off"}""");
        Assert.Empty((await PostAsync(session, "/home/index", null)).GetProperty("userNoticeList").EnumerateArray());
    }

    [Fact]
    public async Task Hard_answers_503_plaintext_except_boot_battle_end_result_and_401s_user_online()
    {
        var session = await CreateSessionAsync();
        await AdminAsync("POST", """{"mode":"hard","title":"Down","message":"Back soon"}""");

        foreach (var path in new[] { "/home/index", "/battle/entry", "/battle/start" })
        {
            using var refused = await RawPostAsync(session, path, null);
            Assert.Equal(HttpStatusCode.ServiceUnavailable, refused.StatusCode);
            // Plaintext JSON, not D2C: the client parses it before any decryption.
            using var body = JsonDocument.Parse(await refused.Content.ReadAsStringAsync());
            var error = body.RootElement.GetProperty("error");
            Assert.Equal("1000", error.GetProperty("code").GetString());
            Assert.Equal("Down", error.GetProperty("title").GetString());
            Assert.Equal("Back soon", error.GetProperty("message").GetString());
        }

        // Nobody can log in either.
        using (var auth = await PostAuthAsync(_factory.CreateClient()))
            Assert.Equal(HttpStatusCode.ServiceUnavailable, auth.StatusCode);

        using (var online = await RawPostAsync(session, "/user/online", null))
            Assert.Equal(HttpStatusCode.Unauthorized, online.StatusCode);

        foreach (var path in new[] { "/boot/index", "/battle/end", "/battle/result" })
        {
            using var passed = await RawPostAsync(session, path, null);
            Assert.Equal(HttpStatusCode.OK, passed.StatusCode);
        }

        await AdminAsync("POST", """{"mode":"off"}""");
        await PostAsync(session, "/home/index", null);
    }

    [Fact]
    public async Task Hard_mode_matches_no_new_tickets_on_the_grpc_stream()
    {
        var maintenance = new MaintenanceState(NullLogger<MaintenanceState>.Instance,
            Path.Combine(Path.GetTempPath(), $"kf-maintenance-{Guid.NewGuid():N}.json"));
        try
        {
            maintenance.Set(MaintenanceMode.Hard, null, null);
            var photon = new PhotonServerManager(Options.Create(new PhotonServerOptions { Enabled = false }),
                NullLogger<PhotonServerManager>.Instance);
            var matchmaking = new BattleMatchmakingService(NullLogger<BattleMatchmakingService>.Instance, photon, maintenance);
            var (_, ticket) = matchmaking.RegisterEntry("1000001", "Late", 1, 1, 1, [3010001, 3010002, 3010003, 3010004]);

            var writer = new CountingWriter();
            await matchmaking.StreamAssignmentsAsync(ticket, writer, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal(0, writer.Count);
        }
        finally
        {
            File.Delete(maintenance.FilePath);
        }
    }

    [Fact]
    public async Task Admin_endpoint_only_answers_unforwarded_loopback_callers()
    {
        // No remote address at all, a remote one, and loopback carrying either proxy header (= came through nginx).
        Assert.Equal(HttpStatusCode.NotFound, (await AdminAsync("GET", null, remote: null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AdminAsync("GET", null, IPAddress.Parse("203.0.113.5"))).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AdminAsync("GET", null, IPAddress.Loopback, "X-Forwarded-For")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AdminAsync("GET", null, IPAddress.Loopback, "X-Real-IP")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,
            (await AdminAsync("POST", """{"mode":"hard"}""", IPAddress.Loopback, "X-Forwarded-For")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,
            (await AdminAsync("POST", """{"mode":"hard"}""", IPAddress.Parse("10.0.0.7"))).StatusCode);
        Assert.Equal(MaintenanceMode.Off, _factory.Services.GetRequiredService<MaintenanceState>().Current.Mode);

        var status = await AdminAsync("GET", null, IPAddress.IPv6Loopback);
        Assert.Equal(HttpStatusCode.OK, status.StatusCode);
        Assert.Equal("off", status.Json.GetProperty("mode").GetString());
        Assert.Equal(HttpStatusCode.BadRequest, (await AdminAsync("POST", """{"mode":"sideways"}""")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AdminAsync("GET", null, IPAddress.Loopback, path: "/admin/other")).StatusCode);
    }

    [Fact]
    public void State_round_trips_through_the_file_and_the_notice_id_follows_the_text()
    {
        var path = Path.Combine(Path.GetTempPath(), $"kf-maintenance-{Guid.NewGuid():N}", "maintenance.json");
        try
        {
            var first = new MaintenanceState(NullLogger<MaintenanceState>.Instance, path);
            Assert.Equal(MaintenanceMode.Off, first.Current.Mode);
            var warning = first.Set(MaintenanceMode.Warning, "Soon", "Maintenance at 12:00");

            var reloaded = new MaintenanceState(NullLogger<MaintenanceState>.Instance, path).Current;
            Assert.Equal(MaintenanceMode.Warning, reloaded.Mode);
            Assert.Equal("Soon", reloaded.Title);
            Assert.Equal("Maintenance at 12:00", reloaded.Message);
            Assert.Equal(warning.NoticeId, reloaded.NoticeId);

            Assert.Equal(warning.NoticeId, first.Set(MaintenanceMode.Warning, "Soon", "Maintenance at 12:00").NoticeId);
            Assert.True(first.Set(MaintenanceMode.Warning, "Soon", "Maintenance at 12:30").NoticeId > warning.NoticeId);

            var hard = first.Set(MaintenanceMode.Hard, null, null);
            Assert.Equal(MaintenanceState.DefaultHardMessage, hard.Message);
            Assert.Equal(MaintenanceMode.Hard, new MaintenanceState(NullLogger<MaintenanceState>.Instance, path).Current.Mode);
        }
        finally
        {
            Directory.Delete(Path.GetDirectoryName(path)!, recursive: true);
        }
    }

    private sealed record AdminResponse(HttpStatusCode StatusCode, JsonElement Json);

    // TestServer has no socket, so the remote address is set on the context directly (null unless a test sets it).
    private async Task<AdminResponse> AdminAsync(string method, string? body, IPAddress? remote = null,
        string? proxyHeader = null, string path = "/admin/maintenance")
    {
        var context = await _factory.Server.SendAsync(http =>
        {
            http.Request.Method = method;
            http.Request.Path = path;
            http.Request.Host = new HostString("127.0.0.1", 8080);
            http.Connection.RemoteIpAddress = remote;
            if (proxyHeader is not null) http.Request.Headers[proxyHeader] = "198.51.100.1";
            if (body is not null) http.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes(body));
        });
        var text = await new StreamReader(context.Response.Body).ReadToEndAsync();
        var json = context.Response.StatusCode == 200 ? JsonDocument.Parse(text).RootElement.Clone() : default;
        return new AdminResponse((HttpStatusCode)context.Response.StatusCode, json);
    }

    private Task<AdminResponse> AdminAsync(string method, string? body) => AdminAsync(method, body, IPAddress.Loopback);

    private static async Task<HttpResponseMessage> PostAuthAsync(HttpClient client)
    {
        var key = Encoding.ASCII.GetBytes("0123456789abcdef0123456789abcdef");
        var payload = JsonSerializer.Serialize(new { hash = Encoding.ASCII.GetString(key), uuid = Guid.NewGuid().ToString("N") });
        var request = new HttpRequestMessage(HttpMethod.Post, "/auth/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(payload), Encoding.ASCII.GetBytes(CommonCode), new byte[16]))
        };
        request.Headers.Host = Host;
        return await client.SendAsync(request);
    }

    private async Task<DemoSession> CreateSessionAsync()
    {
        var client = _factory.CreateClient();
        using var response = await PostAuthAsync(client);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        client.DefaultRequestHeaders.Add("x-app-access-token", response.Headers.GetValues("x-app-access-token").Single());
        return new DemoSession(client, Encoding.ASCII.GetBytes("0123456789abcdef0123456789abcdef"),
            response.Headers.GetValues("x-app-user-id").Single());
    }

    private static async Task<HttpResponseMessage> RawPostAsync(DemoSession session, string path, object? body)
    {
        var json = body is null ? "{}" : JsonSerializer.Serialize(body);
        var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(json), session.Key, new byte[16]))
        };
        request.Headers.Host = Host;
        return await session.Client.SendAsync(request);
    }

    private static async Task<JsonElement> PostAsync(DemoSession session, string path, object? body)
    {
        using var response = await RawPostAsync(session, path, body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("0", response.Headers.GetValues("x-app-status-code").Single());
        using var document = JsonDocument.Parse(D2CCodec.Decode(await response.Content.ReadAsByteArrayAsync(), session.Key));
        return document.RootElement.Clone();
    }

    private sealed record DemoSession(HttpClient Client, byte[] Key, string UserId);

    private sealed class CountingWriter : IServerStreamWriter<GetAssignmentsResponse>
    {
        public WriteOptions? WriteOptions { get; set; }
        public int Count { get; private set; }

        public Task WriteAsync(GetAssignmentsResponse message)
        {
            Count++;
            return Task.CompletedTask;
        }
    }
}
