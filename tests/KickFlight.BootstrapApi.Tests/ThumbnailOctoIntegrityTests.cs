using System.Security.Cryptography;
using System.Text.Json;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class ThumbnailOctoIntegrityTests
{
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
        var fixtures = Directory.GetFiles(Path.Combine(root, "config/fixtures"), "resource-list-12345*.json");
        Assert.Equal(27, fixtures.Length);

        foreach (var fixturePath in fixtures)
        {
            using var fixtureDocument = JsonDocument.Parse(File.ReadAllBytes(fixturePath));
            var database = Convert.FromBase64String(
                fixtureDocument.RootElement.GetProperty("bodyBase64").GetString()!);
            var rows = ParseFields(database)
                .Where(field => field.Number == 2 && field.WireType == 2)
                .Select(field => ParseFields(field.Bytes!))
                .Where(fields => fields.Any(field => field.Number == 11 &&
                    field.WireType == 2 && ThumbnailNames.ContainsKey(Text(field.Bytes!))))
                .ToArray();

            var isCurrentRevision = Path.GetFileName(fixturePath) == "resource-list-12345-from-26.json";
            Assert.Equal(isCurrentRevision ? 0 : ThumbnailNames.Count, rows.Length);

            foreach (var fields in rows)
            {
                var octoData = fields.ToDictionary(field => field.Number);
                var objectName = Text(octoData[11].Bytes!);
                var name = ThumbnailNames[objectName];
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
