#!/usr/bin/env bash
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
release=$1
project=prj_ajWtZrwLFrkaogc8JlTN1337XuXn
team=team_UVOyq5riM1SM2zgg9g2tlzZN
scope=muratcagangogebakans-projects
production=https://soony-launch-control.vercel.app
cli=(vercel --scope "$scope" --token "$SOONY_VERCEL_CI_TOKEN")
check="$repo/.github/soony-vercel/verify.py"

cd "$release/deployment"
printf '{"projectId":"%s","orgId":"%s","projectName":"soony-launch-control"}\n' "$project" "$team" > .vercel/project.json

previous=$("${cli[@]}" api "/v13/deployments/soony-launch-control.vercel.app?teamId=$team" |
  jq -er '.id | select(startswith("dpl_"))')
result=$("${cli[@]}" deploy --yes --prebuilt --prod --skip-domain \
  --meta "soonySourceCommit=$GITHUB_SHA" --meta "soonyUiCommit=$GITHUB_SHA" \
  --meta soonySnapshotCommit=4de57a7 --meta soonyMode=protected-replay \
  --meta hostedAgentTrace=summary-only --meta supplierExamples=fictional)
id=$(jq -er '.deployment.id | select(startswith("dpl_"))' <<< "$result")
url=$(jq -er '.deployment.url' <<< "$result")

bypass=$(openssl rand -hex 32)
echo "::add-mask::$bypass"
revoke() {
  "${cli[@]}" project protection disable "$project" --protection-bypass \
    --protection-bypass-secret "$bypass" --yes >/dev/null
}
trap revoke EXIT
"${cli[@]}" project protection enable "$project" --protection-bypass \
  --protection-bypass-secret "$bypass" --yes >/dev/null
SOONY_TEST_BYPASS="$bypass" python "$check" "$url" --browser
revoke
trap - EXIT

"${cli[@]}" promote "$id" --yes
if ! python "$check" "$production"; then
  echo '::error::Production checks failed. Restoring the previous verified deployment.'
  "${cli[@]}" promote "$previous" --yes
  exit 1
fi
echo "Verified production deployment $id from $GITHUB_SHA."
