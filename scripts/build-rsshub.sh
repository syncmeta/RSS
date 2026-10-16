#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir="$root/.rsshub-build"
if [ -e "$build_dir" ]; then
    echo 'Build directory already exists; move it aside before rebuilding.' >&2
    exit 1
fi
git clone --no-checkout https://github.com/DIYgod/RSSHub.git "$build_dir"
git -C "$build_dir" checkout --detach bc785f8157fbec6e6f9ec18ff76be7e6477511b7
git -C "$build_dir" apply --check "$root/deploy/rsshub-custom-routes/fork-vs-upstream.patch"
git -C "$build_dir" apply "$root/deploy/rsshub-custom-routes/fork-vs-upstream.patch"
for route in caixin cugb nytimes; do
    mkdir -p "$build_dir/lib/routes/$route"
    cp -R "$root/deploy/rsshub-custom-routes/$route/." "$build_dir/lib/routes/$route/"
done
mkdir -p "$build_dir/lib/routes/truthsocial"
cp -R "$root/lib/routes/truthsocial/." "$build_dir/lib/routes/truthsocial/"
docker build -t rsshub-custom:local "$build_dir"
