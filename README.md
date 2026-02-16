# qbo-cli

A command-line interface for the QuickBooks Online API. Query entities, run reports, create invoices — all from your terminal.

## Features

- **OAuth 2.0 authentication** with local callback server or manual mode
- **Query** entities using QBO's SQL-like syntax with automatic pagination
- **CRUD operations** on any QBO entity (Customer, Invoice, Bill, etc.)
- **Financial reports** — P&L, Balance Sheet, Cash Flow, and more
- **Raw API access** for anything the CLI doesn't cover
- **Auto token refresh** — access tokens refresh transparently
- **TSV and JSON output** — pipe to `jq`, `awk`, spreadsheets
- **Sandbox support** for development and testing
- **File-locked token storage** — safe for concurrent use

## Installation

```bash
pip install qbo-cli
```

Requires Python 3.9+.

## Setup

### 1. Create an Intuit Developer App

Go to [developer.intuit.com](https://developer.intuit.com), create an app, and note your **Client ID** and **Client Secret**.

Add a **Redirect URI** in your app's settings. For production apps, Intuit requires HTTPS with a real domain (e.g., `https://yourapp.example.com/callback`). For development, `https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl` works. Set `QBO_REDIRECT_URI` to match.

> **Tip:** If you're running on a headless server, use `qbo auth init --manual` — the redirect doesn't need to resolve. You'll just copy the URL from your browser's address bar after authorization.

### 2. Configure Credentials

**Option A: Environment variables** (recommended for CI/scripts)

```bash
export QBO_CLIENT_ID="your-client-id"
export QBO_CLIENT_SECRET="your-client-secret"
```

**Option B: Config file** (`~/.qbo/config.json`)

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}
```

Environment variables take precedence over the config file.

### 3. Authorize

```bash
qbo auth init
```

This opens an OAuth flow — authorize in your browser, and tokens are saved to `~/.qbo/tokens.json` (chmod 600).

On headless servers, use manual mode:

```bash
qbo auth init --manual
```

## Usage

### Check auth status

```bash
qbo auth status
```

### Query entities

```bash
# All customers
qbo query "SELECT * FROM Customer"

# Recent invoices
qbo query "SELECT * FROM Invoice WHERE TxnDate > '2025-01-01'"

# Unpaid invoices
qbo query "SELECT * FROM Invoice WHERE Balance > '0'"

# Vendors with email
qbo query "SELECT DisplayName, PrimaryEmailAddr FROM Vendor"

# Count items
qbo query "SELECT COUNT(*) FROM Item"

# TSV output (great for spreadsheets)
qbo query "SELECT DisplayName, Balance FROM Customer WHERE Balance > '0'" -f tsv
```

Queries automatically paginate through all results (up to 100 pages × 1000 rows).

### Get a single entity

```bash
qbo get Customer 5
qbo get Invoice 1042
```

### Create an entity

```bash
echo '{
  "DisplayName": "John Smith",
  "PrimaryEmailAddr": {"Address": "john@example.com"}
}' | qbo create Customer

echo '{
  "CustomerRef": {"value": "5"},
  "Line": [{
    "Amount": 150.00,
    "DetailType": "SalesItemLineDetail",
    "SalesItemLineDetail": {"ItemRef": {"value": "1"}}
  }]
}' | qbo create Invoice
```

### Update an entity

```bash
# Fetch, modify, and update
qbo get Customer 5 | jq '.Customer.CompanyName = "New Name"' | qbo update Customer
```

### Delete an entity

```bash
qbo delete Invoice 1042
```

The CLI fetches the entity first (to get the required `SyncToken`), then deletes it.

### Run reports

```bash
# Profit and Loss for a date range
qbo report ProfitAndLoss --start-date 2025-01-01 --end-date 2025-12-31

# Balance Sheet as of today
qbo report BalanceSheet

# Using date macros
qbo report ProfitAndLoss --date-macro "Last Month"
qbo report ProfitAndLoss --date-macro "This Year"

# With extra parameters
qbo report ProfitAndLoss --start-date 2025-01-01 --end-date 2025-12-31 accounting_method=Cash
```

Available reports: `ProfitAndLoss`, `BalanceSheet`, `CashFlow`, `CustomerIncome`, `AgedReceivables`, `AgedPayables`, `GeneralLedger`, `TrialBalance`, and more.

### Raw API access

```bash
# GET request
qbo raw GET "query?query=SELECT * FROM CompanyInfo"

# POST with body
echo '{"TrackQtyOnHand": true}' | qbo raw POST "item"
```

### Output formats

```bash
# JSON (default)
qbo query "SELECT * FROM Customer"

# TSV (tab-separated, for spreadsheets/awk)
qbo query "SELECT * FROM Customer" -f tsv

# Pipe to jq
qbo query "SELECT * FROM Customer" | jq '.[].DisplayName'
```

### Sandbox mode

```bash
# Use sandbox API endpoint
qbo --sandbox query "SELECT * FROM Customer"

# Or set via env/config
export QBO_SANDBOX=true
```

## Configuration Reference

| Setting | Env Variable | Config Key | Default |
|---------|-------------|------------|---------|
| Client ID | `QBO_CLIENT_ID` | `client_id` | — |
| Client Secret | `QBO_CLIENT_SECRET` | `client_secret` | — |
| Redirect URI | `QBO_REDIRECT_URI` | `redirect_uri` | — (must match your Intuit app) |
| Realm ID | `QBO_REALM_ID` | `realm_id` | From auth flow |
| Sandbox mode | `QBO_SANDBOX` | `sandbox` | `false` |

Config file location: `~/.qbo/config.json`

Token storage: `~/.qbo/tokens.json` (created automatically, chmod 600)

## Token Management

- **Access tokens** expire every 60 minutes. The CLI refreshes them automatically before each request.
- **Refresh tokens** are valid for 100 days. Each refresh extends the 100-day window (rolling expiry).
- If you don't use the CLI for 100+ days, the refresh token expires and you need to re-authorize with `qbo auth init`.
- The CLI warns you when the refresh token has fewer than 14 days remaining.
- Token refresh uses file locking — safe to run concurrent `qbo` commands.

Force a manual refresh:

```bash
qbo auth refresh
```

## Contributing

Contributions welcome. Please open an issue first to discuss what you'd like to change.

```bash
git clone https://github.com/alexph-dev/qbo-cli.git
cd qbo-cli
pip install -e .
```

## License

MIT — see [LICENSE](LICENSE).
