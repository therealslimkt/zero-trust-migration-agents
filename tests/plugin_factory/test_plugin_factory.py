from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from plugin_factory import FactoryError, build_release, validate_plugin, verify_release


REPOSITORY = Path(__file__).resolve().parents[2]
REFERENCE = REPOSITORY / "plugin_factory" / "reference" / "inert-fixture-inspector"
GOLDEN = REPOSITORY / "plugin_factory" / "generated" / "inert-fixture-inspector"
BASH_VERIFIER = REPOSITORY / "plugin_factory" / "verifiers" / "verify-plugin.sh"
POWERSHELL_VERIFIER = REPOSITORY / "plugin_factory" / "verifiers" / "Verify-Plugin.ps1"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class PluginFactoryTests(unittest.TestCase):
    def test_reference_plugin_is_inert_and_conformant_to_narrow_profile(self) -> None:
        report = validate_plugin(REFERENCE)

        self.assertEqual(report.name, "inert-fixture-inspector")
        self.assertEqual(report.version, "1.0.0")
        self.assertEqual(report.skills, ("inspect-synthetic-fixture",))
        self.assertTrue(report.mcp_valid)
        self.assertEqual(report.diagnostics, ())
        self.assertRegex(report.tree_digest, r"^sha256:[0-9a-f]{64}$")

    def test_build_is_repeatable_and_matches_committed_golden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            first_digest = build_release(REFERENCE, first)
            second_digest = build_release(REFERENCE, second)

            self.assertEqual(first_digest, second_digest)
            self.assertEqual(_files(first), _files(second))
            self.assertEqual(_files(first), _files(GOLDEN))
            receipt = verify_release(first, first_digest)
            self.assertEqual(receipt.status, "verified_inert")
            self.assertEqual(receipt.activation, "disabled")

    def test_evidence_binds_inventory_sbom_and_provenance(self) -> None:
        bundle = json.loads((GOLDEN / "bundle.json").read_text(encoding="utf-8"))
        sbom = json.loads(
            (GOLDEN / "evidence" / "sbom.cdx.json").read_text(encoding="utf-8")
        )
        provenance = json.loads(
            (GOLDEN / "evidence" / "provenance.intoto.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(bundle["profile"], "inert-skills-only")
        self.assertEqual(bundle["activation"], "disabled")
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["specVersion"], "1.7")
        self.assertEqual(provenance["_type"], "https://in-toto.io/Statement/v1")
        self.assertEqual(
            provenance["predicateType"], "https://slsa.dev/provenance/v1"
        )
        self.assertEqual(
            provenance["subject"][0]["digest"]["sha256"],
            bundle["pluginTreeDigest"][7:],
        )

    def test_tamper_extra_file_and_wrong_expected_digest_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "release"
            digest = build_release(REFERENCE, release)
            skill = release / "plugin" / "skills" / "inspect-synthetic-fixture" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
            with self.assertRaisesRegex(FactoryError, "checksums_mismatch"):
                verify_release(release, digest)

            shutil.rmtree(release)
            digest = build_release(REFERENCE, release)
            (release / "unexpected.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(FactoryError, "checksums_mismatch"):
                verify_release(release, digest)

            shutil.rmtree(release)
            build_release(REFERENCE, release)
            with self.assertRaisesRegex(FactoryError, "release_digest_mismatch"):
                verify_release(release, "sha256:" + ("0" * 64))

    def test_unknown_manifest_field_is_reported_but_escape_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            shutil.copytree(REFERENCE, root)
            manifest_path = root / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unknownPortableClaim"] = "ignored"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = validate_plugin(root)
            self.assertEqual(
                report.diagnostics,
                ("manifest_unknown_field:unknownPortableClaim",),
            )

            outside = Path(temporary) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "escape")
            with self.assertRaisesRegex(FactoryError, "package_path_kind"):
                validate_plugin(root)

    def test_bash_verifier_accepts_golden_and_rejects_tamper(self) -> None:
        release_digest = "sha256:" + hashlib.sha256(
            (GOLDEN / "SHA256SUMS").read_bytes()
        ).hexdigest()
        valid = subprocess.run(
            ["sh", str(BASH_VERIFIER), str(GOLDEN), release_digest],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(valid.stdout.strip(), "verified_inert")

        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary) / "release"
            shutil.copytree(GOLDEN, altered)
            (altered / "bundle.json").write_text("{}", encoding="utf-8")
            invalid = subprocess.run(
                ["sh", str(BASH_VERIFIER), str(altered), release_digest],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid.returncode, 0)

    def test_verifier_scripts_do_not_contain_execution_primitives(self) -> None:
        bash = BASH_VERIFIER.read_text(encoding="utf-8")
        powershell = POWERSHELL_VERIFIER.read_text(encoding="utf-8")
        for forbidden in ("eval ", "source ", "unzip ", "tar ", "curl ", "wget "):
            self.assertNotIn(forbidden, bash)
        for forbidden in (
            "Invoke-Expression",
            "Start-Process",
            "Invoke-WebRequest",
            "Expand-Archive",
        ):
            self.assertNotIn(forbidden, powershell)

        executable = shutil.which("pwsh")
        if executable:
            release_digest = "sha256:" + hashlib.sha256(
                (GOLDEN / "SHA256SUMS").read_bytes()
            ).hexdigest()
            completed = subprocess.run(
                [
                    executable,
                    "-NoProfile",
                    "-File",
                    str(POWERSHELL_VERIFIER),
                    str(GOLDEN),
                    release_digest,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "verified_inert")


if __name__ == "__main__":
    unittest.main()
