#!/bin/zsh
# Builds llama.xcframework (with mtmd, the audio in/out library) for a real iPhone.
# Needs full Xcode (not just Command Line Tools). Run from anywhere.
set -euo pipefail
HERE="${0:A:h}/.."
cd "$HERE/vendor/llama.cpp"
# Real device only: skips the simulator, macOS, visionOS and tvOS slices to save time and disk.
./build-xcframework.sh ios-device
mkdir -p "$HERE/Frameworks"
rm -rf "$HERE/Frameworks/llama.xcframework"
cp -R build-apple/llama.xcframework "$HERE/Frameworks/"
echo "Built: $HERE/Frameworks/llama.xcframework"
