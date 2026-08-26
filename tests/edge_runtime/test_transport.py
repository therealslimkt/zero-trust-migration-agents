import subprocess
import unittest

from edge_runtime.transport import SourceTransportError, TailscaleSSHTransport
from edge_runtime.types import SourceSpec, get_source_spec


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def completed(returncode=0, stdout=b""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=b"")


class TailscaleSSHTransportTests(unittest.TestCase):
    def test_reads_allowlisted_export_through_magicdns(self):
        runner = FakeRunner([completed(), completed(stdout=b"fixture")])
        transport = TailscaleSSHTransport(runner=runner)

        payload = transport.read(get_source_spec("jde"))

        self.assertEqual(payload.data, b"fixture")
        self.assertEqual(runner.calls[0][0][-1], "legacy-jde-db")
        self.assertEqual(runner.calls[1][0][:3], ["tailscale", "ssh", "kohalloran@legacy-jde-db"])
        self.assertNotIn("100.", " ".join(runner.calls[1][0]))

    def test_rejects_ip_hostname(self):
        spec = SourceSpec("jde", "100.106.76.39", "/home/kohalloran/file", "jde")
        with self.assertRaises(ValueError):
            TailscaleSSHTransport(runner=FakeRunner([])).read(spec)

    def test_rejects_substituted_path_on_allowlisted_host(self):
        spec = SourceSpec(
            "jde",
            "legacy-jde-db",
            "/home/kohalloran/other.bin",
            "jde-as400-f0101",
        )
        with self.assertRaises(ValueError):
            TailscaleSSHTransport(runner=FakeRunner([])).read(spec)

    def test_fails_closed_when_ping_fails(self):
        runner = FakeRunner([completed(returncode=1)])
        with self.assertRaises(SourceTransportError):
            TailscaleSSHTransport(runner=runner).read(get_source_spec("maxdb"))
        self.assertEqual(len(runner.calls), 1)

    def test_rejects_oversized_export(self):
        runner = FakeRunner([completed(), completed(stdout=b"12345")])
        with self.assertRaises(SourceTransportError):
            TailscaleSSHTransport(max_bytes=4, runner=runner).read(get_source_spec("btrieve"))

    def test_payload_repr_does_not_expose_raw_bytes(self):
        runner = FakeRunner([completed(), completed(stdout=b"secret fixture")])
        payload = TailscaleSSHTransport(runner=runner).read(get_source_spec("jde"))
        self.assertNotIn("secret fixture", repr(payload))


if __name__ == "__main__":
    unittest.main()
