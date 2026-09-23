namespace KickFlight.BootstrapApi;

public sealed class HarnessOptions
{
    public bool StrictMode { get; set; } = true;
    public string FixtureDirectory { get; set; } = "config/fixtures";
    public string ResourceCatalogPath { get; set; } = "config/resources/catalog.json";
    public string CaptureDirectory { get; set; } = "captures";
    public bool PersistCaptures { get; set; }
    public int MaxCapturedBodyBytes { get; set; } = 65_536;
    public string[] FirstPartyHosts { get; set; } =
    [
        "kickflight-api.grenge.jp",
        "colorful-api-octo-sb.grenge.jp",
        "kickflight-resource-api.grenge.jp"
    ];
    public string[] DirectClientHosts { get; set; } = [];

    /// <summary>
    /// Optional Octo CDN url format (e.g. "https://pub-xxxx.r2.dev/{o}") handed to direct clients instead of
    /// "{scheme}://{request host}/cdn/{o}". Lets the asset bundles live on an external static host so the initial
    /// 700 MB download does not have to squeeze through this machine's uplink.
    /// </summary>
    public string? OctoCdnUrlFormat { get; set; }
}
