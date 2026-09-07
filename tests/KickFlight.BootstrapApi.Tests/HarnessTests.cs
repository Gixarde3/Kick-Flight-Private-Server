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
        Assert.Equal(new byte[] { 0x08, 0x10 }, body[..2]);
        var protobufText = Encoding.UTF8.GetString(body);
        Assert.Contains("ui/localize/en/title/title_logo.unity3d", protobufText);
        Assert.Contains("7pXtSo", protobufText);
        Assert.Contains("Og1RF0", protobufText);
        Assert.Contains("ujPPwv", protobufText);
        Assert.Contains("Ei4139", protobufText);
        Assert.Contains("originalshader.unity3d", protobufText);
        Assert.Contains("shader/preloadgameshadervariants.unity3d", protobufText);
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
        Assert.Equal(new byte[] { 0x08, 0x10 }, body[..2]);
    }

    [Fact]
    public async Task Octo_current_revision_preserves_the_url_format()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/v1/list/12345/15");
        request.Headers.Host = "kickflight-resource-api.grenge.jp";
        using var response = await _factory.CreateClient().SendAsync(request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsByteArrayAsync();
        Assert.Contains("/cdn/{o}", Encoding.UTF8.GetString(body));
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

    [Fact]
    public async Task Download_master_returns_kicker_costume_and_matches_served_master()
    {
        var client = _factory.CreateClient();
        var host = "kickflight-api.grenge.jp";
        var sessionKey = "0123456789abcdef0123456789abcdef";
        var sessionKeyBytes = Encoding.ASCII.GetBytes(sessionKey);
        var commonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";
        var commonCodeBytes = Encoding.ASCII.GetBytes(commonCode);

        // 1. Authenticate to establish demo session
        var testUuid = Guid.NewGuid().ToString("N");
        var authPayload = JsonSerializer.Serialize(new { hash = sessionKey, uuid = testUuid });
        var authVector = new byte[16];
        var encodedAuth = D2CCodec.Encode(Encoding.UTF8.GetBytes(authPayload), commonCodeBytes, authVector);
        using var authRequest = new HttpRequestMessage(HttpMethod.Post, "/auth/index")
        {
            Content = new ByteArrayContent(encodedAuth)
        };
        authRequest.Headers.Host = host;
        using var authResponse = await client.SendAsync(authRequest);
        Assert.Equal(HttpStatusCode.OK, authResponse.StatusCode);
        var accessToken = authResponse.Headers.GetValues("x-app-access-token").Single();

        // 2. Request /download/master
        using var masterRequest = new HttpRequestMessage(HttpMethod.Post, "/download/master")
        {
            Content = new ByteArrayContent(Array.Empty<byte>())
        };
        masterRequest.Headers.Host = host;
        masterRequest.Headers.Add("x-app-access-token", accessToken);
        using var masterResponse = await client.SendAsync(masterRequest);
        Assert.Equal(DemoSessionApi.MasterVersion, masterResponse.Headers.GetValues("x-app-master-hash").Single());

        var masterEncrypted = await masterResponse.Content.ReadAsByteArrayAsync();
        var masterDecrypted = D2CCodec.Decode(masterEncrypted, sessionKeyBytes);
        using var masterDoc = JsonDocument.Parse(masterDecrypted);
        var downloadList = masterDoc.RootElement.GetProperty("masterDownloadList");
        Assert.True(downloadList.GetArrayLength() >= 1);

        var kickerCostumeEntry = downloadList.EnumerateArray().First(e => e.GetProperty("name").GetString() == "KickerCostume");
        Assert.Equal("KickerCostume", kickerCostumeEntry.GetProperty("name").GetString());
        var masterUrl = kickerCostumeEntry.GetProperty("url").GetString();
        Assert.NotNull(masterUrl);
        Assert.StartsWith($"http://{host}/demo-master/KickerCostume", masterUrl);
        var expectedHash = kickerCostumeEntry.GetProperty("hash").GetString();
        var expectedSize = kickerCostumeEntry.GetProperty("size").GetInt32();

        // 3. Request GET /demo-master/KickerCostume
        using var getMasterRequest = new HttpRequestMessage(HttpMethod.Get, new Uri(masterUrl).PathAndQuery);
        getMasterRequest.Headers.Host = host;
        using var getMasterResponse = await client.SendAsync(getMasterRequest);
        Assert.Equal(HttpStatusCode.OK, getMasterResponse.StatusCode);
        Assert.Equal("application/octet-stream", getMasterResponse.Content.Headers.ContentType?.MediaType);

        var masterBytes = await getMasterResponse.Content.ReadAsByteArrayAsync();
        Assert.Equal(expectedSize, masterBytes.Length);
        Assert.Equal(expectedHash, Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(masterBytes)).ToLowerInvariant());

        var decryptedMaster = D2CCodec.Decode(masterBytes, Encoding.ASCII.GetBytes("1a837b9ee2ae11a07a0f529a4cd4b61c"));
        using var costumeDoc = JsonDocument.Parse(decryptedMaster);
        var list = costumeDoc.RootElement;
        Assert.Equal(118, list.GetArrayLength());
        Assert.Equal(1, list[0].GetProperty("id").GetInt32());
        Assert.Equal(1, list[0].GetProperty("kickerId").GetInt32());
        Assert.Equal(1, list[0].GetProperty("costumeId").GetInt32());

        // 4. Request GET /demo-master/Kicker (verify 14 kickers)
        using var getKickerRequest = new HttpRequestMessage(HttpMethod.Get, "/demo-master/Kicker");
        getKickerRequest.Headers.Host = host;
        using var getKickerResponse = await client.SendAsync(getKickerRequest);
        Assert.Equal(HttpStatusCode.OK, getKickerResponse.StatusCode);
        var kickerBytes = await getKickerResponse.Content.ReadAsByteArrayAsync();
        var decryptedKicker = D2CCodec.Decode(kickerBytes, Encoding.ASCII.GetBytes("1a837b9ee2ae11a07a0f529a4cd4b61c"));
        using var kickerDoc = JsonDocument.Parse(decryptedKicker);
        Assert.Equal(14, kickerDoc.RootElement.GetArrayLength());
        Assert.Equal("Tsubame", kickerDoc.RootElement[0].GetProperty("name").GetString());
        Assert.Equal("Sid", kickerDoc.RootElement[13].GetProperty("name").GetString());

        // 5. Request GET /demo-master/BattleRule (verify Spanish localization)
        using var getRuleRequest = new HttpRequestMessage(HttpMethod.Get, "/demo-master/BattleRule");
        getRuleRequest.Headers.Host = host;
        using var getRuleResponse = await client.SendAsync(getRuleRequest);
        Assert.Equal(HttpStatusCode.OK, getRuleResponse.StatusCode);
        var ruleBytes = await getRuleResponse.Content.ReadAsByteArrayAsync();
        var decryptedRule = D2CCodec.Decode(ruleBytes, Encoding.ASCII.GetBytes("1a837b9ee2ae11a07a0f529a4cd4b61c"));
        using var ruleDoc = JsonDocument.Parse(decryptedRule);
        Assert.Equal("Cristalmanía", ruleDoc.RootElement[0].GetProperty("name").GetString());
        Assert.Equal("Bola rápida", ruleDoc.RootElement[2].GetProperty("name").GetString());

        // 6. Request POST /startup/index (verify 14 kickers unlocked)
        using var startupRequest = new HttpRequestMessage(HttpMethod.Post, "/startup/index")
        {
            Content = new ByteArrayContent(Array.Empty<byte>())
        };
        startupRequest.Headers.Host = host;
        startupRequest.Headers.Add("x-app-access-token", accessToken);
        using var startupResponse = await client.SendAsync(startupRequest);
        Assert.Equal(HttpStatusCode.OK, startupResponse.StatusCode);
        var startupBytes = await startupResponse.Content.ReadAsByteArrayAsync();
        var startupDecrypted = D2CCodec.Decode(startupBytes, sessionKeyBytes);
        using var startupDoc = JsonDocument.Parse(startupDecrypted);
        var userKickerList = startupDoc.RootElement.GetProperty("userKickerList");
        Assert.Equal(14, userKickerList.GetArrayLength());
        var userDiscList = startupDoc.RootElement.GetProperty("userDiscList");
        Assert.Equal(126, userDiscList.GetArrayLength());

        // 7. Request POST /home/index (initial kickerId = 1, 5 decks)
        using var homeRequest = new HttpRequestMessage(HttpMethod.Post, "/home/index")
        {
            Content = new ByteArrayContent(Array.Empty<byte>())
        };
        homeRequest.Headers.Host = host;
        homeRequest.Headers.Add("x-app-access-token", accessToken);
        using var homeResponse = await client.SendAsync(homeRequest);
        Assert.Equal(HttpStatusCode.OK, homeResponse.StatusCode);
        var homeBytes = await homeResponse.Content.ReadAsByteArrayAsync();
        var homeDecrypted = D2CCodec.Decode(homeBytes, sessionKeyBytes);
        using var homeDoc = JsonDocument.Parse(homeDecrypted);
        Assert.Equal(1, homeDoc.RootElement.GetProperty("userPlayer").GetProperty("kickerId").GetInt32());
        var userDiscDeckList = homeDoc.RootElement.GetProperty("userDiscDeckList");
        Assert.Equal(5, userDiscDeckList.GetArrayLength());

        // 8. Select kicker 8 (Anna), costume 2 via POST /kicker/change
        var changePayload = JsonSerializer.Serialize(new { kickerId = 8, kickerCostumeId = 2 });
        var encodedChange = D2CCodec.Encode(Encoding.UTF8.GetBytes(changePayload), sessionKeyBytes, new byte[16]);
        using var changeRequest = new HttpRequestMessage(HttpMethod.Post, "/kicker/change")
        {
            Content = new ByteArrayContent(encodedChange)
        };
        changeRequest.Headers.Host = host;
        changeRequest.Headers.Add("x-app-access-token", accessToken);
        using var changeResponse = await client.SendAsync(changeRequest);
        Assert.Equal(HttpStatusCode.OK, changeResponse.StatusCode);
        Assert.Equal("0", changeResponse.Headers.GetValues("x-app-status-code").Single());

        // 9. Update Deck 2 and switch active deck via POST /disc/change
        var discChangePayload = JsonSerializer.Serialize(new
        {
            discDeckNumber = 2,
            userDiscDeckList = new[]
            {
                new { number = 2, discIdList = new[] { 3010050, 3010051, 3010052, 3010053 } }
            }
        });
        var encodedDiscChange = D2CCodec.Encode(Encoding.UTF8.GetBytes(discChangePayload), sessionKeyBytes, new byte[16]);
        using var discChangeRequest = new HttpRequestMessage(HttpMethod.Post, "/disc/change")
        {
            Content = new ByteArrayContent(encodedDiscChange)
        };
        discChangeRequest.Headers.Host = host;
        discChangeRequest.Headers.Add("x-app-access-token", accessToken);
        using var discChangeResponse = await client.SendAsync(discChangeRequest);
        Assert.Equal(HttpStatusCode.OK, discChangeResponse.StatusCode);
        Assert.Equal("0", discChangeResponse.Headers.GetValues("x-app-status-code").Single());

        // 10. Request POST /home/index again (persisted kickerId = 8, kickerCostumeId = 2, activeDeck = 2)
        using var homeRequest2 = new HttpRequestMessage(HttpMethod.Post, "/home/index")
        {
            Content = new ByteArrayContent(Array.Empty<byte>())
        };
        homeRequest2.Headers.Host = host;
        homeRequest2.Headers.Add("x-app-access-token", accessToken);
        using var homeResponse2 = await client.SendAsync(homeRequest2);
        Assert.Equal(HttpStatusCode.OK, homeResponse2.StatusCode);
        var homeBytes2 = await homeResponse2.Content.ReadAsByteArrayAsync();
        var homeDecrypted2 = D2CCodec.Decode(homeBytes2, sessionKeyBytes);
        using var homeDoc2 = JsonDocument.Parse(homeDecrypted2);
        Assert.Equal(8, homeDoc2.RootElement.GetProperty("userPlayer").GetProperty("kickerId").GetInt32());
        Assert.Equal(2, homeDoc2.RootElement.GetProperty("userPlayer").GetProperty("kickerCostumeId").GetInt32());
        Assert.Equal(2, homeDoc2.RootElement.GetProperty("userPlayer").GetProperty("discDeckNumber").GetInt32());
        var updatedDeck2 = homeDoc2.RootElement.GetProperty("userDiscDeckList").EnumerateArray().First(d => d.GetProperty("number").GetInt32() == 2);
        Assert.Equal(3010050, updatedDeck2.GetProperty("discIdList")[0].GetInt32());
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
