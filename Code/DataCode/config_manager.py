from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os
import threading

import yaml


@dataclass
class AgentConfig:
    name: str
    system_prompt: str
    available_tools: list[str] = field(default_factory=list)
    available_skills: list[str] = field(default_factory=list)
    model: str | None = None


class ConfigManager:
    def __init__(self, platform_yaml: str, agents_dir: str):
        self._platform_path = Path(platform_yaml)
        self._agents_dir = Path(agents_dir)
        self._platform: dict = {}
        self._agents: dict[str, AgentConfig] = {}
        self._observer = None

    def load(self) -> None:
        self._load_platform()
        self._load_agents()

    def _load_platform(self) -> None:
        with open(self._platform_path, encoding="utf-8") as f:
            self._platform = yaml.safe_load(f) or {}
        # 环境变量覆盖 API key
        env_key = os.environ.get("LLM_API_KEY")
        if env_key:
            self._platform.setdefault("llm", {})["api_key"] = env_key

    def _load_agents(self) -> None:
        new_agents: dict[str, AgentConfig] = {}
        main_dir = self._agents_dir / "main"
        if main_dir.exists():
            main_config = self._load_agent_dir(main_dir, "main")
            if main_config:
                new_agents["main"] = main_config
                self._load_sub_agents_into(new_agents)
        self._agents = new_agents  # atomic reference swap

    def _load_sub_agents_into(self, agents: dict[str, AgentConfig]) -> None:
        sub_dir = self._agents_dir / "sub"
        if not sub_dir.exists():
            return
        main = agents.get("main")
        for agent_path in sorted(sub_dir.iterdir()):
            if agent_path.is_dir():
                config = self._load_agent_dir(agent_path, agent_path.name, parent=main)
                if config:
                    agents[agent_path.name] = config

    def _load_agent_dir(self, path: Path, name: str, parent: AgentConfig | None = None) -> AgentConfig | None:
        prompt_file = path / "系统提示词.txt"
        if not prompt_file.exists():
            return None

        system_prompt = prompt_file.read_text(encoding="utf-8").strip()
        available_tools = self._load_list_file(path / "可用工具.txt")
        available_skills = self._load_list_file(path / "可用技能.txt")

        model_file = path / "LLM模型.txt"
        model = model_file.read_text(encoding="utf-8").strip() if model_file.exists() else None

        if parent:
            available_tools = available_tools or parent.available_tools
            available_skills = available_skills or parent.available_skills
            model = model or parent.model

        if model is None:
            model = self.get("llm.default_model")

        return AgentConfig(
            name=name,
            system_prompt=system_prompt,
            available_tools=available_tools,
            available_skills=available_skills,
            model=model,
        )

    @staticmethod
    def _load_list_file(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def get(self, param_name: str, default: Any = None) -> Any:
        keys = param_name.split(".")
        value = self._platform
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_agent_config(self, name: str) -> AgentConfig | None:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    def validate(self) -> list[str]:
        errors = []
        llm = self._platform.get("llm", {})
        if not llm.get("base_url"):
            errors.append("llm.base_url is required")
        if not llm.get("api_key"):
            errors.append("llm.api_key is required")
        if not llm.get("default_model"):
            errors.append("llm.default_model is required")
        if "main" not in self._agents:
            errors.append("main agent config is required")
        return errors

    def watch(self, callback) -> None:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        manager = self

        class ReloadHandler(FileSystemEventHandler):
            def __init__(self_inner):
                self_inner._timer = None

            def on_modified(self_inner, event):
                if not event.is_directory:
                    if self_inner._timer:
                        self_inner._timer.cancel()
                    self_inner._timer = threading.Timer(0.5, self_inner._reload)
                    self_inner._timer.daemon = True
                    self_inner._timer.start()

            def _reload(self_inner):
                manager.load()
                callback()

        self._observer = Observer()
        self._observer.schedule(ReloadHandler(), str(self._agents_dir), recursive=True)
        self._observer.schedule(ReloadHandler(), str(self._platform_path.parent), recursive=False)
        self._observer.start()

    def stop_watch(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
