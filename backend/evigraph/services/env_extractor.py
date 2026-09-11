"""Environment-variable read sites in source and config.

The consumer half of config ownership. Env-var indirection is the #1 documented
false-negative cause across every published dependency-extraction tool: a call
like ``fetch(process.env.ORDERS_URL)`` is invisible unless the read site is
recorded here and joined to its definition by R9.

Regex rather than AST because these are single-expression idioms that appear
identically across framework versions, and because a file with a partial parse
must still yield its env reads.
"""

import re
from dataclasses import dataclass

# JS/TS: process.env.NAME, process.env["NAME"], import.meta.env.NAME, Deno.env.get
_JS = re.compile(
    r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"
    r"|process\.env\[\s*['\"]([^'\"]+)['\"]\s*\]"
    r"|import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"
    r"|Deno\.env\.get\(\s*['\"]([^'\"]+)['\"]")

# Python: os.environ["X"], os.environ.get("X"), os.getenv("X"), environ["X"]
_PY = re.compile(
    r"os\.environ\.get\(\s*['\"]([^'\"]+)['\"]"
    r"|os\.environ\[\s*['\"]([^'\"]+)['\"]\s*\]"
    r"|os\.getenv\(\s*['\"]([^'\"]+)['\"]"
    r"|(?<!os\.)\benviron\[\s*['\"]([^'\"]+)['\"]\s*\]")

# JVM: @Value("${x.y:default}"), System.getenv("X"), env.getProperty("x.y")
_JVM = re.compile(
    r"System\.getenv\(\s*\"([^\"]+)\""
    r"|@Value\s*\(\s*\"\$\{([^:}]+)"
    r"|getProperty\(\s*\"([^\"]+)\"")

# Go: os.Getenv("X"), os.LookupEnv("X"), viper.GetString("x.y")
_GO = re.compile(
    r"os\.Getenv\(\s*\"([^\"]+)\""
    r"|os\.LookupEnv\(\s*\"([^\"]+)\""
    r"|viper\.Get(?:String|Int|Bool)?\(\s*\"([^\"]+)\"")

# C#: Environment.GetEnvironmentVariable("X"), Configuration["X"], GetValue<T>("X")
_CSHARP = re.compile(
    r"Environment\.GetEnvironmentVariable\(\s*\"([^\"]+)\""
    r"|(?:_?[Cc]onfiguration)\[\s*\"([^\"]+)\"\s*\]"
    r"|GetValue<[^>]+>\(\s*\"([^\"]+)\"")

# Ruby: ENV["X"], ENV.fetch("X")
_RUBY = re.compile(r"ENV\[\s*['\"]([^'\"]+)['\"]\s*\]|ENV\.fetch\(\s*['\"]([^'\"]+)['\"]")

# ${VAR} / ${VAR:-default} inside config files and compose/entrypoint scripts
_SHELL_INTERP = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)[:\-}]")

_LANG_PATTERNS = {
    "javascript": (_JS,), "typescript": (_JS,),
    "python": (_PY,),
    "java": (_JVM,), "kotlin": (_JVM,), "scala": (_JVM,),
    "go": (_GO,),
    "c#": (_CSHARP,), "csharp": (_CSHARP,),
    "ruby": (_RUBY,),
}

# Names so generic that joining on them across repos would be noise, not signal.
GENERIC_ENV_NAMES = frozenset({
    "PATH", "HOME", "USER", "SHELL", "PWD", "LANG", "TERM", "TZ", "HOSTNAME",
    "NODE_ENV", "ENV", "ENVIRONMENT", "DEBUG", "LOG_LEVEL", "PORT", "TMPDIR",
    "CI", "GOPATH", "JAVA_HOME", "PYTHONPATH", "LD_LIBRARY_PATH",
})


@dataclass
class EnvRead:
    name: str
    line: int
    generic: bool


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def extract_env_reads(content: str, language: str | None) -> list[EnvRead]:
    """Env-var names this file reads, de-duplicated, first occurrence wins."""
    patterns = _LANG_PATTERNS.get((language or "").lower(), ())
    seen: dict[str, EnvRead] = {}
    for pattern in patterns:
        for match in pattern.finditer(content):
            name = next((g for g in match.groups() if g), "")
            if name and name not in seen:
                seen[name] = EnvRead(name=name, line=_line_of(content, match.start()),
                                     generic=is_generic_env(name))
    return list(seen.values())


def extract_shell_interpolations(content: str) -> list[EnvRead]:
    """``${VAR}`` references in config files, compose files and entrypoints."""
    seen: dict[str, EnvRead] = {}
    for match in _SHELL_INTERP.finditer(content):
        name = match.group(1)
        if name and name not in seen:
            seen[name] = EnvRead(name=name, line=_line_of(content, match.start()),
                                 generic=is_generic_env(name))
    return list(seen.values())


_SHELL_DEFAULT = re.compile(
    r"^\$\{[A-Za-z_][A-Za-z0-9_]*:-([^}]*)\}$")


def shell_default(value: str) -> str | None:
    """The fallback in a whole-value `${VAR:-fallback}`, or None.

    Compose and entrypoint scripts declare a default inline, and that
    default is what runs unless an operator overrides it — a statically
    knowable value, not a template nobody rendered. `is_unrendered_template`
    correctly refuses the raw string; this reads the part of it that IS
    determined.

    Whole-value only. `http://${HOST:-db}:${PORT:-5432}/x` needs the shell
    to assemble, and splicing the pieces here would be rendering by hand —
    the same line the Helm chase refuses to cross.
    """
    match = _SHELL_DEFAULT.match((value or "").strip())
    if not match:
        return None
    fallback = match.group(1).strip()
    # A nested or still-templated fallback is not a value either.
    if not fallback or "${" in fallback:
        return None
    return fallback


def is_generic_env(name: str) -> bool:
    return name.upper() in GENERIC_ENV_NAMES


def looks_like_endpoint_var(name: str) -> bool:
    """Whether a variable name suggests it carries a network target.

    R9 resolves every variable it can, but this ranks which unresolved ones are
    worth surfacing: an unresolved ``ORDERS_SERVICE_URL`` is a missing edge,
    an unresolved ``RETRY_COUNT`` is not.
    """
    upper = name.upper()
    return any(token in upper for token in (
        "URL", "URI", "HOST", "ENDPOINT", "ADDR", "ADDRESS", "SERVER",
        "BROKER", "BOOTSTRAP", "QUEUE", "TOPIC", "BASE_PATH", "BASEPATH",
        "SERVICE", "UPSTREAM", "TARGET", "DSN", "CONNECTION",
    ))
