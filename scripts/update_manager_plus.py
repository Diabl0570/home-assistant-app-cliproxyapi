import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "cliproxyapi/manager-plus.json"

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "home-assistant-cliproxy-updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

def parse(version):
    return tuple(map(int, version.removeprefix("v").split(".")))

def main():
    current = json.loads(MANIFEST.read_text())
    release = json.loads(fetch(f"https://api.github.com/repos/{current['repository']}/releases/latest"))
    version = release["tag_name"].removeprefix("v")
    if release["prerelease"] or release["draft"] or not re.fullmatch(r"1\.\d+\.\d+", version):
        raise SystemExit("Latest release requires manual review: only stable v1 updates are automatic")
    if parse(version) <= parse(current["version"]):
        return
    asset = f"cpa-manager-plus_v{version}_linux_amd64.tar.gz"
    assets = {item["name"]: item["browser_download_url"] for item in release["assets"]}
    if asset not in assets or "checksums.txt" not in assets or "release-info.json" not in assets:
        raise SystemExit("Release missing amd64 asset, official checksums or release info")
    info = json.loads(fetch(assets["release-info.json"]))
    update = info.get("update", {})
    minimum_upgrade = update.get("minimum_direct_upgrade_version")
    minimum_proxy = info.get("compatibility", {}).get("minimum_cpa_version")
    proxy = json.loads((ROOT / "cliproxyapi/updater.json").read_text())["version"]
    if (info.get("release", {}).get("stage") != "stable" or update.get("breaking") is not False
            or update.get("migration_required") is not False
            or (minimum_upgrade and parse(minimum_upgrade) > parse(current["version"]))
            or (minimum_proxy and parse(minimum_proxy) > parse(proxy))):
        raise SystemExit("Release is breaking, needs migration or a newer CLIProxyAPI: manual review required")
    checksums = fetch(assets["checksums.txt"]).decode()
    match = re.search(r"^([a-fA-F0-9]{64})\s+\*?(?:\./)?" + re.escape(asset) + r"$", checksums, re.M)
    if not match:
        raise SystemExit("Official checksum missing for amd64 asset")
    current.update(version=version, asset=asset, sha256=match[1].lower())
    MANIFEST.write_text(json.dumps(current, indent=2) + "\n")
    config = ROOT / "cliproxyapi/config.yaml"
    text = config.read_text()
    app = re.search(r'^version: "([^"\n]+)-(\d+)"$', text, re.M)
    app_version = f"{app[1]}-{int(app[2]) + 1}"
    config.write_text(text.replace(app[0], f'version: "{app_version}"'))
    changelog = ROOT / "cliproxyapi/CHANGELOG.md"
    changelog.write_text(f"# {app_version}\n\n- Update CPA Manager Plus to {version}; upstream checksum pinned.\n\n" + changelog.read_text())

if __name__ == "__main__":
    main()
