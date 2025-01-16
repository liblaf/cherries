from liblaf import cherries


def default_plugins() -> list[cherries.Plugin]:
    return [cherries.plugin.PluginLogging(), cherries.plugin.PluginGit()]
