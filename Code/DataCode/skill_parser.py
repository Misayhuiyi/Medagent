"""SkillParser：解析 Claude Code Skills 标准的 SKILL.md 文件。

YAML frontmatter + Markdown body，支持变量替换和目录批量解析。
"""

from __future__ import annotations

import re
import shlex
import subprocess
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SkillDef:
    name: str
    description: str
    body: str
    mode: str = "autonomous"  # "autonomous" | "sequential"
    allowed_tools: list[str] = field(default_factory=list)
    arguments: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    effort: str = "medium"  # "low" | "medium" | "high"
    agent: str | None = None
    hooks: dict[str, Any] = field(default_factory=dict)
    sub_skills: list[str] = field(default_factory=list)
    source_path: str = ""
    skill_dir: str = ""       # skill 包目录的绝对路径
    version: str = ""
    author: str = ""
    license: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillParser:
    """解析 SKILL.md 文件。"""

    VALID_MODES = {"autonomous", "sequential"}
    VALID_EFFORTS = {"low", "medium", "high"}

    def parse(self, skill_path: str | Path) -> SkillDef:
        """解析单个 SKILL.md 文件。"""
        path = Path(skill_path)
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        content = path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(content)

        if frontmatter is None:
            raise ValueError(f"Missing YAML frontmatter in {path}")

        try:
            meta = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter in {path}: {e}") from e

        name = meta.get("name")
        if not name:
            raise ValueError(f"Missing required field 'name' in {path}")

        description = meta.get("description", "")
        if not description:
            raise ValueError(f"Missing required field 'description' in {path}")

        mode = meta.get("mode", "autonomous")
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}' in {path}. Must be one of {self.VALID_MODES}")

        effort = meta.get("effort", "medium")
        if effort not in self.VALID_EFFORTS:
            raise ValueError(f"Invalid effort '{effort}' in {path}. Must be one of {self.VALID_EFFORTS}")

        version = str(meta.get("version", "") or "")
        author = str(meta.get("author", "") or "")
        license_field = str(meta.get("license", "") or "")
        meta_field: dict[str, Any] = meta.get("metadata", {}) or {}

        return SkillDef(
            name=name,
            description=description,
            body=body.strip(),
            mode=mode,
            allowed_tools=meta.get("allowed-tools", meta.get("allowed_tools", [])),
            arguments=meta.get("arguments", {}),
            model=meta.get("model"),
            effort=effort,
            agent=meta.get("agent"),
            hooks=meta.get("hooks", {}),
            sub_skills=meta.get("sub-skills", meta.get("sub_skills", [])),
            source_path=str(path),
            version=version,
            author=author,
            license=license_field,
            metadata=meta_field,
        )

    def parse_dir(self, skills_dir: str | Path) -> list[SkillDef]:
        """扫描 skills_dir 下的直接子目录，解析每个 SKILL.md。"""
        skills_path = Path(skills_dir)
        if not skills_path.exists():
            return []

        skills = []
        for child in sorted(skills_path.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                try:
                    skill = self.parse(skill_md)
                    skill.skill_dir = str(child.resolve())
                    skills.append(skill)
                except (ValueError, yaml.YAMLError):
                    continue
        return skills

    def resolve_vars(self, body: str, args: dict[str, str] | None = None,
                     skill_dir: str = "") -> str:
        """替换 $ARGUMENTS.xxx 变量和 ${CLAUDE_SKILL_DIR}。"""
        resolved = body

        # 替换 $ARGUMENTS.xxx
        if args:
            for key, value in args.items():
                resolved = resolved.replace(f"$ARGUMENTS.{key}", str(value))

        # 替换 ${CLAUDE_SKILL_DIR}
        resolved = resolved.replace("${CLAUDE_SKILL_DIR}", skill_dir)

        return resolved

    def resolve_context(self, body: str) -> str:
        """替换 !command 动态注入（执行命令，stdout 注入，不使用 shell）。"""
        def _run_command(match: re.Match) -> str:
            cmd = match.group(1).strip()
            try:
                parts = shlex.split(cmd)
                result = subprocess.run(
                    parts, capture_output=True, text=True, timeout=10
                )
                return result.stdout.strip()
            except (subprocess.TimeoutExpired, Exception):
                return f"[command failed: {cmd}]"

        return re.sub(r"^!(`(.+?)`|(.+))$", _run_command, body, flags=re.MULTILINE)

    def _split_frontmatter(self, content: str) -> tuple[str | None, str]:
        """分割 YAML frontmatter 和 Markdown body。"""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, content
