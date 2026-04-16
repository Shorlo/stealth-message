using System.Text.Json;
using System.Text.Json.Serialization;
using StealthMessage.Crypto;

namespace StealthMessage.Network;

// ---------------------------------------------------------------------------
// Supporting data types
// ---------------------------------------------------------------------------

/// <summary>Room entry returned in a roomsinfo frame.</summary>
public sealed record RoomInfo(
    string Id,
    string Kind,
    int    Peers,
    bool   Available);

/// <summary>Peer entry returned in a peerlist frame.</summary>
public sealed record PeerInfo(
    string Alias,
    string Fingerprint);

// ---------------------------------------------------------------------------
// Frame hierarchy
// ---------------------------------------------------------------------------

public abstract record WireFrame;

// Client → Server (or Server → Client for server-hello)
public sealed record HelloFrame(
    string Version,
    string Room,
    string Alias,
    string PubKey) : WireFrame;

public sealed record ServerHelloFrame(
    string Version,
    string Alias,
    string PubKey) : WireFrame;

public sealed record MessageFrame(
    string  Id,
    string  Payload,
    long    Timestamp,
    string? Sender = null) : WireFrame;

public sealed record PeerListFrame(
    IReadOnlyList<PeerInfo> Peers) : WireFrame;

public sealed record RoomListFrame(
    IReadOnlyList<string> Groups) : WireFrame;

public sealed record RoomsInfoFrame(
    IReadOnlyList<RoomInfo> Rooms) : WireFrame;

public sealed record PendingFrame  : WireFrame;
public sealed record ApprovedFrame : WireFrame;
public sealed record PingFrame     : WireFrame;
public sealed record PongFrame     : WireFrame;
public sealed record ByeFrame      : WireFrame;

public sealed record ListRoomsFrame : WireFrame;

public sealed record KickFrame(string Reason) : WireFrame;
public sealed record MoveFrame(string Room)   : WireFrame;

public sealed record ErrorFrame(int Code, string Reason) : WireFrame;

// ---------------------------------------------------------------------------
// Serialization / Deserialization
// ---------------------------------------------------------------------------

public static class WireFrameSerializer
{
    private static readonly JsonSerializerOptions _opts = new()
    {
        PropertyNamingPolicy        = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition      = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>
    /// Deserializes a JSON string into the appropriate <see cref="WireFrame"/> subtype
    /// by inspecting the <c>"type"</c> field.
    /// </summary>
    /// <exception cref="ProtocolException">Thrown for unknown or malformed frames.</exception>
    public static WireFrame Parse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        if (!root.TryGetProperty("type", out var typeProp))
            throw new ProtocolException(ProtocolException.Malformed, "Frame missing 'type' field.");

        string type = typeProp.GetString() ?? string.Empty;

        return type switch
        {
            "hello" => ParseHello(root),
            "server_hello" => new ServerHelloFrame(
                root.GetString("version"),
                root.GetString("alias"),
                root.GetString("pubkey")),
            "message" => new MessageFrame(
                root.GetString("id"),
                root.GetString("payload"),
                root.GetLong("timestamp"),
                root.GetStringOrNull("sender")),
            "peerlist" => new PeerListFrame(
                root.GetProperty("peers").EnumerateArray()
                    .Select(p => new PeerInfo(p.GetString("alias"), p.GetString("fingerprint")))
                    .ToList()),
            "roomlist" => new RoomListFrame(
                root.GetProperty("groups").EnumerateArray()
                    .Select(e => e.GetString()!)
                    .ToList()),
            "roomsinfo" => new RoomsInfoFrame(
                root.GetProperty("rooms").EnumerateArray()
                    .Select(r => new RoomInfo(
                        r.GetString("id"),
                        r.GetString("kind"),
                        r.GetInt("peers"),
                        r.GetBool("available")))
                    .ToList()),
            "pending"   => new PendingFrame(),
            "approved"  => new ApprovedFrame(),
            "ping"      => new PingFrame(),
            "pong"      => new PongFrame(),
            "bye"       => new ByeFrame(),
            "listrooms" => new ListRoomsFrame(),
            "kick"      => new KickFrame(root.GetString("reason")),
            "move"      => new MoveFrame(root.GetString("room")),
            "error"     => new ErrorFrame(root.GetInt("code"), root.GetString("reason")),
            _ => throw new ProtocolException(ProtocolException.Malformed, $"Unknown frame type: '{type}'.")
        };
    }

    private static WireFrame ParseHello(JsonElement root)
    {
        // "hello" is used for both client→server and server→client.
        // When it has "room" it is a client hello; when it has "alias" + "pub_key"
        // but no "room" it is a server hello.
        if (root.TryGetProperty("room", out _))
        {
            return new HelloFrame(
                root.GetString("version"),
                root.GetString("room"),
                root.GetString("alias"),
                root.GetString("pubkey"));
        }
        return new ServerHelloFrame(
            root.GetString("version"),
            root.GetString("alias"),
            root.GetString("pubkey"));
    }

    /// <summary>Serializes a <see cref="WireFrame"/> to its JSON wire representation.</summary>
    public static string Serialize(WireFrame frame)
    {
        return frame switch
        {
            HelloFrame f => Obj(("type", "hello"), ("version", f.Version), ("room", f.Room),
                                ("alias", f.Alias), ("pubkey", f.PubKey)),
            ServerHelloFrame f => Obj(("type", "hello"), ("version", f.Version),
                                      ("alias", f.Alias), ("pubkey", f.PubKey)),
            MessageFrame f     => SerializeMessage(f),
            PeerListFrame f    => SerializePeerList(f),
            RoomListFrame f    => SerializeRoomList(f),
            RoomsInfoFrame f   => SerializeRoomsInfo(f),
            PendingFrame       => Obj(("type", "pending")),
            ApprovedFrame      => Obj(("type", "approved")),
            PingFrame          => Obj(("type", "ping")),
            PongFrame          => Obj(("type", "pong")),
            ByeFrame           => Obj(("type", "bye")),
            ListRoomsFrame     => Obj(("type", "listrooms")),
            KickFrame f        => Obj(("type", "kick"),   ("reason", f.Reason)),
            MoveFrame f        => Obj(("type", "move"),   ("room",   f.Room)),
            ErrorFrame f       => Obj(("type", "error"),  ("code",   f.Code.ToString()),
                                      ("reason",          f.Reason)),
            _ => throw new ArgumentException($"Unknown frame type: {frame.GetType().Name}")
        };
    }

    // ------------------------------------------------------------------
    // Private helpers
    // ------------------------------------------------------------------

    private static string SerializeMessage(MessageFrame f)
    {
        using var ms     = new System.IO.MemoryStream();
        using var writer = new Utf8JsonWriter(ms);
        writer.WriteStartObject();
        writer.WriteString("type", "message");
        writer.WriteString("id", f.Id);
        writer.WriteString("payload", f.Payload);
        writer.WriteNumber("timestamp", f.Timestamp);
        if (f.Sender is not null) writer.WriteString("sender", f.Sender);
        writer.WriteEndObject();
        writer.Flush();
        return System.Text.Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string SerializePeerList(PeerListFrame f)
    {
        using var ms     = new System.IO.MemoryStream();
        using var writer = new Utf8JsonWriter(ms);
        writer.WriteStartObject();
        writer.WriteString("type", "peerlist");
        writer.WriteStartArray("peers");
        foreach (var p in f.Peers)
        {
            writer.WriteStartObject();
            writer.WriteString("alias", p.Alias);
            writer.WriteString("fingerprint", p.Fingerprint);
            writer.WriteEndObject();
        }
        writer.WriteEndArray();
        writer.WriteEndObject();
        writer.Flush();
        return System.Text.Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string SerializeRoomList(RoomListFrame f)
    {
        using var ms     = new System.IO.MemoryStream();
        using var writer = new Utf8JsonWriter(ms);
        writer.WriteStartObject();
        writer.WriteString("type", "roomlist");
        writer.WriteStartArray("groups");
        foreach (var g in f.Groups) writer.WriteStringValue(g);
        writer.WriteEndArray();
        writer.WriteEndObject();
        writer.Flush();
        return System.Text.Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string SerializeRoomsInfo(RoomsInfoFrame f)
    {
        using var ms     = new System.IO.MemoryStream();
        using var writer = new Utf8JsonWriter(ms);
        writer.WriteStartObject();
        writer.WriteString("type", "roomsinfo");
        writer.WriteStartArray("rooms");
        foreach (var r in f.Rooms)
        {
            writer.WriteStartObject();
            writer.WriteString("id", r.Id);
            writer.WriteString("kind", r.Kind);
            writer.WriteNumber("peers", r.Peers);
            writer.WriteBoolean("available", r.Available);
            writer.WriteEndObject();
        }
        writer.WriteEndArray();
        writer.WriteEndObject();
        writer.Flush();
        return System.Text.Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string Obj(params (string key, object? val)[] pairs)
    {
        using var ms     = new System.IO.MemoryStream();
        using var writer = new Utf8JsonWriter(ms);
        writer.WriteStartObject();
        foreach (var (k, v) in pairs)
        {
            switch (v)
            {
                case string s: writer.WriteString(k, s); break;
                case int i:    writer.WriteNumber(k, i); break;
                case long l:   writer.WriteNumber(k, l); break;
                case bool b:   writer.WriteBoolean(k, b); break;
                default:       writer.WriteString(k, v?.ToString() ?? string.Empty); break;
            }
        }
        writer.WriteEndObject();
        writer.Flush();
        return System.Text.Encoding.UTF8.GetString(ms.ToArray());
    }
}

// ---------------------------------------------------------------------------
// JsonElement extension helpers (avoid repeated boilerplate)
// ---------------------------------------------------------------------------

internal static class JsonElementExtensions
{
    public static string GetString(this JsonElement el, string property) =>
        el.GetProperty(property).GetString()
            ?? throw new ProtocolException(ProtocolException.Malformed,
                                           $"'{property}' is null.");

    public static string? GetStringOrNull(this JsonElement el, string property) =>
        el.TryGetProperty(property, out var p) ? p.GetString() : null;

    public static int GetInt(this JsonElement el, string property) =>
        el.GetProperty(property).GetInt32();

    public static long GetLong(this JsonElement el, string property) =>
        el.GetProperty(property).GetInt64();

    public static bool GetBool(this JsonElement el, string property) =>
        el.GetProperty(property).GetBoolean();
}
