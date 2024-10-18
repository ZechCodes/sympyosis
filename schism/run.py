import os
import sys
from importlib import import_module

from schism.controllers import activate, SchismController, start


def launch_services(services: set[str]):
    controller = setup_controller(services)
    setup_entry_points(controller)
    controller.launch()


def setup_controller(services: set[str]) -> SchismController:
    controller = activate(services)
    controller.bootstrap()
    return controller


def setup_entry_points(controller: SchismController):
    for name, entry_point in controller.entry_points.items():
        globals()[name] = entry_point


def start_application(module_path: str, entry_point_name: str):
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as e:
        raise RuntimeError(f"The specified entrypoint module {module_path!r} could not be found.") from e

    try:
        entry_point_callback = getattr(module, entry_point_name)
    except AttributeError as e:
        raise RuntimeError(f"The specified entrypoint callback {entry_point_name!r} could not be found in the {module_path!r} module.") from e

    start(entry_point_callback())


def main():
    match sys.argv[1:]:
        case ("run", "services", *services) if len(services) > 0:
            launch_services({
                service.strip()
                for service in sys.argv[3:]
                if service.strip()
            })

        case ("run", entry_point) if "." in entry_point:
            start_application(*entry_point.rsplit(".", 1))

        case _ if "SCHISM_ACTIVE_SERVICES" in os.environ:
            launch_services({
                service.strip()
                for service in os.environ["SCHISM_ACTIVE_SERVICES"].split(",")
                if service.strip()
            })

        case _:
            print("""Welcome to Schism!

Schism is a simple service autowiring framework for Python. It allows you to write service oriented applications that
can also be easily be run as monoliths.

Usage:
    schism run services <service>...    - Run the specified services
    schism run <module>.<entry_point>   - Run the specified entry point""")


main()
