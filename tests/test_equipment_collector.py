import json
import socket
import threading

import pytest

from lcomfine.app.equipment_collector import collect_once, decode_json_line, snapshot_from_line


def test_decode_json_line_rejects_non_object_and_oversized_frame():
    assert decode_json_line('{"print_speed": 10}')['print_speed'] == 10
    with pytest.raises(ValueError):
        decode_json_line('[1, 2]')
    with pytest.raises(ValueError):
        decode_json_line(b"x" * (64 * 1024 + 1))


def test_snapshot_from_line_uses_gallus_common_model():
    result = snapshot_from_line(json.dumps({"print_speed": 123.4, "uv_power": 70}))
    assert result["machine"] == "Gallus EMS430"
    assert result["values"]["print_speed"] == 123.4
    assert result["read_only"] is True


def test_collect_once_reads_push_frame_without_writing():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        conn, _ = server.accept()
        try:
            conn.sendall(b'{"print_speed": 111.0, "web_tension": 12.5}\n')
        finally:
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        result = collect_once("127.0.0.1", port)
        assert result["values"]["print_speed"] == 111.0
        assert result["values"]["web_tension"] == 12.5
    finally:
        server.close()
