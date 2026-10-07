using KickFlight.BootstrapApi;
using Xunit;

namespace KickFlight.BootstrapApi.Tests;

public sealed class PlayerDisplayIdCodecTests
{
    [Theory]
    [InlineData(1_000_001L, 100_001_000_001L)]
    [InlineData(99_999_999_999L, 199_999_999_999L)]
    public void Short_stored_ids_map_to_twelve_digit_public_ids(long storedId, long expectedPublicId)
    {
        var publicId = PlayerDisplayIdCodec.ToPublic(storedId);

        Assert.Equal(expectedPublicId, publicId);
        Assert.Equal(12, publicId.ToString(System.Globalization.CultureInfo.InvariantCulture).Length);
        Assert.True(PlayerDisplayIdCodec.TryDecodePublic(publicId, out var decoded));
        Assert.Equal(storedId, decoded);
    }

    [Theory]
    [InlineData(100_000_000_000L)]
    [InlineData(999_999_999_999L)]
    [InlineData(1_000_000_000_000L)]
    public void Existing_long_stored_ids_are_not_rewritten(long storedId)
    {
        Assert.Equal(storedId, PlayerDisplayIdCodec.ToPublic(storedId));
    }

    [Fact]
    public void Exact_stored_id_wins_before_public_namespace_decode()
    {
        const long shortStoredId = 1_000_001;
        var publicId = PlayerDisplayIdCodec.ToPublic(shortStoredId);
        var existingLongIdProfile = new TestProfile(publicId, "existing-long-id");
        var shortIdProfile = new TestProfile(shortStoredId, "short-id");
        var profiles = new Dictionary<long, TestProfile>
        {
            [publicId] = existingLongIdProfile,
            [shortStoredId] = shortIdProfile
        };

        var resolved = PlayerDisplayIdCodec.Find(publicId, id => profiles.GetValueOrDefault(id));

        Assert.Same(existingLongIdProfile, resolved);
    }

    private sealed record TestProfile(long PlayerId, string Name);
}
