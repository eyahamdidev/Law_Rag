"""Versioned prompt library.

Each prompt lives in prompts/library/<id>.yaml with every version it has had:

    id: rag.answer
    agent: rag
    role: what the prompt does in the system
    current: v2
    versions:
      - version: v1
        date: 2026-10-12
        techniques: [role prompting, structured output]
        system: |
          ...
        user: |
          ... {{question}} ...
        observed_failures: [what went wrong, with the eval id or trace that showed it]
      - version: v2
        changes: what changed and which failure it fixes
        ...

Templates use {{name}} placeholders so JSON examples inside a prompt need no
escaping. Every rendered prompt carries "<id>@<version>", which the agents
put in their trace, so a run can be tied to the exact prompt text.
`python -m app.prompts.library` writes docs/PROMPT_LIBRARY.md from the YAML.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import REPO_ROOT

LIBRARY_DIR = Path(__file__).parent / "library"
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_VERSION_KEYS = {"version", "date", "changes", "techniques", "system", "user", "observed_failures"}


@dataclass
class PromptVersion:
    prompt_id: str
    version: str
    system: str
    user: str
    techniques: list[str] = field(default_factory=list)
    # Other keys of the version (e.g. per-language instructions), read by the caller.
    extras: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.prompt_id}@{self.version}"

    def _fill(self, template: str, values: dict) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in values:
                raise KeyError(f"{self.ref} needs '{name}'")
            return str(values[name])

        return _PLACEHOLDER.sub(replace, template)

    def messages(self, **values) -> list[dict]:
        out = []
        if self.system.strip():
            out.append({"role": "system", "content": self._fill(self.system, values).strip()})
        out.append({"role": "user", "content": self._fill(self.user, values).strip()})
        return out


@lru_cache(maxsize=None)
def _load(prompt_id: str) -> dict:
    path = LIBRARY_DIR / f"{prompt_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No prompt '{prompt_id}' in {LIBRARY_DIR}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def get_prompt(prompt_id: str, version: str | None = None) -> PromptVersion:
    spec = _load(prompt_id)
    wanted = version or spec["current"]
    for item in spec["versions"]:
        if item["version"] == wanted:
            return PromptVersion(
                prompt_id=prompt_id,
                version=wanted,
                system=item.get("system", ""),
                user=item["user"],
                techniques=item.get("techniques", []),
                extras={k: v for k, v in item.items() if k not in _VERSION_KEYS},
            )
    raise KeyError(f"{prompt_id} has no version {wanted}")


def all_prompts() -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(LIBRARY_DIR.glob("*.yaml"))]


def write_markdown(path: Path | None = None) -> Path:
    path = path or REPO_ROOT / "docs" / "PROMPT_LIBRARY.md"
    lines = [
        "# Prompt library",
        "",
        "Generated from `backend/app/prompts/library/*.yaml` by `python -m app.prompts.library`.",
        "Edit the YAML, not this file.",
        "",
    ]
    for spec in all_prompts():
        lines += [f"## `{spec['id']}`", "", f"**Agent:** {spec['agent']}  ", f"**Current:** {spec['current']}", ""]
        lines += [spec["role"].strip(), ""]
        for item in spec["versions"]:
            lines += [f"### {item['version']} ({item.get('date', '')})", ""]
            if item.get("changes"):
                lines += [f"**Changes:** {item['changes'].strip()}", ""]
            lines += [f"**Techniques:** {', '.join(item.get('techniques', []))}", ""]
            if item.get("system"):
                lines += ["System:", "", "```text", item["system"].rstrip(), "```", ""]
            lines += ["User:", "", "```text", item["user"].rstrip(), "```", ""]
            failures = item.get("observed_failures") or []
            lines += ["**Observed failures:**", ""]
            lines += [f"- {f}" for f in failures] if failures else ["- None recorded yet."]
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_markdown())
