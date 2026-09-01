using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using KickFlight.BootstrapApi;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class HarnessTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly WebApplicationFactory<Program> _factory;

    public HarnessTests(WebApplicationFactory<Program> factory) => _factory = factory;

    [Theory]
    [InlineData("/health/live")]
    [InlineData("/health/ready")]
    public async Task Health_endpoints_are_successful(string path)
    {
        using var response = await _factory.CreateClient().GetAsync(path);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Theory]
    [InlineData("kickflight-api.grenge.jp", "POST", "application/json")]
    [InlineData("colorful-api-octo-sb.grenge.jp", "GET", "application/x-protobuf")]
    [InlineData("kickflight-resource-api.grenge.jp", "GET", "application/octet-stream")]
    public async Task Fixtures_route_by_host_method_and_path(string host, string method, string contentType)
    {
        using var request = new HttpRequestMessage(new HttpMethod(method), "/__fixture-probe");
        request.Headers.Host = host;
        if (method == "POST") request.Content = JsonContent.Create(new { probe = true });
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.True(response.IsSuccessStatusCode);
        Assert.Equal(contentType, response.Content.Headers.ContentType?.MediaType);
        Assert.Contains("harness-", response.Headers.GetValues("x-kickflight-fixture").Single());
    }

    [Fact]
    public async Task Unknown_route_is_strict_and_never_forwards()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/definitely-unknown");
        request.Headers.Host = "kickflight-api.grenge.jp";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        var json = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("disabled", json.GetProperty("upstream").GetString());
    }

    [Fact]
    public async Task Boot_route_returns_the_recovered_binary_contract()
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "/boot/index")
        {
            Content = new ByteArrayContent(new byte[32])
        };
        request.Content.Headers.ContentType = new("application/octet-stream");
        request.Headers.Host = "kickflight-api.grenge.jp";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("0", response.Headers.GetValues("x-app-status-code").Single());
        Assert.Equal("application/octet-stream", response.Content.Headers.ContentType?.MediaType);
        var body = await response.Content.ReadAsByteArrayAsync();
        Assert.Equal(96, body.Length);
        Assert.Equal("63A85ADB36726F4612A52A07B9BBE93387D683B48B424DA50FE2718B9BE31686",
            Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(body)));
    }

    [Fact]
    public async Task Observed_octo_list_route_returns_the_reconstructed_title_database()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/v1/list/12345/0");
        request.Headers.Host = "kickflight-resource-api.grenge.jp";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("application/x-protobuf", response.Content.Headers.ContentType?.MediaType);
        var body = await response.Content.ReadAsByteArrayAsync();
        Assert.True(body.Length > 300);
        Assert.Equal(new byte[] { 0x08, 0x02 }, body[..2]);
        var protobufText = Encoding.UTF8.GetString(body);
        Assert.Contains("7pXtSo", protobufText);
        Assert.Contains("ujPPwv", protobufText);
        Assert.Contains("Ei4139", protobufText);
        Assert.Contains("/cdn/{o}", protobufText);
    }

    [Fact]
    public async Task Octo_revision_one_can_update_to_the_reconstructed_title_database()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/v1/list/12345/1");
        request.Headers.Host = "kickflight-resource-api.grenge.jp";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsByteArrayAsync();
        Assert.Equal(new byte[] { 0x08, 0x02 }, body[..2]);
    }

    [Fact]
    public async Task Configured_direct_client_host_routes_by_method_and_path()
    {
        using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
            config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Harness:DirectClientHosts:0"] = "192.168.1.34"
            })));
        using var request = new HttpRequestMessage(HttpMethod.Post, "/boot/index")
        {
            Content = new ByteArrayContent(new byte[32])
        };
        request.Content.Headers.ContentType = new("application/octet-stream");
        request.Headers.Host = "192.168.1.34:18080";
        using var response = await factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("accepted-boot-index-d2c", response.Headers.GetValues("x-kickflight-fixture").Single());
    }

    [Fact]
    public async Task Cataloged_resource_streams_with_integrity_and_range_support()
    {
        var directory = Path.Combine(Path.GetTempPath(), "kickflight-resources", Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(directory);
        var resourcePath = Path.Combine(directory, "sample.bundle");
        var catalogPath = Path.Combine(directory, "catalog.json");
        var bytes = Enumerable.Range(0, 32).Select(value => (byte)value).ToArray();
        await File.WriteAllBytesAsync(resourcePath, bytes);
        await File.WriteAllTextAsync(catalogPath, JsonSerializer.Serialize(new
        {
            schemaVersion = 1,
            resources = new[]
            {
                new
                {
                    id = "sample-bundle",
                    host = "kickflight-resource-api.grenge.jp",
                    requestPath = "/cdn/sample.bundle",
                    logicalName = "Test bundle",
                    sourcePath = resourcePath,
                    contentType = "application/octet-stream",
                    sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes))
                }
            }
        }));

        try
        {
            using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Harness:ResourceCatalogPath"] = catalogPath
                })));
            using var request = new HttpRequestMessage(HttpMethod.Get, "/cdn/sample.bundle");
            request.Headers.Host = "kickflight-resource-api.grenge.jp";
            request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(4, 7);
            using var response = await factory.CreateClient().SendAsync(request);
            Assert.Equal(HttpStatusCode.PartialContent, response.StatusCode);
            Assert.Equal(bytes[4..8], await response.Content.ReadAsByteArrayAsync());
            Assert.Equal("application/octet-stream", response.Content.Headers.ContentType?.MediaType);
            Assert.Equal($"\"{Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant()}\"", response.Headers.ETag?.Tag);
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public async Task Cataloged_resource_routes_through_direct_client_host()
    {
        var directory = Path.Combine(Path.GetTempPath(), "kickflight-resources", Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(directory);
        var resourcePath = Path.Combine(directory, "sample.bin");
        var catalogPath = Path.Combine(directory, "catalog.json");
        var bytes = "direct-resource"u8.ToArray();
        await File.WriteAllBytesAsync(resourcePath, bytes);
        await File.WriteAllTextAsync(catalogPath, JsonSerializer.Serialize(new
        {
            schemaVersion = 1,
            resources = new[]
            {
                new
                {
                    id = "direct-resource",
                    host = "kickflight-resource-api.grenge.jp",
                    requestPath = "/cdn/direct.bin",
                    logicalName = "Direct resource",
                    sourcePath = resourcePath,
                    sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes))
                }
            }
        }));

        try
        {
            using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Harness:ResourceCatalogPath"] = catalogPath,
                    ["Harness:DirectClientHosts:0"] = "192.168.1.12"
                })));
            using var request = new HttpRequestMessage(HttpMethod.Get, "/cdn/direct.bin");
            request.Headers.Host = "192.168.1.12:18080";
            using var response = await factory.CreateClient().SendAsync(request);
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Equal(bytes, await response.Content.ReadAsByteArrayAsync());
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public async Task Unconfigured_direct_client_host_remains_rejected()
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "/boot/index");
        request.Headers.Host = "192.168.1.99:18080";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal((HttpStatusCode)421, response.StatusCode);
    }

    [Fact]
    public void D2c_codec_matches_known_aes256_cbc_pkcs7_vector()
    {
        var key = Encoding.ASCII.GetBytes("0123456789abcdef0123456789abcdef");
        var vector = Enumerable.Range(0, 16).Select(value => (byte)value).ToArray();
        var encoded = D2CCodec.Encode("{}"u8, key, vector);
        Assert.Equal(
            "000102030405060708090A0B0C0D0E0F4D0F4FA5133FB38F26F5A933DFB9695C",
            Convert.ToHexString(encoded));
        Assert.Equal("{}", Encoding.UTF8.GetString(D2CCodec.Decode(encoded, key)));
    }

    [Fact]
    public async Task Unknown_host_is_rejected()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/anything");
        request.Headers.Host = "example.invalid";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal((HttpStatusCode)421, response.StatusCode);
    }

    [Fact]
    public void Every_known_sensitive_header_is_redacted_deterministically()
    {
        var inspector = new SafeRequestInspector();
        var headers = new HeaderDictionary();
        foreach (var name in SafeRequestInspector.SensitiveHeaders) headers[name] = "sensitive-value";
        var result = inspector.InspectHeaders(headers);
        foreach (var name in SafeRequestInspector.SensitiveHeaders)
        {
            var serialized = JsonSerializer.Serialize(result[name]);
            Assert.DoesNotContain("sensitive-value", serialized);
            Assert.Contains("sha256_12", serialized);
            using var fingerprint = JsonDocument.Parse(serialized);
            Assert.Equal(15, fingerprint.RootElement.GetProperty("length").GetInt32());
        }
    }

    [Fact]
    public void Json_body_redacts_device_and_auth_values()
    {
        var inspector = new SafeRequestInspector();
        var result = inspector.InspectBody(Encoding.UTF8.GetBytes("{\"uuid\":\"abc\",\"accessToken\":\"def\",\"safe\":42}"), "application/json", false);
        var json = JsonSerializer.Serialize(result);
        Assert.DoesNotContain("abc", json);
        Assert.DoesNotContain("def", json);
        Assert.Contains("safe", json);
    }

    [Fact]
    public async Task Capture_limit_truncates_preview_but_hashes_full_body()
    {
        var captureDirectory = Path.Combine(Path.GetTempPath(), "kickflight-tests", Guid.NewGuid().ToString("n"));
        try
        {
            using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Harness:PersistCaptures"] = "true",
                    ["Harness:CaptureDirectory"] = captureDirectory,
                    ["Harness:MaxCapturedBodyBytes"] = "4"
                })));
            using var request = new HttpRequestMessage(HttpMethod.Post, "/__fixture-probe")
            {
                Content = new StringContent("1234567890", Encoding.UTF8, "text/plain")
            };
            request.Headers.Host = "kickflight-api.grenge.jp";
            request.Headers.Add("x-app-access-token", "must-not-appear-in-capture");
            using var response = await factory.CreateClient().SendAsync(request);
            Assert.True(response.IsSuccessStatusCode);
            var file = Directory.GetFiles(captureDirectory, "request-*.json").Single();
            using var capture = JsonDocument.Parse(await File.ReadAllTextAsync(file));
            var body = capture.RootElement.GetProperty("body");
            Assert.Equal(10, body.GetProperty("totalBytes").GetInt64());
            Assert.Equal(4, body.GetProperty("capturedBytes").GetInt32());
            Assert.True(body.GetProperty("truncated").GetBoolean());
            Assert.DoesNotContain("must-not-appear-in-capture", await File.ReadAllTextAsync(file));
        }
        finally
        {
            if (Directory.Exists(captureDirectory)) Directory.Delete(captureDirectory, recursive: true);
        }
    }

    [Fact]
    public async Task Fixture_changes_reload_without_recompiling()
    {
        var fixtureDirectory = Path.Combine(Path.GetTempPath(), "kickflight-fixtures", Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(fixtureDirectory);
        var fixturePath = Path.Combine(fixtureDirectory, "reload.json");
        try
        {
            WriteReloadFixture(fixturePath, "first");
            using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Harness:FixtureDirectory"] = fixtureDirectory
                })));
            var client = factory.CreateClient();
            using var first = new HttpRequestMessage(HttpMethod.Get, "/reload");
            first.Headers.Host = "kickflight-api.grenge.jp";
            Assert.Equal("first", await (await client.SendAsync(first)).Content.ReadAsStringAsync());

            WriteReloadFixture(fixturePath, "second-longer");
            using var second = new HttpRequestMessage(HttpMethod.Get, "/reload");
            second.Headers.Host = "kickflight-api.grenge.jp";
            Assert.Equal("second-longer", await (await client.SendAsync(second)).Content.ReadAsStringAsync());
        }
        finally
        {
            if (Directory.Exists(fixtureDirectory)) Directory.Delete(fixtureDirectory, recursive: true);
        }
    }

    [Fact]
    public void Production_code_has_no_upstream_client_api()
    {
        var root = FindRepositoryRoot();
        var sourceFiles = Directory.GetFiles(Path.Combine(root, "src"), "*.cs", SearchOption.AllDirectories);
        var forbidden = new[] { "HttpClient", "SocketsHttpHandler", "WebRequest.Create", "TcpClient" };
        foreach (var file in sourceFiles)
        {
            var source = File.ReadAllText(file);
            foreach (var symbol in forbidden) Assert.DoesNotContain(symbol, source);
        }
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "KickFlight.PrivateServer.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static void WriteReloadFixture(string path, string body)
    {
        File.WriteAllText(path, JsonSerializer.Serialize(new
        {
            id = "reload-test",
            enabled = true,
            host = "kickflight-api.grenge.jp",
            method = "GET",
            path = "/reload",
            statusCode = 200,
            contentType = "text/plain",
            body
        }));
    }
}
