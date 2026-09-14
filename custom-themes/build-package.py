#!/usr/bin/env python3
"""Build standalone, reproducible Keycloak theme archives; Python standard library only."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent


def write_archive(path, files):
    # Keycloak 23 resolves resources/ itself through ClassLoader.getResource().
    # A ZIP containing only file entries renders templates but returns 404 for assets.
    directories = set()
    for name in files:
        parts = name.split("/")
        directories.update("/".join(parts[:index]) + "/" for index in range(1, len(parts)))
    entries = {**{name: b"" for name in directories}, **files}
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(entries.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o40755 << 16) | 0x10 if name.endswith("/") else 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content, compresslevel=9)
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Archive integrity check failed: {path}")
        if path.suffix == ".jar" and not archive.getinfo("theme/kub/login/resources/").is_dir():
            raise ValueError("JAR must include the resource root directory entry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("VERSION must contain a semantic version, such as 1.0.0")

    manifest = (ROOT / "META-INF/keycloak-themes.json").read_bytes()
    if json.loads(manifest) != {"themes": [{"name": "kub", "types": ["login"]}]}:
        raise ValueError("The archive must register only the kub login theme")

    theme = ROOT / "kub"
    files = {}
    allowed = {".ftl", ".properties", ".css", ".woff2", ".webp", ".ico", ".txt"}
    for path in sorted(theme.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not portable theme resources: {path}")
        if path.is_file():
            relative = path.relative_to(theme).as_posix()
            if path.suffix not in allowed or any(part.startswith(".") for part in Path(relative).parts):
                raise ValueError(f"Unexpected file in theme: {relative}")
            files[relative] = path.read_bytes()

    required = [
        "login/theme.properties", "login/login.ftl", "login/template.ftl",
        "login/messages/messages_uk.properties", "login/messages/messages_en.properties",
        "login/resources/css/kub.css", "login/resources/img/kub-logo-hq.webp",
        "login/resources/img/favicon.ico", "login/resources/fonts/OFL.txt",
    ] + [f"login/resources/fonts/ibm-plex-sans-{weight}.woff2" for weight in (400, 500, 600, 700)]
    for name in required:
        if not files.get(name):
            raise ValueError(f"Missing required resource: {name}")
    if files["login/messages/messages_uk.properties"] != files["login/messages/messages_en.properties"]:
        raise ValueError("The Ukrainian and fallback message bundles must be identical")
    for relative in re.findall(r'url\("([^"\)]+)"\)', files["login/resources/css/kub.css"].decode()):
        resource = (theme / "login/resources/css" / relative).resolve()
        if not resource.is_relative_to(theme.resolve()) or not resource.is_file():
            raise ValueError(f"CSS resource is not included in the theme: {relative}")

    jar_files = {f"theme/kub/{name}": content for name, content in files.items()}
    jar_files["META-INF/keycloak-themes.json"] = manifest
    jar_files["META-INF/MANIFEST.MF"] = (
        "Manifest-Version: 1.0\r\nImplementation-Title: KUB Login Theme\r\n"
        f"Implementation-Version: {version}\r\n\r\n"
    ).encode()
    for name in ("THIRD-PARTY-NOTICES.md", "licenses/Apache-2.0.txt"):
        jar_files[f"META-INF/{name}"] = (ROOT / name).read_bytes()

    prefix = f"kub-theme-{version}"
    zip_files = {f"{prefix}/kub/{name}": content for name, content in files.items()}
    for name in ("README.md", "INSTALL.md", "VERSION", "install.sh", "THIRD-PARTY-NOTICES.md", "licenses/Apache-2.0.txt"):
        zip_files[f"{prefix}/{name}"] = (ROOT / name).read_bytes()

    args.output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for extension, contents in (("jar", jar_files), ("zip", zip_files)):
        destination = args.output / f"{prefix}.{extension}"
        write_archive(destination, contents)
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        checksums.append(f"{checksum}  {destination.name}\n")
        print(f"Created {destination} ({destination.stat().st_size:,} bytes)")
    (args.output / "SHA256SUMS").write_text("".join(checksums))
    (args.output / "INSTALL.md").write_bytes((ROOT / "INSTALL.md").read_bytes())
    print(f"Verified {len(files)} theme resources; SHA256SUMS and INSTALL.md written")


if __name__ == "__main__":
    main()
