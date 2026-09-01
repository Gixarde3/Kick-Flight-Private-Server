using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace KickFlight.BootstrapApi;

public sealed class SafeRequestInspector
{
    public static readonly HashSet<string> SensitiveHeaders = new(StringComparer.OrdinalIgnoreCase)
    {
        "authorization", "cookie", "set-cookie", "x-api-key", "x-octo-key",
        "x-app-access-token", "x-app-adid", "x-app-adjust-adid", "x-app-idfa",
        "x-app-user-id", "x-device-id", "x-app-device-id"
    };

    private static readonly string[] SensitiveKeyParts =
    [
        "token", "secret", "password", "cookie", "authorization", "uuid", "uniqueid",
        "deviceid", "advertisingid", "adid", "idfa", "apikey", "userid", "hash"
    ];

    public IReadOnlyDictionary<string, object> InspectHeaders(IHeaderDictionary headers) => headers
        .OrderBy(h => h.Key, StringComparer.OrdinalIgnoreCase)
        .ToDictionary(
            h => h.Key,
            h => SensitiveHeaders.Contains(h.Key) ? Fingerprint(h.Value.ToString()) : (object)h.Value.ToString(),
            StringComparer.OrdinalIgnoreCase);

    public IReadOnlyDictionary<string, object> InspectQuery(IQueryCollection query) => query
        .OrderBy(q => q.Key, StringComparer.OrdinalIgnoreCase)
        .ToDictionary(
            q => q.Key,
            q => IsSensitiveKey(q.Key) ? Fingerprint(q.Value.ToString()) : (object)q.Value.ToString(),
            StringComparer.OrdinalIgnoreCase);

    public object InspectBody(ReadOnlySpan<byte> bytes, string? contentType, bool truncated)
    {
        var mediaType = contentType?.Split(';', 2)[0].Trim();
        if (string.Equals(mediaType, "application/json", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                var node = JsonNode.Parse(bytes);
                RedactJson(node);
                return new { format = "json", truncated, preview = node?.ToJsonString() ?? "null" };
            }
            catch (JsonException)
            {
                return new { format = "invalid-json", truncated, preview = SafeText(bytes) };
            }
        }

        if (string.Equals(mediaType, "application/x-www-form-urlencoded", StringComparison.OrdinalIgnoreCase))
            return new { format = "form", truncated, preview = InspectForm(SafeText(bytes)) };

        if (mediaType?.StartsWith("text/", StringComparison.OrdinalIgnoreCase) == true)
            return new { format = "text", truncated, preview = SafeText(bytes) };

        return new { format = "binary", truncated, capturedBytes = bytes.Length };
    }

    public static object Fingerprint(string value)
    {
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant()[..12];
        return new { redacted = true, present = true, length = value.Length, sha256_12 = hash };
    }

    private static bool IsSensitiveKey(string key)
    {
        var compact = new string(key.Where(char.IsLetterOrDigit).ToArray()).ToLowerInvariant();
        return SensitiveKeyParts.Any(compact.Contains);
    }

    private static void RedactJson(JsonNode? node)
    {
        if (node is JsonObject obj)
        {
            foreach (var property in obj.ToArray())
            {
                if (IsSensitiveKey(property.Key) && property.Value is not null)
                    obj[property.Key] = JsonSerializer.SerializeToNode(Fingerprint(property.Value.ToJsonString()));
                else
                    RedactJson(property.Value);
            }
        }
        else if (node is JsonArray array)
        {
            foreach (var child in array) RedactJson(child);
        }
    }

    private static string SafeText(ReadOnlySpan<byte> bytes)
    {
        var text = Encoding.UTF8.GetString(bytes);
        return text.Length <= 2_048 ? text : text[..2_048] + "…";
    }

    private static IReadOnlyDictionary<string, object> InspectForm(string text)
    {
        var result = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in text.Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = pair.Split('=', 2);
            var key = Uri.UnescapeDataString(parts[0].Replace('+', ' '));
            var value = parts.Length == 2 ? Uri.UnescapeDataString(parts[1].Replace('+', ' ')) : "";
            result[key] = IsSensitiveKey(key) ? Fingerprint(value) : value;
        }
        return result;
    }
}

public sealed record InspectedBody(long TotalBytes, int CapturedBytes, bool Truncated, string Sha256, object View);
