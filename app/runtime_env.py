"""Hosted configuration: API keys from SSM Parameter Store, chosen before the app starts.

When SSM_PARAMETER_PREFIX is set (the Lambda deployment), every SecureString under that prefix is
loaded into the process environment by its last path segment (…/ANTHROPIC_API_KEY ->
ANTHROPIC_API_KEY), without overriding variables already set. Values are never logged; only the
names that were loaded are. Locally nothing happens and keys come from .env as before.
"""

import logging
import os

log = logging.getLogger("pharmassist.app")


def load_ssm_secrets() -> list[str]:
    prefix = os.environ.get("SSM_PARAMETER_PREFIX")
    if not prefix:
        return []
    import boto3
    ssm = boto3.client("ssm")
    loaded, kw = [], {"Path": prefix.rstrip("/"), "WithDecryption": True, "Recursive": False}
    while True:
        page = ssm.get_parameters_by_path(**kw)
        for p in page["Parameters"]:
            name = p["Name"].rsplit("/", 1)[-1]
            if name not in os.environ:
                os.environ[name] = p["Value"]
                loaded.append(name)
        if not page.get("NextToken"):
            break
        kw["NextToken"] = page["NextToken"]
    log.info("loaded %d secrets from SSM: %s", len(loaded), ", ".join(sorted(loaded)))
    return loaded
