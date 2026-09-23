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
        // The first stream gets Stage 1, the interim roster that the join broadcasts to it, Stage 2 and Stage 3.
        var firstWriter = new CollectingWriter(expectedCount: 4, firstCancellation);
        var secondWriter = new CollectingWriter(expectedCount: 3, secondCancellation);

        var firstStream = service.StreamAssignmentsAsync(ticket4, firstWriter, firstCancellation.Token);
        await firstWriter.FirstWrite;
        var secondStream = service.StreamAssignmentsAsync(ticket3, secondWriter, secondCancellation.Token);

        await Task.WhenAll(firstWriter.WaitForExpectedWritesAsync(), secondWriter.WaitForExpectedWritesAsync());
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => firstStream);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => secondStream);

        // The join does not start the match: both clients wait out the window before the bots fill in.
        Assert.Equal(0, Bots(secondWriter.Responses[0].Assignment));

        var firstFinal = firstWriter.Responses[^1].Assignment;
        var secondFinal = secondWriter.Responses[^1].Assignment;
        Assert.NotEmpty(firstFinal.Connection);
        Assert.Equal(firstFinal.Connection, secondFinal.Connection);
        Assert.Equal("1000003", ReadFirstRosterUser(firstFinal));
        Assert.Equal("1000003", ReadFirstRosterUser(secondFinal));

        using var replayCancellation = new CancellationTokenSource();
        var replayWriter = new CollectingWriter(expectedCount: 1, replayCancellation);
        var replayStream = service.StreamAssignmentsAsync(ticket4, replayWriter, replayCancellation.Token);
        await replayWriter.WaitForExpectedWritesAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => replayStream);

        Assert.Single(replayWriter.Responses);
        Assert.Equal(firstFinal.Connection, replayWriter.Responses[0].Assignment.Connection);
    }

    [Fact]
    public async Task Three_humans_share_the_first_room_instead_of_opening_a_second_one()
    {
        var service = CreateService();

        var (_, ticket1) = service.RegisterEntry("1000001", "Player 0001", 1, 1, 1, [3010001, 3010002, 3010003, 3010004]);
        var (_, ticket2) = service.RegisterEntry("1000002", "Player 0002", 2, 1, 1, [3010001, 3010002, 3010003, 3010004]);
        var (_, ticket3) = service.RegisterEntry("1000003", "Player 0003", 3, 1, 1, [3010001, 3010002, 3010003, 3010004]);

        using var firstCancellation = new CancellationTokenSource();
        using var secondCancellation = new CancellationTokenSource();
        using var thirdCancellation = new CancellationTokenSource();
        // Stage 1 + one interim roster per later join + Stage 2 + Stage 3.
        var firstWriter = new CollectingWriter(expectedCount: 5, firstCancellation);
        var secondWriter = new CollectingWriter(expectedCount: 4, secondCancellation);
        var thirdWriter = new CollectingWriter(expectedCount: 3, thirdCancellation);

        var firstStream = service.StreamAssignmentsAsync(ticket1, firstWriter, firstCancellation.Token);
        await firstWriter.FirstWrite;
        var secondStream = service.StreamAssignmentsAsync(ticket2, secondWriter, secondCancellation.Token);
        await secondWriter.FirstWrite;
        var thirdStream = service.StreamAssignmentsAsync(ticket3, thirdWriter, thirdCancellation.Token);

        await Task.WhenAll(
            firstWriter.WaitForExpectedWritesAsync(),
            secondWriter.WaitForExpectedWritesAsync(),
            thirdWriter.WaitForExpectedWritesAsync());
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => firstStream);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => secondStream);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => thirdStream);

        // One room, three humans, and the waiting clients watched each other arrive: no second room, no early bots.
        var connection = firstWriter.Responses[^1].Assignment.Connection;
        Assert.NotEmpty(connection);
        Assert.Equal(connection, secondWriter.Responses[^1].Assignment.Connection);
        Assert.Equal(connection, thirdWriter.Responses[^1].Assignment.Connection);
        Assert.Equal(2, Roster(firstWriter.Responses[1].Assignment).Count); // Player 0001 + the join
        Assert.Equal(3, Roster(firstWriter.Responses[2].Assignment).Count); // + Player 0003, still no bots
        Assert.Equal(0, Bots(firstWriter.Responses[2].Assignment));

        var roster = Roster(firstWriter.Responses[^1].Assignment);
        Assert.Equal(8, roster.Count);
        Assert.Equal(3, roster.Count(entry => entry.GetProperty("kickerAiParameterId").GetInt32() == 0));
        Assert.Equal(4, roster.Count(entry => entry.GetProperty("teamType").GetInt32() == 0));
        Assert.Equal(4, roster.Count(entry => entry.GetProperty("teamType").GetInt32() == 1));
    }

    [Fact]
    public async Task Solo_player_still_gets_a_full_roster_of_bots_when_the_window_closes()
    {
        var service = CreateService();

        var (_, ticket) = service.RegisterEntry("1000001", "Solo", 1, 1, 1, [3010001, 3010002, 3010003, 3010004]);

        using var cancellation = new CancellationTokenSource();
        var writer = new CollectingWriter(expectedCount: 3, cancellation);

        var stream = service.StreamAssignmentsAsync(ticket, writer, cancellation.Token);
        await writer.WaitForExpectedWritesAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => stream);

        Assert.Empty(writer.Responses[0].Assignment.Connection);
        Assert.Empty(writer.Responses[1].Assignment.Connection);
        Assert.NotEmpty(writer.Responses[^1].Assignment.Connection);

        var roster = Roster(writer.Responses[^1].Assignment);
        Assert.Equal(8, roster.Count);
        Assert.Equal("1000001", roster[0].GetProperty("userId").GetString());
        Assert.Equal(7, roster.Count(entry => entry.GetProperty("kickerAiParameterId").GetInt32() > 0));
    }

    [Fact]
    public async Task Eight_humans_start_at_once_with_no_bots_and_no_extra_room()
    {
        var service = CreateService();
        // Long enough that it cannot close on its own: the eighth join is what starts the match.
        service.MatchWindow = TimeSpan.FromSeconds(30);

        var cancellations = new List<CancellationTokenSource>();
        var writers = new List<CollectingWriter>();
        var streams = new List<Task>();

        for (var i = 0; i < 8; i++)
        {
            var userId = $"10000{i + 1:00}";
            var (_, ticket) = service.RegisterEntry(userId, $"Player {userId}", 1, 1, 1,
                [3010001, 3010002, 3010003, 3010004]);

            var cancellation = new CancellationTokenSource();
            cancellations.Add(cancellation);
            // Stage 1, one interim roster per later join (8 - index - 1), Stage 2, Stage 3.
            var writer = new CollectingWriter(expectedCount: 10 - i, cancellation);
            writers.Add(writer);
            streams.Add(service.StreamAssignmentsAsync(ticket, writer, cancellation.Token));
        }

        // The eighth join starts the match on its own: nobody waits out the 30 s window.
        await Task.WhenAll(writers.Select(writer => writer.WaitForExpectedWritesAsync()));
        await Task.WhenAll(streams.Select(async stream =>
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => stream)));
        foreach (var cancellation in cancellations) cancellation.Dispose();

        var connection = writers[0].Responses[^1].Assignment.Connection;
        Assert.NotEmpty(connection);
        foreach (var writer in writers)
        {
            Assert.Equal(connection, writer.Responses[^1].Assignment.Connection);

            var roster = Roster(writer.Responses[^1].Assignment);
            Assert.Equal(8, roster.Count);
            Assert.All(roster, entry => Assert.Equal(0, entry.GetProperty("kickerAiParameterId").GetInt32()));
            Assert.Equal(4, roster.Count(entry => entry.GetProperty("teamType").GetInt32() == 0));
            Assert.Equal(4, roster.Count(entry => entry.GetProperty("teamType").GetInt32() == 1));
        }
    }

    [Fact]
    public void Window_extension_matches_the_agreed_schedule()
    {
        var service = CreateService(fastWindow: false);

        // The shipped defaults (20 s base, 5 s for the second human), unless the environment overrides them.
        if (Environment.GetEnvironmentVariable("KF_MATCH_WINDOW_SECONDS") is null)
        {
            Assert.Equal(20.0, service.MatchWindow.TotalSeconds, 3);
        }
        if (Environment.GetEnvironmentVariable("KF_MATCH_JOIN_INCREMENT_SECONDS") is null)
        {
            Assert.Equal(5.0, service.JoinIncrementBaseSeconds, 3);
        }

        service.MatchWindow = TimeSpan.FromSeconds(20);
        service.JoinIncrementBaseSeconds = 5.0;

        Assert.Equal(0.0, service.JoinIncrementSeconds(1), 3); // the first human only opens the window
        Assert.Equal(5.0, service.JoinIncrementSeconds(2), 3);
        Assert.Equal(4.5, service.JoinIncrementSeconds(3), 3);
        Assert.Equal(4.0, service.JoinIncrementSeconds(4), 3);
        Assert.Equal(2.0, service.JoinIncrementSeconds(8), 3);

        var total = service.MatchWindow.TotalSeconds
            + Enumerable.Range(2, 7).Select(service.JoinIncrementSeconds).Sum();
        Assert.Equal(44.5, total, 3);
    }

    private static BattleMatchmakingService CreateService(bool fastWindow = true)
    {
        var photon = new PhotonServerManager(
            Options.Create(new PhotonServerOptions { Enabled = false }),
            NullLogger<PhotonServerManager>.Instance);
        var service = new BattleMatchmakingService(NullLogger<BattleMatchmakingService>.Instance, photon);

        if (fastWindow)
        {
            // Still a real deadline, only short: the agreed schedule has its own test.
            service.MatchWindow = TimeSpan.FromMilliseconds(200);
            service.JoinIncrementBaseSeconds = 0.05;
        }

        return service;
    }

    private static string ReadFirstRosterUser(Assignment assignment)
    {
        return Roster(assignment)[0].GetProperty("userId").GetString()!;
    }

    private static List<JsonElement> Roster(Assignment assignment)
    {
        var battleJson = assignment.Properties.Fields["battle"].StructValue.ToString();
        using var document = JsonDocument.Parse(battleJson);
        return document.RootElement.GetProperty("battlePlayerList")
            .EnumerateArray()
            .Select(entry => entry.Clone())
            .ToList();
    }

    private static int Bots(Assignment assignment)
    {
        return Roster(assignment).Count(entry => entry.GetProperty("kickerAiParameterId").GetInt32() > 0);
    }

    private sealed class CollectingWriter : IServerStreamWriter<GetAssignmentsResponse>
    {
        // A stage write that never arrives would otherwise hang the suite instead of failing it.
        private static readonly TimeSpan WriteTimeout = TimeSpan.FromSeconds(30);

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

        public async Task WaitForExpectedWritesAsync()
        {
            try
            {
                await _expectedWrites.Task.WaitAsync(WriteTimeout);
            }
            catch (TimeoutException)
            {
                throw new TimeoutException(
                    $"only {Responses.Count} of {_expectedCount} expected writes arrived within {WriteTimeout}");
            }
        }

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
