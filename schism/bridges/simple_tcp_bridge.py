import asyncio
import hashlib
import os
import pickle
from functools import lru_cache, partial
from typing import Type, TYPE_CHECKING

from bevy import get_repository
from pydantic import BaseModel

from .base import BaseBridge, BridgeClient, BridgeServer, RemoteError
from .bridge_helpers import ResponseBuilder
from schism.configs import SchismConfigModel
from schism.controllers import get_controller

if TYPE_CHECKING:
    from schism.services import Service


def _generate_signature(data: bytes) -> bytes:
    return hashlib.sha256(data + SimpleTCPBridge.SECRET_KEY).hexdigest().encode()


class RequestPayload(BaseModel):
    method: str
    args: tuple
    kwargs: dict


class SimpleTCPConfig(SchismConfigModel, lax=True):
    serve_on: str
    client: str


class SimpleTCPClient(BridgeClient):
    config: SimpleTCPConfig

    @property
    @lru_cache
    def host(self) -> str:
        return (
            self.config.client
            if self.config.client
            else self.config.serve_on
        ).split(":")[0]

    @property
    def port(self) -> int:
        return int(
            (
                self.config.client
                if self.config.client
                else self.config.serve_on
            ).split(":")[1]
        )

    def __getattr__(self, item):
        return partial(self.__make_request, item)

    async def __make_request(self, method, *args, **kwargs):
        request = RequestPayload(method=method, args=args, kwargs=kwargs)
        data = pickle.dumps(request)
        signature = _generate_signature(data)
        payload = signature + data
        length = len(payload)

        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except OSError as e:
            raise RuntimeError(
                f"Unable to connect to {self.service.__module__}.{self.service.__qualname__} service on {self.host}:{self.port}"
            ) from e

        writer.write(length.to_bytes(4) + payload)
        await writer.drain()

        length_bytes = await reader.read(4)
        length = int.from_bytes(length_bytes)
        payload = await reader.read(length)
        signature, data = payload[:64], payload[64:]
        if signature != _generate_signature(data):
            raise ValueError(
                f"Received an invalid signature from the service {self.service.__module__}.{self.service.__name__}"
            )

        response = pickle.loads(data)
        if response["status"] == "error":
            remote_error = (
                f"\n"
                f"{''.join(response['data']['traceback'])}\n"
                f"---------------------------------------------\n"
                f"The above stacktrace is from a remote service\n"
                f"---------------------------------------------"
            )
            error = response["data"]["error"]
            raise error from RemoteError(remote_error)

        return response["data"]


class SimpleTCPServer(BridgeServer):
    config: SimpleTCPConfig

    @property
    @lru_cache
    def host(self) -> str:
        return self.config.serve_on.split(":")[0]

    @property
    @lru_cache
    def port(self) -> int:
        return int(self.config.serve_on.split(":")[1])

    async def launch(self):
        server = await asyncio.start_server(self._handle_request, self.host, self.port)

        async with server:
            await server.serve_forever()

    async def _handle_request(self, reader, writer):
        with ResponseBuilder() as result:
            length_bytes = await reader.read(4)
            length = int.from_bytes(length_bytes)

            payload = await reader.read(length)
            signature, data = payload[:64], payload[64:]
            if signature != _generate_signature(data):
                raise ValueError("Invalid signature")

            else:
                request: RequestPayload = pickle.loads(data)
                service = get_repository().get(self.service)
                method = getattr(service, request.method)
                result.set(await method(*request.args, **request.kwargs))

        response = pickle.dumps(result.to_dict())
        signature = _generate_signature(response)
        length = len(response) + len(signature)
        writer.write(length.to_bytes(4) + signature + response)

        await writer.drain()
        writer.close()


class SimpleTCPBridge(BaseBridge):
    SECRET_KEY = os.environ.get("SCHISM_TCP_BRIDGE_SECRET", "").encode()

    @classmethod
    def create_client(cls, service_type: "Type[Service]", config: SimpleTCPConfig):
        return SimpleTCPClient(service_type, config)

    @classmethod
    def create_server(cls, service_type: "Type[Service]", config: SimpleTCPConfig):
        server = SimpleTCPServer(service_type, config)
        get_controller().add_launch_task(server.launch())
        return server

    @classmethod
    def config_factory(cls, bridge_config: str | dict[str, str | int]) -> SimpleTCPConfig:
        match bridge_config:
            case str() as serve_on:
                return SimpleTCPConfig(serve_on=serve_on, client=serve_on)

            case {"serve_on": str() as serve_on, "client": str() as client}:
                return SimpleTCPConfig(serve_on=serve_on, client=client)

            case {"serve_on": str() as serve_on}:
                return SimpleTCPConfig(serve_on=serve_on, client=serve_on)

            case _:
                raise ValueError(f"Invalid bridge configuration for {cls.__name__}: {bridge_config}")
