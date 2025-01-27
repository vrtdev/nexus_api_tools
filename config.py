"""Dataclasses to hold and parse tool configuration"""
from dataclasses import dataclass, field, fields, MISSING
from typing import List, Optional, TypeVar

import yaml

T = TypeVar("T", bound="MergeableDataclass")


@dataclass
class MergeableDataclass:
    def merge(self: T, other: T) -> T:
        if type(self) is not type(other):
            raise TypeError(f"Cannot merge dataclasses of different types: {type(self)} and {type(other)}")

        for f in fields(other):
            other_value = getattr(other, f.name)
            if f.default is not MISSING and other_value != f.default:
                setattr(self, f.name, other_value)
            elif f.default_factory is not MISSING and callable(f.default_factory):
                if other_value != f.default_factory():
                    setattr(self, f.name, other_value)
            elif other_value is not None:
                setattr(self, f.name, other_value)

        return self


@dataclass
class NexusServer(MergeableDataclass):
    host: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    docker_host: Optional[str] = None

    def fix_paths(self):
        # Ensure `host` and `docker_host` always ends with a '/'
        if self.host and not self.host.endswith("/"):
            self.host += "/"
        if self.docker_host and not self.docker_host.endswith("/"):
            self.docker_host += "/"

    def __post_init__(self):
        self.fix_paths()


@dataclass
class Action:
    repo: str
    active: bool = True
    source: NexusServer = field(default_factory=NexusServer)
    destination: NexusServer = field(default_factory=NexusServer)
    target_repo: Optional[str] = None
    repo_type: Optional[str] = None
    description: Optional[str] = None
    action: Optional[str] = None
    path: Optional[str] = None

    def fix_paths(self):
        # Ensure `path` always ends with a '/'
        if self.path and not self.path.endswith("/"):
            self.path += "/"

    def __post_init__(self):
        self.fix_paths()
        if not self.target_repo:
            self.target_repo = self.repo


@dataclass
class NexusCopyConfig:
    actions: List[Action]
    source: NexusServer = field(default_factory=NexusServer)
    destination: NexusServer = field(default_factory=NexusServer)
    default_action: Optional[str] = "both"
    local_path: str = "./"

    def fix_paths(self):
        if self.local_path and not self.local_path.endswith("/"):
            self.local_path += "/"

    def __post_init__(self):
        self.fix_paths()

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'NexusCopyConfig':
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        actions = [Action(**action) for action in data.get('actions', [])]
        config = cls(
            default_action=data.get('default_action'),
            local_path=data.get('local_path'),
            actions=actions,
        )
        if 'source' in data:
            config.source = NexusServer(**data['source'])

        if 'destination' in data:
            config.destination = NexusServer(**data['destination'])

        return config
