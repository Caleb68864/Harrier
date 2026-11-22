"""harrier-mcp command-line flags.

Before: main() ignored argv, so ``harrier-mcp --help`` or ``--version`` in a
terminal started the stdio server and sat waiting for JSON-RPC on stdin, and
a mistyped flag was silently accepted.
"""

import pytest

from harrier import server


def _no_server(monkeypatch):
    def boom():
        raise AssertionError("the server must not start")

    monkeypatch.setattr(server, "create_app", boom)


def test_help_prints_usage_and_does_not_start_the_server(monkeypatch, capsys):
    _no_server(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        server.main(["--help"])
    assert exc.value.code == 0
    assert "stdio" in capsys.readouterr().out


def test_version_prints_the_package_version(monkeypatch, capsys):
    from harrier import __version__

    _no_server(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        server.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unknown_flag_is_an_error(monkeypatch, capsys):
    _no_server(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        server.main(["--port", "80"])
    assert exc.value.code == 2


def test_no_args_starts_the_server(monkeypatch):
    ran = []
    monkeypatch.setattr(server, "create_app",
                        lambda: type("A", (), {"run": lambda self: ran.append(1)})())
    server.main([])
    assert ran == [1]
