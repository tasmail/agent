"""Host-owned opt-in nginx policy settings shared by all native render paths."""

import re


def nginx_policy_options(config):
    options = {}
    for key in ("nginx_server_include", "nginx_backend_server_include"):
        value = config.get(key)
        if value is None or value == "":
            options[key] = None
        elif (
            not isinstance(value, str)
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+\.conf", value)
            or ".." in value.split("/")
        ):
            raise ValueError(f"{key} must be an absolute literal .conf path")
        else:
            options[key] = value
    for key in ("nginx_canonical_forwarding", "nginx_external_real_ip"):
        value = config.get(key, False)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        options[key] = value
    return options
