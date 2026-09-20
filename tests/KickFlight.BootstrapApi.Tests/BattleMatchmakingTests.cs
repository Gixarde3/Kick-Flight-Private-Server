using System.Text.Json;
using Grpc.Core;
using KickFlight.BootstrapApi;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using OpenMatch;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class BattleMatchmakingTests
{
    [Fact]
    public async Task Streaming_match_is_canonical_and_completed_assignment_is_replayable()
    {
        var service = CreateService();
        var (_, ticket4) = service.RegisterEntry("1000004", "Player 0004", 1, 1, 1, [3010001, 3010002, 3010003, 3010004]);
        var (_, ticket3) = service.RegisterEntry("1000003", "Player 0003", 1, 1, 1, [3010001, 3010002, 3010003, 3010004]);

        using var firstCancellation = new CancellationTokenSource();
        using var secondCancellation = new CancellationTokenSource();
        var firstWriter = new CollectingWriter(expectedCount: 3, firstCancellation);
        var secondWriter = new CollectingWriter(expectedCount: 3, secondCancellation);

        var firstStream = service.StreamAssignmentsAsync(ticket4, firstWriter, firstCancellation.Token);
        await firstWriter.FirstWrite;
        var secondStream = service.StreamAssignmentsAsync(ticket3, secondWriter, secondCancellation.Token);

        await Task.WhenAll(firstWriter.ExpectedWrites, secondWriter.ExpectedWrites);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => firstStream);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => secondStream);

        var firstFinal = firstWriter.Responses[^1].Assignment;
        var secondFinal = secondWriter.Responses[^1].Assignment;
        Assert.NotEmpty(firstFinal.Connection);
        Assert.Equal(firstFinal.Connection, secondFinal.Connection);
        Assert.Equal("1000003", ReadFirstRosterUser(firstFinal));
        Assert.Equal("1000003", ReadFirstRosterUser(secondFinal));

        using var replayCancellation = new CancellationTokenSource();
        var replayWriter = new CollectingWriter(expectedCount: 1, replayCancellation);
        var replayStream = service.StreamAssignmentsAsync(ticket4, replayWriter, replayCancellation.Token);
        await replayWriter.ExpectedWrites;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => replayStream);

        Assert.Single(replayWriter.Responses);
        Assert.Equal(firstFinal.Connection, replayWriter.Responses[0].Assignment.Connection);
    }

    private static BattleMatchmakingService CreateService()
    {
        var photon = new PhotonServerManager(
            Options.Create(new PhotonServerOptions { Enabled = false }),
            NullLogger<PhotonServerManager>.Instance);
        return new BattleMatchmakingService(NullLogger<BattleMatchmakingService>.Instance, photon);
    }

    private static string ReadFirstRosterUser(Assignment assignment)
    {
        var battleJson = assignment.Properties.Fields["battle"].StructValue.ToString();
        using var document = JsonDocument.Parse(battleJson);
        return document.RootElement.GetProperty("battlePlayerList")[0].GetProperty("userId").GetString()!;
    }

    private sealed class CollectingWriter : IServerStreamWriter<GetAssignmentsResponse>
    {
        private readonly int _expectedCount;
        private readonly CancellationTokenSource _cancellation;
        private readonly TaskCompletionSource _firstWrite = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _expectedWrites = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public CollectingWriter(int expectedCount, CancellationTokenSource cancellation)
        {
            _expectedCount = expectedCount;
            _cancellation = cancellation;
        }

        public WriteOptions? WriteOptions { get; set; }
        public List<GetAssignmentsResponse> Responses { get; } = [];
        public Task FirstWrite => _firstWrite.Task;
        public Task ExpectedWrites => _expectedWrites.Task;

        public Task WriteAsync(GetAssignmentsResponse message)
        {
            Responses.Add(message);
            _firstWrite.TrySetResult();
            if (Responses.Count >= _expectedCount)
            {
                _expectedWrites.TrySetResult();
                _cancellation.Cancel();
            }
            return Task.CompletedTask;
        }
    }
}
