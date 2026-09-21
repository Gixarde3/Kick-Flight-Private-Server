namespace KickFlight.BootstrapApi.PlayerStore;

// Picks the store. A connection string means PostgreSQL; no connection string means the JSON files.
//
// The fallback is not a second production path: it exists so `dotnet test` and a local `start-server.bat`
// need no database, which keeps the suite hermetic. The deployment always sets the connection string, so
// player state there is always in PostgreSQL. Anything added to IPlayerStore that only the Postgres
// implementation can honour must therefore be verified against the deployment, not just the suite.
public static class PlayerStoreFactory
{
    public const string ConnectionStringKey = "PlayerStore:ConnectionString";

    public static IPlayerStore Create(IServiceProvider services, IConfiguration configuration)
    {
        var connectionString = configuration[ConnectionStringKey]
            ?? configuration.GetConnectionString("KickFlight");

        if (string.IsNullOrWhiteSpace(connectionString))
        {
            services.GetRequiredService<ILogger<JsonPlayerStore>>()
                .LogWarning("No {Key} configured: player state is in per-user JSON files, not PostgreSQL",
                    ConnectionStringKey);
            return new JsonPlayerStore(
                services.GetRequiredService<ILogger<JsonPlayerStore>>(),
                services.GetRequiredService<IWebHostEnvironment>());
        }

        return new PostgresPlayerStore(
            services.GetRequiredService<ILogger<PostgresPlayerStore>>(),
            connectionString);
    }
}
