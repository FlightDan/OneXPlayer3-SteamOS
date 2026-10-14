"""Human-readable bundle identity, separate from Valve's system identity."""


def render(bundle_release):
    return f"# {bundle_release['product']} Version\n\n{bundle_release['display_version']}\n"
