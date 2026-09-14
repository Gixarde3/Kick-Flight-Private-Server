using System.Net.Sockets;
using Microsoft.Extensions.Options;

namespace KickFlight.BootstrapApi;

public interface IPhotonServerManager
{
    PhotonServerOptions Options { get; }
    PhotonServerStatus GetStatus();
    Task<PhotonServerStatus> CheckHealthAsync(CancellationToken cancellationToken = default);
}

public sealed record PhotonServerStatus(
    bool Enabled,
    string Host,
    int MasterServerPort,
    int GameServerPort,
    int NameServerPort,
    string ContainerName,
    string RepositoryUrl,
    bool MasterReachable,
    bool GameReachable,
    bool NameReachable,
    DateTime LastCheckedUtc,
    string? Message = null);

public sealed class PhotonServerManager : IPhotonServerManager
{
    private readonly PhotonServerOptions _options;
    private readonly ILogger<PhotonServerManager> _logger;
    private PhotonServerStatus _lastStatus;

    public PhotonServerOptions Options => _options;

    public PhotonServerManager(IOptions<PhotonServerOptions> options, ILogger<PhotonServerManager> logger)
    {
        _options = options.Value;
        _logger = logger;
        _lastStatus = new PhotonServerStatus(
            _options.Enabled,
            _options.Host,
            _options.MasterServerPort,
            _options.GameServerPort,
            _options.NameServerPort,
            _options.ContainerName,
            _options.RepositoryUrl,
            MasterReachable: false,
            GameReachable: false,
            NameReachable: false,
            DateTime.UtcNow,
            Message: "Initialized, health check pending");

        _logger.LogInformation(
            "Registered Photon/LuxonServer dependency: Host={Host}, Master={MasterPort}, Game={GamePort}, Name={NamePort}, Repo={Repo}",
            _options.Host,
            _options.MasterServerPort,
            _options.GameServerPort,
            _options.NameServerPort,
            _options.RepositoryUrl);
    }

    public PhotonServerStatus GetStatus() => _lastStatus;

    public async Task<PhotonServerStatus> CheckHealthAsync(CancellationToken cancellationToken = default)
    {
        if (!_options.Enabled)
        {
            _lastStatus = new PhotonServerStatus(
                false,
                _options.Host,
                _options.MasterServerPort,
                _options.GameServerPort,
                _options.NameServerPort,
                _options.ContainerName,
                _options.RepositoryUrl,
                false,
                false,
                false,
                DateTime.UtcNow,
                "PhotonServer disabled in configuration");
            return _lastStatus;
        }

        var masterOk = await PingUdpOrTcpPortAsync(_options.Host, _options.MasterServerPort, cancellationToken);
        var gameOk = await PingUdpOrTcpPortAsync(_options.Host, _options.GameServerPort, cancellationToken);
        var nameOk = await PingUdpOrTcpPortAsync(_options.Host, _options.NameServerPort, cancellationToken);

        var isAllHealthy = masterOk && gameOk && nameOk;
        var message = isAllHealthy
            ? "All Photon/LuxonServer services (Master, Game, Name) are active and responding"
            : $"Partial or unreached services: Master={masterOk}, Game={gameOk}, Name={nameOk}";

        _lastStatus = new PhotonServerStatus(
            true,
            _options.Host,
            _options.MasterServerPort,
            _options.GameServerPort,
            _options.NameServerPort,
            _options.ContainerName,
            _options.RepositoryUrl,
            masterOk,
            gameOk,
            nameOk,
            DateTime.UtcNow,
            message);

        if (isAllHealthy)
        {
            _logger.LogInformation("Photon/LuxonServer health check OK: {Message}", message);
        }
        else
        {
            _logger.LogWarning("Photon/LuxonServer health check WARNING: {Message}", message);
        }

        return _lastStatus;
    }

    private async Task<bool> PingUdpOrTcpPortAsync(string host, int port, CancellationToken cancellationToken)
    {
        try
        {
            var targetHost = host == "10.0.2.2" ? "127.0.0.1" : host;
            using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            using var timeoutCts = new CancellationTokenSource(_options.HealthCheckTimeoutMs);
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);
            
            await socket.ConnectAsync(targetHost, port, linked.Token);
            return socket.Connected;
        }
        catch
        {
            try
            {
                var targetHost = host == "10.0.2.2" ? "127.0.0.1" : host;
                using var udpSocket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
                udpSocket.Connect(targetHost, port);
                byte[] ping = [0x00, 0x00, 0x00, 0x00];
                udpSocket.Send(ping);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
