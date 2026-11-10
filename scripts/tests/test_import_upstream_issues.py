"""Offline regression tests for the importer; every gh process is mocked."""

import copy
import importlib.util
import io
import json
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "import-upstream-issues.py"
SPEC = importlib.util.spec_from_file_location("coolify_issue_import", SCRIPT)
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer
SPEC.loader.exec_module(importer)


def issue(number=42, identity=420, label="🐛 Possible Bug", body="Reproduce the reported problem."):
    return {
        "id": identity, "number": number, "title": "Deployment failure",
        "html_url": f"https://github.com/coollabsio/coolify/issues/{number}",
        "body": body, "state": "open", "comments": 0,
        "user": {"login": "original-author", "id": 9},
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-02-01T00:00:00Z",
        "labels": [{"name": label, "color": "abcdef", "description": "Original label"}],
        "assignees": [{"login": "upstream-maintainer"}], "milestone": {"number": 7, "title": "Upstream"},
    }


def entry(body="Reproduce the reported problem."):
    return {"issue": issue(body=body), "comments": [], "analysis_markdown": "Check the actual deployment path."}


def snapshot(entries=None):
    return {"schema_version": 1, "source_repository": "coollabsio/coolify",
            "target_repository": "mleem97/coolify", "captured_at": "2026-11-10T12:00:00Z",
            "issues": entries if entries is not None else [entry()]}


def repo(enabled=True, push=True, admin=True):
    return {"full_name": "mleem97/coolify", "has_issues": enabled, "archived": False,
            "permissions": {"push": push, "admin": admin}}


class FakeClock:
    def __init__(self):
        self.current = 1000.0
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += seconds


class FakeGh:
    """Reject every unexpected process call, including unexpected writes."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, args, **kwargs):
        assert args[:2] == ["gh", "api"]
        assert args[args.index("--hostname") + 1] == "github.com"
        assert "shell" not in kwargs
        assert kwargs["timeout"] == 120
        method = args[args.index("--method") + 1]
        endpoint = next(value for value in args if value == "user" or value.startswith("repos/"))
        payload = json.loads(kwargs["input"]) if kwargs["input"] is not None else None
        self.calls.append((method, endpoint, payload))
        assert self.responses, f"Unexpected request: {method} {endpoint}"
        expected_method, expected_endpoint, data, *options = self.responses.pop(0)
        assert (method, endpoint) == (expected_method, expected_endpoint)
        if isinstance(data, Exception):
            raise data
        status, headers = options if options else (200, {})
        if callable(data):
            data = data(payload)
        stdout = f"HTTP/2.0 {status}\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items())
        stdout += "\r\n" + json.dumps(data, ensure_ascii=False)
        return SimpleNamespace(returncode=0 if status < 400 else 1, stdout=stdout, stderr="")


TARGET_ISSUES = "repos/mleem97/coolify/issues?state=all&per_page=100&sort=created&direction=asc"
TARGET_LABELS = "repos/mleem97/coolify/labels?per_page=100"


def client(responses, apply=False, enabled=True, enable_issues=False):
    fake = FakeGh([("GET", "user", {"login": "mleem97"}),
                   ("GET", "repos/mleem97/coolify", repo(enabled)), *responses])
    clock = FakeClock()
    api = importer.GitHub(apply=apply, enable_issues=enable_issues,
                          run=fake, now=clock.now, sleep=clock.sleep)
    api.verify()
    return api, fake, clock


class ImportSafetyTests(unittest.TestCase):
    def test_reads_every_page_and_rejects_cross_host_pagination(self):
        first = "repos/coollabsio/coolify/issues?state=open&per_page=100"
        second = "repos/coollabsio/coolify/issues?state=open&per_page=100&page=2"
        fake = FakeGh([
            ("GET", first, [{"number": 1}], 200,
             {"Link": f'<https://api.github.com/{second}>; rel="next"'}),
            ("GET", second, [{"number": 2}]),
        ])
        api = importer.GitHub(run=fake)

        self.assertEqual(api.all_pages(first), [{"number": 1}, {"number": 2}])
        self.assertFalse(fake.responses)
        unsafe = FakeGh([("GET", first, [], 200, {"Link": '<https://evil.example/steal>; rel="next"'})])
        with self.assertRaisesRegex(importer.ImportFailure, "Unsichere Pagination"):
            importer.GitHub(run=unsafe).all_pages(first)
        self.assertEqual(len(unsafe.calls), 1)

    def test_or_filter_selects_each_label_once_and_excludes_prs_and_closed_issues(self):
        records = [issue(number=index, identity=index, label=label) for index, label in enumerate(importer.LABELS, 1)]
        two_labels = issue(number=8, identity=8)
        two_labels["labels"].append({"name": "🔍 Triage"})
        records.append(two_labels)
        records.extend([issue(number=9, label="unrelated"), {**issue(number=10), "state": "closed"},
                        {**issue(number=11), "pull_request": {"url": "example"}}])

        selected = [record["number"] for record in records if importer.selected(record)]

        self.assertEqual(selected, [1, 2, 3, 4, 5, 8])

    def test_wrong_authenticated_account_cannot_write_or_even_query_target(self):
        fake = FakeGh([("GET", "user", {"login": "another-account"})])
        api = importer.GitHub(apply=True, run=fake)

        with self.assertRaisesRegex(importer.ImportFailure, "nicht als mleem97"):
            api.verify()
        with self.assertRaises(importer.ImportFailure):
            api.request("POST", "repos/mleem97/coolify/issues", {"title": "x", "body": "y", "labels": []})
        self.assertEqual(fake.calls, [("GET", "user", None)])

    def test_missing_target_permissions_blocks_mutation(self):
        fake = FakeGh([("GET", "user", {"login": "mleem97"}),
                       ("GET", "repos/mleem97/coolify", repo(push=False, admin=False))])
        api = importer.GitHub(apply=True, run=fake)

        with self.assertRaisesRegex(importer.ImportFailure, "Schreibrechte"):
            api.verify()
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_refuses_source_writes_overwrites_and_unexpected_payload_keys(self):
        api, fake, _ = client([], apply=True)
        attempts = [
            ("POST", "repos/coollabsio/coolify/issues", {"title": "x", "body": "y", "labels": []}),
            ("PATCH", "repos/mleem97/coolify/issues/9", {"body": "overwrite"}),
            ("POST", "repos/mleem97/coolify/issues", {"title": "x", "body": "y", "labels": [], "assignees": ["someone"]}),
            ("POST", "repos/mleem97/coolify/issues", {"title": "x", "body": "y", "labels": [], "milestone": 2}),
            ("DELETE", "repos/mleem97/coolify/issues/9", {}),
            ("POST", "repos/mleem97/coolify/../coolify/issues", {}),
        ]
        for method, endpoint, payload in attempts:
            with self.subTest(endpoint=endpoint, payload=payload):
                with self.assertRaises(importer.ImportFailure):
                    api.request(method, endpoint, payload)
        self.assertEqual(len(fake.calls), 2)

    def test_dry_run_with_disabled_issues_reports_plan_without_writing(self):
        api, fake, _ = client([( "GET", TARGET_ISSUES, {"message": "Issues disabled"}, 410, {})], enabled=False)
        rendered = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        messages = []

        stats = importer.import_issues(api, [rendered], messages.append)

        self.assertEqual(stats["new_issues"], 1)
        self.assertTrue(any("--apply --enable-issues" in message for message in messages))
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_enables_only_with_explicit_apply_and_enable_flag(self):
        api, fake, _ = client([], apply=True, enabled=False)
        with self.assertRaisesRegex(importer.ImportFailure, "--apply --enable-issues"):
            importer.import_issues(api, [], lambda _: None)
        self.assertEqual(len(fake.calls), 2)
        api, fake, _ = client([
            ("PATCH", "repos/mleem97/coolify", repo()),
            ("GET", TARGET_ISSUES, []), ("GET", TARGET_LABELS, []),
        ], apply=True, enabled=False, enable_issues=True)

        importer.import_issues(api, [], lambda _: None)

        self.assertEqual([call for call in fake.calls if call[0] != "GET"],
                         [("PATCH", "repos/mleem97/coolify", {"has_issues": True})])

    def test_preserves_existing_label_colors_and_never_assigns_original_people(self):
        rendered = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        api, fake, _ = client([
            ("GET", TARGET_ISSUES, []),
            ("GET", TARGET_LABELS, [{"name": "🐛 Possible Bug", "color": "000000"}]),
            ("POST", "repos/mleem97/coolify/issues", lambda payload: {"number": 1, "body": payload["body"]}, 201, {}),
        ], apply=True)

        importer.import_issues(api, [rendered], lambda _: None)

        writes = [call for call in fake.calls if call[0] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(set(writes[0][2]), {"title", "body", "labels"})
        self.assertIn("upstream-maintainer", writes[0][2]["body"])

    def test_second_run_finds_closed_issue_and_creates_no_duplicate(self):
        rendered = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        existing = {"number": 7, "body": rendered.bodies[0] + "\nOwner's own note.", "state": "closed"}
        api, fake, _ = client([( "GET", TARGET_ISSUES, [existing]), ("GET", TARGET_LABELS, [])], apply=True)

        stats = importer.import_issues(api, [rendered], lambda _: None)

        self.assertEqual(stats["new_issues"], 0)
        self.assertEqual(stats["existing_issues"], 1)
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))
        self.assertTrue(existing["body"].endswith("Owner's own note."))

    def test_resume_adds_only_missing_parts(self):
        rendered = importer.render_issue(entry(body="🌍" * 35_000), "2026-11-10T12:00:00Z")
        self.assertGreaterEqual(len(rendered.bodies), 3)
        existing = {"number": 7, "body": rendered.bodies[0]}
        responses = [("GET", TARGET_ISSUES, [existing]),
                     ("GET", "repos/mleem97/coolify/issues/7/comments?per_page=100", [{"body": rendered.bodies[1]}]),
                     ("GET", TARGET_LABELS, [])]
        for _ in rendered.bodies[2:]:
            responses.append(("POST", "repos/mleem97/coolify/issues/7/comments", lambda payload: {"body": payload["body"]}, 201, {}))
        api, fake, clock = client(responses, apply=True)

        stats = importer.import_issues(api, [rendered], lambda _: None)

        self.assertEqual(stats["new_comments"], len(rendered.bodies) - 2)
        self.assertEqual([call[2]["body"] for call in fake.calls if call[0] == "POST"], rendered.bodies[2:])
        self.assertTrue(all(delay >= 8 for delay in clock.sleeps))

    def test_quoted_markers_are_not_treated_as_existing_imports(self):
        rendered = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        quoted = {"number": 10, "body": "Example:\n```markdown\n" + rendered.bodies[0] + "\n```"}

        self.assertEqual(importer.existing_imports([quoted]), {})
        mismatched = {"number": 10, "body": rendered.bodies[0].replace("number=42 ", "number=43 ", 1)}
        api, fake, _ = client([( "GET", TARGET_ISSUES, [mismatched])])
        with self.assertRaisesRegex(importer.ImportFailure, "Quell-ID und Quellnummer"):
            importer.import_issues(api, [rendered], lambda _: None)

    def test_changed_snapshot_preserves_issue_and_does_not_append_duplicate_copy(self):
        old = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        changed = entry(body="A changed upstream report.")
        new = importer.render_issue(changed, "2026-11-10T13:00:00Z")
        api, fake, _ = client([( "GET", TARGET_ISSUES, [{"number": 1, "body": old.bodies[0]}]),
                              ("GET", TARGET_LABELS, [])], apply=True)

        stats = importer.import_issues(api, [new], lambda _: None)

        self.assertEqual(stats["changed_snapshots"], 1)
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_same_live_content_has_stable_digest_across_capture_times(self):
        first = importer.render_issue(entry(), "2026-11-10T12:00:00Z")
        later = importer.render_issue(entry(), "2026-11-10T13:00:00Z")

        self.assertEqual(first.digest, later.digest)

    def test_ambiguous_post_timeout_is_never_retried(self):
        api, fake, _ = client([("POST", "repos/mleem97/coolify/issues",
                                subprocess.TimeoutExpired(["gh"], 120))], apply=True)

        with self.assertRaises(importer.AmbiguousWrite):
            api.request("POST", "repos/mleem97/coolify/issues", {"title": "Example", "body": "Body", "labels": []})
        self.assertEqual(len([call for call in fake.calls if call[0] == "POST"]), 1)

    def test_rate_limit_sets_cooldown_and_blocks_immediate_retry(self):
        api, fake, clock = client([("POST", "repos/mleem97/coolify/issues",
                                   {"message": "secondary rate limit"}, 429, {"Retry-After": "37"})], apply=True)

        with self.assertRaisesRegex(importer.ApiFailure, "37 Sekunden"):
            api.request("POST", "repos/mleem97/coolify/issues", {"title": "Example", "body": "Body", "labels": []})
        with self.assertRaisesRegex(importer.ImportFailure, "Wartezeit"):
            api.get("user")
        self.assertEqual(api.state["blocked_until"], 1037)
        self.assertEqual(len(fake.calls), 3)

    def test_write_pacing_spaces_distinct_mutations_by_at_least_eight_seconds(self):
        api, fake, clock = client([
            ("POST", "repos/mleem97/coolify/labels", {}, 201, {}),
            ("POST", "repos/mleem97/coolify/labels", {}, 201, {}),
        ], apply=True)

        api.request("POST", "repos/mleem97/coolify/labels", {"name": "one", "color": "ffffff", "description": ""})
        api.request("POST", "repos/mleem97/coolify/labels", {"name": "two", "color": "ffffff", "description": ""})

        self.assertEqual(clock.sleeps, [8.0])

    def test_unicode_payloads_are_bounded_without_losing_original_characters(self):
        original = "😀Ä\n" * 20_000
        rendered = importer.render_issue(entry(body=original), "2026-11-10T12:00:00Z")

        self.assertTrue(all(len(body.encode("utf-8")) <= 55_000 for body in rendered.bodies))
        reconstructed = "".join(re.findall(r"```markdown\n(.*?)\n```", "\n".join(rendered.bodies), re.S))
        self.assertEqual(reconstructed, original)
        self.assertEqual("".join(importer.utf8_chunks(original, 101)), original)

    def test_neutralizes_prose_mentions_and_keeps_executable_code_unchanged(self):
        prose = "Ask @alice and [@team](https://github.com/team); inspect #123.\n```sh\nprintf '@bob #456'\n```\n"

        result = importer.rewrite_prose(prose)

        self.assertIn("@\u200balice", result)
        self.assertIn("[@\u200bteam]", result)
        self.assertIn("[#123](https://github.com/coollabsio/coolify/issues/123)", result)
        self.assertIn("printf '@bob #456'", result)
        literal = importer.literal_blocks("Original", "@alice\n```\n#123\n~~~\n")[0]
        self.assertIn("````markdown", literal)
        self.assertIn("@alice\n```\n#123\n~~~\n", literal)

    def test_redacts_complete_and_partial_keys_tokens_and_aws_credentials(self):
        pem = "-----BEGIN PRIVATE KEY-----\n" + "MII" + "A" * 140 + "\n-----END PRIVATE KEY-----"
        partial = "```env\nKEY=-----BEGIN RSA PRIVATE KEY-----\\n" + "B" * 120 + "\n```\nFragment " + "C" * 100
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.a_signature_long_enough"
        github = "ghp_" + "d" * 36
        aws_id = "AKIA" + "E" * 16
        aws_secret = "AWS_SECRET_ACCESS_KEY=" + "f" * 40

        cleaned, counts = importer.redact_secrets("\n".join((pem, partial, jwt, github, aws_id, aws_secret)))

        for secret in ("MII" + "A" * 140, "B" * 120, "C" * 100, jwt, github, aws_id, "f" * 40):
            self.assertNotIn(secret, cleaned)
        self.assertIn("PEM", counts)
        self.assertIn("unvollständiger privater Schlüssel", counts)
        self.assertIn("JWT", counts)
        self.assertIn("AWS-Secret", counts)

    def test_preserves_public_certificate_alongside_a_private_key(self):
        certificate = "-----BEGIN CERTIFICATE-----\n" + "MII" + "A" * 140 + "\n-----END CERTIFICATE-----"
        private_key = "-----BEGIN PRIVATE KEY-----\n" + "MII" + "B" * 140 + "\n-----END PRIVATE KEY-----"

        redacted, counts = importer.redact_secrets(certificate + "\n" + private_key)

        self.assertIn(certificate, redacted)
        self.assertNotIn("MII" + "B" * 140, redacted)
        self.assertEqual(counts, {"PEM": 1})

    def test_redacts_notification_capabilities_and_retains_normal_source_urls(self):
        unsubscribe = "https://github.com/notifications/unsubscribe-auth/SECRET_CAPABILITY?x=1"
        reply = "reply+SECRET_EMAIL_TOKEN@reply.github.com"
        normal = "https://github.com/coollabsio/coolify/issues/8684#issuecomment-4241585495"

        redacted, counts = importer.redact_secrets(f"[unsubscribe]({unsubscribe})\n<{reply}>\n{normal}")

        self.assertNotIn("SECRET_CAPABILITY", redacted)
        self.assertNotIn("SECRET_EMAIL_TOKEN", redacted)
        self.assertIn(normal, redacted)
        self.assertEqual(counts, {"GitHub-Abmeldelink": 1, "GitHub-Antwortadresse": 1})

    def test_live_resume_snapshot_is_redacted_private_and_renderable(self):
        token = "ghp_" + "z" * 36
        data = snapshot([entry(body="A log accidentally contains " + token)])
        with tempfile.TemporaryDirectory() as directory:
            path, cleaned = importer.freeze_live_snapshot(data, Path(directory))

            self.assertNotIn(token, path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            loaded, entries = importer.load_snapshot(path, importer.DEFAULT_TARGET)
            rendered = importer.render_issue(entries[0], loaded["captured_at"])
            self.assertIn("Live-Snapshot", rendered.bodies[0])
            self.assertNotIn(token, rendered.bodies[0])
            self.assertIn(token, data["issues"][0]["issue"]["body"])

    def test_counter_discrepancy_requires_an_explicit_collection_note(self):
        data = snapshot()
        data["issues"][0]["issue"]["comments"] = 2

        with self.assertRaisesRegex(importer.ImportFailure, "collection_notes"):
            importer.validate_snapshot(data, importer.DEFAULT_TARGET)
        data["issues"][0]["collection_notes"] = ["All API pages returned zero objects despite the counter of two; cause unknown."]
        self.assertEqual(len(importer.validate_snapshot(data, importer.DEFAULT_TARGET)), 1)

    def test_snapshot_rejects_mismatched_source_url_and_duplicate_identity(self):
        data = snapshot()
        data["issues"][0]["issue"]["html_url"] = "https://github.com/another/repo/issues/42"
        with self.assertRaisesRegex(importer.ImportFailure, "Quell-URL"):
            importer.validate_snapshot(data, importer.DEFAULT_TARGET)
        data = snapshot()
        data["issues"].append(copy.deepcopy(data["issues"][0]))
        with self.assertRaisesRegex(importer.ImportFailure, "Doppeltes Quell-Issue"):
            importer.validate_snapshot(data, importer.DEFAULT_TARGET)

    def test_local_validation_never_invokes_gh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(snapshot()), encoding="utf-8")
            output = io.StringIO()
            with patch.object(importer.subprocess, "run", side_effect=AssertionError("No gh allowed")), redirect_stdout(output):
                result = importer.main(["--validate-snapshot", "--snapshot", str(path)])

        self.assertEqual(result, 0)
        self.assertIn("1 Issues", output.getvalue())
        self.assertEqual(importer.DEFAULT_SNAPSHOT, SCRIPT.parents[1] / "docs/upstream-issues/snapshot.json")

    def test_local_lock_excludes_second_process_and_persists_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with importer.LocalLock(importer.DEFAULT_TARGET, root) as first:
                with self.assertRaisesRegex(importer.ImportFailure, "bereits ein Import"):
                    with importer.LocalLock(importer.DEFAULT_TARGET, root):
                        self.fail("Second lock acquired")
                first.state["blocked_until"] = 1234
                first.save()
            with importer.LocalLock(importer.DEFAULT_TARGET, root) as resumed:
                self.assertEqual(resumed.state["blocked_until"], 1234)


if __name__ == "__main__":
    unittest.main()
