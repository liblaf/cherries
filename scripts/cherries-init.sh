#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"

PROJECT_NAME="$(basename "$git_root")"

if [[ -d ".dvc/" ]]; then
  # dvc init
  dvc config --project core.autostage true
  url="$(
    rbw get --field "uris" "DVC" |
      head --lines="1"
  )"
  url="${url/#http/webdav}"
  url="${url%%/}"
  url="${url}/$PROJECT_NAME/"
  dvc remote add --local --default "default" "$url"
  dvc remote modify --local "default" user "$(rbw get --field "username" "DVC")"
  dvc remote modify --local "default" password "$(rbw get --field "password" "DVC")"
fi
