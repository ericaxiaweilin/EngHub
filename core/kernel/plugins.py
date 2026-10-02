"""Composable plugin runtime for the unified EngHub harness.

This is the narrow integration seam between the existing Python harness and
the DeepSeek Harness ideas we are adopting:

* capabilities have a named definition, provider, and consumer;
* plugins mount in dependency order and unwind their registrations on unload;
* profiles compose ordered plugin layers and optional configuration overlays;
* runtime hooks are waterfall events, so extensions do not import the loop;
* the registry is deliberately model-agnostic.

The runtime is intentionally small.  Existing SkillRegistry, persistence and
model adapters remain valid providers while they migrate behind this seam.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

_logger = logging.getLogger("engflow_plugins")

PluginListener = Callable[[Dict[str, Any], Callable[..., Awaitable[Any]]], Any]
Cleanup = Callable[[], Any]


class PluginRuntimeError(RuntimeError):
    """Raised when a plugin composition or capability contract is invalid."""


@dataclass(frozen=True)
class CapabilityDefinition:
    """The stable contract name a provider implements and consumers use."""

    key: str
    description: str = ""
    contract: str = ""


@dataclass
class _Capability:
    definition: CapabilityDefinition
    provider: Any
    owner: str


@dataclass(frozen=True)
class PluginSpec:
    """A declarative plugin layer in a profile."""

    plugin_id: str
    setup: Callable[["PluginContext"], Any]
    depends_on: Tuple[str, ...] = ()
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessProfile:
    """Ordered plugin composition with a patch overlay."""

    name: str
    plugins: Tuple[str, ...]
    patch: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class _MountedPlugin:
    spec: PluginSpec
    context: "PluginContext"
    active: bool = True


class PluginContext:
    """The scoped registration context handed to one plugin."""

    def __init__(self, registry: "HarnessPluginRegistry", plugin_id: str, config: Dict[str, Any]):
        self.registry = registry
        self.plugin_id = plugin_id
        self.config = dict(config)
        self._cleanups: List[Cleanup] = []

    def define(self, key: str, *, description: str = "", contract: str = "") -> CapabilityDefinition:
        definition = self.registry.define(
            key, description=description, contract=contract, owner=self.plugin_id,
        )
        return definition

    def provide(
        self,
        key: str,
        provider: Any,
        *,
        description: str = "",
        contract: str = "",
        replace: bool = False,
    ) -> Any:
        self.registry.provide(
            key,
            provider,
            owner=self.plugin_id,
            description=description,
            contract=contract,
            replace=replace,
        )
        self._cleanups.append(lambda: self.registry.unprovide(key, owner=self.plugin_id))
        return provider

    def consume(self, key: str) -> Any:
        return self.registry.require(key)

    def subscribe(self, event: str, listener: PluginListener, *, priority: int = 0) -> str:
        token = self.registry.subscribe(
            event, listener, owner=self.plugin_id, priority=priority,
        )
        self._cleanups.append(lambda: self.registry.unsubscribe(token))
        return token

    def add_cleanup(self, cleanup: Cleanup) -> Cleanup:
        self._cleanups.append(cleanup)
        return cleanup

    def cleanup(self) -> None:
        for cleanup in reversed(self._cleanups):
            try:
                result = cleanup()
                if inspect.isawaitable(result):
                    raise PluginRuntimeError(
                        "异步插件清理必须通过显式生命周期适配器完成"
                    )
            except Exception:  # noqa: BLE001
                _logger.exception("plugin cleanup failed: %s", self.plugin_id)
        self._cleanups.clear()


class HarnessPluginRegistry:
    """Registry for plugins, capabilities, and waterfall extension points."""

    def __init__(self) -> None:
        self._definitions: Dict[str, CapabilityDefinition] = {}
        self._capabilities: Dict[str, _Capability] = {}
        self._plugins: Dict[str, _MountedPlugin] = {}
        self._listeners: Dict[str, List[Tuple[int, str, PluginListener]]] = {}
        self._profiles: Dict[str, HarnessProfile] = {}

    # ── Capability Definition / Provider / Consumer ──

    def define(
        self,
        key: str,
        *,
        description: str = "",
        contract: str = "",
        owner: str = "runtime",
    ) -> CapabilityDefinition:
        if not key or not key.strip():
            raise PluginRuntimeError("capability key 不能为空")
        current = self._definitions.get(key)
        if current is not None:
            return current
        definition = CapabilityDefinition(key=key, description=description, contract=contract)
        self._definitions[key] = definition
        return definition

    def provide(
        self,
        key: str,
        provider: Any,
        *,
        owner: str = "runtime",
        description: str = "",
        contract: str = "",
        replace: bool = False,
    ) -> None:
        definition = self.define(
            key, description=description, contract=contract, owner=owner,
        )
        current = self._capabilities.get(key)
        if current is not None and current.owner != owner and not replace:
            raise PluginRuntimeError(
                f"capability {key} 已由 {current.owner} 提供，不能由 {owner} 覆盖"
            )
        self._capabilities[key] = _Capability(definition, provider, owner)

    def unprovide(self, key: str, *, owner: Optional[str] = None) -> bool:
        current = self._capabilities.get(key)
        if current is None or (owner is not None and current.owner != owner):
            return False
        self._capabilities.pop(key, None)
        return True

    def unprovide_owner(self, owner: str) -> int:
        """Remove every capability owned by one unloaded plugin."""
        keys = [key for key, value in self._capabilities.items() if value.owner == owner]
        for key in keys:
            self._capabilities.pop(key, None)
        return len(keys)

    def consume(self, key: str, *, required: bool = True) -> Any:
        current = self._capabilities.get(key)
        if current is None:
            if required:
                raise PluginRuntimeError(f"capability 未提供: {key}")
            return None
        return current.provider

    require = consume

    # ── Plugin lifecycle ──

    def register_profile(self, profile: HarnessProfile) -> None:
        self._profiles[profile.name] = profile

    def mount(self, spec: PluginSpec, *, config: Optional[Dict[str, Any]] = None) -> None:
        if spec.plugin_id in self._plugins:
            return
        missing = [dependency for dependency in spec.depends_on if dependency not in self._plugins]
        if missing:
            raise PluginRuntimeError(
                f"plugin {spec.plugin_id} 缺少依赖: {', '.join(missing)}"
            )
        merged_config = dict(spec.config)
        merged_config.update(config or {})
        context = PluginContext(self, spec.plugin_id, merged_config)
        try:
            result = spec.setup(context)
            if inspect.isawaitable(result):
                raise PluginRuntimeError(
                    f"plugin {spec.plugin_id} 的 setup 不能在同步启动阶段返回 awaitable"
                )
        except Exception:
            context.cleanup()
            raise
        self._plugins[spec.plugin_id] = _MountedPlugin(spec=spec, context=context)

    def mount_profile(
        self,
        profile: HarnessProfile,
        specs: Dict[str, PluginSpec],
    ) -> None:
        self.register_profile(profile)
        for plugin_id in profile.plugins:
            spec = specs.get(plugin_id)
            if spec is None:
                raise PluginRuntimeError(f"profile {profile.name} 未找到 plugin: {plugin_id}")
            self.mount(spec, config=profile.patch.get(plugin_id))

    def unmount(self, plugin_id: str) -> None:
        mounted = self._plugins.get(plugin_id)
        if mounted is None:
            return
        dependents = [
            current.spec.plugin_id
            for current in self._plugins.values()
            if plugin_id in current.spec.depends_on and current.spec.plugin_id != plugin_id
        ]
        if dependents:
            raise PluginRuntimeError(
                f"plugin {plugin_id} 仍被使用: {', '.join(dependents)}"
            )
        mounted.context.cleanup()
        self.unprovide_owner(plugin_id)
        mounted.active = False
        self._plugins.pop(plugin_id, None)

    # ── Waterfall hooks ──

    def subscribe(
        self,
        event: str,
        listener: PluginListener,
        *,
        owner: str = "runtime",
        priority: int = 0,
    ) -> str:
        token = f"listener-{uuid.uuid4().hex[:12]}"
        self._listeners.setdefault(event, []).append((priority, token, listener))
        self._listeners[event].sort(key=lambda row: row[0])
        return token

    def unsubscribe(self, token: str) -> bool:
        removed = False
        for event, listeners in self._listeners.items():
            kept = [row for row in listeners if row[1] != token]
            removed = removed or len(kept) != len(listeners)
            self._listeners[event] = kept
        return removed

    async def dispatch(
        self,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Run listeners in priority order; listeners may call ``next``.

        A failed optional extension is isolated from the chat request.  Strict
        mode is available for tests and administrative workflows.
        """
        current = dict(payload or {})
        listeners = list(self._listeners.get(event, ()))

        async def invoke(index: int, value: Dict[str, Any]) -> Dict[str, Any]:
            if index >= len(listeners):
                return value
            _, _, listener = listeners[index]

            async def next_handler(next_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                return await invoke(index + 1, dict(next_payload or value))

            try:
                result = listener(value, next_handler)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict):
                    return result
                return await next_handler(value)
            except Exception:
                if strict:
                    raise
                _logger.exception("plugin hook failed: event=%s", event)
                return await next_handler(value)

        return await invoke(0, current)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "plugins": sorted(self._plugins),
            "profiles": sorted(self._profiles),
            "capabilities": sorted(self._capabilities),
            "definitions": sorted(self._definitions),
            "events": {
                event: len(listeners) for event, listeners in self._listeners.items()
            },
        }


_RUNTIME = HarnessPluginRegistry()
_CORE_BOOTSTRAPPED = False


def _mount_core_plugin(registry: HarnessPluginRegistry) -> None:
    """Mount the minimal host services shared by every profile."""
    def setup(ctx: PluginContext) -> None:
        from core.kernel.events import get_harness_event_bus

        ctx.provide(
            "harness.plugins",
            registry,
            description="Harness composition registry",
            contract="HarnessPluginRegistry",
        )
        ctx.provide(
            "harness.events",
            get_harness_event_bus(),
            description="Replayable harness event bus",
            contract="HarnessEventBus",
        )

    registry.mount(PluginSpec("enghub.harness.core", setup))


def get_harness_plugin_registry() -> HarnessPluginRegistry:
    """Return the process-wide composition registry used by Chat V2."""
    global _CORE_BOOTSTRAPPED
    if not _CORE_BOOTSTRAPPED:
        _mount_core_plugin(_RUNTIME)
        _CORE_BOOTSTRAPPED = True
    return _RUNTIME


def reset_harness_plugin_registry() -> None:
    """Test helper; production code should use plugin lifecycle methods."""
    global _RUNTIME, _CORE_BOOTSTRAPPED
    _RUNTIME = HarnessPluginRegistry()
    _CORE_BOOTSTRAPPED = False
