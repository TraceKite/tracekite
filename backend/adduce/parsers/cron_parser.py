"""Crontab entries whose command calls a service over HTTP.

A `curl` in a crontab is a real cross-service dependency with no code
behind it — invisible to every source extractor, and exactly the kind of
edge that surprises whoever breaks it at 03:00. Only entries with a
literal http(s) URL are taken: a cron line running a script *might* call
anything, and might is not evidence.

Recognised files: `crontab`, anything under a `cron.d/` directory, and
`*.cron`. Pure: bytes and a path in, entries out, `[]` for anything
unrecognised.
"""

import re
from dataclasses import dataclass

_CRON_FILE = re.compile(r"(^|/)(crontab|cron\.d/[^/]+)$|\.cron$")

# Five time fields (or @hourly-style shortcuts), optional run-as user, then
# the command. Precision over coverage: a malformed schedule is not a
# schedule, and guessing one would timestamp an edge with fiction.
_ENTRY = re.compile(
    r"^\s*(@\w+|(?:[\d*/,-]+\s+){4}[\d*/,-]+)\s+(?:(\w+)\s+)?(.+)$")
_URL = re.compile(r"https?://[^\s'\"]+")
_CURL_METHOD = re.compile(r"(?:curl|wget)[^|;&]*?(?:-X|--request)\s+(\w+)",
                          re.I)


@dataclass
class CronCall:
    """One scheduled HTTP call, as declared."""
    schedule: str
    method: str
    url: str
    line: int
    command: str


def is_cron_file(file_path: str) -> bool:
    return bool(_CRON_FILE.search(file_path))


def parse_crontab(file_path: str, content: str) -> list[CronCall]:
    """Every scheduled entry with a literal URL in its command.

    Entries without one are not returned and not guessed at — the file
    may schedule a hundred scripts; the URLs are the only claims this
    parser can cite.
    """
    if not is_cron_file(file_path):
        return []
    calls: list[CronCall] = []
    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") \
                or re.match(r"^\w+\s*=", stripped):
            # Blank, comment, or a SHELL=/bin/sh-style variable line.
            continue
        entry = _ENTRY.match(line)
        if not entry:
            continue
        command = entry.group(3)
        for url in _URL.findall(command):
            method = _CURL_METHOD.search(command)
            calls.append(CronCall(
                schedule=entry.group(1).strip(),
                method=(method.group(1).upper() if method else "GET"),
                url=url.rstrip(");,'\""), line=number, command=command))
    return calls
