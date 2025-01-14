"""
A simple dependency injection framework
"""
import contextlib
import dataclasses
import functools
import inspect
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

try:
    from typing_extensions import GenericMeta  # type: ignore
except ImportError:
    GenericMeta = type

if TYPE_CHECKING:
    GenericMeta = type


class _SentinelClass:
    pass


sentinel = _SentinelClass()


class ProviderMeta(GenericMeta):  # type: ignore
    def __new__(
        mcs,
        class_name: str,
        bases: Tuple[type],
        attrs: Dict[str, Any],
        state_fields: Tuple[str, ...] = (),
        **kwargs: Any
    ) -> "ProviderMeta":
        state_fields_key = "STATE_FIELDS"
        all_state_fields = set(state_fields)
        for base in bases:
            state_fields_ = getattr(
                base, state_fields_key, ()
            )  # this class property is retained for compatibility with the old code
            all_state_fields.update(state_fields_)
        all_state_fields.update(attrs.pop(state_fields_key, ()))
        attrs[state_fields_key] = tuple(all_state_fields)
        cls: "ProviderMeta" = super(ProviderMeta, mcs).__new__(
            mcs, class_name, bases, attrs, **kwargs
        )
        return cls


VT = TypeVar("VT")


class Provider(Generic[VT], metaclass=ProviderMeta):
    """
    the base class for Provider implementations. Could be used as the type annotations
    of all the implementations.
    """

    STATE_FIELDS: Tuple[str, ...] = ("_override",)

    def __init__(self) -> None:
        self._override: Union[_SentinelClass, VT] = sentinel

    def _provide(self) -> VT:
        raise NotImplementedError

    def set(self, value: Union[_SentinelClass, VT]) -> None:
        """
        set the value to this provider, overriding the original values
        """
        if isinstance(value, _SentinelClass):
            return
        self._override = value

    @contextlib.contextmanager
    def patch(self, value: Union[_SentinelClass, VT]) -> Generator[None, None, None]:
        """
        patch the value of this provider, restoring the original value after the context
        """
        if isinstance(value, _SentinelClass):
            yield
            return
        original = self._override
        self._override = value
        yield
        self._override = original

    def get(self) -> VT:
        """
        get the value of this provider
        """
        if not isinstance(self._override, _SentinelClass):
            return self._override
        return self._provide()

    def reset(self) -> None:
        """
        remove the overriding and restore the original value
        """
        self._override = sentinel

    def __getstate__(self) -> Dict[str, Any]:
        return {f: getattr(self, f) for f in self.STATE_FIELDS}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        for i in self.STATE_FIELDS:
            setattr(self, i, state[i])


class _ProvideClass:
    """
    used as the default value of a injected functool/method. Would be replaced by the
    final value of the provider when this function/method gets called.
    """

    def __getitem__(self, provider: Provider[VT]) -> VT:
        return provider  # type: ignore


Provide = _ProvideClass()


def _inject_args(
    args: Tuple[Union[Provider[VT], Any], ...]
) -> Tuple[Union[VT, Any], ...]:
    return tuple(a.get() if isinstance(a, Provider) else a for a in args)


def _inject_kwargs(
    kwargs: Dict[str, Union[Provider[VT], Any]]
) -> Dict[str, Union[VT, Any]]:
    return {k: v.get() if isinstance(v, Provider) else v for k, v in kwargs.items()}


WrappedCallable = TypeVar("WrappedCallable", bound=Callable[..., Any])


def _inject(func: WrappedCallable, squeeze_none: bool) -> WrappedCallable:
    if getattr(func, "_is_injected", False):
        return func

    sig = inspect.signature(func)

    @functools.wraps(func)
    def _(
        *args: Optional[Union[Any, _SentinelClass]],
        **kwargs: Optional[Union[Any, _SentinelClass]]
    ) -> Any:
        if not squeeze_none:
            filtered_args = tuple(a for a in args if not isinstance(a, _SentinelClass))
            filtered_kwargs = {
                k: v for k, v in kwargs.items() if not isinstance(v, _SentinelClass)
            }
        else:
            filtered_args = tuple(a for a in args if a is not None)
            filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}

        bind = sig.bind_partial(*filtered_args, **filtered_kwargs)
        bind.apply_defaults()

        return func(*_inject_args(bind.args), **_inject_kwargs(bind.kwargs))

    setattr(_, "_is_injected", True)
    return cast(WrappedCallable, _)


@overload
def inject(func: WrappedCallable, squeeze_none: bool = False) -> WrappedCallable:
    ...


@overload
def inject(
    func: None = None, squeeze_none: bool = False
) -> Callable[[WrappedCallable], WrappedCallable]:
    ...


def inject(
    func: Optional[WrappedCallable] = None, squeeze_none: bool = False
) -> Union[WrappedCallable, Callable[[WrappedCallable], WrappedCallable]]:
    """
    used with `Provide`, inject values to provided defaults of the decorated
    function/method when gets called.
    """
    if func is None:
        wrapper = functools.partial(_inject, squeeze_none=squeeze_none)
        return cast(Callable[[WrappedCallable], WrappedCallable], wrapper)

    if callable(func):
        return _inject(func, squeeze_none=squeeze_none)

    raise ValueError("You must pass either None or Callable")


def sync_container(from_: Any, to_: Any) -> None:
    """
    sync container states from `from_` to `to_`
    """
    for field in dataclasses.fields(to_):
        src = field.default
        target = getattr(from_, field.name, None)
        if target is None:
            continue
        if isinstance(src, Provider):
            src.__setstate__(target.__getstate__())
        elif dataclasses.is_dataclass(src):
            sync_container(src, target)


container = dataclasses.dataclass(frozen=True)


skip = not_passed = sentinel

__all__ = [
    "container",
    "Provider",
    "Provide",
    "inject",
    "not_passed",
    "skip",
    "sync_container",
]
