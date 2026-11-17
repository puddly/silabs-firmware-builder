"""Tool to combine the GBLs of an app and its bootloader into one GBL."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import pathlib
import typing

from pygbl import FirmwareImage, GBL3Metadata, parse_firmware_image

from .build_project import CombinedManifest, Manifest
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


def combine(
    manifest: CombinedManifest, artifacts: pathlib.Path, output_dir: pathlib.Path
) -> None:
    """Combine the GBLs a combined manifest names, signed and encrypted like the app."""
    app_image, app_metadata = find_firmware(manifest.app, artifacts)
    bootloader_image, bootloader_metadata = find_firmware(
        manifest.bootloader, artifacts
    )

    # The app's metadata stays at the top level and the bootloader's is nested under
    # `bootloader`. Older clients parse every `manifest.json` entry as single-image
    # metadata: they need a top-level `fw_type`, exactly one top-level `*_version` key
    # besides `sdk_version`, and `metadata_version` no higher than 2.
    del bootloader_metadata["metadata_version"]
    metadata = {**app_metadata, "bootloader": bootloader_metadata}

    image = app_image.combine_bootloader_app(bootloader_image)
    image = dataclasses.replace(
        image,
        tags=[
            GBL3Metadata(metadata=json.dumps(metadata, sort_keys=True).encode("utf-8"))
            if isinstance(tag, GBL3Metadata)
            else tag
            for tag in image.tags
        ],
    ).regenerate_crc()

    # Program data in the app GBL is already compressed, so compressing again is a no-op
    gbl = finalize_gbl(
        image,
        compression=manifest.app.gbl.get("compression", None),
        encrypt_key_path=manifest.app.encryption_key_path,
        sign_key_path=manifest.app.signing_key_path,
    )

    output_path = output_dir / f"{manifest.output_stem(metadata)}.gbl"
    check_gbl_size(output_path.name, gbl, manifest.app.gbl.get("max_size", None))
    output_path.write_bytes(gbl)
    _LOGGER.info("Wrote %s", output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=pathlib.Path,
        help="Combined manifests",
    )
    parser.add_argument(
        "--artifacts",
        type=pathlib.Path,
        required=True,
        help="Directory containing the GBLs built from the app and bootloader manifests",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        required=True,
        help="Directory to write the combined GBLs to",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for path in args.manifests:
        combine(CombinedManifest.load(path), args.artifacts, args.output_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
