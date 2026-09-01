using System.Security.Cryptography;

namespace KickFlight.BootstrapApi;

public static class D2CCodec
{
    public const int KeySizeBytes = 32;
    public const int VectorSizeBytes = 16;

    public static byte[] Encode(ReadOnlySpan<byte> plaintext, ReadOnlySpan<byte> parallelCode, ReadOnlySpan<byte> parallelEc)
    {
        Validate(parallelCode, parallelEc);
        using var aes = Aes.Create();
        aes.KeySize = 256;
        aes.BlockSize = 128;
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;
        aes.Key = parallelCode.ToArray();
        aes.IV = parallelEc.ToArray();

        var ciphertext = aes.EncryptCbc(plaintext, aes.IV, PaddingMode.PKCS7);
        var result = new byte[VectorSizeBytes + ciphertext.Length];
        parallelEc.CopyTo(result);
        ciphertext.CopyTo(result, VectorSizeBytes);
        return result;
    }

    public static byte[] Decode(ReadOnlySpan<byte> body, ReadOnlySpan<byte> parallelCode)
    {
        if (parallelCode.Length != KeySizeBytes)
            throw new ArgumentException($"Parallel code must contain exactly {KeySizeBytes} bytes.", nameof(parallelCode));
        if (body.Length < VectorSizeBytes * 2 || body.Length % VectorSizeBytes != 0)
            throw new ArgumentException("D2C body must contain a 16-byte vector followed by one or more AES blocks.", nameof(body));

        using var aes = Aes.Create();
        aes.KeySize = 256;
        aes.BlockSize = 128;
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;
        aes.Key = parallelCode.ToArray();
        var vector = body[..VectorSizeBytes].ToArray();
        return aes.DecryptCbc(body[VectorSizeBytes..], vector, PaddingMode.PKCS7);
    }

    private static void Validate(ReadOnlySpan<byte> parallelCode, ReadOnlySpan<byte> parallelEc)
    {
        if (parallelCode.Length != KeySizeBytes)
            throw new ArgumentException($"Parallel code must contain exactly {KeySizeBytes} bytes.", nameof(parallelCode));
        if (parallelEc.Length != VectorSizeBytes)
            throw new ArgumentException($"Parallel EC/vector must contain exactly {VectorSizeBytes} bytes.", nameof(parallelEc));
    }
}
