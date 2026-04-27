#!/usr/bin/env python3
"""Download NMME hindcast data from IRI Data Library and upload to S3.

Designed for resource-constrained EC2: downloads one init time at a time,
uploads to S3 immediately, then deletes the local file.

Prerequisites:
  - AWS CLI configured (aws s3 cp must work)
  - IRI Data Library auth configured in ~/.netrc or ~/.dodsrc:
      machine iridl.ldeo.columbia.edu
      login <your-email>
      password <your-password>
  - Python packages: xarray, netcdf4, numpy

Usage:
  python download_nmme_hindcasts.py [--bucket s3://acc.ord] [--models gemnemo,cesm1,canesm5,gem52nemo]
"""

import argparse
import os
import subprocess
import sys
import time

import numpy as np
import xarray as xr

MODELS = {
    "ccsm4": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.COLA-RSMAS-CCSM4/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "geoss2s": {
        # Use NASA-GEOSS2S/.HINDCAST (current GEOS-S2S model). The earlier
        # NASA-GMAO/.MONTHLY endpoint is a legacy version that no longer
        # matches what IRI serves — re-download required if old data exists.
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NASA-GEOSS2S/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "spear": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.GFDL-SPEAR/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "gemnemo": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.GEM-NEMO/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "cesm1": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NCAR-CESM1/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "canesm5": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.CanSIPS-IC4/.CanESM5/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
    "gem52nemo": {
        "base_url": "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.CanSIPS-IC4/.GEM5.2-NEMO/.HINDCAST/.MONTHLY",
        "variables": {
            "prec": {"canonical": "precip"},
            "tref": {"canonical": "temp", "squeeze_dims": ["Z"]},
        },
    },
}

ENCODING_OPTS = {"zlib": True, "complevel": 4}


def s3_key_exists(s3_path):
    """Check if an S3 object already exists (for resume support)."""
    result = subprocess.run(
        ["aws", "s3", "ls", s3_path],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def s3_upload(local_path, s3_path):
    subprocess.run(
        ["aws", "s3", "cp", local_path, s3_path, "--quiet"],
        check=True,
    )


def decode_init_time(s_val):
    """Convert IRI S coordinate (months since 1960-01-01) to YYYY-MM string."""
    ref_total = 1960 * 12  # Jan 1960
    total = ref_total + int(round(float(s_val)))
    year = total // 12
    month = total % 12 + 1
    return f"{year}-{month:02d}"


def download_model(model_name, model_cfg, bucket, tmp_dir):
    """Download all hindcast data for one model, one init at a time."""
    print(f"\n{'='*60}")
    print(f"  {model_name.upper()}")
    print(f"{'='*60}")

    # Open all variable endpoints lazily to get dimension info
    var_datasets = {}
    for native_var, var_cfg in model_cfg["variables"].items():
        url = f"{model_cfg['base_url']}/.{native_var}/dods"
        print(f"Opening {url} ...")
        try:
            ds = xr.open_dataset(url, decode_times=False)
            var_datasets[native_var] = (ds, var_cfg)
        except Exception as e:
            print(f"  ERROR opening {native_var}: {e}")
            return

    # Get init times from first variable
    first_ds = next(iter(var_datasets.values()))[0]
    s_values = first_ds.S.values
    n_inits = len(s_values)
    print(f"Found {n_inits} init times")

    uploaded = 0
    skipped = 0
    errors = 0

    for i, s_val in enumerate(s_values):
        init_label = decode_init_time(s_val)
        fname = f"{model_name}_{init_label}.nc"
        s3_path = f"{bucket}/nmme-hindcasts/{model_name}/{fname}"

        # Resume: skip if already uploaded
        if s3_key_exists(s3_path):
            skipped += 1
            if skipped <= 3 or skipped % 50 == 0:
                print(f"  [{i+1}/{n_inits}] skip {init_label} (exists)")
            continue

        local_path = os.path.join(tmp_dir, fname)
        try:
            # Download all variables for this init time
            merged = xr.Dataset()
            for native_var, (ds, var_cfg) in var_datasets.items():
                da = ds[native_var].sel(S=s_val).load()
                # Squeeze singleton dims (e.g., Z=1 for tref)
                for dim in var_cfg.get("squeeze_dims", []):
                    if dim in da.dims and da.sizes[dim] == 1:
                        da = da.squeeze(dim, drop=True)
                merged[var_cfg["canonical"]] = da

            # Save with compression
            encoding = {v: ENCODING_OPTS for v in merged.data_vars}
            merged.to_netcdf(local_path, encoding=encoding)

            # Upload and delete
            s3_upload(local_path, s3_path)
            uploaded += 1
            size_mb = os.path.getsize(local_path) / 1e6
            print(f"  [{i+1}/{n_inits}] {init_label} -> {size_mb:.1f} MB -> S3")

        except Exception as e:
            errors += 1
            print(f"  [{i+1}/{n_inits}] ERROR {init_label}: {e}")
            # Brief pause on error before continuing
            time.sleep(2)

        finally:
            if os.path.exists(local_path):
                os.unlink(local_path)

    # Close datasets
    for ds, _ in var_datasets.values():
        ds.close()

    print(f"\n  {model_name}: {uploaded} uploaded, {skipped} skipped, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Download NMME hindcasts from IRI to S3")
    parser.add_argument("--bucket", default="s3://acc.ord", help="S3 bucket (default: s3://acc.ord)")
    parser.add_argument("--models", default="gemnemo,cesm1,canesm5,gem52nemo",
                        help="Comma-separated model names (default: gemnemo,cesm1,canesm5,gem52nemo)")
    parser.add_argument("--tmp-dir", default="/tmp/nmme", help="Temp directory for downloads")
    args = parser.parse_args()

    os.makedirs(args.tmp_dir, exist_ok=True)

    model_names = [m.strip() for m in args.models.split(",")]
    for name in model_names:
        if name not in MODELS:
            print(f"Unknown model: {name}. Available: {', '.join(MODELS)}")
            sys.exit(1)

    print(f"Downloading NMME hindcasts to {args.bucket}")
    print(f"Models: {', '.join(model_names)}")
    print(f"Temp dir: {args.tmp_dir}")

    for name in model_names:
        download_model(name, MODELS[name], args.bucket, args.tmp_dir)

    print("\nDone!")


if __name__ == "__main__":
    main()
