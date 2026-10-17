# Cofferant — QR ordering & management for cafés and restaurants

Persian (RTL) Django app. Customers scan a table QR, order from a mobile menu, pay and track the order live;
staff run the kitchen from a live board and see sales analytics. Built to be **sold**: a developer panel issues
subscription licenses and can cancel a customer's panel at any moment.

## Features

**For the café's customers**
- QR menu per table — search, categories, popular items, saved cart, customise sheet (e.g. 70/30), Wi-Fi card.
- Coupon codes, optional tip (5/10/15 %), live price breakdown computed on the server, one-tap upsell suggestions.
- Pay at the table with **Zarinpal** (online) or on delivery. Live order tracking and a rating prompt.
- Call waiter / ask for the bill / water from the table.

**For the café owner**
- Live kitchen board with sound alerts and late-order highlighting; dashboard with revenue, top sellers, busiest hours, tips, online share.
- Menu and table management (QR generation + printable sheets), order history with CSV export, coupons.
- **White-label settings**: name, logo, **primary and alternate colours**, notice banner, tax / service charge, pause ordering.
- Setup checklist on the dashboard to get a new café live in minutes.

**For you, the developer / seller**
- `/developer/` panel: create customers, issue licenses (**1 month · 3 · 6 months · 1 · 2 years · forever**), renew, **cancel / reactivate**, see revenue and who is about to expire.
- Choose each vendor's **username and password** (or let the system generate one) and change it any time.
- **Edit subscription prices** in the panel; they feed the sales page and the new-customer form.
- **Trash**: delete a customer to the trash (their site and panel go offline, data is kept), restore any time, or purge permanently after typing the business name.
- **Automatic backups every 12 hours** of every database, every hosted customer and all photos; browse and download them in the panel.
- Cancelling takes effect within seconds: the vendor panel and ordering stop working (the public menu stays visible but read-only). Data is kept; reactivating restores everything.

## Two ways to sell it

| | **A. On your domain (SaaS)** | **B. On the customer's domain** |
|---|---|---|
| Customer gets | `mycafe.yourdomain.com` | their own server + domain |
| You run | one server, `DEPLOYMENT_MODE=platform` | nothing — they run it, `DEPLOYMENT_MODE=standalone` |
| Isolation | separate database + upload folder per customer | their own install |
| Licence check | local, instant | the install asks your server (`/api/license/verify/`), cached 5 min, 72 h offline grace |
| Create in | Developer panel → *Mode: panel on our domain* | Developer panel → *Mode: install on customer's domain* → copy the `.env` snippet |

### A. Deploy your SaaS platform
DNS: `yourdomain.com` **and** `*.yourdomain.com` → your server.
```bash
git clone <repo> /opt/cofferant && cd /opt/cofferant
MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@example.com ./scripts/bootstrap-vps.sh
```
Wildcard TLS needs DNS validation: set `CF_API_TOKEN` (Cloudflare) and run `make ssl CHALLENGE=cloudflare` for auto-renewal,
or `make ssl CHALLENGE=dns` for a manual TXT record. Then sign in at `https://yourdomain.com/users/login/` with the admin
account from `.env` and open **`/developer/`** → *New customer*. The owner's login is shown once; send it to your customer.

### B. Install on a customer's own domain
In the developer panel create a customer with *Mode: install on customer's domain* and copy the shown values. On the customer's server:
```bash
git clone <repo> /opt/cofferant && cd /opt/cofferant
MODE=standalone DOMAIN=menu.mycafe.com LETSENCRYPT_EMAIL=owner@mycafe.com \
LICENSE_KEY=CFR-XXXX-XXXX-XXXX-XXXX LICENSE_SERVER_URL=https://yourdomain.com \
./scripts/bootstrap-vps.sh
```
If you cancel the license (or it expires) their panel locks within ~5 minutes. *Honest limitation:* a self-hosted customer has the
source code, so this is a commercial control, not unbreakable DRM — pair it with a contract. Hosted customers (A) cannot bypass it.

### Handy commands (`make help` lists all)
| | |
|---|---|
| `make env` / `make up` | create `.env` with generated secrets / build + start |
| `make ssl` | host nginx + Let's Encrypt |
| `make deploy-check` | pre-flight: secrets, tests, migrations, repo hygiene |
| `make deploy-health HOST=https://…` | post-deploy smoke checks |
| `make images-bundle` → `make load-images` | build on your PC, ship to a tiny VPS |
| `make backup` | take a backup now and copy it to `backups/` |
| `make backups-list` | automatic backups kept on the server (every 12 h, last 28) |
| `make restore FILE=…` / `make restore-latest` | restore a backup — checks the archive first, then replaces all data |
| `make admin-password` | rotate the admin password |
| `make demo` | demo menu, tables and orders |

## Run locally
```bash
make install && make migrate && make demo && make run     # or: python -m venv .venv … pip install -r requirements.txt
```
Open `/users/login/`. On an empty database the login page offers **first-run setup** to create the owner account
(public self-registration closes once a staff account exists).

Try the platform mode locally (Chrome resolves `*.localhost`):
```bash
DEPLOYMENT_MODE=platform PLATFORM_DOMAIN=localhost python manage.py runserver
# http://localhost:8000/developer/  → create a customer "demo" → http://demo.localhost:8000/
```

## Configuration
See `.env.example`. Key variables: `DEPLOYMENT_MODE`, `PLATFORM_DOMAIN`, `DJANGO_SECRET_KEY`, `ADMIN_PASSWORD`,
`LICENSE_*` (self-hosted), `PRICE_*` / `SALES_CONTACT` (prices on your sales page).

## Security notes
- Staff-only vendor views, CSRF everywhere, server-side pricing (tax, coupons, tips are never trusted from the browser),
  rate-limited ordering/quote/verify endpoints, unguessable tracking and payment links, payment callbacks bound to the issued authority.
- Tenant databases are separate files; the router sends every non-licensing model to the request's tenant, so customers can't see each other's data.
- Production (`DJANGO_DEBUG=0`) requires `DJANGO_SECRET_KEY`, sets secure cookies and HSTS.
- A `backup` container snapshots all databases (using SQLite's online-backup, safe while serving traffic) and photos every `BACKUP_INTERVAL_HOURS` (default 12), keeping `BACKUP_KEEP` archives (default 28 = 14 days) on the server. Server-side backups don't protect against losing the server itself, so download one now and then from `/developer/backups/` or run `make backup` from your PC.
- SQLite suits single-server deployments; move to PostgreSQL if you outgrow one machine.

## Tests
```bash
python manage.py test
```
