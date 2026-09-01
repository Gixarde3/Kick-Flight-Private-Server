using System.Buffers;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace KickFlight.BootstrapApi;

public sealed class RequestCaptureMiddleware
{
    private static readonly JsonSerializerOptions CaptureJson = new(JsonSerializerDefaults.Web);
    private readonly RequestDelegate _next;
    private readonly HarnessOptions _options;
    private readonly IWebHostEnvironment _environment;
    private readonly ILogger<RequestCaptureMiddleware> _logger;

    public RequestCaptureMiddleware(
        RequestDelegate next,
        IOptions<HarnessOptions> options,
        IWebHostEnvironment environment,
        ILogger<RequestCaptureMiddleware> logger)
    {
        _next = next;
        _options = options.Value;
        _environment = environment;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context, SafeRequestInspector inspector)
    {
        var correlationId = Guid.NewGuid().ToString("n");
        context.Response.Headers["x-correlation-id"] = correlationId;
        var inspectedBody = await ReadBodyAsync(context.Request, inspector, _options.MaxCapturedBodyBytes, context.RequestAborted);
        var observation = new
        {
            timestampUtc = DateTimeOffset.UtcNow,
            correlationId,
            method = context.Request.Method,
            scheme = context.Request.Scheme,
            host = FixtureStore.NormalizeHost(context.Request.Host.Host),
            path = context.Request.Path.Value,
            query = inspector.InspectQuery(context.Request.Query),
            headers = inspector.InspectHeaders(context.Request.Headers),
            body = inspectedBody
        };

        using (_logger.BeginScope(new Dictionary<string, object> { ["correlationId"] = correlationId }))
        {
            _logger.LogInformation("Received {Method} {Host}{Path}; body bytes={BodyBytes} sha256={BodySha256}",
                context.Request.Method, context.Request.Host.Host, context.Request.Path,
                inspectedBody.TotalBytes, inspectedBody.Sha256);
            _logger.LogInformation("Safe request observation: {Observation}",
                JsonSerializer.Serialize(observation, CaptureJson));
            if (_options.PersistCaptures) await PersistAsync(observation, correlationId, context.RequestAborted);
            await _next(context);
            _logger.LogInformation("Completed {Method} {Host}{Path} with {StatusCode}",
                context.Request.Method, context.Request.Host.Host, context.Request.Path, context.Response.StatusCode);
        }
    }

    private static async Task<InspectedBody> ReadBodyAsync(
        HttpRequest request, SafeRequestInspector inspector, int limit, CancellationToken cancellationToken)
    {
        request.EnableBuffering();
        request.Body.Position = 0;
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var captured = new MemoryStream(Math.Min(limit, 65_536));
        var rented = ArrayPool<byte>.Shared.Rent(16_384);
        long total = 0;
        try
        {
            int read;
            while ((read = await request.Body.ReadAsync(rented.AsMemory(0, rented.Length), cancellationToken)) > 0)
            {
                hash.AppendData(rented, 0, read);
                total += read;
                var remaining = Math.Max(0, limit - (int)captured.Length);
                if (remaining > 0) captured.Write(rented, 0, Math.Min(read, remaining));
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(rented, clearArray: true);
            request.Body.Position = 0;
        }

        var bytes = captured.ToArray();
        var truncated = total > bytes.Length;
        return new InspectedBody(total, bytes.Length, truncated,
            Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant(),
            inspector.InspectBody(bytes, request.ContentType, truncated));
    }

    private async Task PersistAsync(object observation, string correlationId, CancellationToken cancellationToken)
    {
        var configured = _options.CaptureDirectory;
        var directory = RepositoryPaths.Resolve(configured, _environment.ContentRootPath);
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, $"request-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{correlationId}.json");
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(observation, CaptureJson), cancellationToken);
    }
}
