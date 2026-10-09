using System.Net;
using System.Text;
using KickFlight.BootstrapApi;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class LatestInformationTests : IDisposable
{
    private readonly string _stateFile = Path.Combine(Path.GetTempPath(), $"kf-latest-information-{Guid.NewGuid():N}", "latest-information.json");
    private readonly WebApplicationFactory<Program> _factory;

    public LatestInformationTests()
    {
        _factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder => builder
            .UseContentRoot(AppContext.BaseDirectory)
            .UseSetting("LatestInformation:FilePath", _stateFile));
    }

    [Fact]
    public void State_persists_and_renders_the_supported_safe_formatting()
    {
        var state = new LatestInformationState(NullLogger<LatestInformationState>.Instance, _stateFile);
        state.Set("## Update\nTwo lines\nremain together.\n\n- **New mode**\n- `maintenance`\n- https://example.com\n\n<script>alert(1)</script>");

        var html = new LatestInformationState(NullLogger<LatestInformationState>.Instance, _stateFile).BuildHtml();
        Assert.Contains("<h3>Update</h3>", html);
        Assert.Contains("<p>Two lines<br>remain together.</p>", html);
        Assert.Contains("<li><strong>New mode</strong></li>", html);
        Assert.Contains("<li><code>maintenance</code></li>", html);
        Assert.Contains("href=\"https://example.com\"", html);
        Assert.Contains("&lt;script&gt;alert(1)&lt;/script&gt;", html);
        Assert.DoesNotContain("<script>alert(1)</script>", html);
    }

    [Fact]
    public void State_keeps_the_previous_value_when_disk_persistence_fails()
    {
        var blocker = Path.Combine(Path.GetTempPath(), $"kf-latest-information-blocker-{Guid.NewGuid():N}");
        File.WriteAllText(blocker, "not a directory");
        try
        {
            var state = new LatestInformationState(NullLogger<LatestInformationState>.Instance,
                Path.Combine(blocker, "latest-information.json"));
            var original = state.Current;
            Assert.Throws<InvalidOperationException>(() => state.Set("must not be reported saved"));
            Assert.Equal(original, state.Current);
        }
        finally
        {
            File.Delete(blocker);
        }
    }

    [Fact]
    public async Task Admin_endpoint_is_loopback_only_and_saved_content_is_served_to_the_webview()
    {
        Assert.Equal(HttpStatusCode.NotFound, await AdminAsync(IPAddress.Parse("203.0.113.5"), "GET", null));
        Assert.Equal(HttpStatusCode.NotFound, await AdminAsync(IPAddress.Loopback, "GET", null, "X-Real-IP"));
        Assert.Equal(HttpStatusCode.OK, await AdminAsync(IPAddress.Loopback, "POST", """{"content":"## Server news\n\n- Matchmaking is back"}"""));
        Assert.Equal("## Server news\n\n- Matchmaking is back",
            _factory.Services.GetRequiredService<LatestInformationState>().Current.Content);
        Assert.Contains("<h3>Server news</h3>", _factory.Services.GetRequiredService<LatestInformationState>().BuildHtml());

        using var response = await _factory.CreateClient().GetAsync("/webview/information/index");
        var html = await response.Content.ReadAsStringAsync();
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/html", response.Content.Headers.ContentType?.MediaType);
        Assert.Contains("<h2>Latest Information</h2>", html);
        Assert.Contains("<h3>Server news</h3>", html);
        Assert.Contains("<li>Matchmaking is back</li>", html);

        Assert.Equal(HttpStatusCode.BadRequest, await AdminAsync(IPAddress.Loopback, "POST", """{"content":123}"""));
        Assert.Equal(HttpStatusCode.BadRequest, await AdminAsync(IPAddress.Loopback, "POST",
            "{\"content\":\"" + new string('x', LatestInformationState.MaximumContentLength + 1) + "\"}"));
    }

    private async Task<HttpStatusCode> AdminAsync(IPAddress remote, string method, string? body, string? proxyHeader = null)
    {
        var context = await _factory.Server.SendAsync(http =>
        {
            http.Request.Method = method;
            http.Request.Path = "/admin/latest-information";
            http.Request.Host = new HostString("127.0.0.1", 8080);
            http.Connection.RemoteIpAddress = remote;
            if (proxyHeader is not null) http.Request.Headers[proxyHeader] = "198.51.100.1";
            if (body is not null) http.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes(body));
        });
        return (HttpStatusCode)context.Response.StatusCode;
    }

    public void Dispose()
    {
        _factory.Dispose();
        var directory = Path.GetDirectoryName(_stateFile)!;
        if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
    }
}
