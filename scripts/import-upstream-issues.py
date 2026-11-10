#!/usr/bin/env python3
"""Copy selected upstream issues into Marvin's fork using Python 3.10+ and gh.

No remote writes occur without --apply. Run --validate-snapshot for an entirely
local check. Existing issue bodies, labels, assignees and milestones are never
updated. Re-run the SAME snapshot to resume an interrupted import.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit


SOURCE = "coollabsio/coolify"
DEFAULT_TARGET = "mleem97/coolify"
EXPECTED_LOGIN = "mleem97"
LABELS = frozenset((
    "🔍 Triage", "🖌️ UI/UX", "🐛 Possible Bug",
    "🔴 High Priority", "🟠 Medium Priority",
))
MAX_BODY_BYTES = 55_000
WRITE_INTERVAL = 8.0
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "docs/upstream-issues/snapshot.json"
ISSUE_MARKER = re.compile(
    r"<!-- coolify-upstream:v1 source=coollabsio/coolify id=(\d+) number=(\d+) "
    r"digest=([0-9a-f]{64}) parts=(\d+) -->"
)
PART_MARKER = re.compile(
    r"<!-- coolify-upstream-part:v1 id=(\d+) digest=([0-9a-f]{64}) part=(\d+) -->"
)


class ImportFailure(Exception):
    """An actionable failure; the caller must not continue writing."""


class ApiFailure(ImportFailure):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


class AmbiguousWrite(ImportFailure):
    """The server might have committed a request whose result was not received."""


def positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ImportFailure(f"Ungültige positive Ganzzahl: {name}.")
    return value


def clean_terminal(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))


def validate_target(target: str) -> str:
    if not re.fullmatch(r"mleem97/[A-Za-z0-9_.-]+", target) or target.endswith(("/.", "/..")):
        raise ImportFailure("Das Ziel muss ein Repository von mleem97 sein.")
    return target


class LocalLock:
    """A per-user, per-target POSIX lock, retained to avoid an unlink race."""

    def __init__(self, target: str, directory: Path | None = None):
        cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        self.directory = directory or cache / "coolify-issue-import"
        self.path = self.directory / (target.replace("/", "--") + ".lock")
        self.file = None
        self.state: dict = {}

    def __enter__(self):
        try:
            import fcntl
        except ImportError as exc:
            raise ImportFailure("Für die Importsperre Linux, macOS oder WSL verwenden.") from exc
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ImportFailure("Die lokale Importsperre ist keine reguläre Datei.")
        self.file = os.fdopen(descriptor, "r+", encoding="utf-8")
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.file.close()
            raise ImportFailure("Für dieses Ziel läuft bereits ein Import.") from exc
        raw = self.file.read()
        if raw:
            try:
                self.state = json.loads(raw)
                if not isinstance(self.state, dict):
                    raise ValueError()
                for key in ("last_write_at", "blocked_until"):
                    value = self.state.get(key, 0)
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError()
            except (ValueError, TypeError) as exc:
                self.file.close()
                raise ImportFailure(f"Ungültiger Sperrstatus: {self.path}") from exc
        return self

    def save(self) -> None:
        self.file.seek(0)
        json.dump(self.state, self.file)
        self.file.truncate()
        self.file.flush()
        os.fsync(self.file.fileno())

    def __exit__(self, *_):
        if self.file:
            self.file.close()


class GitHub:
    def __init__(self, target=DEFAULT_TARGET, apply=False, enable_issues=False,
                 run=None, now=None, sleep=None, lock=None):
        self.target = validate_target(target)
        self.apply = apply
        self.enable_requested = enable_issues
        self.run = run or subprocess.run
        self.now = now or time.time
        self.sleep = sleep or time.sleep
        self.lock = lock
        self.state = lock.state if lock else {}
        self.verified = False
        self.repository: dict = {}

    def _save_state(self):
        if self.lock:
            self.lock.save()

    def _guard(self, method: str, endpoint: str, payload: dict | None):
        parsed = urlsplit(endpoint)
        if parsed.scheme or parsed.netloc or parsed.fragment or endpoint.startswith("/"):
            raise ImportFailure("Nur relative, fest begrenzte GitHub-API-Pfade sind erlaubt.")
        path = parsed.path
        readable = path == "user" or any(
            path == f"repos/{repo}" or path.startswith(f"repos/{repo}/")
            for repo in (SOURCE, self.target)
        )
        if not readable or ".." in path.split("/") or "%" in path or "\\" in path:
            raise ImportFailure("API-Pfad außerhalb der erlaubten Repositories.")
        if method == "GET":
            if payload is not None:
                raise ImportFailure("GET-Anfragen dürfen keinen Schreib-Payload enthalten.")
            return
        if not self.apply or not self.verified:
            raise ImportFailure("Schreibzugriff ohne --apply und Identitäts-/Repository-Prüfung verweigert.")
        if parsed.query or not isinstance(payload, dict):
            raise ImportFailure("Ungültiger Schreibaufruf.")
        base = f"repos/{self.target}"
        permitted = False
        if method == "PATCH" and path == base:
            permitted = (self.enable_requested and payload == {"has_issues": True}
                         and self.repository.get("permissions", {}).get("admin") is True)
        elif method == "POST" and self.repository.get("has_issues") is True:
            if path == base + "/labels":
                permitted = set(payload) == {"name", "color", "description"}
            elif path == base + "/issues":
                permitted = set(payload) == {"title", "body", "labels"}
            elif re.fullmatch(re.escape(base) + r"/issues/[1-9]\d*/comments", path):
                permitted = set(payload) == {"body"}
        if not permitted:
            raise ImportFailure("Diese Mutation ist nicht freigegeben; die Quelle bleibt ausschließlich lesbar.")
        if "body" in payload:
            if not isinstance(payload["body"], str) or len(payload["body"].encode("utf-8")) > MAX_BODY_BYTES:
                raise ImportFailure("Issue-/Kommentar-Payload überschreitet die sichere Byte-Grenze oder ist kein Text.")

    @staticmethod
    def _decode(stdout: str) -> tuple[int, dict[str, str], object]:
        remaining = stdout.replace("\r\n", "\n")
        status = None
        headers: dict[str, str] = {}
        while remaining.startswith("HTTP/"):
            header, separator, remaining = remaining.partition("\n\n")
            match = re.match(r"HTTP/\S+\s+(\d{3})", header)
            if not separator or not match:
                raise ValueError("Ungültige HTTP-Antwort")
            status = int(match.group(1))
            headers = {}
            for line in header.splitlines()[1:]:
                key, colon, value = line.partition(":")
                if colon:
                    headers[key.lower().strip()] = value.strip()
        if status is None:
            raise ValueError("HTTP-Status fehlt")
        return status, headers, json.loads(remaining) if remaining.strip() else None

    def request(self, method: str, endpoint: str, payload=None):
        self._guard(method, endpoint, payload)
        cooldown = self.state.get("blocked_until", 0) - self.now()
        if cooldown > 0:
            raise ImportFailure(f"GitHub-Wartezeit aktiv: frühestens in {math.ceil(cooldown)} Sekunden erneut starten.")
        if method != "GET":
            remaining = WRITE_INTERVAL - (self.now() - self.state.get("last_write_at", -math.inf))
            if remaining > 0:
                self.sleep(remaining)
            self.state["last_write_at"] = self.now()
            self._save_state()
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                "--include", "--header", "Accept: application/vnd.github+json",
                "--header", "X-GitHub-Api-Version: 2022-11-28", endpoint]
        if payload is not None:
            args.extend(["--input", "-"])
        try:
            result = self.run(
                args, input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                capture_output=True, text=True, encoding="utf-8", timeout=120,
                env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_PAGER": "cat"},
            )
        except FileNotFoundError as exc:
            raise ImportFailure("GitHub CLI fehlt. Bitte gh installieren und als mleem97 anmelden.") from exc
        except (subprocess.TimeoutExpired, OSError, UnicodeError) as exc:
            if method != "GET":
                raise AmbiguousWrite(
                    "Schreibantwort nicht sicher empfangen. Nicht automatisch wiederholt. "
                    "Ziel prüfen und denselben Snapshot erneut ausführen; vorhandene Marker werden abgeglichen."
                ) from exc
            raise ApiFailure(None, "GitHub-Abfrage fehlgeschlagen; Verbindung und gh-Anmeldung prüfen.") from exc
        try:
            status, headers, data = self._decode(result.stdout)
        except (ValueError, TypeError) as exc:
            if method != "GET":
                raise AmbiguousWrite("Unklare Schreibantwort. Abbruch ohne Wiederholung; Ziel prüfen und denselben Snapshot erneut starten.") from exc
            raise ApiFailure(None, "GitHub-Antwort nicht lesbar; gh auth status und Verbindung prüfen.") from exc
        if 200 <= status < 300 and result.returncode == 0:
            return data, headers
        message = str(data.get("message", "")) if isinstance(data, dict) else ""
        limited = status == 429 or (status == 403 and (
            "retry-after" in headers or headers.get("x-ratelimit-remaining") == "0"
            or re.search(r"rate.limit|abuse", message, re.I)
        ))
        if limited:
            delay = 60.0
            if "retry-after" in headers:
                try:
                    delay = max(1, float(headers["retry-after"]))
                except ValueError:
                    try:
                        delay = max(1, parsedate_to_datetime(headers["retry-after"]).timestamp() - self.now())
                    except (TypeError, ValueError, OverflowError):
                        pass
            elif headers.get("x-ratelimit-remaining") == "0":
                try:
                    delay = max(1, float(headers["x-ratelimit-reset"]) - self.now() + 1)
                except (KeyError, ValueError):
                    pass
            if not math.isfinite(delay):
                delay = 60.0
            self.state["blocked_until"] = self.now() + delay
            self._save_state()
            raise ApiFailure(status, f"GitHub-Rate-Limit. Frühestens in {math.ceil(delay)} Sekunden denselben Befehl erneut ausführen.")
        if method != "GET" and (status == 408 or status >= 500 or 200 <= status < 400):
            raise AmbiguousWrite(f"Unklarer Schreibausgang (HTTP {status}). Keine automatische Wiederholung; Ziel prüfen und denselben Snapshot erneut starten.")
        raise ApiFailure(status, f"GitHub lehnt {method} {urlsplit(endpoint).path} ab (HTTP {status}). Berechtigungen und gh-Anmeldung prüfen.")

    def get(self, endpoint: str):
        return self.request("GET", endpoint)[0]

    def all_pages(self, endpoint: str) -> list[dict]:
        initial_path = urlsplit(endpoint).path
        seen = set()
        values: list[dict] = []
        while endpoint:
            if endpoint in seen:
                raise ImportFailure("Wiederholte Pagination-URL; Abbruch statt unvollständigem Import.")
            seen.add(endpoint)
            page, headers = self.request("GET", endpoint)
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ImportFailure("Unerwartetes Format einer GitHub-Collection.")
            values.extend(page)
            next_links = [url for url, relation in re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', headers.get("link", "")) if relation == "next"]
            endpoint = ""
            if next_links:
                if len(next_links) != 1:
                    raise ImportFailure("Mehrdeutige Pagination-Antwort.")
                link = urlsplit(next_links[0])
                if (link.scheme != "https" or link.netloc != "api.github.com"
                        or link.fragment or link.path.lstrip("/") != initial_path):
                    raise ImportFailure("Unsichere Pagination-URL verweigert.")
                endpoint = link.path.lstrip("/") + ("?" + link.query if link.query else "")
        return values

    def verify(self):
        user = self.get("user")
        if not isinstance(user, dict) or user.get("login") != EXPECTED_LOGIN:
            raise ImportFailure("GitHub CLI ist nicht als mleem97 angemeldet. gh auth status prüfen; GH_TOKEN/GITHUB_TOKEN können eine andere Anmeldung vorgeben.")
        repo = self.get(f"repos/{self.target}")
        if not isinstance(repo, dict) or repo.get("full_name", "").lower() != self.target.lower():
            raise ImportFailure("Das zurückgegebene Repository entspricht nicht dem Ziel.")
        if repo.get("archived") or repo.get("disabled"):
            raise ImportFailure("Das Zielrepository ist archiviert oder deaktiviert.")
        permissions = repo.get("permissions", {})
        if not any(permissions.get(key) is True for key in ("push", "maintain", "admin")):
            raise ImportFailure("Keine bestätigten Schreibrechte im Zielrepository.")
        if type(repo.get("has_issues")) is not bool:
            raise ImportFailure("Der Issue-Status des Ziels konnte nicht geprüft werden.")
        self.repository, self.verified = repo, True
        return repo

    def enable_issues(self):
        repo, _ = self.request("PATCH", f"repos/{self.target}", {"has_issues": True})
        if not isinstance(repo, dict) or repo.get("has_issues") is not True:
            raise AmbiguousWrite("Aktivierung der Issues nicht bestätigt; Ziel prüfen und erneut starten.")
        self.repository["has_issues"] = True


def selected(issue: dict) -> bool:
    return ("pull_request" not in issue and issue.get("state") == "open"
            and any(label.get("name") in LABELS for label in issue.get("labels", []) if isinstance(label, dict)))


def validate_snapshot(snapshot: object, target: str) -> list[dict]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ImportFailure("Snapshot-Schema muss schema_version=1 verwenden.")
    if snapshot.get("source_repository") != SOURCE or snapshot.get("target_repository", target) != target:
        raise ImportFailure("Quelle oder Ziel des Snapshots stimmt nicht überein.")
    if not isinstance(snapshot.get("captured_at"), str) or not snapshot["captured_at"]:
        raise ImportFailure("Dem Snapshot fehlt captured_at.")
    try:
        captured = dt.datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise ImportFailure("captured_at muss ein ISO-8601-Zeitstempel mit Zeitzone sein.") from exc
    entries = snapshot.get("issues")
    if not isinstance(entries, list):
        raise ImportFailure("Snapshot issues muss ein Array sein.")
    global_notes = snapshot.get("collection_notes", [])
    if not isinstance(global_notes, list) or any(not isinstance(note, str) for note in global_notes):
        raise ImportFailure("Ungültige globale Erfassungsvermerke.")
    seen_ids, seen_numbers = set(), set()
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("issue"), dict):
            raise ImportFailure("Ungültiger Issue-Eintrag im Snapshot.")
        issue = entry["issue"]
        if not isinstance(issue.get("labels"), list) or any(not isinstance(label, dict) for label in issue["labels"]):
            raise ImportFailure("Issue-Labels müssen ein Array von Labelobjekten sein.")
        if issue.get("state") not in ("open", "closed"):
            raise ImportFailure("Ungültiger Quell-Issue-Status.")
        if not selected(issue):
            continue
        number, identity = positive_int(issue.get("number"), "issue.number"), positive_int(issue.get("id"), "issue.id")
        if identity in seen_ids or number in seen_numbers:
            raise ImportFailure(f"Doppeltes Quell-Issue im Snapshot: {number}.")
        seen_ids.add(identity)
        seen_numbers.add(number)
        if issue.get("html_url") != f"https://github.com/{SOURCE}/issues/{number}":
            raise ImportFailure(f"Falsche Quell-URL bei Issue {number}.")
        if not isinstance(issue.get("title"), str) or not issue["title"].strip():
            raise ImportFailure(f"Fehlender Titel bei Issue {number}.")
        if issue.get("body") is not None and not isinstance(issue["body"], str):
            raise ImportFailure(f"Ungültiger Text bei Issue {number}.")
        if not isinstance(entry.get("analysis_markdown", ""), str):
            raise ImportFailure(f"Ungültige Analyse bei Issue {number}.")
        notes = entry.get("collection_notes", [])
        if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
            raise ImportFailure(f"Ungültige Erfassungsvermerke bei Issue {number}.")
        comments = entry.get("comments")
        if not isinstance(comments, list):
            raise ImportFailure(f"Kommentare fehlen bei Issue {number}.")
        count = entry.get("reported_comment_count", issue.get("comments"))
        if type(count) is not int or count < 0:
            raise ImportFailure(f"Ungültiger Kommentarzähler bei Issue {number}.")
        if count != len(comments) and not (notes or global_notes):
            raise ImportFailure(f"Issue {number}: {count} Kommentare gemeldet, {len(comments)} erfasst; collection_notes muss die Abweichung erklären.")
        seen_comments = set()
        for comment in comments:
            if not isinstance(comment, dict):
                raise ImportFailure(f"Ungültiger Kommentar bei Issue {number}.")
            comment_id = positive_int(comment.get("id"), "comment.id")
            if comment_id in seen_comments:
                raise ImportFailure(f"Doppelter Kommentar bei Issue {number}.")
            seen_comments.add(comment_id)
            if comment.get("body") is not None and not isinstance(comment["body"], str):
                raise ImportFailure(f"Ungültiger Kommentartext bei Issue {number}.")
            if comment.get("html_url") != f"https://github.com/{SOURCE}/issues/{number}#issuecomment-{comment_id}":
                raise ImportFailure(f"Falsche Kommentar-URL bei Issue {number}.")
        result.append({**entry, "collection_notes": global_notes + notes})
    return sorted(result, key=lambda entry: entry["issue"]["number"])


def load_snapshot(path: Path, target: str) -> tuple[dict, list[dict]]:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportFailure(f"Snapshot kann nicht gelesen werden: {path}") from exc
    return snapshot, validate_snapshot(snapshot, target)


def live_snapshot(api: GitHub) -> tuple[dict, list[dict]]:
    source = api.all_pages(f"repos/{SOURCE}/issues?state=open&per_page=100&sort=created&direction=asc")
    entries = []
    for issue in source:
        if not selected(issue):
            continue
        number = positive_int(issue.get("number"), "issue.number")
        comments = api.all_pages(f"repos/{SOURCE}/issues/{number}/comments?per_page=100")
        notes = []
        if issue.get("comments") != len(comments):
            notes.append(f"Die API meldet {issue.get('comments')} Kommentare; sämtliche abgerufenen Seiten enthalten {len(comments)} Kommentarobjekte. Ursache nicht festgestellt.")
        entries.append({"issue": issue, "comments": comments, "collection_notes": notes,
                        "reported_comment_count": issue.get("comments"), "analysis_markdown": ""})
    snapshot = {"schema_version": 1, "source_repository": SOURCE,
                "target_repository": api.target,
                "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "issues": entries}
    return snapshot, validate_snapshot(snapshot, api.target)


def redact_secrets(text: str) -> tuple[str, dict[str, int]]:
    # Public certificate/key examples are useful reproduction data, not secrets.
    public_pem = re.compile(r"-----BEGIN (CERTIFICATE|X509 CERTIFICATE|PUBLIC KEY|RSA PUBLIC KEY)-----[\s\S]*?-----END \1-----")
    public_blocks = list(public_pem.finditer(text))
    if public_blocks:
        parts, totals, offset = [], {}, 0
        for block in public_blocks:
            redacted, counts = redact_secrets(text[offset:block.start()])
            parts.extend((redacted, block[0]))
            for name, count in counts.items():
                totals[name] = totals.get(name, 0) + count
            offset = block.end()
        redacted, counts = redact_secrets(text[offset:])
        parts.append(redacted)
        for name, count in counts.items():
            totals[name] = totals.get(name, 0) + count
        return "".join(parts), totals
    counts: dict[str, int] = {}

    def replace(pattern, replacement, category, flags=0):
        nonlocal text
        text, count = re.subn(pattern, replacement, text, flags=flags)
        if count:
            counts[category] = counts.get(category, 0) + count

    had_private_key = bool(re.search(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", text))
    replace(r"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----[\s\S]*?-----END \1-----",
            "[REDACTED: private PEM key]", "PEM")
    replace(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?(?=\n\s*(?:`{3,}|~{3,}|#{1,6}\s)|\Z)",
            "[REDACTED: incomplete private-key snippet]", "unvollständiger privater Schlüssel")
    if had_private_key:
        replace(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/])",
                "[REDACTED: key-like Base64 fragment]", "Schlüsselfragment")
    replace(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
            "[REDACTED: JWT]", "JWT")
    replace(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
            "[REDACTED: GitHub token]", "GitHub-Token")
    replace(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED: AWS access key ID]", "AWS-Zugriffsschlüssel")
    replace(r"(?i)(\b(?:aws_secret_access_key|aws_session_token)\b[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9/+=]{20,})",
            r"\1[REDACTED: AWS secret]", "AWS-Secret")
    replace(r"https?://github\.com/notifications/unsubscribe-auth/[^\s<>()\"'\]]+",
            "[REDACTED: GitHub unsubscribe link]", "GitHub-Abmeldelink", re.I)
    replace(r"reply\+[^@\s<>()\"']+@reply\.github\.com\b",
            "[REDACTED: GitHub reply address]", "GitHub-Antwortadresse", re.I)
    return text, counts


def freeze_live_snapshot(snapshot: dict, directory: Path) -> tuple[Path, dict]:
    """Persist only redacted data so a live import has a reproducible resume file."""
    totals: dict[str, int] = {}

    def redact_value(value):
        if isinstance(value, str):
            cleaned, counts = redact_secrets(value)
            for name, count in counts.items():
                totals[name] = totals.get(name, 0) + count
            return cleaned
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: redact_value(item) for key, item in value.items()}
        return value

    cleaned = redact_value(snapshot)
    if totals:
        cleaned.setdefault("collection_notes", []).append(
            "Der Live-Snapshot wurde vor dem Speichern redigiert: "
            + ", ".join(f"{name}: {count}" for name, count in sorted(totals.items()))
            + ". Diese Heuristik garantiert nicht, sämtliche Geheimnisse zu erkennen."
        )
    validate_snapshot(cleaned, cleaned["target_repository"])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix="live-snapshot-", suffix=".json", dir=directory)
    path = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(cleaned, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, cleaned


def rewrite_prose(text: str) -> str:
    """Do not change code/URLs; neutralize mentions and expand bare issue refs."""
    protected = re.compile(r"(`+).*?\1|!?\[[^\]]*\]\([^)]*\)|<https?://[^>]*>|https?://\S+")

    def plain(value):
        value = re.sub(r"(?<![\w@])@(?=[A-Za-z0-9])", "@\u200b", value)
        return re.sub(r"(?<![\w/#&=?])#([1-9]\d*)\b",
                      lambda match: f"[#{match[1]}](https://github.com/{SOURCE}/issues/{match[1]})", value)

    result, fence = [], None
    for line in text.splitlines(keepends=True):
        delimiter = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if delimiter:
            token = delimiter[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append(line)
            continue
        if fence:
            result.append(line)
            continue
        offset = 0
        for match in protected.finditer(line):
            token = match[0]
            if token.startswith(("[", "![")):
                label, separator, destination = token.partition("](")
                label = re.sub(r"(?<![\w@])@(?=[A-Za-z0-9])", "@\u200b", label)
                token = label + separator + destination
            result.extend((plain(line[offset:match.start()]), token))
            offset = match.end()
        result.append(plain(line[offset:]))
    return "".join(result)


def utf8_chunks(text: str, maximum: int) -> list[str]:
    if maximum < 4:
        raise ValueError("UTF-8 chunks need room for a complete character")
    if not text:
        return [""]
    chunks, current, size = [], [], 0
    for character in text:
        width = len(character.encode("utf-8"))
        if size + width > maximum:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += width
    if current:
        chunks.append("".join(current))
    return chunks


def literal_blocks(title: str, text: str, language="markdown") -> list[str]:
    chunks = utf8_chunks(text, 20_000)
    blocks = []
    for index, chunk in enumerate(chunks, 1):
        longest = {symbol: max([len(value) for value in re.findall(re.escape(symbol) + "+", chunk)] or [0]) for symbol in ("`", "~")}
        symbol = min(longest, key=longest.get)
        fence = symbol * max(3, longest[symbol] + 1)
        suffix = f" — Abschnitt {index}/{len(chunks)}" if len(chunks) > 1 else ""
        blocks.append(f"<details>\n<summary>{title}{suffix}</summary>\n\n{fence}{language}\n{chunk}\n{fence}\n\n</details>")
    return blocks


def source_references(text: str) -> list[str]:
    numbers = sorted(set(re.findall(r"(?<![\w/#])#([1-9]\d*)\b", text)), key=int)
    links = [f"[#{number}](https://github.com/{SOURCE}/issues/{number})" for number in numbers]
    return ["Kurzreferenzen im Original (Upstream): " + ", ".join(links[start:start + 40]) for start in range(0, len(links), 40)]


@dataclass
class RenderedIssue:
    identity: int
    number: int
    title: str
    labels: list[dict]
    digest: str
    bodies: list[str]
    redactions: dict[str, int]


def render_issue(entry: dict, captured_at: str) -> RenderedIssue:
    issue = entry["issue"]
    identity, number = issue["id"], issue["number"]
    redactions: dict[str, int] = {}

    def redact(value: str) -> str:
        value, counts = redact_secrets(value)
        for name, count in counts.items():
            redactions[name] = redactions.get(name, 0) + count
        return value

    title = rewrite_prose(redact(issue["title"]))
    # Titles are plain text; do not introduce Markdown links into them.
    title = re.sub(r"\[#(\d+)\]\(https://github.com/coollabsio/coolify/issues/\d+\)", r"#\1", title)
    if len(title) > 256 or "\n" in title or "\r" in title:
        raise ImportFailure(f"Issue {number}: Titel passt nicht in GitHubs Titelfeld.")
    analysis = redact(entry.get("analysis_markdown", "").strip())
    if not analysis:
        analysis = "Für diesen Live-Abruf liegt keine individuelle Aufarbeitung vor. Reproduktion, Ursachenprüfung, Umsetzung und Tests sind offen. Dieses Issue ist durch den Import nicht behoben."
    analysis = rewrite_prose(analysis)
    if len(analysis.encode("utf-8")) > 45_000:
        analysis_blocks = literal_blocks("Aufarbeitung (langer Markdown-Text)", analysis)
    else:
        analysis_blocks = [analysis]
    reported = entry.get("reported_comment_count", issue.get("comments", 0))
    units = [f"## Herkunft\n\nQuelle: [coollabsio/coolify Issue {number}]({issue['html_url']})\n\n"
             f"Erfasst: `{clean_terminal(captured_at)}`. Original-ID: `{identity}`. "
             f"Abrufbare Kommentare: **{len(entry['comments'])}**, Quellzähler: **{reported}**.\n\n"
             "Dies ist eine unabhängige Arbeitskopie. GitHub zeigt den importierenden Account und den Importzeitpunkt an; Originalautoren und Originalzeiten stehen im Snapshot. "
             "Wörtliche Originaltexte sind als Codeblöcke eingefügt, damit Erwähnungen keine Benachrichtigungen auslösen und Codebeispiele erhalten bleiben."]
    if not re.match(r"^#{1,6}\s", analysis):
        units.append("## Aufarbeitung")
    units.extend(analysis_blocks)
    notes = entry.get("collection_notes", [])
    if notes:
        units.append("## Erfassungsvermerke\n\n" + "\n".join("- " + rewrite_prose(redact(note)) for note in notes))
    original = redact(issue.get("body") or "")
    units.extend(["## Original-Issue", *literal_blocks("Originaltext (erkannte Schlüssel redigiert)", original), *source_references(original)])
    metadata_keys = ("id", "node_id", "number", "html_url", "user", "created_at", "updated_at",
                     "closed_at", "state", "state_reason", "labels", "assignees", "milestone",
                     "locked", "author_association", "comments", "reactions")
    metadata = {key: issue[key] for key in metadata_keys if key in issue}
    units.extend(literal_blocks("Ursprüngliche Metadaten (keine neuen Zuweisungen)", redact(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)), "json"))
    if entry["comments"]:
        units.append("## Diskussion — attribuierter Snapshot")
    for comment in sorted(entry["comments"], key=lambda value: (value.get("created_at", ""), value["id"])):
        author = (comment.get("user") or {}).get("login", "[nicht verfügbar]")
        created = comment.get("created_at", "[nicht verfügbar]")
        updated = comment.get("updated_at", "[nicht verfügbar]")
        # All untrusted metadata is inside literal blocks, never in HTML labels.
        comment_text = (f"Originalautor: {author}\nOriginal erstellt: {created}\nOriginal geändert: {updated}\n"
                        f"Original-Kommentar-ID: {comment['id']}\n\n{comment.get('body') or ''}")
        comment_text = redact(comment_text)
        units.append(f"### [Originalkommentar {comment['id']}]({comment['html_url']})")
        units.extend(literal_blocks(f"Kommentar {comment['id']}", comment_text))
        units.extend(source_references(comment.get("body") or ""))
    if redactions:
        units.insert(1, "**Redaktion vor Veröffentlichung:** " + ", ".join(f"{name}: {count}" for name, count in sorted(redactions.items())) + ". Erkennbare Schlüssel wurden durch Platzhalter ersetzt; diese Heuristik ist keine Garantie, sämtliche Geheimnisse zu erkennen.")
    payloads, current, current_bytes = [], [], 0
    for unit in units:
        size = len(unit.encode("utf-8"))
        if size > MAX_BODY_BYTES - 512:
            raise ImportFailure(f"Issue {number}: Ein unteilbarer Textabschnitt ist zu groß.")
        if current and current_bytes + size + 2 > MAX_BODY_BYTES - 512:
            payloads.append("\n\n".join(current))
            current, current_bytes = [], 0
        current.append(unit)
        current_bytes += size + (2 if len(current) > 1 else 0)
    if current:
        payloads.append("\n\n".join(current))
    labels = issue.get("labels", [])
    for label in labels:
        if (not isinstance(label, dict) or not isinstance(label.get("name"), str)
                or not 1 <= len(label["name"]) <= 50
                or not isinstance(label.get("color", "ededed"), str)
                or not re.fullmatch(r"[0-9a-fA-F]{6}", label.get("color", "ededed"))):
            raise ImportFailure(f"Issue {number}: Ungültiges Label.")
        if label.get("description") is not None and not isinstance(label["description"], str):
            raise ImportFailure(f"Issue {number}: Ungültige Labelbeschreibung.")
        if redact_secrets(label["name"])[1]:
            raise ImportFailure(f"Issue {number}: Ein Labelname enthält ein erkennbares Secret; vor dem Import redigieren.")
    # Capture time is informational: an unchanged --live result can be resumed.
    capture_text = f"Erfasst: `{clean_terminal(captured_at)}`."
    hash_payloads = [payload.replace(capture_text, "Erfasst: [Zeitpunkt des ersten Imports].", 1) for payload in payloads]
    digest = hashlib.sha256(json.dumps([title, hash_payloads, labels], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    bodies = []
    for index, payload in enumerate(payloads):
        marker = f"<!-- coolify-upstream-part:v1 id={identity} digest={digest} part={index} -->\n"
        if index == 0:
            marker = f"<!-- coolify-upstream:v1 source={SOURCE} id={identity} number={number} digest={digest} parts={len(payloads)} -->\n" + marker
        bodies.append(marker + payload)
    if any(len(body.encode("utf-8")) > MAX_BODY_BYTES for body in bodies):
        raise ImportFailure(f"Issue {number}: Zu großer fertiger Payload.")
    return RenderedIssue(identity, number, title, labels, digest, bodies, redactions)


def existing_imports(issues: list[dict]) -> dict[int, tuple[dict, re.Match]]:
    result = {}
    for issue in issues:
        if "pull_request" in issue:
            continue
        first = (issue.get("body") or "").split("\n", 1)[0]
        marker = ISSUE_MARKER.fullmatch(first)
        if marker:
            identity = int(marker[1])
            if identity in result:
                raise ImportFailure(f"Mehrere Ziel-Issues haben denselben Herkunftsmarker {identity}; zuerst manuell prüfen.")
            positive_int(issue.get("number"), "target issue.number")
            result[identity] = (issue, marker)
    return result


def import_issues(api: GitHub, rendered: list[RenderedIssue], emit=print) -> dict[str, int]:
    enabled = api.repository.get("has_issues") is True
    if not enabled and api.apply:
        if not api.enable_requested:
            raise ImportFailure("Issues sind im Ziel deaktiviert. Zum Import --apply --enable-issues verwenden.")
        api.enable_issues()
        enabled = True
    try:
        destination = api.all_pages(f"repos/{api.target}/issues?state=all&per_page=100&sort=created&direction=asc")
    except ApiFailure as exc:
        if enabled or exc.status not in (404, 410) or api.apply:
            raise
        destination = []
        emit("Issues deaktiviert: bestehende Issues können erst nach Aktivierung vollständig abgeglichen werden.")
    imports = existing_imports(destination)
    stats = {"new_issues": 0, "existing_issues": 0, "new_comments": 0, "changed_snapshots": 0}
    pending = []
    for item in rendered:
        existing = imports.get(item.identity)
        if not existing:
            pending.append((item, None, set()))
            stats["new_issues"] += 1
            stats["new_comments"] += len(item.bodies) - 1
            continue
        issue, marker = existing
        if int(marker[2]) != item.number:
            raise ImportFailure(f"Quell-ID und Quellnummer widersprechen sich bei Ziel-Issue {issue['number']}.")
        stats["existing_issues"] += 1
        if marker[3] != item.digest:
            stats["changed_snapshots"] += 1
            emit(f"Quelle {item.number}: anderer Snapshot bereits importiert; Ziel-Issue {issue['number']} bleibt unverändert.")
            continue
        if int(marker[4]) != len(item.bodies):
            raise ImportFailure(f"Inkonsistente Teilezahl bei Ziel-Issue {issue['number']}.")
        known = {0}
        if len(item.bodies) > 1:
            for comment in api.all_pages(f"repos/{api.target}/issues/{issue['number']}/comments?per_page=100"):
                part = PART_MARKER.fullmatch((comment.get("body") or "").split("\n", 1)[0])
                if part and int(part[1]) == item.identity and part[2] == item.digest:
                    index = int(part[3])
                    if index in known or not 0 < index < len(item.bodies):
                        raise ImportFailure(f"Doppelter oder ungültiger Teil bei Ziel-Issue {issue['number']}.")
                    known.add(index)
        stats["new_comments"] += len(item.bodies) - len(known)
        pending.append((item, issue, known))
    emit(f"{'Import' if api.apply else 'Vorschau'}: {stats['new_issues']} neue Issues, {stats['existing_issues']} bereits vorhanden, {stats['new_comments']} neue Fortsetzungskommentare.")
    if not enabled:
        emit("Für die tatsächliche Ausführung sind --apply --enable-issues erforderlich.")
    if not api.apply:
        return stats
    labels = api.all_pages(f"repos/{api.target}/labels?per_page=100")
    known_labels = {label["name"].casefold() for label in labels}
    for item, existing, known in pending:
        if existing is None:
            for label in item.labels:
                if label["name"].casefold() not in known_labels:
                    description, _ = redact_secrets(label.get("description") or "")
                    api.request("POST", f"repos/{api.target}/labels", {
                        "name": label["name"], "color": label.get("color", "ededed"),
                        "description": description[:100],
                    })
                    known_labels.add(label["name"].casefold())
            created, _ = api.request("POST", f"repos/{api.target}/issues", {
                "title": item.title, "body": item.bodies[0], "labels": [label["name"] for label in item.labels],
            })
            if (not isinstance(created, dict) or type(created.get("number")) is not int
                    or created["number"] <= 0 or created.get("body") != item.bodies[0]):
                raise AmbiguousWrite("Issue-Erstellung nicht vollständig bestätigt. Abbruch; Ziel prüfen und denselben Snapshot erneut starten.")
            existing, known = created, {0}
            emit(f"Quelle {item.number} → https://github.com/{api.target}/issues/{created['number']}")
        for index, body in enumerate(item.bodies[1:], 1):
            if index not in known:
                created, _ = api.request("POST", f"repos/{api.target}/issues/{existing['number']}/comments", {"body": body})
                if not isinstance(created, dict) or created.get("body") != body:
                    raise AmbiguousWrite("Kommentar-Erstellung nicht vollständig bestätigt. Abbruch; denselben Snapshot erneut starten.")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="Vorbereiteter Snapshot; Standard relativ zum Script-Repository.")
    source.add_argument("--live", action="store_true", help="Alle aktuell passenden Quell-Issues lesen; ohne individuelle Analyse.")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Zielrepository unter mleem97.")
    parser.add_argument("--apply", action="store_true", help="Import tatsächlich ausführen; Standard ist Vorschau.")
    parser.add_argument("--enable-issues", action="store_true", help="Mit --apply deaktivierte Ziel-Issues aktivieren.")
    parser.add_argument("--validate-snapshot", action="store_true", help="Nur lokale Schema-/Payload-Prüfung; keine GitHub-Aufrufe.")
    args = parser.parse_args(argv)
    if args.enable_issues and not args.apply:
        parser.error("--enable-issues setzt --apply voraus")
    if args.validate_snapshot and (args.live or args.apply or args.enable_issues):
        parser.error("--validate-snapshot ist nicht mit --live oder Schreiboptionen kombinierbar")
    try:
        target = validate_target(args.target)
        snapshot, entries = (None, None) if args.live else load_snapshot(args.snapshot, target)
        rendered = None if args.live else [render_issue(entry, snapshot["captured_at"]) for entry in entries]
        if args.validate_snapshot:
            bodies = [body for item in rendered for body in item.bodies]
            print(f"Snapshot gültig: {len(rendered)} Issues, {sum(len(entry['comments']) for entry in entries)} Kommentare, "
                  f"{len(bodies) - len(rendered)} Fortsetzungskommentare, größter Payload {max((len(body.encode('utf-8')) for body in bodies), default=0)} UTF-8-Bytes.")
            print(f"Zusätzliche Redaktionen beim Rendern: {sum(sum(item.redactions.values()) for item in rendered)}.")
            return 0
        context = LocalLock(target) if args.apply else contextlib.nullcontext(None)
        with context as lock:
            api = GitHub(target, args.apply, args.enable_issues, lock=lock)
            api.verify()
            if args.live:
                snapshot, entries = live_snapshot(api)
                if args.apply:
                    frozen_path, snapshot = freeze_live_snapshot(snapshot, lock.directory)
                    entries = validate_snapshot(snapshot, target)
                    resume = ["python3", str(Path(__file__).resolve()), "--snapshot", str(frozen_path),
                              "--target", target, "--apply"]
                    if args.enable_issues:
                        resume.append("--enable-issues")
                    print(f"Redigierter Live-Snapshot (Dateimodus 0600): {frozen_path}")
                    print("Wiederaufnahme genau dieses Imports: " + shlex.join(resume))
                rendered = [render_issue(entry, snapshot["captured_at"]) for entry in entries]
            import_issues(api, rendered)
        return 0
    except (ImportFailure, OSError) as exc:
        print("Fehler: " + clean_terminal(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen. Denselben Snapshot erneut starten, um vorhandene Issues und Teile abzugleichen.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
