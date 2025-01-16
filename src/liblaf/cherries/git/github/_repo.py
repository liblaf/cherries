import re

import git

GITHUB_URL_PATTERNS: list[str] = [
    r"https://github\.com/(?P<user>[^/]+)/(?P<repo>[^/]+)(?:\.git)?"
]


def user_repo(
    repo: git.Repo | None = None,
) -> tuple[str, str] | tuple[None, None]:
    if repo is None:
        repo = git.Repo(search_parent_directories=True)
    remote: git.Remote = repo.remote()
    for pattern in GITHUB_URL_PATTERNS:
        match: re.Match[str] | None = re.match(pattern, remote.url)
        if not match:
            continue
        user: str = match.group("user")
        repo_name: str = match.group("repo")
        return user, repo_name
    return None, None
