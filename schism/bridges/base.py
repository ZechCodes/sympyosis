from abc import ABC, abstractmethod
from typing import Type, TYPE_CHECKING

if TYPE_CHECKING:
    from schism.services import Service


class BridgeClient:
    ...


class BridgeServer:
    ...


class BaseBridge(ABC):
    @classmethod
    @abstractmethod
    def create_client(cls, service_type: "Type[Service]") -> BridgeClient:
        ...

    @classmethod
    @abstractmethod
    def create_server(cls, service_type: "Type[Service]") -> BridgeServer:
        ...