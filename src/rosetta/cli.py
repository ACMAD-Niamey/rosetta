"""Rosetta command-line interface."""
import subprocess
import sys
import click


@click.group()
def cli():
    """Rosetta — climate data integration CLI."""


@cli.group()
def cache():
    """Inspect and manage the local Nuthatch cache."""


@cache.command("list")
def cache_list():
    """List all cached Rosetta entries."""
    subprocess.run([sys.executable, "-m", "nuthatch", "list", "--namespace", "rosetta"],
                   check=False)


@cache.command("clear")
@click.option("--product", default=None,
              help="Rosetta product name to clear (e.g. nmme/cfsv2). Omit to clear all.")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def cache_clear(product, yes):
    """Remove cached Rosetta entries."""
    label = f"product '{product}'" if product else "ALL Rosetta cache entries"
    if not yes:
        click.confirm(f"This will delete {label}. Continue?", abort=True)
    cmd = [sys.executable, "-m", "nuthatch", "delete", "--namespace", "rosetta", "--force"]
    if product:
        cmd += ["--cache-key", product]
    subprocess.run(cmd, check=False)
