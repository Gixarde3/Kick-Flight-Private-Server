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
}
