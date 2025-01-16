from liblaf import cherries


def default_plugins() -> list[cherries.Plugin]:
    return [cherries.plugin.PluginGit()]
