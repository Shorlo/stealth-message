using StealthMessage.Network;

namespace StealthMessage.Tests.Network;

public sealed class WireMessageTests
{
    // -----------------------------------------------------------------------
    // Parse — one test per frame type
    // -----------------------------------------------------------------------

    [Fact]
    public void Parse_HelloFrame_ClientHello()
    {
        string json = """{"type":"hello","version":"1","room":"general","alias":"Alice","pubkey":"ABC"}""";
        var frame = WireFrameSerializer.Parse(json) as HelloFrame;

        Assert.NotNull(frame);
        Assert.Equal("1",       frame.Version);
        Assert.Equal("general", frame.Room);
        Assert.Equal("Alice",   frame.Alias);
        Assert.Equal("ABC",     frame.PubKey);
    }

    [Fact]
    public void Parse_ServerHelloFrame()
    {
        string json = """{"type":"hello","version":"1","alias":"Server","pubkey":"XYZ"}""";
        var frame = WireFrameSerializer.Parse(json) as ServerHelloFrame;

        Assert.NotNull(frame);
        Assert.Equal("Server", frame.Alias);
        Assert.Equal("XYZ",    frame.PubKey);
    }

    [Fact]
    public void Parse_MessageFrame_WithSender()
    {
        string json = """{"type":"message","id":"abc","payload":"pay","timestamp":1234567890,"sender":"Bob"}""";
        var frame = WireFrameSerializer.Parse(json) as MessageFrame;

        Assert.NotNull(frame);
        Assert.Equal("abc",    frame.Id);
        Assert.Equal("pay",    frame.Payload);
        Assert.Equal(1234567890L, frame.Timestamp);
        Assert.Equal("Bob",    frame.Sender);
    }

    [Fact]
    public void Parse_MessageFrame_WithoutSender()
    {
        string json = """{"type":"message","id":"id1","payload":"p","timestamp":0}""";
        var frame = WireFrameSerializer.Parse(json) as MessageFrame;

        Assert.NotNull(frame);
        Assert.Null(frame.Sender);
    }

    [Fact]
    public void Parse_PeerListFrame()
    {
        string json = """{"type":"peerlist","peers":[{"alias":"Bob","fingerprint":"FP1"}]}""";
        var frame = WireFrameSerializer.Parse(json) as PeerListFrame;

        Assert.NotNull(frame);
        Assert.Single(frame.Peers);
        Assert.Equal("Bob", frame.Peers[0].Alias);
        Assert.Equal("FP1", frame.Peers[0].Fingerprint);
    }

    [Fact]
    public void Parse_RoomListFrame()
    {
        string json = """{"type":"roomlist","groups":["room1","room2"]}""";
        var frame = WireFrameSerializer.Parse(json) as RoomListFrame;

        Assert.NotNull(frame);
        Assert.Equal(2, frame.Groups.Count);
        Assert.Contains("room1", frame.Groups);
    }

    [Fact]
    public void Parse_RoomsInfoFrame()
    {
        string json = """{"type":"roomsinfo","rooms":[{"id":"a","kind":"1to1","peers":1,"available":false}]}""";
        var frame = WireFrameSerializer.Parse(json) as RoomsInfoFrame;

        Assert.NotNull(frame);
        Assert.Single(frame.Rooms);
        var room = frame.Rooms[0];
        Assert.Equal("a",    room.Id);
        Assert.Equal("1to1", room.Kind);
        Assert.Equal(1,      room.Peers);
        Assert.False(room.Available);
    }

    [Fact]
    public void Parse_ListRoomsFrame()
    {
        var frame = WireFrameSerializer.Parse("""{"type":"listrooms"}""");
        Assert.IsType<ListRoomsFrame>(frame);
    }

    [Fact]
    public void Parse_PendingFrame()  => Assert.IsType<PendingFrame>(WireFrameSerializer.Parse("""{"type":"pending"}"""));

    [Fact]
    public void Parse_ApprovedFrame() => Assert.IsType<ApprovedFrame>(WireFrameSerializer.Parse("""{"type":"approved"}"""));

    [Fact]
    public void Parse_PingFrame()     => Assert.IsType<PingFrame>(WireFrameSerializer.Parse("""{"type":"ping"}"""));

    [Fact]
    public void Parse_PongFrame()     => Assert.IsType<PongFrame>(WireFrameSerializer.Parse("""{"type":"pong"}"""));

    [Fact]
    public void Parse_ByeFrame()      => Assert.IsType<ByeFrame>(WireFrameSerializer.Parse("""{"type":"bye"}"""));

    [Fact]
    public void Parse_KickFrame()
    {
        var frame = WireFrameSerializer.Parse("""{"type":"kick","reason":"spam"}""") as KickFrame;
        Assert.NotNull(frame);
        Assert.Equal("spam", frame.Reason);
    }

    [Fact]
    public void Parse_MoveFrame()
    {
        var frame = WireFrameSerializer.Parse("""{"type":"move","room":"vip"}""") as MoveFrame;
        Assert.NotNull(frame);
        Assert.Equal("vip", frame.Room);
    }

    [Fact]
    public void Parse_ErrorFrame()
    {
        var frame = WireFrameSerializer.Parse("""{"type":"error","code":4006,"reason":"full"}""") as ErrorFrame;
        Assert.NotNull(frame);
        Assert.Equal(4006,   frame.Code);
        Assert.Equal("full", frame.Reason);
    }

    [Fact]
    public void Parse_UnknownType_ThrowsProtocolException()
    {
        var ex = Assert.Throws<ProtocolException>(
            () => WireFrameSerializer.Parse("""{"type":"bogus"}"""));
        Assert.Equal(ProtocolException.Malformed, ex.Code);
    }

    [Fact]
    public void Parse_MissingTypeField_ThrowsProtocolException()
    {
        Assert.Throws<ProtocolException>(
            () => WireFrameSerializer.Parse("""{"foo":"bar"}"""));
    }

    // -----------------------------------------------------------------------
    // Serialize — round-trip sanity checks
    // -----------------------------------------------------------------------

    [Fact]
    public void Serialize_HelloFrame_ContainsExpectedFields()
    {
        var frame = new HelloFrame("1", "room1", "Alice", "PUBKEY");
        string json = WireFrameSerializer.Serialize(frame);

        Assert.Contains("\"hello\"", json);
        Assert.Contains("room1",     json);
        Assert.Contains("Alice",     json);
        Assert.Contains("PUBKEY",    json);
    }

    [Fact]
    public void Serialize_MessageFrame_OmitsSenderWhenNull()
    {
        var frame = new MessageFrame("id1", "payload", 1000);
        string json = WireFrameSerializer.Serialize(frame);

        Assert.DoesNotContain("sender", json);
    }

    [Fact]
    public void Serialize_MessageFrame_IncludesSenderWhenSet()
    {
        var frame = new MessageFrame("id1", "payload", 1000, "Bob");
        string json = WireFrameSerializer.Serialize(frame);

        Assert.Contains("\"sender\"", json);
        Assert.Contains("Bob",        json);
    }

    [Fact]
    public void Serialize_PingFrame_IsCorrect()
    {
        Assert.Equal("""{"type":"ping"}""", WireFrameSerializer.Serialize(new PingFrame()));
    }

    [Fact]
    public void Serialize_ByeFrame_IsCorrect()
    {
        Assert.Equal("""{"type":"bye"}""", WireFrameSerializer.Serialize(new ByeFrame()));
    }

    [Fact]
    public void Serialize_ListRoomsFrame_IsCorrect()
    {
        Assert.Equal("""{"type":"listrooms"}""", WireFrameSerializer.Serialize(new ListRoomsFrame()));
    }

    [Fact]
    public void Serialize_RoomsInfoFrame_ParseRoundTrip()
    {
        var original = new RoomsInfoFrame(new[]
        {
            new RoomInfo("r1", "group", 2, true),
            new RoomInfo("r2", "1to1",  0, true),
        });
        string json = WireFrameSerializer.Serialize(original);
        var parsed  = WireFrameSerializer.Parse(json) as RoomsInfoFrame;

        Assert.NotNull(parsed);
        Assert.Equal(2,     parsed.Rooms.Count);
        Assert.Equal("r1",  parsed.Rooms[0].Id);
        Assert.Equal(2,     parsed.Rooms[0].Peers);
    }

    // -----------------------------------------------------------------------
    // ProtocolException constants
    // -----------------------------------------------------------------------

    [Fact]
    public void ProtocolException_ErrorCodes_AreCorrect()
    {
        Assert.Equal(4001, ProtocolException.VersionMismatch);
        Assert.Equal(4002, ProtocolException.Malformed);
        Assert.Equal(4006, ProtocolException.RoomFull);
        Assert.Equal(4007, ProtocolException.RoomNotFound);
        Assert.Equal(4008, ProtocolException.JoinDenied);
    }
}
