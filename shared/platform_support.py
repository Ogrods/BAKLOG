import sys


def current_platform():
    return sys.platform


def platform_supported(platforms):
    if not platforms:
        return True
    return sys.platform in tuple(platforms)
