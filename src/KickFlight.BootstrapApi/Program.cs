using System.Security.Cryptography.X509Certificates;
using KickFlight.BootstrapApi;
using Microsoft.Extensions.Options;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddJsonConsole(options =>
{
    options.IncludeScopes = true;
    options.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ";
    options.UseUtcTimestamp = true;
});

builder.Services.Configure<HarnessOptions>(builder.Configuration.GetSection("Harness"));
builder.Services.Configure<PhotonServerOptions>(builder.Configuration.GetSection(PhotonServerOptions.SectionName));
builder.Services.AddSingleton<FixtureStore>();
builder.Services.AddSingleton<ResourceCatalogStore>();
builder.Services.AddSingleton<SafeRequestInspector>();
builder.Services.AddSingleton<IPhotonServerManager, PhotonServerManager>();
builder.Services.AddSingleton<BattleMatchmakingService>();
builder.Services.AddSingleton<OpenMatchFrontendService>();
builder.Services.AddSingleton<DemoSessionApi>();
builder.Services.AddGrpc();

var certificatePath = builder.Configuration["Certificate:Path"];
var certificatePassword = builder.Configuration["Certificate:Password"];
var httpPort = builder.Configuration.GetValue("HttpPort", 8080);
var grpcPort = builder.Configuration.GetValue("GrpcPort", 18081);

builder.WebHost.ConfigureKestrel(options =>
{
    options.ListenAnyIP(httpPort, o => o.Protocols = Microsoft.AspNetCore.Server.Kestrel.Core.HttpProtocols.Http1);
    options.ListenAnyIP(grpcPort, o => o.Protocols = Microsoft.AspNetCore.Server.Kestrel.Core.HttpProtocols.Http2);
    if (!string.IsNullOrWhiteSpace(certificatePath) && File.Exists(certificatePath))
    {
        options.ListenAnyIP(builder.Configuration.GetValue("HttpsPort", 8443), listen =>
            listen.UseHttps(new X509Certificate2(certificatePath, certificatePassword)));
    }
});

var app = builder.Build();
app.UseMiddleware<RequestCaptureMiddleware>();
app.MapGrpcService<OpenMatchFrontendService>();

app.MapGet("/health/live", () => Results.Json(new { status = "live" }));
app.MapGet("/health/photon", async (IPhotonServerManager photonManager, CancellationToken ct) =>
{
    var status = await photonManager.CheckHealthAsync(ct);
    return Results.Json(status, statusCode: (status.MasterReachable || !status.Enabled) ? 200 : 503);
});
app.MapGet("/health/ready", async (FixtureStore store, ResourceCatalogStore resourceStore, IPhotonServerManager photonManager, CancellationToken ct) =>
{
    var snapshot = store.GetSnapshot();
    var resourceSnapshot = resourceStore.GetSnapshot();
    var photonStatus = await photonManager.CheckHealthAsync(ct);
    var errors = snapshot.Errors.Concat(resourceSnapshot.Errors).ToList();
    if (photonStatus.Enabled && !photonStatus.MasterReachable)
    {
        errors.Add($"Photon MasterServer unreachable at {photonStatus.Host}:{photonStatus.MasterServerPort}");
    }
    return errors.Count == 0
        ? Results.Json(new { status = "ready", fixtureCount = snapshot.Fixtures.Count, resourceCount = resourceSnapshot.Resources.Count, photon = photonStatus })
        : Results.Json(new { status = "not-ready", errors, photon = photonStatus }, statusCode: 503);
});

app.MapMethods("/{**path}", new[] { "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS" },
    async (HttpContext context, FixtureStore store, ResourceCatalogStore resourceStore, DemoSessionApi demoSessionApi,
        IOptions<HarnessOptions> options, ILoggerFactory loggerFactory) =>
    {
        var host = FixtureStore.NormalizeHost(context.Request.Host.Host);
        var firstParty = options.Value.FirstPartyHosts.Contains(host, StringComparer.OrdinalIgnoreCase);
        var directClient = options.Value.DirectClientHosts.Contains(host, StringComparer.OrdinalIgnoreCase)
            || (!options.Value.StrictMode && System.Net.IPAddress.TryParse(host, out _));
        if (!firstParty && !directClient)
        {
            return Results.Json(new { error = "local-host-not-allowed", host }, statusCode: 421);
        }

        var demoResult = await demoSessionApi.TryHandleAsync(context);
        if (demoResult is not null) return demoResult;

        if (HttpMethods.IsGet(context.Request.Method) || HttpMethods.IsHead(context.Request.Method))
        {
            var resource = directClient
                ? resourceStore.MatchDirect(context.Request.Path.Value ?? "/")
                : resourceStore.Match(host, context.Request.Path.Value ?? "/");
            if (resource is not null)
            {
                context.Response.Headers.CacheControl = "public,max-age=31536000,immutable";
                context.Response.Headers.ETag = $"\"{resource.Definition.Sha256.ToLowerInvariant()}\"";
                loggerFactory.CreateLogger("ResourceRouting").LogInformation(
                    "request -> resource: {Method} {Host}{Path} -> {ResourceId} ({LogicalName})",
                    context.Request.Method, host, context.Request.Path, resource.Definition.Id, resource.Definition.LogicalName);
                return Results.File(resource.SourceFile, resource.Definition.ContentType, enableRangeProcessing: true);
            }
        }

        var fixture = directClient
            ? store.MatchDirect(context.Request.Method, context.Request.Path.Value ?? "/")
            : store.Match(host, context.Request.Method, context.Request.Path.Value ?? "/");
        if (fixture is null)
        {
            loggerFactory.CreateLogger("FixtureRouting").LogWarning(
                "No local fixture for {Method} {Host}{Path}; upstream is disabled",
                context.Request.Method, host, context.Request.Path);
            return Results.Json(new
            {
                error = options.Value.StrictMode ? "local-fixture-missing" : "local-no-response",
                upstream = "disabled",
                host,
                method = context.Request.Method,
                path = context.Request.Path.Value
            }, statusCode: options.Value.StrictMode ? 404 : 501);
        }

        foreach (var header in fixture.Headers)
        {
            context.Response.Headers[header.Key] = header.Value;
        }

        loggerFactory.CreateLogger("FixtureRouting").LogInformation(
            "request -> fixture -> response: {Method} {Host}{Path} -> {FixtureId} -> {StatusCode}",
            context.Request.Method, host, context.Request.Path, fixture.Id, fixture.StatusCode);

        return new LocalFixtureResult(fixture.GetBodyBytes(), fixture.ContentType, fixture.StatusCode);
    });

app.Run();

public partial class Program;
