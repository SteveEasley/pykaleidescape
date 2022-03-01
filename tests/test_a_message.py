"""Tests for message module."""

import pytest

from kaleidescape import const
from kaleidescape import message as messages
from kaleidescape.error import MessageParseError
from kaleidescape.message import MESSAGE_TYPE_REQUEST, MessageParser, Request, Response


def test_message_parser():
    """Test message parser."""
    parsed = MessageParser("01/2/003:MESSAGE_NAME:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    assert parsed.seq == 2
    assert parsed.status == 3
    assert parsed.name == "MESSAGE_NAME"
    assert parsed.fields == []
    assert parsed.checksum == 123


def test_message_parser_with_fields():
    """Test message parser with fields."""
    parsed = MessageParser("01/2/003:MESSAGE_NAME:field1:field2:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    assert parsed.seq == 2
    assert parsed.status == 3
    assert parsed.name == "MESSAGE_NAME"
    assert parsed.fields == ["field1", "field2"]
    assert parsed.checksum == 123


def test_message_parser_event():
    """Test message parse as event."""
    parsed = MessageParser("01/!/003:MESSAGE_NAME:field1:field2:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    assert parsed.seq == -1
    assert parsed.status == 3
    assert parsed.name == "MESSAGE_NAME"
    assert parsed.fields == ["field1", "field2"]
    assert parsed.checksum == 123


def test_message_parser_request():
    """Test message parse when message is request."""
    parsed = MessageParser("01/1/GET_MESSAGE_NAME:field1:field2:/123", True)
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    assert parsed.seq == 1
    assert parsed.status == 0
    assert parsed.name == "GET_MESSAGE_NAME"
    assert parsed.fields == ["field1", "field2"]
    assert parsed.checksum is 0


def test_message_parser_device_id():
    """Test message parser device_id."""
    parsed = MessageParser("01/2/003:MESSAGE_NAME:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    parsed = MessageParser("01.02/2/003:MESSAGE_NAME:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 2
    parsed = MessageParser("#0A123F12/2/003:MESSAGE_NAME:/123")
    assert parsed.device_id == "#0A123F12"
    assert parsed.zone == 0
    parsed = MessageParser("#0A123F12.02/2/003:MESSAGE_NAME:/123")
    assert parsed.device_id == "#0A123F12"
    assert parsed.zone == 2


def test_message_parser_bad_device_id():
    """Test message parser with bad device_id."""
    with pytest.raises(MessageParseError) as err:
        MessageParser("1/2/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("001/2/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("aa/2/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("/2/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01./2/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01.0a/2/003:MESSAGE_NAME:/123")


def test_message_parser_seq():
    """Test message parser seq."""
    parsed = MessageParser("01/9/003:MESSAGE_NAME:/123")
    assert parsed.seq == 9
    parsed = MessageParser("01/!/003:MESSAGE_NAME:/123")
    assert parsed.seq == -1


def test_message_parser_bad_seq():
    """Test message parser with bad seq."""
    with pytest.raises(MessageParseError) as err:
        MessageParser("01//003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_SEQ_NUMBER] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/22/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_SEQ_NUMBER] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/aa/003:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_SEQ_NUMBER] in str(err.value)


def test_message_parser_status():
    """Test message parser status."""
    parsed = MessageParser("01/0/999:MESSAGE_NAME:/123")
    assert parsed.status == 999


def test_message_parser_bad_status():
    """Test message parser with bad status."""
    with pytest.raises(MessageParseError) as err:
        MessageParser("01/2/0001:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_UNDETERMINED_ERROR] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/2/01:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_UNDETERMINED_ERROR] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/2/aaa:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_UNDETERMINED_ERROR] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/2/:MESSAGE_NAME:/123")
    assert const.RESPONSE_ERROR[const.ERROR_UNDETERMINED_ERROR] in str(err.value)


def test_message_parser_name():
    """Test message parser name."""
    parsed = MessageParser("01/2/003:MESSAGE_NAME_123:/123")
    assert parsed.name == "MESSAGE_NAME_123"


def test_message_parser_bad_name():
    """Test message parser with bad name."""
    with pytest.raises(MessageParseError) as err:
        MessageParser("01/2/003:MESSAGE_NAME/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_REQUEST] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/2//123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_REQUEST] in str(err.value)
    with pytest.raises(MessageParseError):
        MessageParser("01/2/:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_REQUEST] in str(err.value)


def test_message_parser_field_decoding():
    """Test message parser field decoding."""
    parsed = MessageParser("01/2/003:MESSAGE_NAME:f\\d225ncy:/123")
    assert parsed.fields == ["fáncy"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:f\\\\d225ncy:/123")
    assert parsed.fields == ["f\\d225ncy"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:colon\\:separated:/123")
    assert parsed.fields == ["colon:separated"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:forward\\/slash:/123")
    assert parsed.fields == ["forward/slash"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:back\\\\slash:/123")
    assert parsed.fields == ["back\\slash"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:new\\nline:/123")
    assert parsed.fields == ["new\nline"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:new\\\nline:/123")
    assert parsed.fields == ["new\nline"]
    parsed = MessageParser("01/2/003:MESSAGE_NAME:new\\\rline:/123")
    assert parsed.fields == ["new\rline"]


def test_message_parser_bad_fields():
    """Test message parser with bad fields."""
    with pytest.raises(MessageParseError):
        MessageParser("01/2/:MESSAGE_NAME:field/123")


def test_message_parser_empty_name():
    """Test message parser with empty name."""
    parsed = MessageParser("01/2/000:/123")
    assert parsed.device_id == "01"
    assert parsed.zone == 0
    assert parsed.seq == 2
    assert parsed.status == 0
    assert parsed.name == ""
    assert parsed.fields == []
    assert parsed.checksum == 123


def test_message_response_with_empty_name():
    """Test message response with empty name"""
    message = Response(MessageParser("01/2/999:/123"))
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == 2
    assert message.status == 999
    assert message.fields == []
    assert message.is_event is False
    assert message.is_error is True
    assert message.error == const.RESPONSE_ERROR[message.status]
    assert str(message) == "01/2/999:/123"


def test_message_response_from_command():
    """Test message response from command."""
    message = Response.factory("01/2/000:AVAILABLE_DEVICES:01:02:/123")
    assert isinstance(message, messages.AvailableDevices)
    assert message.type == messages.MESSAGE_TYPE_RESPONSE
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == 2
    assert message.status == 0
    assert message.name == "AVAILABLE_DEVICES"
    assert message.fields == ["01", "02"]
    assert message.is_event is False
    assert message.is_error is False
    assert str(message) == "01/2/000:AVAILABLE_DEVICES:01:02:/123"


def test_message_response_from_event():
    """Test message response from event."""
    message = Response.factory("01/!/000:AVAILABLE_DEVICES:01:02:/123")
    assert isinstance(message, messages.AvailableDevices)
    assert message.type == messages.MESSAGE_TYPE_EVENT
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == -1
    assert message.status == 0
    assert message.name == "AVAILABLE_DEVICES"
    assert message.fields == ["01", "02"]
    assert message.is_event is True
    assert message.is_error is False
    assert str(message) == "01/!/000:AVAILABLE_DEVICES:01:02:/123"


def test_message_response_with_error_status():
    """Test message response with error status."""
    message = Response.factory("01/2/003:AVAILABLE_DEVICES:01:02:/123")
    assert isinstance(message, messages.AvailableDevices)
    assert message.type == messages.MESSAGE_TYPE_RESPONSE
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == 2
    assert message.status == 3
    assert message.name == "AVAILABLE_DEVICES"
    assert message.fields == ["01", "02"]
    assert message.is_event is False
    assert message.is_error is True
    assert message.error == const.RESPONSE_ERROR[message.status]
    assert str(message) == "01/2/003:AVAILABLE_DEVICES:01:02:/123"


def test_message_response_with_parse_error():
    """Test message response with parse error."""
    with pytest.raises(MessageParseError) as err:
        Response.factory("ERR/2/003:AVAILABLE_DEVICES:01:02:/123")
    assert const.RESPONSE_ERROR[const.ERROR_INVALID_DEVICE] in str(err.value)


def test_message_request():
    """Test message request."""
    message = Request()
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == -1
    assert message.status == 0
    assert message.fields == []
    assert message.type == MESSAGE_TYPE_REQUEST


def test_message_request_with_fields():
    """Test message request."""
    message = Request(0, ["field1", "field2"])
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == -1
    assert message.status == 0
    assert message.fields == ["field1", "field2"]
    assert message.type == MESSAGE_TYPE_REQUEST


def test_message_get_available_devices():
    """Test message request as GET_AVAILABLE_DEVICES."""
    message = messages.GetAvailableDevices()
    message.seq = 2
    assert message.device_id == "01"
    assert message.zone == 0
    assert message.seq == 2
    assert message.status == 0
    assert message.name == "GET_AVAILABLE_DEVICES"
    assert message.fields == []
    assert str(message) == "01/2/GET_AVAILABLE_DEVICES:"
