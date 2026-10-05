using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

// The telemetry sink writes daily NDJSON files when Analysis:Directory points at a writable path (the VPS default
// has no writable mount, so it logs instead). The host is pointed at a per-run temp directory so the assertions
// read exactly what this class produced and nothing else.
public sealed class AnalysisTelemetryFixture : IDisposable
{
    public AnalysisTelemetryFixture()
    {
        Directory = Path.Combine(Path.GetTempPath(), "kf-analysis-" + Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(Directory);
        Factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.UseContentRoot(AppContext.BaseDirectory);
            builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Analysis:Directory"] = Directory,
                ["Analysis:EntriesPerMinute"] = "30"
            }));
        });
    }

    public WebApplicationFactory<Program> Factory { get; }
    public string Directory { get; }

    public void Dispose()
    {
        Factory.Dispose();
        try { System.IO.Directory.Delete(Directory, recursive: true); } catch { /* best effort */ }
    }
}

public sealed class AnalysisTelemetryTests : IClassFixture<AnalysisTelemetryFixture>
{
    private const string Host = "kickflight-api.grenge.jp";
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";

    private readonly AnalysisTelemetryFixture _fixture;

    public AnalysisTelemetryTests(AnalysisTelemetryFixture fixture) => _fixture = fixture;

    [Fact]
    public async Task Entries_are_recorded_with_userId_key_and_value()
    {
        var session = await CreateSessionAsync();
        session.Client.DefaultRequestHeaders.Add("x-app-application-version", "2.11.0");

        var before = ReadEntries().Count;
        await PostAsync(session, "/analysis/index", new
        {
            analysisList = new object[]
            {
                new { key = "SendBattleEndError", value = "boom" },
                new { key = "photon/ping", value = "42" }
            }
        });

        var added = ReadEntries().Skip(before).ToList();
        Assert.Equal(2, added.Count);
        Assert.All(added, entry => Assert.Equal(session.UserId, entry.UserId));
        Assert.Equal("SendBattleEndError", added[0].Key);
        Assert.Equal("boom", added[0].Value);
        Assert.Equal("42", added[1].Value);
        Assert.Equal("2.11.0", added[0].AppVersion);
        Assert.False(string.IsNullOrEmpty(added[0].Utc));
    }

    [Fact]
    public async Task Rate_limit_drops_entries_beyond_the_per_minute_limit()
    {
        var session = await CreateSessionAsync();
        var entries = Enumerable.Range(0, 40)
            .Select(i => (object)new { key = $"event-{i}", value = "x" })
            .ToArray();

        await PostAsync(session, "/analysis/index", new { analysisList = entries });

        Assert.Equal(30, ReadEntries().Count(entry => entry.UserId == session.UserId));

        // The window is one minute, so a second request in the same window is dropped too.
        await PostAsync(session, "/analysis/index", new { analysisList = new object[] { new { key = "late", value = "x" } } });
        Assert.Equal(30, ReadEntries().Count(entry => entry.UserId == session.UserId));
    }

    [Fact]
    public async Task Malformed_body_answers_success_and_records_nothing()
    {
        var session = await CreateSessionAsync();
        var before = ReadEntries().Count(entry => entry.UserId == session.UserId);

        using var request = new HttpRequestMessage(HttpMethod.Post, "/analysis/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes("not json"), session.Key, new byte[16]))
        };
        request.Headers.Host = Host;
        using var response = await session.Client.SendAsync(request);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("0", response.Headers.GetValues("x-app-status-code").Single());
        var decrypted = D2CCodec.Decode(await response.Content.ReadAsByteArrayAsync(), session.Key);
        Assert.Equal("{}", Encoding.UTF8.GetString(decrypted));
        Assert.Equal(before, ReadEntries().Count(entry => entry.UserId == session.UserId));
    }

    [Fact]
    public async Task Unauthenticated_request_keeps_the_stub_behaviour_and_records_nothing()
    {
        var before = ReadEntries().Count;

        using var client = _fixture.Factory.CreateClient();
        client.DefaultRequestHeaders.Add("x-app-access-token", "not-a-token-this-server-issued");
        using var request = new HttpRequestMessage(HttpMethod.Post, "/analysis/index")
        {
            Content = new ByteArrayContent(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 })
        };
        request.Headers.Host = Host;
        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("1", response.Headers.GetValues("x-app-status-code").Single());
        Assert.Equal(before, ReadEntries().Count);
    }

    private List<AnalysisEntry> ReadEntries()
    {
        var path = Path.Combine(_fixture.Directory, $"analysis-{DateTime.UtcNow:yyyyMMdd}.ndjson");
        if (!File.Exists(path)) return new List<AnalysisEntry>();

        var entries = new List<AnalysisEntry>();
        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            using var document = JsonDocument.Parse(line);
            var root = document.RootElement;
            entries.Add(new AnalysisEntry(
                root.GetProperty("utc").GetString() ?? "",
                root.GetProperty("userId").GetString() ?? "",
                root.GetProperty("key").GetString() ?? "",
                root.GetProperty("value").GetString() ?? "",
                root.GetProperty("appVersion").GetString() ?? ""));
        }
        return entries;
    }

    private async Task<DemoSession> CreateSessionAsync()
    {
        var client = _fixture.Factory.CreateClient();
        var key = Encoding.ASCII.GetBytes("0123456789abcdef0123456789abcdef");
        var payload = JsonSerializer.Serialize(new { hash = Encoding.ASCII.GetString(key), uuid = Guid.NewGuid().ToString("N") });

        using var request = new HttpRequestMessage(HttpMethod.Post, "/auth/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(payload), Encoding.ASCII.GetBytes(CommonCode), new byte[16]))
        };
        request.Headers.Host = Host;
        using var response = await client.SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        client.DefaultRequestHeaders.Add("x-app-access-token", response.Headers.GetValues("x-app-access-token").Single());
        return new DemoSession(client, key, response.Headers.GetValues("x-app-user-id").Single());
    }

    private static async Task<JsonElement> PostAsync(DemoSession session, string path, object? body)
    {
        var json = body is null ? "{}" : JsonSerializer.Serialize(body);
        using var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(json), session.Key, new byte[16]))
        };
        request.Headers.Host = Host;
        using var response = await session.Client.SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("0", response.Headers.GetValues("x-app-status-code").Single());

        var decrypted = D2CCodec.Decode(await response.Content.ReadAsByteArrayAsync(), session.Key);
        using var document = JsonDocument.Parse(decrypted);
        return document.RootElement.Clone();
    }

    private sealed record DemoSession(HttpClient Client, byte[] Key, string UserId);
    private sealed record AnalysisEntry(string Utc, string UserId, string Key, string Value, string AppVersion);
}
