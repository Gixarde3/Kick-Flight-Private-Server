namespace KickFlight.BootstrapApi;

public sealed class LocalFixtureResult(byte[] body, string contentType, int statusCode) : IResult
{
    public async Task ExecuteAsync(HttpContext httpContext)
    {
        httpContext.Response.StatusCode = statusCode;
        httpContext.Response.ContentType = contentType;
        httpContext.Response.ContentLength = body.Length;
        if (!HttpMethods.IsHead(httpContext.Request.Method))
            await httpContext.Response.Body.WriteAsync(body, httpContext.RequestAborted);
    }
}
