import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "cliproxyapi/updater.json"

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "home-assistant-cliproxy-updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

def main():
    current = json.loads(MANIFEST.read_text())
    release = json.loads(fetch(f"https://api.github.com/repos/{current['repository']}/releases/latest"))
    version = release["tag_name"].removeprefix("v")
    if release["prerelease"] or release["draft"] or not re.fullmatch(r"8\.\d+\.\d+", version):
        raise SystemExit("Latest release requires manual review: only stable v8 updates are automatic")
    if tuple(map(int, version.split("."))) <= tuple(map(int, current["version"].split("."))):
        return
    asset = f"CLIProxyAPI_{version}_linux_amd64.tar.gz"
    assets = {item["name"]: item["browser_download_url"] for item in release["assets"]}
    if asset not in assets:
        raise SystemExit("Release missing amd64 asset")
    checksum_asset = next((name for name in assets if name.endswith("checksums.txt")), None)
    if checksum_asset is None:
        raise SystemExit("Release missing official checksums")
    checksums = fetch(assets[checksum_asset]).decode()
    match = re.search(r"^([a-fA-F0-9]{64})\s+\*?" + re.escape(asset) + r"$", checksums, re.M)
    if not match:
        raise SystemExit("Official checksum missing for amd64 asset")
    current.update(version=version, asset=asset, sha256=match[1].lower())
    MANIFEST.write_text(json.dumps(current, indent=2) + "\n")
    config = ROOT / "cliproxyapi/config.yaml"
    config.write_text(re.sub(r'^version: "[^"\n]+"$', f'version: "{version}-1"', config.read_text(), flags=re.M))
    changelog = ROOT / "cliproxyapi/CHANGELOG.md"
    changelog.write_text(f"# {version}-1\n\n- Update CLIProxyAPI to {version}; upstream checksum pinned.\n\n" + changelog.read_text())

if __name__ == "__main__":
    main()
