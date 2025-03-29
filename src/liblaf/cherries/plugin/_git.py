import git
import pydantic_settings as ps

from liblaf import cherries


class PluginGit(cherries.Plugin):
    model_config = ps.SettingsConfigDict(env_prefix=cherries.ENV_PREFIX + "GIT_")
    auto_commit: bool = False
    auto_commit_message: str = cherries.git.DEFAULT_COMMIT_MESSAGE

    def _pre_start(self) -> None:
        if self.auto_commit:
            cherries.git.commit(self.auto_commit_message)

    def _post_start(self, run: cherries.Experiment) -> None:
        r = git.Repo(search_parent_directories=True)
        sha: str = r.head.commit.hexsha
        run.log_other("cherries/git/sha", sha)
        if browse := cherries.git.permalink(repo=r):
            run.log_other("cherries/git/browse", browse)
        if entrypoint := cherries.git.permalink(repo=r, filepath=run.entrypoint):
            run.log_other("cherries/git/entrypoint", entrypoint)
