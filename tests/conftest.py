import pytest


def pytest_addoption(parser):
    parser.addoption("--api", action="store")
    parser.addoption("--secret", action="store")
