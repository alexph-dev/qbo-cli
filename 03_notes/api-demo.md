# QBO CLI API Demo

*2026-03-17T06:33:32Z by Showboat 0.6.1*
<!-- showboat-id: 7fb95a22-33b2-48fd-a395-bc6e3e9368a2 -->

Goal: document and smoke-test the QBO CLI API surface without live QuickBooks credentials. The demo uses `uv run --no-sync` so recorded outputs stay stable for verification.

```bash
uv run --no-sync qbo --help
```

```output
usage: qbo [-h] [--version] [--format {text,json,tsv}] [--sandbox]
           {auth,query,search,get,create,update,delete,report,raw,gl-report} ...

QuickBooks Online CLI — query, create, update, delete entities and run
reports.

positional arguments:
  {auth,query,search,get,create,update,delete,report,raw,gl-report}
    auth                Authentication commands
    query               Run a QBO query (SQL-like)
    search              Run query, then text-search rows locally
    get                 Get a single entity by ID
    create              Create an entity (JSON on stdin)
    update              Update an entity (JSON on stdin)
    delete              Delete an entity by ID
    report              Run a QBO report
    raw                 Make a raw API request
    gl-report           Hierarchical General Ledger report by account &
                        customer

options:
  -h, --help            show this help message and exit
  --version, -V         show program's version number and exit
  --format, -f {text,json,tsv}
                        Output format (default: text)
  --sandbox             Use sandbox API endpoint
```

The main entrypoint exposes auth, CRUD, reports, raw HTTP access, and the GL report helper. For API-oriented usage, `raw` is the narrowest interface.

```bash
uv run --no-sync qbo raw --help
```

```output
usage: qbo raw [-h] [-o {text,json,tsv}] method path

positional arguments:
  method                HTTP method (GET, POST, PUT, DELETE)
  path                  API path after /v3/company/{realm}/

options:
  -h, --help            show this help message and exit
  -o, --output, --format {text,json,tsv}
                        Output format: text (default), json, tsv
```

Live example from the README once credentials are configured:

`qbo raw GET "query?query=SELECT * FROM CompanyInfo"`

For POST or PUT, the CLI reads JSON from stdin.

