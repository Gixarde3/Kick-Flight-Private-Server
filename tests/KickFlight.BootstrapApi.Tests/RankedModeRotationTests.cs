using System.Net;
using System.Text;
using System.Text.Json;
using Grpc.Core;
using KickFlight.BootstrapApi;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using OpenMatch;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class RankedModeRotationTests
{
    private const string Host = "kickflight-api.grenge.jp";
    private const string SessionKey = "0123456789abcdef0123456789abcdef";
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";

    [Fact]
    public void Daily_schedule_covers_each_hour_once_and_matches_utc_epoch_cycle()
    {
        using var document = JsonDocument.Parse(RankedModeRotation.BuildScheduleJson());
        var rows = document.RootElement.EnumerateArray().ToArray();
        Assert.Equal(24, rows.Length);
        Assert.Equal(new[] { 8, 8, 8 }, Enumerable.Range(1, 3)
            .Select(type => rows.Count(row => row.GetProperty("seasonMatchBattleRuleType").GetInt32() == type)));
        Assert.Equal("00:00:00", rows.Single(row => row.GetProperty("startTime").GetString() == "23:00:00")
            .GetProperty("endTime").GetString());

        for (var utcHour = 0; utcHour < 24; utcHour++)
        {
            var instant = DateTimeOffset.UnixEpoch.AddHours(utcHour).AddMinutes(30);
            var jstTime = instant.AddHours(9).TimeOfDay;
            var active = rows.Where(row => IsInScheduleWindow(row, jstTime)).ToArray();
            var row = Assert.Single(active);
            Assert.Equal(RankedModeRotation.RuleIdAt(instant), row.GetProperty("battleRuleId").GetInt32());
        }
    }

    [Theory]
    [InlineData(0, 7)]
    [InlineData(3599, 7)]
    [InlineData(3600, 8)]
    [InlineData(7200, 4)]
    [InlineData(10800, 7)]
    public void Resolver_changes_exactly_at_utc_hour_boundaries(long unixSeconds, int expectedRuleId)
    {
        Assert.Equal(expectedRuleId, RankedModeRotation.RuleIdAt(DateTimeOffset.FromUnixTimeSeconds(unixSeconds)));
    }

    [Fact]
    public async Task Battle_entry_rejects_previous_hour_rule_and_accepts_current_rule()
    {
        var clock = new AdjustableTimeProvider(DateTimeOffset.FromUnixTimeSeconds(2 * 3600));
        using var factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.UseContentRoot(AppContext.BaseDirectory);
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<TimeProvider>();
                services.AddSingleton<TimeProvider>(clock);
            });
        });
        var client = factory.CreateClient();
        var sessionKey = Encoding.ASCII.GetBytes(SessionKey);
        var commonCode = Encoding.ASCII.GetBytes(CommonCode);
        var authPayload = JsonSerializer.Serialize(new { hash = SessionKey, uuid = Guid.NewGuid().ToString("N") });
        using var authRequest = new HttpRequestMessage(HttpMethod.Post, "/auth/index")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(authPayload), commonCode, new byte[16]))
        };
        authRequest.Headers.Host = Host;
        using var authResponse = await client.SendAsync(authRequest);
        Assert.Equal(HttpStatusCode.OK, authResponse.StatusCode);
        var accessToken = authResponse.Headers.GetValues("x-app-access-token").Single();

        async Task<HttpResponseMessage> Enter(int ruleId)
        {
            var body = JsonSerializer.Serialize(new { battleRuleId = ruleId });
            using var request = new HttpRequestMessage(HttpMethod.Post, "/battle/entry")
            {
                Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(body), sessionKey, new byte[16]))
            };
            request.Headers.Host = Host;
            request.Headers.Add("x-app-access-token", accessToken);
            return await client.SendAsync(request);
        }

        var previousRule = RankedModeRotation.RuleIdAt(clock.GetUtcNow().AddHours(-1));
        var activeRule = RankedModeRotation.RuleIdAt(clock.GetUtcNow());
        using var rejected = await Enter(previousRule);
        Assert.Equal(HttpStatusCode.OK, rejected.StatusCode);
        Assert.Equal("1", rejected.Headers.GetValues("x-app-status-code").Single());
        Assert.Equal("{}", Encoding.UTF8.GetString(D2CCodec.Decode(await rejected.Content.ReadAsByteArrayAsync(), sessionKey)));

        using var accepted = await Enter(activeRule);
        Assert.Equal(HttpStatusCode.OK, accepted.StatusCode);
        Assert.Equal("0", accepted.Headers.GetValues("x-app-status-code").Single());
        using var acceptedBody = JsonDocument.Parse(D2CCodec.Decode(await accepted.Content.ReadAsByteArrayAsync(), sessionKey));
        Assert.False(string.IsNullOrWhiteSpace(acceptedBody.RootElement.GetProperty("battleEntryTicketId").GetString()));

        var battleEntryId = acceptedBody.RootElement.GetProperty("battleEntryId").GetString()!;
        var ticketId = acceptedBody.RootElement.GetProperty("battleEntryTicketId").GetString()!;
        var matchmaking = factory.Services.GetRequiredService<BattleMatchmakingService>();
        matchmaking.MatchWindow = TimeSpan.FromMilliseconds(1);
        matchmaking.JoinIncrementBaseSeconds = 0;
        using var assignmentCancellation = new CancellationTokenSource();
        var assignmentWriter = new FinalAssignmentWriter();
        var assignmentTask = matchmaking.StreamAssignmentsAsync(ticketId, assignmentWriter, assignmentCancellation.Token);
        var battleId = await assignmentWriter.FinalBattleId.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(activeRule, matchmaking.GetRoomBattleRuleId(battleId));

        // The room keeps its selected mode when the global hourly rotation advances during matchmaking.
        clock.SetUtcNow(clock.GetUtcNow().AddHours(1));
        var newRule = RankedModeRotation.RuleIdAt(clock.GetUtcNow());
        Assert.NotEqual(activeRule, newRule);
        var startPayload = JsonSerializer.Serialize(new { battleId, battleRuleId = newRule });
        using var startRequest = new HttpRequestMessage(HttpMethod.Post, "/battle/start")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(startPayload), sessionKey, new byte[16]))
        };
        startRequest.Headers.Host = Host;
        startRequest.Headers.Add("x-app-access-token", accessToken);
        using var startResponse = await client.SendAsync(startRequest);
        Assert.Equal(HttpStatusCode.OK, startResponse.StatusCode);
        using var startBody = JsonDocument.Parse(D2CCodec.Decode(await startResponse.Content.ReadAsByteArrayAsync(), sessionKey));
        Assert.Equal(2, startBody.RootElement.GetProperty("guardianParameter").GetProperty("id").GetInt32());

        var resultPayload = JsonSerializer.Serialize(new { battleEntryId });
        using var resultRequest = new HttpRequestMessage(HttpMethod.Post, "/battle/result")
        {
            Content = new ByteArrayContent(D2CCodec.Encode(Encoding.UTF8.GetBytes(resultPayload), sessionKey, new byte[16]))
        };
        resultRequest.Headers.Host = Host;
        resultRequest.Headers.Add("x-app-access-token", accessToken);
        using var resultResponse = await client.SendAsync(resultRequest);
        Assert.Equal(HttpStatusCode.OK, resultResponse.StatusCode);
        using var resultBody = JsonDocument.Parse(D2CCodec.Decode(await resultResponse.Content.ReadAsByteArrayAsync(), sessionKey));
        Assert.Equal(3, resultBody.RootElement.GetProperty("userBattleRank").GetProperty("battleRuleType").GetInt32());
        assignmentCancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => assignmentTask);
    }

    private static bool IsInScheduleWindow(JsonElement row, TimeSpan time)
    {
        var start = TimeSpan.Parse(row.GetProperty("startTime").GetString()!);
        var end = TimeSpan.Parse(row.GetProperty("endTime").GetString()!);
        return end > start ? time >= start && time < end : time >= start || time < end;
    }

    private sealed class AdjustableTimeProvider(DateTimeOffset now) : TimeProvider
    {
        private DateTimeOffset _now = now;

        public override DateTimeOffset GetUtcNow() => _now;

        public void SetUtcNow(DateTimeOffset value) => _now = value;
    }

    private sealed class FinalAssignmentWriter : IServerStreamWriter<GetAssignmentsResponse>
    {
        private readonly TaskCompletionSource<string> _finalBattleId = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public WriteOptions? WriteOptions { get; set; }
        public Task<string> FinalBattleId => _finalBattleId.Task;

        public Task WriteAsync(GetAssignmentsResponse message)
        {
            if (!string.IsNullOrWhiteSpace(message.Assignment.Connection))
                _finalBattleId.TrySetResult(message.Assignment.Connection);
            return Task.CompletedTask;
        }
    }
}
