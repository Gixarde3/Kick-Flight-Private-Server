namespace KickFlight.BootstrapApi;

public sealed class DiagnosticUploadStore
{
    private const long MaxStoredBytes = 2L * 1024 * 1024 * 1024;
    private static readonly TimeSpan Retention = TimeSpan.FromDays(14);
    private readonly string _directory;
    private readonly SemaphoreSlim _writeLock = new(1, 1);

    public DiagnosticUploadStore(string directory)
    {
        _directory = Path.GetFullPath(directory);
        Directory.CreateDirectory(_directory);
        if (!OperatingSystem.IsWindows())
            File.SetUnixFileMode(_directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
    }

    public async Task<StoredDiagnosticUpload> SaveAsync(
        Stream source,
        string? originalFileName,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        var suppliedName = Path.GetFileName(originalFileName ?? string.Empty);
        var extension = Path.GetExtension(suppliedName).ToLowerInvariant();
        if (extension.Length > 12 || extension.Any(c => !char.IsAsciiLetterOrDigit(c) && c != '.'))
            extension = ".bin";

        var stem = Path.GetFileNameWithoutExtension(suppliedName);
        stem = new string(stem.Where(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_').Take(48).ToArray());
        if (string.IsNullOrWhiteSpace(stem)) stem = "log";

        var name = $"diag-upload-{DateTime.UtcNow:yyyyMMdd'T'HHmmssfff'Z'}-{Guid.NewGuid():N}-{stem}{extension}";
        var finalPath = Path.Combine(_directory, name);
        var temporaryPath = Path.Combine(_directory, $".{name}.partial");
        long bytes = 0;

        await _writeLock.WaitAsync(cancellationToken);
        try
        {
            PruneExpiredUploads();
            var storedBytes = GetStoredBytes();
            var fileOptions = new FileStreamOptions
            {
                Mode = FileMode.CreateNew,
                Access = FileAccess.Write,
                Share = FileShare.None,
                BufferSize = 64 * 1024,
                Options = FileOptions.Asynchronous | FileOptions.SequentialScan
            };
            if (!OperatingSystem.IsWindows())
                fileOptions.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
            await using (var target = new FileStream(temporaryPath, fileOptions))
            {
                var buffer = new byte[64 * 1024];
                while (true)
                {
                    var read = await source.ReadAsync(buffer, cancellationToken);
                    if (read == 0) break;
                    if (bytes + read > maxBytes) throw new DiagnosticUploadTooLargeException(maxBytes);
                    if (storedBytes + bytes + read > MaxStoredBytes)
                        throw new DiagnosticUploadCapacityException(MaxStoredBytes);
                    await target.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
                    bytes += read;
                }
                await target.FlushAsync(cancellationToken);
            }

            File.Move(temporaryPath, finalPath);
            return new StoredDiagnosticUpload(name, bytes);
        }
        catch
        {
            try { File.Delete(temporaryPath); } catch (IOException) { }
            throw;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    private void PruneExpiredUploads()
    {
        var now = DateTime.UtcNow;
        foreach (var path in Directory.EnumerateFiles(_directory))
        {
            try
            {
                var name = Path.GetFileName(path);
                var age = now - File.GetLastWriteTimeUtc(path);
                var expiredUpload = name.StartsWith("diag-upload-", StringComparison.Ordinal) && age > Retention;
                var stalePartial = name.StartsWith(".diag-upload-", StringComparison.Ordinal)
                    && name.EndsWith(".partial", StringComparison.Ordinal)
                    && age > TimeSpan.FromDays(1);
                if (expiredUpload || stalePartial) File.Delete(path);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    private long GetStoredBytes()
    {
        long total = 0;
        foreach (var path in Directory.EnumerateFiles(_directory))
        {
            try { total = checked(total + new FileInfo(path).Length); }
            catch (FileNotFoundException) { }
        }
        return total;
    }
}

public sealed record StoredDiagnosticUpload(string Name, long Bytes);

public sealed class DiagnosticUploadTooLargeException(long maxBytes) : Exception
{
    public long MaxBytes { get; } = maxBytes;
}

public sealed class DiagnosticUploadCapacityException(long maxBytes) : Exception
{
    public long MaxBytes { get; } = maxBytes;
}
