using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class ThumbnailOctoIntegrityTests : IClassFixture<ServerTestHostFixture>
{
    private readonly WebApplicationFactory<Program> _factory;

    public ThumbnailOctoIntegrityTests(ServerTestHostFixture fixture) => _factory = fixture.Factory;

    private static readonly IReadOnlyDictionary<string, string> ThumbnailNames = new Dictionary<string, string>
    {
        ["thb045"] = "ui/disc/thumbnail_3010045.unity3d",
        ["thb096"] = "ui/disc/thumbnail_3010096.unity3d",
        ["thb133"] = "ui/disc/thumbnail_3010133.unity3d",
        ["thb136"] = "ui/disc/thumbnail_3010136.unity3d",
        ["thb138"] = "ui/disc/thumbnail_3010138.unity3d"
    };

    [Fact]
    public void Every_title_delta_advertises_integrity_for_the_served_thumbnail_bytes()
    {
        var root = FindRepositoryRoot();
        using var catalogDocument = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, "config/resources/catalog.json")));
        var catalog = catalogDocument.RootElement.GetProperty("resources").EnumerateArray()
            .ToDictionary(resource => resource.GetProperty("requestPath").GetString()!, resource => resource);
        using var titleDocument = JsonDocument.Parse(
            File.ReadAllBytes(Path.Combine(root, "config/resources/title-minimum.json")));
        var title = titleDocument.RootElement;
        var assetVersion = title.GetProperty("assetVersion").GetInt32();
        var currentRevision = title.GetProperty("revision").GetInt32();
        var fromRevisions = title.GetProperty("fromRevisions").EnumerateArray()
            .Select(revision => revision.GetInt32()).ToArray();
        var thumbnailNames = new Dictionary<string, string>(ThumbnailNames, StringComparer.Ordinal);
        foreach (var entry in title.GetProperty("entries").EnumerateArray()
                     .Where(entry => entry.GetProperty("id").GetString()!.StartsWith("kicker-skin-thumb-", StringComparison.Ordinal)))
        {
            var objectName = entry.GetProperty("objectName").GetString()!;
            var name = entry.GetProperty("names")[0].GetString()!;
            Assert.True(thumbnailNames.TryAdd(objectName, name), $"Duplicate thumbnail objectName {objectName}.");
        }
        Assert.Equal(49, thumbnailNames.Count);
        var fixtures = Directory.GetFiles(Path.Combine(root, "config/fixtures"),
            $"resource-list-{assetVersion}*.json");
        Assert.Equal(fromRevisions.Length, fixtures.Length);

        foreach (var fixturePath in fixtures)
        {
            using var fixtureDocument = JsonDocument.Parse(File.ReadAllBytes(fixturePath));
            var database = Convert.FromBase64String(
                fixtureDocument.RootElement.GetProperty("bodyBase64").GetString()!);
            var rows = ParseFields(database)
                .Where(field => field.Number == 2 && field.WireType == 2)
                .Select(field => ParseFields(field.Bytes!))
                .Where(fields => fields.Any(field => field.Number == 11 &&
                    field.WireType == 2 && thumbnailNames.ContainsKey(Text(field.Bytes!))))
                .ToArray();

            var expectedFixturePath = $"/v1/list/{assetVersion}/{currentRevision}";
            var isCurrentRevision = fixtureDocument.RootElement.GetProperty("path").GetString() == expectedFixturePath;
            Assert.Equal(isCurrentRevision ? 0 : thumbnailNames.Count, rows.Length);

            foreach (var fields in rows)
            {
                var octoData = fields.ToDictionary(field => field.Number);
                var objectName = Text(octoData[11].Bytes!);
                var name = thumbnailNames[objectName];
                Assert.Equal(name, Text(octoData[2].Bytes!));
                Assert.Equal(name, Text(octoData[3].Bytes!));

                Assert.True(catalog.TryGetValue($"/cdn/{objectName}", out var catalogEntry),
                    $"Missing catalog route for {objectName}.");
                var sourcePath = Path.GetFullPath(Path.Combine(root,
                    catalogEntry.GetProperty("sourcePath").GetString()!));
                var bytes = File.ReadAllBytes(sourcePath);

                Assert.Equal((ulong)bytes.Length, octoData[4].Varint);
                Assert.Equal((ulong)ComputeCrc32(bytes), octoData[5].Varint);
                Assert.Equal(Convert.ToHexString(MD5.HashData(bytes)).ToLowerInvariant(),
                    Text(octoData[10].Bytes!));
                Assert.Equal(catalogEntry.GetProperty("sha256").GetString(),
                    Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
            }
        }
    }

    [Fact]
    public async Task Every_generated_kicker_thumbnail_is_served_over_its_Octo_cdn_route()
    {
        var root = FindRepositoryRoot();
        using var titleDocument = JsonDocument.Parse(
            File.ReadAllBytes(Path.Combine(root, "config/resources/title-minimum.json")));
        using var catalogDocument = JsonDocument.Parse(
            File.ReadAllBytes(Path.Combine(root, "config/resources/catalog.json")));
        var thumbnails = titleDocument.RootElement.GetProperty("entries").EnumerateArray()
            .Where(entry => entry.GetProperty("id").GetString()!.StartsWith("kicker-skin-thumb-", StringComparison.Ordinal))
            .ToArray();
        Assert.Equal(44, thumbnails.Length);
        Assert.Equal(44, thumbnails.Select(entry => entry.GetProperty("octoId").GetInt32()).Distinct().Count());
        Assert.Equal(44, thumbnails.Select(entry => entry.GetProperty("objectName").GetString()).Distinct().Count());

        var catalog = catalogDocument.RootElement.GetProperty("resources").EnumerateArray()
            .ToDictionary(entry => entry.GetProperty("requestPath").GetString()!, entry => entry, StringComparer.Ordinal);
        using var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureAppConfiguration((_, config) =>
            config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Harness:ResourceCatalogPath"] = Path.Combine(root, "config/resources/catalog.json"),
                ["Harness:DirectClientHosts:0"] = "kickflight-resource-api.grenge.jp"
            })));
        using var client = factory.CreateClient();

        foreach (var thumbnail in thumbnails)
        {
            var objectName = thumbnail.GetProperty("objectName").GetString()!;
            Assert.Matches("^[A-Za-z0-9]{6}$", objectName);
            var name = thumbnail.GetProperty("names")[0].GetString()!;
            var route = $"/cdn/{objectName}";
            Assert.True(catalog.TryGetValue(route, out var resource), $"Missing catalog route for {name}.");
            var sourcePath = Path.GetFullPath(Path.Combine(root, resource.GetProperty("sourcePath").GetString()!));
            Assert.True(File.Exists(sourcePath), $"Missing bundle source for {name}: {sourcePath}");
            var expected = await File.ReadAllBytesAsync(sourcePath);

            using var request = new HttpRequestMessage(HttpMethod.Get, route);
            request.Headers.Host = "kickflight-resource-api.grenge.jp";
            using var response = await client.SendAsync(request);
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Equal(expected, await response.Content.ReadAsByteArrayAsync());
        }
    }

    [Fact]
    public void Every_title_delta_has_unique_octo_ids_and_names()
    {
        var root = FindRepositoryRoot();
        using var titleDocument = JsonDocument.Parse(
            File.ReadAllBytes(Path.Combine(root, "config/resources/title-minimum.json")));
        var currentRevision = titleDocument.RootElement.GetProperty("revision").GetInt32();
        var assetVersion = titleDocument.RootElement.GetProperty("assetVersion").GetInt32();
        var fixtures = Directory.GetFiles(Path.Combine(root, "config/fixtures"),
            $"resource-list-{assetVersion}*.json");
        Assert.NotEmpty(fixtures);

        foreach (var fixturePath in fixtures)
        {
            using var fixtureDocument = JsonDocument.Parse(File.ReadAllBytes(fixturePath));
            var database = Convert.FromBase64String(
                fixtureDocument.RootElement.GetProperty("bodyBase64").GetString()!);
            var path = fixtureDocument.RootElement.GetProperty("path").GetString()!;
            var fromRevision = int.Parse(path[(path.LastIndexOf('/') + 1)..]);
            var isCurrentRevision = fromRevision == currentRevision;
            var ids = new HashSet<ulong>();
            var names = new HashSet<string>(StringComparer.Ordinal);

            var dataMessages = ParseFields(database)
                .Where(field => field.WireType == 2 && field.Number is 2 or 4)
                .ToArray();
            Assert.Equal(isCurrentRevision, dataMessages.Length == 0);

            foreach (var dataMessage in dataMessages)
            {
                var data = ParseFields(dataMessage.Bytes!);
                var id = data.Single(field => field.Number == 1 && field.WireType == 0).Varint;
                var name = Text(data.Single(field => field.Number == 2 && field.WireType == 2).Bytes!);
                var state = data.Single(field => field.Number == 9 && field.WireType == 0).Varint;
                Assert.Equal((ulong)(fromRevision == 0 ? 1 : 2), state);
                Assert.True(ids.Add(id), $"Duplicate Octo id {id} in {Path.GetFileName(fixturePath)} ({name}).");
                Assert.True(names.Add(name), $"Duplicate Octo name {name} in {Path.GetFileName(fixturePath)}.");
            }
        }
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "KickFlight.PrivateServer.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static string Text(byte[] bytes) => System.Text.Encoding.UTF8.GetString(bytes);

    private static IReadOnlyList<ProtobufField> ParseFields(ReadOnlySpan<byte> payload)
    {
        var fields = new List<ProtobufField>();
        var offset = 0;
        while (offset < payload.Length)
        {
            var tag = ReadVarint(payload, ref offset);
            var number = checked((int)(tag >> 3));
            var wireType = checked((int)(tag & 7));
            if (wireType == 0)
            {
                fields.Add(new ProtobufField(number, wireType, ReadVarint(payload, ref offset), null));
            }
            else if (wireType == 2)
            {
                var length = checked((int)ReadVarint(payload, ref offset));
                if (length < 0 || offset + length > payload.Length)
                    throw new InvalidDataException($"Invalid protobuf field length {length} at {offset}.");
                fields.Add(new ProtobufField(number, wireType, 0, payload.Slice(offset, length).ToArray()));
                offset += length;
            }
            else
            {
                throw new InvalidDataException($"Unsupported protobuf wire type {wireType} at {offset}.");
            }
        }
        return fields;
    }

    private static ulong ReadVarint(ReadOnlySpan<byte> payload, ref int offset)
    {
        ulong result = 0;
        for (var shift = 0; shift < 64 && offset < payload.Length; shift += 7)
        {
            var value = payload[offset++];
            result |= (ulong)(value & 0x7F) << shift;
            if ((value & 0x80) == 0) return result;
        }
        throw new InvalidDataException("Invalid protobuf varint.");
    }

    private static uint ComputeCrc32(ReadOnlySpan<byte> bytes)
    {
        var crc = 0xFFFFFFFFu;
        foreach (var value in bytes)
        {
            crc ^= value;
            for (var bit = 0; bit < 8; bit++)
                crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0 : 0xEDB88320u);
        }
        return ~crc;
    }

    private sealed record ProtobufField(int Number, int WireType, ulong Varint, byte[]? Bytes);
}
