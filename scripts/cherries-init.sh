#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"

PROJECT_NAME="$(basename "$git_root")"

if [[ ! -d ".dvc/" ]]; then
  dvc init
fi
dvc config --project core.autostage true
if ! dvc remote default; then
  url="$(
    rbw get --field "uris" "DVC" |
      head --lines="1"
  )"
  url="${url/#http/webdav}"
  url="${url%%/}/$PROJECT_NAME/"
  dvc remote add --local --default --force "default" "$url"
  dvc remote modify --local "default" user "$(rbw get --field "username" "DVC")"
  dvc remote modify --local "default" password "$(rbw get --field "password" "DVC")"
fi

rclone mkdir "dvc:/$PROJECT_NAME/"
