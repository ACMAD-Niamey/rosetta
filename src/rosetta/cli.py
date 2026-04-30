"""Rosetta command-line interface."""
import click
from nuthatch.cli import cli as nuthatch_cli


@click.group()
def cli():
    """Rosetta — climate data integration CLI."""


@cli.group()
def cache():
    """Inspect and manage the local Nuthatch cache."""


@cache.command("list")
@click.option("--namespace", default=None, help="Filter by namespace prefix (e.g. rosetta/cds)")
def cache_list(namespace):
    """List cached entries with sizes."""
    from click.testing import CliRunner
    runner = CliRunner()
    args = ["list"]
    if namespace:
        args += ["--namespace", namespace]
    result = runner.invoke(nuthatch_cli, args, catch_exceptions=False)
    click.echo(result.output)


@cache.command("clear")
@click.option("--product", required=True, help="Rosetta product name (e.g. nmme/cfsv2)")
def cache_clear(product):
    """Remove cached entries for a specific product."""
    namespace = f"rosetta/{product.split('/')[0]}"
    click.echo(f"Clearing cache for product={product} (namespace={namespace})")
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(nuthatch_cli, ["delete", "--namespace", namespace],
                           catch_exceptions=False)
    click.echo(result.output)
