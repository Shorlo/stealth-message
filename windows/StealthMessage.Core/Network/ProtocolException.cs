namespace StealthMessage.Network;

/// <summary>
/// Thrown when a protocol-level error occurs (version mismatch, malformed frame, etc.).
/// Maps to the error codes defined in docs/protocol.md.
/// </summary>
public sealed class ProtocolException(int code, string reason)
    : Exception(reason)
{
    public int Code { get; } = code;

    // Error codes from protocol.md
    public const int VersionMismatch = 4001;
    public const int Malformed       = 4002;
    public const int RoomFull        = 4006;
    public const int RoomNotFound    = 4007;
    public const int JoinDenied      = 4008;
}
