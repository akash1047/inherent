# CLI

Install the command-line client:

```bash
pip install inherent
```

Inspect the available options:

```console
$ inherent --help
Usage: inherent [OPTIONS] COMMAND [ARGS]...

Manage and query an Inherent agent memory stack.

Options:
  --json                 Write machine-readable JSON to stdout.
  --version              Show the CLI version.
  --install-completion   Install completion for the current shell.
  --show-completion      Show completion for the current shell.
  --help                 Show this message and exit.
```

Use `INHERENT_HOME` to move CLI state from its default `~/.inherent` directory.
Connection commands added after this scaffold prefer `INHERENT_URL` and
`INHERENT_API_KEY` over values stored in `config.toml`.
