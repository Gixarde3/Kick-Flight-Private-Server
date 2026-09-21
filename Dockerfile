# Builds the bootstrap API for the NAS deployment. The compose file at the repository root refers to this
# file; deploy/docker-compose.nas.yml is the one that actually runs on the NAS.
#
# Only the API project is built - the test project is not part of the image.
#
# Runtime paths are deliberately NOT baked in. The image carries the binaries under /app; config/, content/
# and data/ are bind-mounted at /srv/repo and the assets tree at /srv/Kick-Flight-Assets, so masters can be
# edited without rebuilding. KF_REPO_ROOT points RepositoryPaths at /srv/repo, and because the asset catalog
# addresses bundles as "../Kick-Flight-Assets/octo_sorted/...", that tree must sit exactly one level above
# the repo root - hence /srv/Kick-Flight-Assets rather than a name of our choosing.

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Restore against the project file alone so a source-only edit reuses the NuGet layer.
COPY src/KickFlight.BootstrapApi/KickFlight.BootstrapApi.csproj src/KickFlight.BootstrapApi/
RUN dotnet restore src/KickFlight.BootstrapApi/KickFlight.BootstrapApi.csproj

COPY src/ src/
RUN dotnet publish src/KickFlight.BootstrapApi/KickFlight.BootstrapApi.csproj \
        -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .

ENV KF_REPO_ROOT=/srv/repo \
    ASPNETCORE_CONTENTROOT=/srv/repo \
    HttpPort=8080 \
    GrpcPort=18081 \
    DOTNET_EnableDiagnostics=0

# 8080 is the HTTP API, reached only through the nginx CDN sidecar; 18081 is gRPC, published directly because
# the client learns it from the matchmaking response and there is nothing to serve in front of it.
EXPOSE 8080 18081

ENTRYPOINT ["dotnet", "KickFlight.BootstrapApi.dll"]
