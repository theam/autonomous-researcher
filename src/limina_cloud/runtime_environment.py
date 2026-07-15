"""Environment policy for provider runtimes and project-supplied resources."""

from __future__ import annotations

import os
from pathlib import Path

SAFE_PROCESS_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "COLORTERM",
        "PATH",
        "SHELL",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "USER",
    }
)
SAFE_CODEX_ENV = SAFE_PROCESS_ENV | {
    "CODEX_CA_CERTIFICATE",
    "CODEX_CI",
    "CODEX_HOME",
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "CODEX_PERMISSION_PROFILE",
    "CODEX_SHELL",
}
SAFE_CLAUDE_ENV = SAFE_PROCESS_ENV | {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_VERTEX",
}

# Project resources are environment variables inside a provider process. These names can execute
# code, replace network/auth configuration, or reach outside the managed workspace before the
# provider's own sandbox starts. Keep the policy centralized and apply it at write and read time.
RESERVED_RESOURCE_NAMES = frozenset(
    {
        "ALL_PROXY",
        "BASH_ENV",
        "ENV",
        "GIT_ASKPASS",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_SSH_COMMAND",
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "NODE_OPTIONS",
        "NO_PROXY",
        "PATH",
        "PERL5LIB",
        "PERL5OPT",
        "PROMPT_COMMAND",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "RUBYOPT",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SSH_ASKPASS",
        "ZDOTDIR",
    }
)
RESERVED_RESOURCE_PREFIXES = (
    "ANTHROPIC_",
    "CLAUDE_",
    "CODEX_",
    "DYLD_",
    "LD_",
    "LIMINA_",
    "OPENAI_",
)


def is_reserved_resource_name(name: str) -> bool:
    normalized = name.strip().upper()
    return normalized in RESERVED_RESOURCE_NAMES or normalized.startswith(
        RESERVED_RESOURCE_PREFIXES
    )


def sanitize_project_environment(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Drop unsafe legacy rows even if they predate the current write-time policy."""
    safe: dict[str, str] = {}
    blocked: list[str] = []
    for name, value in values.items():
        if is_reserved_resource_name(name):
            blocked.append(name)
        else:
            safe[name] = value
    return safe, sorted(blocked)


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def isolated_environment(
    safe_names: frozenset[str] | set[str], runtime_env: dict[str, str]
) -> dict[str, str]:
    """Build a child environment without inheriting control-plane secrets."""
    env = {name: "" for name in os.environ if name not in safe_names}
    env.update({name: value for name, value in os.environ.items() if name in safe_names})
    env.update(runtime_env)
    return env


def codex_environment(runtime_env: dict[str, str], codex_home: Path) -> dict[str, str]:
    """Pin Codex state after overlays and keep raw provider credentials out of the child env."""
    env = isolated_environment(SAFE_CODEX_ENV, runtime_env)
    env["CODEX_HOME"] = str(ensure_private_directory(codex_home))
    env["OPENAI_API_KEY"] = ""
    env["CODEX_API_KEY"] = ""
    env["CODEX_ACCESS_TOKEN"] = ""
    return env


def claude_environment(runtime_env: dict[str, str], config_dir: Path) -> dict[str, str]:
    env = isolated_environment(SAFE_CLAUDE_ENV, runtime_env)
    env["CLAUDE_CONFIG_DIR"] = str(ensure_private_directory(config_dir))
    env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
    return env
