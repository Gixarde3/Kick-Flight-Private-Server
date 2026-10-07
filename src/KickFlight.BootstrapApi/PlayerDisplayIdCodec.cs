namespace KickFlight.BootstrapApi;

/// <summary>
/// Maps persisted player IDs to the 12-digit public IDs accepted by the retail social search dialog.
/// PlayerStore IDs remain unchanged; callers must resolve an exact stored ID before decoding this namespace.
/// </summary>
public static class PlayerDisplayIdCodec
{
    public const long NamespaceBase = 100_000_000_000L;
    public const long NamespaceLimit = 1_000_000_000_000L;

    public static long ToPublic(long playerId) =>
        playerId > 0 && playerId < NamespaceBase ? checked(NamespaceBase + playerId) : playerId;

    public static bool TryDecodePublic(long publicId, out long playerId)
    {
        if (publicId >= NamespaceBase && publicId < NamespaceLimit)
        {
            playerId = publicId - NamespaceBase;
            return playerId > 0;
        }

        playerId = 0;
        return false;
    }

    /// <summary>
    /// Finds an exact stored ID first, then tries decoding a public ID. Exact-first preserves any legacy account
    /// whose stored ID already falls inside the public namespace.
    /// </summary>
    public static T? Find<T>(long requestedId, Func<long, T?> findByStoredId) where T : class
    {
        ArgumentNullException.ThrowIfNull(findByStoredId);
        var exact = findByStoredId(requestedId);
        if (exact is not null) return exact;
        return TryDecodePublic(requestedId, out var playerId) ? findByStoredId(playerId) : null;
    }
}
