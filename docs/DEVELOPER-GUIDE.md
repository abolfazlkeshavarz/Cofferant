# Cofferant — Developer Guide (runbook)

Everything you need to run, sell, back up, move and repair Cofferant **on your own**, without any outside help.
Every command here was run against real containers while writing the project; things that need a real server,
real DNS or real certificates are marked ⚠️ *server-only*.

> Conventions: commands starting with `$` run on **your server** in `/opt/cofferant` unless a heading says
> "on your PC". `make help` always lists every command.

---

## Contents

1. [What you have](#1-what-you-have)
2. [Cheat sheet: "I want to…"](#2-cheat-sheet-i-want-to)
3. [First deployment](#3-first-deployment)
4. [Daily operations](#4-daily-operations)
5. [The developer panel](#5-the-developer-panel)
6. [Selling method 1 — customer on your domain](#6-selling-method-1--customer-on-your-domain)
7. [Customer with their own domain, hosted on your server](#7-customer-with-their-own-domain-hosted-on-your-server)
8. [Selling method 2 — customer's own server and domain (standalone)](#8-selling-method-2--customers-own-server-and-domain-standalone)
9. [Backups and restore](#9-backups-and-restore)
10. [Changing your domain](#10-changing-your-domain)
11. [Moving to a new server](#11-moving-to-a-new-server)
12. [Updating the software](#12-updating-the-software)
13. [Emergency recipes (no web panel needed)](#13-emergency-recipes-no-web-panel-needed)
14. [Troubleshooting](#14-troubleshooting)
15. [Danger zone](#15-danger-zone)
16. [Reference](#16-reference)
17. [Security model — what protects what](#17-security-model--what-protects-what)

---

## 1. What you have

Cofferant is a Persian (RTL) ordering and management system for cafés and restaurants (Django + SQLite, shipped as a Docker app).

```
 customer's phone ──scan QR──► menu ► order ► pay (Zarinpal) ► live tracking
                                       │
 café staff ◄── live board, menu, tables, coupons, reports, settings (vendor panel /vendor/)
                                       │
 YOU ◄── developer panel /developer/: customers, licenses, prices, backups
```

**Two deployment modes** (set by `DEPLOYMENT_MODE` in `.env`):

| | `platform` (your SaaS) | `standalone` (a customer's own install) |
|---|---|---|
| Runs on | **your** server and domain | the **customer's** server and domain |
| Customers | many, each at `name.yourdomain.com` (optionally their own domain) | one café |
| Data | one SQLite file per customer, fully separate | one database |
| Developer panel | yes, `/developer/` | no |
| License check | local, instant | asks your server, cached |

**Where things live** (inside the `app` container; Docker volumes survive restarts and updates):

| What | Path | Volume |
|---|---|---|
| Main database (accounts, licenses, your own café) | `/app/data/db.sqlite3` | `cofferant_data` |
| Each hosted customer's database | `/app/data/tenants/<slug>.sqlite3` | `cofferant_data` |
| Photos (customers in `/app/media/<slug>/`) | `/app/media/` | `cofferant_media` |
| Backups | `/app/backups/cofferant-<time>.tar.gz` | `cofferant_backups` |
| SSH key for off-server backups | `/home/app/.ssh/` | `cofferant_sshkeys` |
| Your settings & secrets | `/opt/cofferant/.env` | (a file on the host) |

Containers: `app` (the website) and `backup` (copies everything every 12 hours). TLS is done by the **host's nginx**
(not Docker), which proxies to `127.0.0.1:8081`.

---

## 2. Cheat sheet: "I want to…"

| I want to… | Do this |
|---|---|
| Deploy on a fresh VPS | `MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@x.com ./scripts/bootstrap-vps.sh` |
| Open the developer panel | `https://yourdomain.com/developer/` (log in as `admin`) |
| Add a customer | Developer panel → **مشتری جدید** |
| Give a customer their own domain (on my server) | Panel → customer → **دامنه اختصاصی** → then `make add-domain DOMAIN=menu.cafe.ir` |
| Sell a standalone install | Panel → customer, mode **نصب روی دامنه مشتری** → send key + command from [section 8](#8-selling-method-2--customers-own-server-and-domain-standalone) |
| Build the customer package (no source code) | `make release VERSION=1.0.0 LICENSE_SERVER_URL=https://yourdomain.com` (on your PC) |
| Lock a customer who didn't pay | Panel → customer → **لغو اشتراک** (works within seconds) |
| Renew a customer | Panel → customer → **تمدید / تغییر اشتراک** |
| Set a customer's password | Panel → customer → **تعیین رمز** |
| Change subscription prices | Panel → **قیمت اشتراک‌ها** |
| Update the software (build on my PC) | `make deploy-remote HOST=root@SERVER` (rollback: `make rollback-remote HOST=root@SERVER`) |
| Update the software (git on the server) | `make backup && make update` |
| See if everything is OK | `make health` |
| Read the logs | `make logs` |
| Back up right now | `make backup` |
| Copy backups to a second server | `make backup-remote-setup REMOTE=user@host:/backups/cofferant` |
| Restore a backup | `make restore FILE=backups/cofferant-….tar.gz` or `make restore-latest` |
| Change my main domain | `make change-domain DOMAIN=newname.com` |
| Move to a new server | `make export` → `./scripts/migrate-import.sh bundle.tar.gz` |
| Reset my admin password | `make admin-password` |
| Create another admin | `make admin-user` |
| Run Python/Django by hand | `make shell` |

---

## 3. First deployment

### 3.1 Prerequisites

- A VPS with **Ubuntu or Debian**, 1 CPU / 1 GB RAM or more, ports **80 and 443** open, root/sudo access.
- A domain you control. For platform mode you need **two DNS records**:

  | Type | Name | Value |
  |---|---|---|
  | A | `@` (yourdomain.com) | server IP |
  | A | `*` (wildcard) | server IP |

  In Cloudflare keep both records on **DNS only** (grey cloud). A name can point to **only one server**: if you ever point it somewhere else (for example while testing another server), your platform goes offline and visitors see whatever that other server answers (see [section 14](#14-troubleshooting)).

- Platform mode needs a **wildcard certificate**, which Let's Encrypt only gives through DNS validation:
  - **Cloudflare DNS (recommended, auto-renews):** create an API token (Cloudflare → My Profile → API Tokens → *Edit zone DNS* template → zone = your domain). Keep it for `.env` (`CF_API_TOKEN`).
  - **Any other DNS provider:** use `CHALLENGE=dns`; you add a TXT record by hand and must **repeat it about every 60 days**.

### 3.2 One command

```bash
$ git clone <your-repo-url> /opt/cofferant && cd /opt/cofferant
$ MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@example.com ./scripts/bootstrap-vps.sh
```

It installs Docker, writes `.env` with generated secrets, builds and starts the app, then sets up nginx and the certificate.
At the end it prints the admin username and password — **save them**. They are also in `/opt/cofferant/.env`.

Cloudflare wildcard (auto-renew):

```bash
$ echo "CF_API_TOKEN=paste_token_here" >> .env
$ CHALLENGE=cloudflare make ssl
```

Manual TXT record instead: `CHALLENGE=dns make ssl` (certbot tells you the record to add).

**Build on your PC instead of on the server (recommended — no git, no compiling on the server).** From your PC, with SSH key login to the server:

```bash
$ make deploy-remote HOST=root@YOUR_SERVER_IP \
      MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@example.com
```

It builds the image on your PC, uploads it (checksum verified) with the compose file and scripts, installs Docker on the server if needed,
loads the image and — on a brand-new server — runs the bootstrap for the certificate and nginx. See [section 12](#12-updating-the-software)
for updates and rollback. (Needs `ssh` on your PC; on Windows, Git for Windows provides it. `ssh-copy-id root@YOUR_SERVER_IP` sets up key login.)

The manual route still works for tiny servers: `make images-bundle` on your PC → `scp` the file → `make load-images && make up-prebuilt` on the server.

### 3.3 Check it

```bash
$ make health
$ make deploy-health HOST=https://yourdomain.com
```

Then open `https://yourdomain.com/developer/`. ✅ If something fails see [Troubleshooting](#14-troubleshooting).

### 3.4 Do these two things right away

```bash
$ make backup-remote-setup REMOTE=backupuser@other-server.com:/backups/cofferant   # off-server backups
```

(`make deploy-check` runs the Python tests, so run it on **your PC** before a release, not on the server.)

---

## 4. Daily operations

| Command | What it does | Example |
|---|---|---|
| `make ps` | container status | `make ps` |
| `make health` | checks containers, migrations, public URLs | shows `[OK]`/`[FAIL]` lines |
| `make logs` | live logs of the app (Ctrl+C to leave) | `make logs` |
| `make restart` | stop + rebuild + start | after editing code |
| `make down` | stop (data is kept) | `make down` |
| `make up` | build and start (waits until healthy) | `make up` |
| `make shell` | Django shell | see [section 13](#13-emergency-recipes-no-web-panel-needed) |
| `make admin-user` | create another superuser (interactive) | `make admin-user` |
| `make admin-password` | new admin password, saved in `.env` | `make admin-password PASSWORD='My-New-Long-Pass-1'` |
| `make deploy-check` | pre-flight checks (secrets, tests, repo hygiene) — run on **your PC** (needs the dev setup: `make install`) | before every release |
| `make deploy-health HOST=…` | health check of a public address | `make deploy-health HOST=https://yourdomain.com` |

Useful raw Docker commands:

```bash
$ docker compose ps                                  # what is running
$ docker compose logs -f --tail=50 app               # live log of the website
$ docker compose logs --tail=50 backup               # log of the backup loop
$ docker compose up -d --force-recreate app backup   # re-create containers so they re-read .env
$ docker compose exec app ls -lh /app/data /app/data/tenants   # see the database files
```

> **Editing `.env` does nothing until the containers are recreated:**
> `docker compose up -d --force-recreate app backup` (a plain `restart` is **not** enough).
> Data is kept; the site is down about 10–20 seconds.

---

## 5. The developer panel

Address: `https://yourdomain.com/developer/`. Only superusers, only on your **root** domain (it deliberately returns 404 on customer addresses).
After login you land here automatically; the vendor panel has a "پنل توسعه‌دهنده" link in its sidebar.

| Page | What you do there |
|---|---|
| **نمای کلی** (dashboard) | revenue this month / total, 6-month chart, active / cancelled / expired counts, customers about to expire, last backup, trash count |
| **مشتریان** (customers) | search and filter; open a customer |
| **مشتری جدید** | create a customer (see below) |
| **قیمت اشتراک‌ها** | edit the six plan prices (toman) — used on the sales page and the new-customer form |
| **پشتیبان‌ها** | list, run, download backups; off-server copy status |
| **پنل کافه من** | your own café's vendor panel |

### 5.1 Creating a customer

Fields: business name, contact, phone, email, **mode**, subdomain (slug), own domain (optional), vendor username/password (optional), **plan**, price received, notes.

- **Mode "پنل روی دامنه ما"** → a database is created immediately at `slug.yourdomain.com`. The owner's login is shown **once** — copy it and send it to the customer. Forgot to copy? Use **تعیین رمز** later.
- **Mode "نصب روی دامنه مشتری"** → no database here; you get a **license key** and the `.env` lines for the customer's server ([section 8](#8-selling-method-2--customers-own-server-and-domain-standalone)).

Slug rules: 3–30 characters, lowercase letters, digits and `-`; reserved names (`www`, `admin`, `api`, `app`, `mail`, `static`, `media`, `developer`, …) are refused.

### 5.2 Plans (subscriptions)

| Plan | Length |
|---|---|
| 1 month | 30 days |
| 3 months | 91 days |
| 6 months | 183 days |
| 1 year | 365 days |
| 2 years | 730 days |
| Forever | never expires |

Renewing while still active **adds** time to the current end date; renewing after expiry starts from today. A "forever" license stays forever.
The amount you enter when creating/renewing is recorded as revenue (it feeds the dashboard).

### 5.3 What each action does

| Action | Effect |
|---|---|
| **لغو اشتراک** (cancel) | the customer's vendor panel locks and **their menu and QR codes stop working**: visitors are redirected to a "contact the coffee shop" page. Hosted: within seconds; standalone: within ~2 minutes. Data is kept. |
| **فعال‌سازی دوباره** | undo a cancel immediately |
| **تمدید** | extends / changes the plan |
| **تعیین رمز** | set the vendor's password (≥8 characters) or leave empty for a random one; shown once |
| **دامنه اختصاصی** | attach the customer's own domain ([section 7](#7-customer-with-their-own-domain-hosted-on-your-server)) |
| **انتقال به سطل زباله** | the customer's site and panel go offline; data kept; can be restored |
| **حذف نهایی** | only from the trash, only after typing the business name: deletes their database and photos for good |

An expired license behaves like a cancelled one. An in-app banner warns the vendor 7 days before expiry.

---

## 6. Selling method 1 — customer on your domain

1. Developer panel → **مشتری جدید** → mode *پنل روی دامنه ما*, choose a slug (e.g. `homecafe`), plan and price → **ساخت**.
2. Copy the shown login (`https://homecafe.yourdomain.com/users/login/`, username `owner`, password).
3. The customer signs in, sets name/logo/colours in **تنظیمات**, adds categories, products and tables, prints QR sheets.

That's it — no server work, because `*.yourdomain.com` already points at you and the wildcard certificate covers it.
Each customer has their own database file and photo folder; one customer can never see another's data.

---

## 7. Customer with their own domain, hosted on your server

For a customer who owns `menu.mycafe.ir` but whose site should run on **your** server.

1. Developer panel → customer → **دامنه اختصاصی مشتری** → type `menu.mycafe.ir` → **ذخیره**.
2. The customer adds a DNS **A record** for `menu.mycafe.ir` pointing to **your server's IP** (the panel shows the IP).
3. ⚠️ *server-only* — on your server, once their DNS points to you:

   ```bash
   $ make add-domain DOMAIN=menu.mycafe.ir          # add WWW=1 to also cover www.menu.mycafe.ir
   ```

   This gets a free Let's Encrypt certificate (renews automatically) and adds an nginx entry for that domain only.

Their `homecafe.yourdomain.com` address keeps working too. Cancel/trash locks or removes **both** addresses.
The app only answers domains registered in the panel; any other host gets a 404.

Remove it later:

```bash
$ make remove-domain DOMAIN=menu.mycafe.ir       # then clear the field in the panel
```

Panel refuses the domain? The message now says why:
- *"already registered for «X»"* → that customer (maybe in the **trash**) still holds it. Clear it on their page or purge them.
- *"still active as an old platform domain (PLATFORM_ALIAS_DOMAINS)"* → see [section 10](#10-changing-your-domain), `DROP_OLD=1`.
- *"belongs to the platform itself"* → it's your own domain or one of its subdomains.

---

## 8. Selling method 2 — customer's own server and domain (standalone)

The customer runs **their own copy** on **their own server and domain**. You still control it through a **license key**:
their install asks your server "is my key valid?" every few minutes. Cancel or let it expire → their panel locks.

### 8.1 What the customer needs

- A VPS (Ubuntu/Debian, 1 CPU / 1 GB or more), root/sudo, ports 80/443 open.
- A domain with an **A record** to that server (e.g. `menu.mycafe.ir`).
- An email address for certificate warnings.
- Nothing else: you send them the package from 8.4 (no repository access).

**What gets installed on their server** (the installer does all of it): Docker Engine + the compose plugin, host nginx + certbot (HTTPS), and **one image, `cofferant-app`**, loaded from the package. That single image already contains Python and all libraries and runs as two containers (`app` and `backup`), so nothing is pulled from Docker Hub for the app, and no Python, database server or repository is needed on the host. The package is about 60 MB compressed. Internet access is used only for Docker's apt repository (once), Let's Encrypt, and your license server.

### 8.2 Step by step

**A. On your side (developer panel)** — **مشتری جدید**:
- Mode: **نصب روی دامنه مشتری**; business name, contact, plan, price; (optional) their domain for your notes.
- Save, open the customer page, and copy the **license key** (`CFR-XXXX-XXXX-XXXX-XXXX`). The page also shows the exact `.env` lines.

**B. Build the customer package** (on **your PC**, once per version — [details in 8.4](#84-the-customer-package-no-source-code)):

```bash
$ make release VERSION=1.0.0 LICENSE_SERVER_URL=https://yourdomain.com
#  -> dist/release/cofferant-customer-1.0.0.tar.gz   (compiled, locked, no source code)
```

**C. On the customer's server** (you do it via SSH, or send them the package and the key):

```bash
$ tar xzf cofferant-customer-1.0.0.tar.gz && cd cofferant-customer-1.0.0
$ sudo ./install.sh                  # asks for: domain, email, license key
```

What this does: installs Docker if needed, loads the application, creates `.env` (random secrets, your key), starts the app,
gets a certificate and configures nginx. At the end it prints the **admin username and password** for the café — hand them to the owner
(they can change the password in **تنظیمات → تغییر رمز عبور**).

**D. Check** (on that server):

```bash
$ make deploy-health HOST=https://menu.mycafe.ir
```

Open `https://menu.mycafe.ir/users/login/`, sign in, and the vendor panel should load. Back in your developer panel, the license page shows
**آخرین بررسی** (last check) with their domain — proof the key is being verified.

**E. Hand over:** the owner adds categories, products and tables and prints the QR sheets.

### 8.3 How the license control works

| Event | What happens on the customer's install |
|---|---|
| Valid license | everything works; a "yes" is re-checked about every **2 minutes** |
| You **cancel** / it **expires** | within ~2 minutes the owner's panel shows the "subscription inactive" page, and **customers who scan a QR code or open the menu/site are redirected to a "contact the coffee shop" page** (café name, phone, Instagram, address) — the menu is not shown at all; online ordering stops |
| You **renew / reactivate** | unlocks within about **15 seconds** (a "no" is only remembered that long). The lock page also has a **"بررسی دوباره"** button that checks instantly |
| Your server is unreachable | the last good answer is trusted for **72 hours** (`LICENSE_GRACE_HOURS`), then it locks |
| License key missing | locked |

The "contact the coffee shop" page uses the café's own details from **تنظیمات** (phone, Instagram, address); fill them in during hand-over.
Sign-in pages stay reachable so the owner can see the lock page and press "check again".

### 8.4 The customer package (no source code)

**Do not give a customer your repository.** `git clone` hands over every readable source file. Build a customer package instead:

```bash
$ make release VERSION=1.0.0 LICENSE_SERVER_URL=https://yourdomain.com
```

What the package contains and guarantees:

| | |
|---|---|
| **No source code** | the image holds compiled bytecode only; every `.py` file (except the tiny `manage.py`) is removed, tests/docs/packaging are not included. The build checks this and fails if any source is left. |
| **Edition lock** | the build is the *standalone* edition: it **cannot be switched to platform mode**, **cannot run with license checks off**, whatever the customer writes in `.env` |
| **Baked-in license server** | `LICENSE_SERVER_URL` is part of the image; setting another address in `.env` is ignored, so a fake "always valid" server cannot be pointed at |
| **Installer** | `install.sh` asks for domain, email and key, installs Docker, loads the image, runs the bootstrap (certificate + nginx) |
| **Customer README** | `README.txt` in English and Persian: install, update, backup, license behaviour |
| **Shell scripts** | the helper scripts are included (they contain no business logic) so the customer can run `make health`, `make backup`, etc. |

I tested the real thing with two containers (a platform and a customer built from this image): valid → works; cancelled → owner locked, menu/QR and home
redirect to the contact page; reactivated → unlocked after ~15 s; and with `DEPLOYMENT_MODE=platform`, `LICENSE_ENFORCE=0` and a fake `LICENSE_SERVER_URL`
in the environment the build stayed standalone, enforced, and used the baked-in server.

**Updating a customer:** build a new version (`make release VERSION=1.1.0 …`), send them the new `.tar.gz` (or just `cofferant-images.tar.gz`
from inside it). On their server: `make update FILE=/path/to/cofferant-images.tar.gz` — it takes a backup first, then installs the new version; data is kept.
Data migrations run automatically at start.

Notes:
- `make release` also tags the image `cofferant-app:latest` on your PC; run `make up` afterwards for your own development build.
- Pass `PLATFORM=linux/arm64` if the customer's server is ARM.
- You still need the platform address (`LICENSE_SERVER_URL`) to stay reachable over HTTPS, and to keep it fixed — it is baked into every released version.
  If you ever change your platform domain, release a new version (`change-domain` keeps the old one working as an alias meanwhile).

⚠️ **Honest limits.** Bytecode can be decompiled by a determined person with time and skill; templates, CSS and JavaScript are readable; the customer
controls their server. The build removes the easy bypasses (flipping settings, reading and editing the source, a fake server) and makes any bypass a
deliberate act. Combine it with: a **contract** (no reselling, no hosting for third parties, no removing the license check), **updates only from you**
(that is your leverage), and logs — the developer panel shows each install's last check time and domain.

### 8.5 If you run the server for the customer yourself

When *you* control the machine (you pay for it, you have the only SSH key), cloning the repository there is fine:

```bash
$ git clone <repo-url> /opt/cofferant && cd /opt/cofferant
$ MODE=standalone DOMAIN=menu.mycafe.ir LETSENCRYPT_EMAIL=owner@mycafe.ir \
  LICENSE_KEY=CFR-XXXX-XXXX-XXXX-XXXX LICENSE_SERVER_URL=https://yourdomain.com \
  ./scripts/bootstrap-vps.sh
```

(In that setup the license can be changed by whoever edits `.env`, so use it only where you hold the keys.)

### 8.6 Looking after a standalone customer

| Task | Command (on their server) |
|---|---|
| Update to the new version | send the new package; `make update FILE=/path/to/cofferant-images.tar.gz` (backs up first) |
| Logs | `make logs` |
| Health | `make health` |
| Their backups | automatic every 12 h in `/app/backups`; recommend `make backup-remote-setup …` |
| Change their domain | `make change-domain DOMAIN=new.mycafe.ir` |
| Move them to a new server | `make export` there → `./scripts/migrate-import.sh bundle.tar.gz` on the new one |
| Lock them | cancel in **your** developer panel |
| They lost the admin password | `make admin-password` on their server |

If their domain changes **and** you keep verifying against your old address, nothing else is needed. If **your** platform domain changes,
update `LICENSE_SERVER_URL` in their `.env` (then `docker compose up -d --force-recreate app backup`) — until then keep your old domain as an alias
([section 10](#10-changing-your-domain)).

### 8.7 Testing a customer install safely

Do this before selling, to see exactly what a customer sees. Rules we learned the hard way:

1. **Give the test customer a domain of its own** — a different name from your platform, e.g. `test1.yourdomain.com` with an A record to the *test server*. Never reuse the platform's own name: a name can point to only one server, and pointing it elsewhere takes your platform offline (the symptom is your domain suddenly showing *another project* — see [section 14](#14-troubleshooting)).
2. Keep Cloudflare records **DNS only** (grey cloud).
3. Install it the way a customer would (the package from 8.4: `sudo ./install.sh`). On a server that already hosts other projects pass a free local port, e.g. `WEB_PORT=8082`, and use its own folder (e.g. `/opt/cofferant-customer1`).
4. DNS not ready yet? Install with `SKIP_SSL=1` (no certificate), test locally with `curl -H "Host: test1.yourdomain.com" http://127.0.0.1:8082/healthz`, and run `make ssl` once the DNS points to the server.
5. A folder that already has a `.env` from an earlier attempt is **refused** if its mode/domain/key differ from what you ask for. On disposable test data: `docker compose down -v && rm .env`, then run the install again.
6. **Never put a second copy on the live platform server** (see [section 15](#15-danger-zone)).

What to check:

| Step | Expected |
|---|---|
| sign in at `https://test1.yourdomain.com/users/login/` | vendor panel opens |
| your panel → the customer | **آخرین بررسی** shows a recent time and the test domain |
| press **لغو اشتراک** | within ~2 minutes the owner's panel locks; scanning a QR code or opening the menu shows the *contact the coffee shop* page |
| press **فعال‌سازی دوباره** | unlocks in about 15 seconds (or press **بررسی دوباره** on the lock page) |
| in the test install's `.env` set `DEPLOYMENT_MODE=platform`, `LICENSE_ENFORCE=0` and a wrong `LICENSE_SERVER_URL`, then `docker compose up -d --force-recreate app` | **no effect** on the compiled package (edition lock) |

Clean up: `docker compose down -v` **in that folder only**, remove its nginx entry (`rm /etc/nginx/sites-enabled/test1.yourdomain.com.conf && nginx -t && systemctl reload nginx`), trash and permanently delete the test customer in your panel, and remove the test DNS record.

---

## 9. Backups and restore

### 9.1 What is backed up

Every backup archive contains **all databases** (main + every hosted customer) **and all uploaded photos**.
It does **not** contain `.env` — keep a private copy of that yourself (it is included only in the `make export` bundle).

### 9.2 Automatic

The `backup` container runs every `BACKUP_INTERVAL_HOURS` (default **12**) and keeps `BACKUP_KEEP` archives (default **28 = 14 days**).
Snapshots use SQLite's online-backup, so they are consistent even while the site is busy.

```bash
$ make backups-list                  # files kept on the server
$ docker compose logs --tail=20 backup
```

### 9.3 Off-server copy (so losing the server doesn't lose the backups)

```bash
$ make backup-remote-setup REMOTE=backupuser@other-server.com:/backups/cofferant
```

It stores the target in `.env`, creates an SSH key **inside the app** and prints the public key. Add that line to
`~/.ssh/authorized_keys` of `backupuser` on the other machine, press Enter, and it tests the connection and sends a first copy.
From then on every backup is copied automatically; the other machine keeps the newest `BACKUP_REMOTE_KEEP` (default 60).

```bash
$ make backup-remote-test            # re-test the connection any time
```

Status (OK / error) also shows on `/developer/backups/`. Non-standard SSH port: add `BACKUP_REMOTE_PORT=2222` to `.env`.

### 9.4 Manual backup

```bash
$ make backup                        # creates one, copies it to ./backups/ on the host
$ scp root@SERVER:/opt/cofferant/backups/cofferant-*.tar.gz .      # to your PC, now and then
```

Also downloadable from `/developer/backups/`.

### 9.5 Restore

⚠️ A restore **replaces all current data** with the backup's state — orders taken after the backup are lost. Take a fresh backup first.

```bash
$ make restore-latest                                   # newest backup on the server
$ make restore FILE=backups/cofferant-20261018-101258.tar.gz   # a specific file (e.g. copied from your PC)
```

Both check the archive **before** deleting anything, stop the app (~30 s), restore, and start it again. Type `yes` when asked.

### 9.6 Test your backups (do this once, and again every few months)

**Safest — rehearse on a throwaway copy (your real data is never touched):**

```bash
$ cd /opt/cofferant && make backup                              # fresh backup in ./backups
$ cp -r /opt/cofferant /opt/cofferant-test && cd /opt/cofferant-test
$ rm -rf backups && mkdir backups
$ sed -i 's/^WEB_PORT=.*/WEB_PORT=8099/; s/^BACKUP_REMOTE=.*/BACKUP_REMOTE=/' .env
$ export COMPOSE_PROJECT_NAME=cofferant-test                    # separate containers and volumes
$ ./scripts/migrate-import.sh /opt/cofferant/backups/cofferant-<time>.tar.gz --skip-install
$ docker compose exec -T app python manage.py shell --no-imports -c "from licensing.models import License; print(License.objects.count(), 'customers restored')"
$ docker compose down -v                                        # throw the test copy away
$ cd /opt && rm -rf /opt/cofferant-test && unset COMPOSE_PROJECT_NAME
```

**In place, with a test customer only:** create customer `restore-test` → `make backup` → in the panel trash it and **حذف نهایی** →
`make restore-latest` → check it is back.

### 9.7 Backups get big?

Photos are copied in full each time. Check: `docker compose exec app sh -c "du -sh /app/media /app/backups"`.
If it grows, lower `BACKUP_KEEP` / `BACKUP_REMOTE_KEEP` in `.env`, then `docker compose up -d --force-recreate app backup`.

---

## 10. Changing your domain

Example: `cofferant.abolfazl.fun` → `cofferant.ir` on the **same server**.

1. **DNS first**: for the new domain add A records for `@` and `*` (platform mode) to the server IP. Check: `nslookup anything.cofferant.ir`.
2. **Certificate access**: Cloudflare token for the new zone in `.env` (`CF_API_TOKEN=…`; tokens are per zone) or use `CHALLENGE=dns`.
3. Run ⚠️ *server-only*:

   ```bash
   $ make change-domain DOMAIN=cofferant.ir                  # Cloudflare token present
   $ CHALLENGE=dns make change-domain DOMAIN=cofferant.ir    # manual TXT record
   ```

   It saves `.env.bak-<time>`, rewrites the domain settings, recreates the containers, gets the certificate + nginx entry.
4. Check: `make deploy-health HOST=https://cofferant.ir`, open `/developer/`, open a customer address.

**The old domain keeps working by default** (it becomes an *alias*): customers' old `name.old-domain` addresses and standalone installs'
license checks keep working until you drop it. To stop serving it:

```bash
$ make change-domain DOMAIN=cofferant.ir DROP_OLD=1       # forgets every old alias
$ make remove-domain DOMAIN=cofferant.abolfazl.fun        # removes its nginx entry (+ optionally its certificate)
```

Going **back** to a domain you tried earlier? The domain you left stays an alias — clear it:
`make change-domain DOMAIN=<current-domain> DROP_OLD=1` (same domain + `DROP_OLD=1` clears all aliases).

Tell hosted customers their new address (`name.newdomain`); update standalone customers' `LICENSE_SERVER_URL` when convenient.

---

## 11. Moving to a new server

### 11.1 Old server still alive (recommended: no data loss)

```bash
# on the OLD server
$ make export                                            # -> dist/cofferant-migration-<time>.tar.gz  (data + settings = SECRETS)
$ scp dist/cofferant-migration-*.tar.gz root@NEW_SERVER:/opt/

# on the NEW server (fresh Ubuntu/Debian)
$ git clone <repo-url> /opt/cofferant && cd /opt/cofferant
$ ./scripts/migrate-import.sh /opt/cofferant-migration-<time>.tar.gz --no-ssl
```

What import does: installs Docker, starts the app with the old `.env`, restores every database and photo, starts it again, and prints which
**customer-owned domains** still need `make add-domain` (those whose DNS already points to the new server are done automatically).

Options: `--domain newname.com` (the domain changes too), `--no-ssl` (no certificate yet — test first), `--drop-old`, `--skip-install` (Docker already set up; restore data only).

**Zero-downtime order:**
1. Import with `--no-ssl`; check with `curl -H "Host: yourdomain.com" http://127.0.0.1:8081/healthz`.
2. Switch DNS (`@`, `*`, and customers' own domains) to the new IP.
3. On the new server: `make ssl` (platform needs `CHALLENGE=cloudflare|dns`), then `make add-domain DOMAIN=…` for each customer domain.
4. `make deploy-health HOST=https://yourdomain.com`; later delete the bundle (it holds secrets) and decommission the old server.

### 11.2 Old server is dead — only a backup exists

Take the newest `cofferant-….tar.gz` from your **off-server copy** (or your PC). A plain backup has no settings, so say what to create:

```bash
$ git clone <repo-url> /opt/cofferant && cd /opt/cofferant
$ MODE=platform DOMAIN=yourdomain.com LETSENCRYPT_EMAIL=you@example.com ADMIN_PASSWORD='ChooseALongPass-1' \
  ./scripts/migrate-import.sh /path/to/cofferant-20261018-101258.tar.gz
```

Everything — customers, licenses, accounts, photos — comes back. Logins keep working (password hashes are in the databases).
Only `.env`-level things are new (secret key, admin password); standalone customers keep verifying against the same domain once DNS points to the new server.

---

## 12. Updating the software

### 12.1 Recommended: build on your PC, push to the server

```bash
# on your PC, in the project folder (SSH key login to the server)
$ make deploy-remote HOST=root@YOUR_SERVER_IP                     # DIR=/opt/cofferant by default
$ make deploy-health HOST=https://yourdomain.com
```

What it does, in order — and stops safely if a step fails:

1. builds the image on your PC (version = the git commit, e.g. `cc19ef6`; `-dirty` if you have uncommitted changes) and checks its CPU architecture
2. uploads it with the small support files (compose, Makefile, scripts) — never your `.env`, databases, photos or backups — and verifies the checksum
3. on the server: **takes a backup first** (if the backup fails, nothing is switched), keeps the running image as `previous`, loads the new one, restarts, and waits until it is healthy
4. prints the result; on a failed health check it tells you how to go back

The server needs **no git and no source checkout** for this. (On a server set up this way, restart with `make up-prebuilt` or `docker compose up -d --no-build`, not `make up`, which tries to build from source.) Options: `DIR=/path` (server folder), `SSH_PORT=2222`, `SSH_KEY=~/.ssh/key`,
`PLATFORM=linux/arm64` (ARM server), `SKIP_BUILD=1` (re-send the image you already built).

**What your PC needs:** Docker Desktop **running** (the image is built on your PC), `ssh` (Git for Windows provides it; use Git Bash), and some free disk space (the packed image, about 60 MB, is kept in `dist/deploy`). The first build takes a few minutes; later ones reuse Docker's cache. The image contains your readable source — fine for your own server (customers get the compiled package from `make release`).

**One-time setup — SSH key login.** The script never asks for a password, so it needs a key:

```bash
# in Git Bash on your PC (use your SSH port; 22 is the default)
$ ls ~/.ssh/id_ed25519 || ssh-keygen -t ed25519            # create a key once (press Enter = no passphrase)
$ ssh-copy-id -p 9011 root@YOUR_SERVER_IP                  # install it on the server (asks the root password once)
$ ssh -p 9011 root@YOUR_SERVER_IP echo ok                  # must print ok WITHOUT asking for a password
$ make deploy-remote HOST=root@YOUR_SERVER_IP SSH_PORT=9011
```

No `ssh-copy-id`? `cat ~/.ssh/id_ed25519.pub | ssh -p 9011 root@YOUR_SERVER_IP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"`.

If the script says *Cannot log in … with a key*, find the reason with `ssh -p PORT -o BatchMode=yes root@IP echo ok`:

| You see | Meaning / fix |
|---|---|
| `Permission denied (publickey)` | your key isn't on the server yet → run `ssh-copy-id` as above |
| `Connection refused` / `timed out` | wrong port or a firewall → check `Port` in `/etc/ssh/sshd_config` on the server and use `SSH_PORT=` |
| it works by hand but not in the script | the key has a **passphrase** (the script can't type it) → `eval $(ssh-agent) && ssh-add ~/.ssh/id_ed25519`, or use a dedicated key without passphrase |
| your key is not `~/.ssh/id_ed25519` | pass `SSH_KEY=~/.ssh/your_key` |
| key accepted for other users but not root | `PermitRootLogin` must be `yes` or `prohibit-password` in `/etc/ssh/sshd_config`, then `systemctl restart ssh` |

**Roll back** to the previous version in one command (about 10 seconds):

```bash
$ make rollback-remote HOST=root@YOUR_SERVER_IP
```

Database changes only go forward: if the newer version changed data, also restore the backup taken at the start of the deploy (`make restore-latest` on the server).

**Brand-new server:** the same `make deploy-remote …` command uploads everything and installs Docker; if the server has no `.env` yet it stops with the one
command to finish (or does it for you when you pass `MODE=platform DOMAIN=… LETSENCRYPT_EMAIL=…`).

### 12.2 Alternative: update from git on the server

```bash
$ cd /opt/cofferant
$ make backup                  # always first
$ make update                  # git pull --ff-only, rebuild, start (migrations run automatically, customers' databases too)
$ make health
```

Only use this if the server has the repository checked out (`git clone`). Building on a small server can run out of memory — then prefer 12.1.

- Migrations for **every hosted customer** run on container start (`migrate_tenants`). Run by hand: `make migrate-tenants`.
- Release checklist on your PC: `make test` and `make deploy-check` pass, then push.
- **Rollback** (git route): `git log --oneline` → `git checkout <old-commit>` → `make up`. With `deploy-remote` use `make rollback-remote` instead. Database changes only go forward, so if a bad
  release changed data, restore the backup (`make restore-latest`).
- Browsers cache styles — after a design change tell users to hard-refresh (Ctrl+F5) once.

### 12.3 Manual route (build on your PC, copy by hand)

The same idea as 12.1, step by step and without the safety net:

```bash
# on your PC
$ make images-bundle                                  # -> dist/cofferant-images.tar.gz   (PLATFORM=linux/arm64 for an ARM server)
$ scp -P 9011 dist/cofferant-images.tar.gz root@YOUR_SERVER_IP:/opt/cofferant/      # scp uses a CAPITAL -P for the port
# on the server
$ cd /opt/cofferant && make backup && make load-images && make up-prebuilt && make health
```

Or stream it without creating a file:

```bash
$ docker build -t cofferant-app:latest .
$ docker save cofferant-app:latest | gzip | ssh -p 9011 root@YOUR_SERVER_IP "gunzip | docker load"
$ ssh -p 9011 root@YOUR_SERVER_IP "cd /opt/cofferant && docker compose up -d --no-build"
```

| | `make deploy-remote` | manual route |
|---|---|---|
| Backup before switching | automatic (stops if it fails) | you run `make backup` yourself |
| Old image kept for rollback | yes (`make rollback-remote`) | no |
| Upload checksum | yes | no |
| Waits until healthy | yes | no |
| Updates compose file and scripts on the server | yes | no — the server must already have them (a git checkout) |

Prefer `make deploy-remote` for regular updates.

---

## 13. Emergency recipes (no web panel needed)

Open a Python shell inside the app: `make shell` (or `docker compose exec app python manage.py shell --no-imports`). Paste what you need.
One-liner form (good for scripts): `docker compose exec -T app python manage.py shell --no-imports -c "<python>"`.

**List customers**
```python
from licensing.models import License
for l in License.objects.all():
    print(l.pk, l.business_name, l.slug, l.mode, l.state, l.expires_at, l.domain)
```

**Cancel / reactivate / renew a customer** (takes effect within ~15 s; hosted)
```python
from licensing.models import License
l = License.objects.get(slug='homecafe')
l.cancel('not paid')        # lock
l.reactivate()              # unlock
l.extend('1y', 4290000)     # add a year, record 4,290,000 toman income  (plans: 1m 3m 6m 1y 2y forever)
```

**Set a vendor's password**
```python
from licensing.models import License
from licensing import services
services.set_owner_password(License.objects.get(slug='homecafe'), 'New-Pass-12345')   # prints the credentials dict
```

**Reset YOUR admin password** — easiest: `make admin-password`. By hand:
```python
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username='admin'); u.set_password('A-Long-New-Pass-1'); u.is_superuser = u.is_staff = True; u.save()
```

**Who holds a domain?**
```python
from licensing.models import License
for l in License.objects.filter(domain__icontains='mycafe'): print(l.pk, l.business_name, l.domain, 'trash' if l.deleted_at else '')
License.objects.filter(domain__iexact='mycafe.ir').update(domain='')       # release it
```

**Unlock a customer who is trashed by mistake**
```python
from licensing.models import License
License.objects.get(slug='homecafe').restore()
```

**Peek into one customer's data**
```python
from licensing import tenancy
with tenancy.use_tenant('homecafe'):
    from management.models import Item, Order
    print(Item.objects.count(), 'products,', Order.objects.count(), 'orders')
```

**Create demo data** (never on a real customer): `make demo` (local) or `PROD=1 make demo`.

---

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `make deploy-health` → `GET /healthz -> 404` right after a domain change | the app still runs with the **old** domain: containers were not recreated (compose lets the shell environment override `.env`) | open a **fresh** shell: `docker compose up -d --force-recreate app backup` |
| Domain form says the domain is **already registered / in use** | another customer (maybe in the trash) holds it, or it is still a platform alias | [section 7](#7-customer-with-their-own-domain-hosted-on-your-server) and [13](#13-emergency-recipes-no-web-panel-needed) |
| `/developer/` shows 404 | not `DEPLOYMENT_MODE=platform`, or you are on a customer address | `grep DEPLOYMENT_MODE .env`; use your root domain |
| `/developer/` redirects to the home page | account is not a superuser | `make admin-user`, or the shell recipe |
| Customer sees **"پنل مدیریت غیرفعال است"** (lock icon) | license cancelled/expired (or key/URL wrong on a standalone install) | renew/reactivate in the panel (unlocks in ~15 s; the owner can press **بررسی دوباره** on the lock page to check at once); standalone: check `LICENSE_KEY`, `LICENSE_SERVER_URL`, DNS to your server |
| Customers scanning a QR code land on a page asking them to **contact the coffee shop** | the café's license is inactive (cancelled/expired/missing key): menu and QR codes are deliberately hidden | renew/reactivate; the page shows the phone/Instagram/address from the café's **تنظیمات**, so keep those filled in |
| Browser warns "certificate not valid" on `name.yourdomain.com` | no wildcard certificate yet | `CHALLENGE=cloudflare make ssl` (or `dns`) |
| `make ssl` fails: *DNS problem / authentication* | wrong or too-narrow Cloudflare token (needs Zone→DNS→Edit for **that** zone), or DNS not pointing | fix token/DNS, rerun `make ssl`. Nothing breaks; the old certificate keeps working |
| `*.yourdomain.com` addresses don't open | missing wildcard DNS record | add `A  *  <server IP>` |
| A customer's own domain doesn't open | DNS not pointing, certificate not issued, or domain not saved in the panel | check `nslookup domain`; `make add-domain DOMAIN=…`; panel field |
| `docker compose` says `DJANGO_SECRET_KEY … missing` | no `.env` in this folder | `cd /opt/cofferant`; `make env` only for new installs (never overwrites) |
| App container "unhealthy" | crash on start (migration/permission/disk) | `make logs`; free disk space; `docker compose up -d --force-recreate app` |
| `no space left on device` | big backups/photos/old images | `docker system df`; lower `BACKUP_KEEP`; `docker image prune` |
| `/usr/bin/env: 'bash\r': No such file or directory` when running a script | the script has **Windows line endings (CRLF)**, usually from files copied from a Windows PC | `sed -i 's/\r$//' scripts/*.sh Makefile docker-compose.yml .env.example deploy/nginx/*.template && chmod +x scripts/*.sh`. Current versions of `make deploy-remote` / `make release` convert automatically, so just deploy again |
| Changed `.env` but nothing changed | containers not recreated | `docker compose up -d --force-recreate app backup` |
| `Bind for 127.0.0.1:8081 failed: port is already allocated` | another program (e.g. another project) uses that local port; with an old `.env` the script kept the stored port | on a test/new folder: `docker compose down -v && rm .env`, then `WEB_PORT=8082 …bootstrap-vps.sh`. (Updated scripts refuse a mismatched `.env` and honour an explicit `WEB_PORT`.) Check free ports with `ss -ltn | grep :8082` |
| Bootstrap said `.env already exists` and ignored your mode / domain / license key | a leftover `.env` from an earlier try | same: remove the disposable `.env`; updated scripts stop with a clear message instead |
| Orders return "too many requests" | rate limit (`ORDER_RATE_LIMIT` per window) | raise `ORDER_RATE_LIMIT` in `.env`, recreate |
| Off-server backup shows an error | key not authorised / wrong user/path / port | `make backup-remote-test`; re-run `make backup-remote-setup`; check `BACKUP_REMOTE_PORT` |
| Standalone customer locked but license is valid | their server cannot reach your server (firewall, wrong URL) or clock very wrong | from their server: `curl -s -X POST -H 'Content-Type: application/json' -d '{"key":"CFR-…"}' https://yourdomain.com/api/license/verify/` |
| Persian text looks broken in a terminal on Windows | console encoding | set `PYTHONIOENCODING=utf-8` (the app itself is fine) |
| After restore, a customer's login fails | backup older than their last password change | set the password again in the panel |
| Your domain suddenly shows **another project** (an app from a different server) | its DNS A record now points to that other server; that server's default nginx site answers unknown names | set the A record back to the right IP. Compare `nslookup yourdomain` with `curl -s https://api.ipify.org` run on each server |
| `make deploy-remote` → *Cannot log in … with a key* | no key login to the server, or wrong port | [12.1 SSH key login](#121-recommended-build-on-your-pc-push-to-the-server) |
| `make deploy-remote` fails during the build with a Docker connection error | Docker Desktop is not running on your PC | start Docker Desktop and run it again |
| `make deploy-remote` stops at the backup step | the app on the server is unhealthy or the disk is full, so nothing was switched | `ssh … 'cd /opt/cofferant && docker compose logs --tail=50 app'`; free space; run again |
| In Git Bash a docker/ssh command complains about a path like `C:/Program Files/Git/app/…` | Git Bash rewrites arguments that start with `/` | prefix with `MSYS_NO_PATHCONV=1`, or wrap the command: `sh -c "…"` |

Still stuck? Collect: `make ps`, `make logs` (last 100 lines), `grep -v -E "SECRET|PASSWORD|TOKEN|KEY" .env`, `make health`. The answer is nearly always in the log.

---

## 15. Danger zone

These **destroy data**. Never run them on the real server unless you mean it:

| Command | Effect |
|---|---|
| `docker compose down -v` | **deletes all volumes = all databases, photos, backups on the server** |
| `make clean` | same as above (asks for `yes`) |
| `make restore …` / `make restore-latest` / `make import …` | **replace all data** with a backup |
| `docker volume rm cofferant_*` | deletes data |
| panel → **حذف نهایی** | permanently deletes one customer (database + photos) |
| `rm -rf /var/lib/docker/volumes/cofferant_*` | deletes data |
| `make up` / `docker compose up` / `bootstrap` in a **second copy** of the project on the live server | the compose project name is fixed (`cofferant`), so the second folder controls the **same containers and data volumes** as the live site and can recreate it with different settings. Use another server, or first `export COMPOSE_PROJECT_NAME=other` **and** a different `WEB_PORT` |

Safe ones: `make down`, `make restart`, `make up`, `docker compose up -d --force-recreate …` (data lives in volumes and survives).
Never copy or edit `*.sqlite3` files by hand while the app runs — use `make backup`.
Careful with `git clone URL /some-folder/`: a path that starts with `/` is **absolute**, so it creates the folder at the disk root, not inside your current directory.

Always keep: (1) off-server backups, (2) a private copy of `.env`, (3) your Cloudflare/DNS access, (4) the repository.

---

## 16. Reference

### 16.1 All `make` targets

| Target | Description | Example |
|---|---|---|
| `help` | list targets | `make help` |
| `env` | create `.env` with generated secrets (never overwrites) | `MODE=platform DOMAIN=x.com make env` |
| `up` / `up-prebuilt` | build+start / start from a loaded image | `make up` |
| `down` / `restart` / `ps` / `logs` | stop / restart / status / logs | `make logs` |
| `update` | `git pull` + `up` | `make update` |
| `clean` | **delete containers and volumes** | — |
| `deploy-remote` / `rollback-remote` | build on your PC, deploy to the server over SSH / go back one version | `make deploy-remote HOST=root@1.2.3.4` |
| `release` | build the locked, compiled **customer package** (no source code) | `make release VERSION=1.0.0 LICENSE_SERVER_URL=https://yourdomain.com` |
| `images` / `images-bundle` / `load-images` | build image / pack for a small VPS / load it | `make images-bundle` |
| `bootstrap` | fresh-VPS one-shot setup | `MODE=platform DOMAIN=x.com LETSENCRYPT_EMAIL=a@b.c make bootstrap` |
| `ssl` | host nginx + certificate | `CHALLENGE=cloudflare make ssl` |
| `add-domain` / `remove-domain` | customer's own domain on this server | `make add-domain DOMAIN=menu.cafe.ir WWW=1` |
| `change-domain` | move to a new domain on this server | `make change-domain DOMAIN=new.com DROP_OLD=1` |
| `export` / `import` | move everything to a new server | `make export` / `make import FILE=bundle.tar.gz DOMAIN=new.com NO_SSL=1` |
| `backup` / `backups-list` | backup now / list | `make backup` |
| `backup-remote-setup` / `backup-remote-test` | off-server copies | `make backup-remote-setup REMOTE=u@h:/backups` |
| `restore` / `restore-latest` | restore (replaces data) | `make restore FILE=backups/….tar.gz` |
| `health` / `deploy-health` / `deploy-check` | checks | `make deploy-health HOST=https://x.com` |
| `admin-user` / `admin-password` | accounts | `make admin-password PASSWORD='…'` |
| `shell` / `migrate-tenants` / `demo` | Django tools | `make shell` |
| `install` / `migrate` / `run` / `test` / `check` | local development | `make install && make migrate && make run` |

### 16.2 Scripts (`scripts/`, called by the targets above)

`bootstrap-vps.sh` (fresh server) · `deploy-remote.sh` (build locally + deploy over SSH) · `build-release.sh` (customer package) · `install-docker.sh` (used by the customer installer) · `init-env.sh` (create `.env`) · `deploy-host-nginx.sh` (nginx + certificate) ·
`add-domain.sh` / `remove-domain.sh` · `change-domain.sh` · `export-bundle.sh` / `migrate-import.sh` ·
`backup-remote-setup.sh` · `build-images.sh` / `load-images.sh` · `health.sh` · `deploy-check.sh` ·
`rotate-admin-password.sh` · `admin.sh` · `demo-data.sh` · `lib.sh` (shared helpers). Inside the image: `docker/entrypoint.sh`, `docker/restore.sh`.

### 16.3 `.env` settings

| Variable | Default | Meaning |
|---|---|---|
| `DEPLOYMENT_MODE` | `standalone` | `platform` (your SaaS) or `standalone` |
| `APP_DOMAIN` | — | the main domain (nginx/certificate scripts use it) |
| `PLATFORM_DOMAIN` | `localhost` | platform root domain (customers are `slug.<this>`) |
| `PLATFORM_ALIAS_DOMAINS` | empty | old platform domains still served (set by `change-domain`) |
| `LETSENCRYPT_EMAIL` | — | certificate warnings |
| `DJANGO_SECRET_KEY` | generated | **required in production**; never share |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | domain(s) | host and origin lists (platform ignores the host list; it checks domains itself) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / generated | the account created/updated at every start |
| `WEB_BIND` / `WEB_PORT` | `127.0.0.1` / `8081` | where the app listens for nginx |
| `CF_API_TOKEN` | empty | Cloudflare token for wildcard certificates |
| `LICENSE_ENFORCE` / `LICENSE_KEY` / `LICENSE_SERVER_URL` / `LICENSE_GRACE_HOURS` | `0` / – / – / `72` | standalone license check |
| `PRICE_1M … PRICE_FOREVER` / `SALES_CONTACT` | defaults | fallback prices (the panel's saved prices win) / contact on the sales page |
| `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP` | `12` / `28` | automatic backups and how many to keep |
| `BACKUP_REMOTE` / `BACKUP_REMOTE_PORT` / `BACKUP_REMOTE_KEEP` | – / `22` / `60` | off-server copy |
| `ORDER_RATE_LIMIT` / `ORDER_RATE_WINDOW` | `6` / `300` | orders per client per window (seconds) |
| `WEB_WORKERS` / `WEB_THREADS` | `2` / `4` | gunicorn size |
| `VERSION` | `latest` | image tag |

After editing: `docker compose up -d --force-recreate app backup`.

### 16.4 Vendor features (what your customers get)

Menu with **their own categories**, products with photos and "popular" flag, availability switch, QR menu per table with printable sheets,
live kitchen board with sound, waiter/bill/water requests, order tracking and ratings, coupons, tips, tax and service charge,
Zarinpal online payment (their merchant code), CSV export, reports (revenue, top sellers, busy hours), brand settings
(name, logo, **primary and alternate colour**, notice, Wi-Fi), change-own-password.
Zarinpal money goes **directly to the café's account**; you take no cut — your income is the subscription.

### 16.5 Local development (your PC)

```bash
make install        # creates .venv and installs requirements
make migrate
make demo           # demo menu, tables, orders
make run            # http://localhost:8000
make test           # the whole test suite (≈110 tests)
```

Try platform mode locally (Chrome resolves `*.localhost`):
`DEPLOYMENT_MODE=platform PLATFORM_DOMAIN=localhost python manage.py runserver` → `http://localhost:8000/developer/` →
create customer `demo` → `http://demo.localhost:8000/`.

**Working from Windows** (your PC):

- Use **Git Bash** (from Git for Windows) for `make`, the scripts and `ssh`. The Makefile finds Git Bash and Docker Desktop by itself.
- **Docker Desktop must be running** for anything that builds or runs containers locally.
- Git Bash rewrites arguments that start with `/` into Windows paths (`/app/x` → `C:/Program Files/Git/app/x`). If a command breaks that way, prefix it with `MSYS_NO_PATHCONV=1`.
- Windows editors may save scripts with CRLF line endings, which break on Linux (`bash\r: No such file or directory`). The repository forces LF (`.gitattributes`), and `make deploy-remote` / `make release` convert files before they leave your PC.
- Persian text in a terminal: `set PYTHONIOENCODING=utf-8` (or `export` in Git Bash) if a script prints garbled characters.

---

## 17. Security model — what protects what

| Layer | What it does | Honest limit |
|---|---|---|
| **Customer isolation** (platform) | each hosted customer has its own SQLite file and photo folder; every query is routed to the current request's customer database; automated tests prove one customer can't see another's data | a bug in routing code would be serious — keep the test suite green (`make test`) |
| **Developer panel** | only superusers, only on your **root** domain; it returns 404 on customer addresses and does not exist in customer builds | protect your admin password and server access |
| **Host policing** | the platform answers only its own domain, its sub-domains and domains you registered for customers; anything else gets 404 | — |
| **Money logic** | prices, tax, service charge, tips and coupons are computed on the server (the browser's numbers are ignored); payment callbacks are bound to the issued payment reference; ordering, quotes and license checks are rate-limited | — |
| **License control** | hosted: checked on every request (15 s cache); standalone: asks your server — a "yes" is remembered 2 min, a "no" 15 s, with a 72 h offline grace. Cancel = panel locked, menu/QR → *contact the coffee shop* page | a customer who controls their server can interfere with it — see the next rows |
| **Customer package** (`make release`) | compiled code with no `.py` sources, locked to the standalone edition (cannot become a platform or skip license checks), license server address baked in | bytecode can be decompiled by a determined expert; templates/CSS/JS are readable. Use a contract (no reselling / hosting for others), send updates only yourself, and watch the last-check times in your panel |
| **Backups** | consistent snapshots every 12 h, optional off-server copy over SSH | backups contain customer data and password hashes — protect the backup server like the main one |

**Secrets and hygiene**

- `.env` (secret key, admin password, tokens) is never committed (git-ignored). Keep a private copy; never paste it or any token into chat, tickets or commits.
- A `make export` bundle contains `.env` — delete it after the move.
- Cloudflare token: permission *Zone → DNS → Edit* for the one zone only; rotate it if it ever leaks.
- Use a long admin password (`make admin-password`); one admin account per person (`make admin-user`).
- Keep the server's OS updated (`apt update && apt upgrade`), allow only the ports you need (your SSH port, 80, 443), and prefer SSH keys over passwords. Fail2ban or similar is recommended but not part of this project.
- Production runs with `DJANGO_DEBUG=0`: secure cookies, HSTS, hidden error details.
