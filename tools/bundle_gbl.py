"""Tool to combine the GBLs of an app and its bootloader into one GBL."""

from __future__ import annotations

import argparse
import logging
import pathlib
import typing

from pygbl import FirmwareImage, parse_firmware_image

from .build_project import BUNDLE_MANIFEST_SUFFIX, Manifest, yaml
from .create_gbl import check_gbl_size, finalize_gbl
from .create_manifest import find_manifest, unlock

_LOGGER = logging.getLogger(__name__)


def find_firmware(
    manifest: Manifest, artifacts: pathlib.Path
) -> tuple[FirmwareImage, dict[str, typing.Any]]:
    """Find the one GBL a manifest built, returning it decrypted with its metadata."""
    matches = []

    for path in sorted(artifacts.glob("*.gbl")):
        firmware = parse_firmware_image(path.read_bytes())
        match = find_manifest([manifest], firmware, path.stem)

        if match is not None:
            matches.append((path, firmware, match[1]))

    ((path, firmware, metadata),) = matches
    _LOGGER.info("Using %s for %s", path, manifest.path)

    return unlock(manifest, firmware), metadata


def bundle(
    bundle_path: pathlib.Path, artifacts: pathlib.Path, output_dir: pathlib.Path
) -> None:
    """Combine the GBLs a bundle manifest names, signed and encrypted like the app."""
    config = yaml.load(bundle_path.read_text())
    app = Manifest.load(bundle_path.parent / config["app"])
    bootloader = Manifest.load(bundle_path.parent / config["bootloader"])

    app_image, app_metadata = find_firmware(app, artifacts)
    bootloader_image, bootloader_metadata = find_firmware(bootloader, artifacts)

    # Program data in the app GBL is already compressed, so compressing again is a no-op
    gbl = finalize_gbl(
        app_image.combine_bootloader_app(bootloader_image),
        compression=app.gbl.get("compression", None),
        encrypt_key_path=app.encryption_key_path,
        sign_key_path=app.signing_key_path,
    )

    name = (
        f"{app.output_stem(app_metadata)}{BUNDLE_MANIFEST_SUFFIX}"
        f"_{bootloader_metadata[bootloader.version_key]}.gbl"
    )
    check_gbl_size(name, gbl, app.gbl.get("max_size", None))
    (output_dir / name).write_bytes(gbl)
    _LOGGER.info("Wrote %s", output_dir / name)


def main() -> None:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "bundles",
        nargs="*",
        type=pathlib.Path,
        help=f"Bundle manifests, named `*{BUNDLE_MANIFEST_SUFFIX}.yaml`",
    )
    parser.add_argument(
        "--artifacts",
        type=pathlib.Path,
        required=True,
        help="Directory containing the GBLs built from the bundled manifests",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        required=True,
        help="Directory to write the combined GBLs to",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for bundle_path in args.bundles:
        bundle(bundle_path, args.artifacts, args.output_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
