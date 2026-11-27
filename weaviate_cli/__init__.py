from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("weaviate-cli")
except PackageNotFoundError:
    __version__ = "unknown version"
