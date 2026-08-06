#!/usr/bin/env bash
#
# apply-lib.sh
#
# Shared machinery for the one-off scripts that apply a change to this
# repository. Source it; do not run it.
#
#     source scripts/apply-lib.sh
#     apply_parse_args "$@"
#     apply_preflight
#     apply_workspace packages/atlas-core
#     ...write files under "$APPLY_ROOT"...
#     apply_verify packages/atlas-core
#     apply_land "feat: something" "Why."
#
# The ordering is the point. Earlier scripts wrote into the repository, then
# verified, then committed. A failing verify therefore left a half-applied
# working tree and sometimes a branch pointing at nothing, and the retry was
# blocked by the debris of the attempt before it. Three cycles were lost to
# that in one day.
#
# Here every change is made to a scratch copy and verified there. The
# repository is not touched until the gates have passed, at which point the
# branch is created and the scratch tree is mirrored back in one step. A
# failure leaves the working tree exactly as it was found.

APPLY_BRANCH=""
APPLY_DRY_RUN=0
APPLY_ALLOW_MAIN=0
APPLY_ROOT=""
APPLY_TREES=()
APPLY_PY=""
APPLY_LANDED=0

apply_step() { echo "==> $*"; }
apply_note() { echo "    $*"; }
apply_die() { echo "error: $*" >&2; exit 1; }

apply_parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) APPLY_DRY_RUN=1 ;;
      --branch)
        APPLY_BRANCH="${2:-}"
        [ -n "$APPLY_BRANCH" ] || apply_die "--branch needs a name"
        shift
        ;;
      --allow-main) APPLY_ALLOW_MAIN=1 ;;
      *) apply_die "unknown argument: $1" ;;
    esac
    shift
  done
}

apply_cleanup() {
  local status=$?
  if [ -n "$APPLY_ROOT" ] && [ -d "$APPLY_ROOT" ]; then
    rm -rf "$APPLY_ROOT"
  fi
  if [ "$status" -ne 0 ]; then
    echo "" >&2
    if [ "$APPLY_LANDED" -eq 0 ]; then
      echo "FAILED before touching the repository." >&2
      echo "The working tree is as you left it; nothing to undo." >&2
    else
      echo "FAILED after landing the change. Inspect with:" >&2
      echo "  git log --oneline -3 && git status --short" >&2
    fi
  fi
}

apply_python() {
  local candidate
  for candidate in py python python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c "import sys" >/dev/null 2>&1; then
      APPLY_PY="$candidate"
      return 0
    fi
  done
  apply_die "no working python found"
}

apply_preflight() {
  apply_step "Preflight"

  git rev-parse --git-dir >/dev/null 2>&1 || apply_die "not a git repository"

  local current
  current="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$APPLY_DRY_RUN" -eq 0 ] && [ -z "$APPLY_BRANCH" ] &&
     [ "$current" = "main" ] && [ "$APPLY_ALLOW_MAIN" -eq 0 ]; then
    apply_die "refusing to commit to main; pass --branch NAME, or --allow-main"
  fi

  local dirty
  dirty="$(git status --porcelain | grep -v -E '(apply|repair|fix)-.*\.sh$' || true)"
  if [ -n "$dirty" ]; then
    echo "working tree is dirty:" >&2
    echo "$dirty" >&2
    exit 1
  fi

  if [ -n "$APPLY_BRANCH" ] && [ "$APPLY_DRY_RUN" -eq 0 ] &&
     git show-ref --verify --quiet "refs/heads/$APPLY_BRANCH"; then
    apply_die "branch $APPLY_BRANCH already exists; delete it or choose another"
  fi

  apply_python
  apply_note "using $APPLY_PY"
}

apply_workspace() {
  [ $# -gt 0 ] || apply_die "apply_workspace needs at least one tree"
  APPLY_TREES=("$@")

  APPLY_ROOT="$(mktemp -d)"
  trap apply_cleanup EXIT

  # Tracked files only. Copying the working tree wholesale drags in
  # __pycache__ and coverage data, which then get committed by git add -A in
  # a repository that has not ignored them.
  # A path may not exist yet: a change that creates a file names it here so
  # the file is written, verified, and landed like any other.
  local tree existing=()
  for tree in "${APPLY_TREES[@]}"; do
    [ -e "$tree" ] && existing+=("$tree")
  done

  local file
  if [ ${#existing[@]} -gt 0 ]; then
    while IFS= read -r -d '' file; do
      mkdir -p "$APPLY_ROOT/$(dirname "$file")"
      cp "$file" "$APPLY_ROOT/$file"
    done < <(git ls-files -z -- "${existing[@]}")
  fi

  apply_note "working in a scratch copy of: ${APPLY_TREES[*]}"
}

apply_normalize() {
  if command -v ruff >/dev/null 2>&1; then
    local tree
    for tree in "${APPLY_TREES[@]}"; do
      ruff check --fix -q "$APPLY_ROOT/$tree" 2>/dev/null || true
      ruff format -q "$APPLY_ROOT/$tree" 2>/dev/null || true
    done
    apply_note "normalized with the repository ruff configuration"
  else
    apply_note "ruff not on PATH, skipping normalization"
  fi
}

apply_verify() {
  local package="$1"

  apply_step "Verify"
  ( cd "$APPLY_ROOT/$package" && "$APPLY_PY" -m pytest -q )

  if command -v ruff >/dev/null 2>&1; then
    local tree
    for tree in "${APPLY_TREES[@]}"; do
      ruff check --no-cache "$APPLY_ROOT/$tree" >/dev/null
      ruff format --check --no-cache "$APPLY_ROOT/$tree" >/dev/null
    done
    apply_note "ruff check and format clean"
  fi

  if command -v mypy >/dev/null 2>&1; then
    local module
    module="$(basename "$package" | tr '-' '_')"
    if [ -d "$APPLY_ROOT/$package/src/$module" ]; then
      ( cd "$APPLY_ROOT/$package" &&
        MYPYPATH=src mypy --strict "src/$module" >/dev/null ) &&
        apply_note "mypy strict clean"
    fi
  fi
}

apply_land() {
  local subject="$1"
  local body="$2"

  if [ "$APPLY_DRY_RUN" -eq 1 ]; then
    apply_step "Done (dry run: verified in scratch, repository untouched)"
    exit 0
  fi

  apply_step "Landing"

  if [ -n "$APPLY_BRANCH" ]; then
    git checkout -q main
    git pull --ff-only
    git checkout -qb "$APPLY_BRANCH"
  fi

  # Copy the scratch tree over the real one, then remove the tracked files it
  # no longer contains. Deleting the directory first would be simpler and
  # would also destroy a developer's untracked files, which are none of this
  # script's business.
  local tree file existing=()
  for tree in "${APPLY_TREES[@]}"; do
    if [ -d "$APPLY_ROOT/$tree" ]; then
      mkdir -p "$tree"
      cp -r "$APPLY_ROOT/$tree/." "$tree/"
    elif [ -f "$APPLY_ROOT/$tree" ]; then
      mkdir -p "$(dirname "$tree")"
      cp "$APPLY_ROOT/$tree" "$tree"
    else
      apply_die "the change produced nothing at $tree"
    fi
    [ -e "$tree" ] && existing+=("$tree")
  done
  APPLY_LANDED=1

  if [ ${#existing[@]} -gt 0 ]; then
    while IFS= read -r -d '' file; do
      [ -e "$APPLY_ROOT/$file" ] || rm -f "$file"
    done < <(git ls-files -z -- "${existing[@]}")
  fi

  git add -A "${APPLY_TREES[@]}"

  if git diff --cached --quiet; then
    apply_note "nothing changed; no commit made"
    return 0
  fi

  git commit -q -m "$subject" -m "$body"
  apply_note "committed: $subject"

  trap - EXIT
  rm -rf "$APPLY_ROOT"

  apply_step "Done"
  apply_note "next: ./scripts/ship.sh ${APPLY_BRANCH:-<branch>}"
}
