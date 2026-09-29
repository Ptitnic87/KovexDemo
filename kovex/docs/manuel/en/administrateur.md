# Administrator manual

This manual is for the person who installs, configures and operates Kovex.

## Design constraint

Kovex is meant to run **entirely locally, on a server with no outbound
access**. No function calls an external service. That has two consequences:
dependencies must be installed before the server is isolated, and nothing in
the product "updates itself".

## Installation

1. Python 3.11 or newer.
2. `pip install -r requirements.lock` — **on a machine with network access**,
   or from an internal package repository. On the isolated server that command
   fails for lack of network; use
   `pip install --no-index --find-links <folder> -r requirements.lock` instead.
   `requirements.lock` pins the exact versions the test suite has run;
   `requirements.txt` only carries lower bounds and is meant for development.
3. Copy `.env.example` to `.env`. `START_KOVEX.bat` creates it automatically if
   it is missing, with a randomly drawn signing key.
4. Run `START_KOVEX.bat`. `STOP_KOVEX.bat` stops both servers.

## Starting without the script

The Windows script only chains two commands. On another system, or to start
the two halves separately:

```
python run_api.py            # API,       http://127.0.0.1:8000
python serve_frontend.py     # interface, http://127.0.0.1:3000
```

Both must run at the same time, in two terminals. Ports and addresses are set
through `KOVEX_API_PORT`, `KOVEX_API_HOST`, `KOVEX_FRONTEND_PORT`,
`KOVEX_FRONTEND_HOST`.

`serve_frontend.py` is not a plain file server: it serves the interface with
`Cache-Control: no-store`. Without that, the browser serves a cached
`index.html` after an update, and the interface stays on the old version even
though the fix is deployed — which sends you looking for the fault in the
wrong place.

On first start an administrator account is created with a **random password
displayed once** in the API console. Write it down. There is no default
account, and that is deliberate: a default password in an identity governance
product is a contradiction.

## Configuration

Everything is set through environment variables in `.env`. Each one is
detailed in `docs/02-parametres.md`. The most structural ones:

| Variable | Effect |
|---|---|
| `PYGIA_SECRET_KEY` | Token signing key. **Unique per installation.** A shared key allows a valid administrator token to be forged elsewhere. |
| `PYGIA_ENV` | `production` refuses dangerous combinations at startup. |
| `PYGIA_AUTH_DISABLED` | Disables authentication. Refused in production. Never enable it on a served instance. |
| `PYGIA_RATE_LIMIT` | Rate limiting. Disabling it removes the only brake on a brute-force attack against the login. |
| `PYGIA_ALLOWED_ORIGINS` | Origins allowed by CORS. |
| `PYGIA_AUDIT_FILE` | Location of the audit trail. |

## Workspaces

A workspace isolates the data, the configuration and the knowledge base of one
client or one environment. Creating a workspace creates its tree; deleting it
archives its knowledge base before erasing the rest.

The audit trail lives **outside the workspaces**. Deleting a workspace must not
erase the history of the decisions taken on it.

## Visual themes

The application opens in the product's own colours. A workspace can carry its
client's: a **theme** is a folder placed under `themes/`, inside the workspace
folder, holding a `theme.json` file and, optionally, a logo.

```
workspaces/<workspace>/themes/<theme-name>/theme.json
workspaces/<workspace>/themes/<theme-name>/logo.png
```

The file declares its labels per language, its colours per display variant, and
the name of its logo:

```json
{
  "libelles": { "fr": "Nom affiché", "en": "Displayed name", "de": "Angezeigter Name" },
  "logo": "logo.png",
  "variantes": {
    "dark":  { "accent-primary": "#6d28d9", "encre-primary": "#c4b5fd" },
    "light": { "accent-primary": "#5b21b6", "encre-primary": "#5b21b6" }
  }
}
```

Three rules, and a refusal always says which one was missed:

- **Both variants are required**, with the same tokens on either side. A theme
  covering only the dark display would leave the light one in the product's
  colours, and the screen would change identity according to a personal
  setting.
- **Only the stylesheet's colour tokens can be redefined**, with a six-digit
  hexadecimal value. A gradient, a translucent veil or a computed mix stay out
  of reach: replacing them with a solid colour would break the effect they
  produce.
- **Contrast is recomputed** on the resulting palette, against the same WCAG AA
  contract as the original palette. A theme that makes a text illegible is
  refused, and the reason names the offending pair with its ratio.

The logo is judged on its bytes, not on its name. Accepted formats are PNG,
JPEG and WebP; the vector format is not, because an SVG is a document that can
carry script and would be served from the application's own origin.

A ready-to-copy template ships with the product, in
`docs/exemples/theme-exemple/`. Its colours belong to no one: the product
carries no third-party brand, and a client's colours are placed on the
installation that needs them.

The theme is chosen from the workspace card, **Workspaces** screen, once the
folder has been placed — never at creation time, where the workspace folder has
just been created and holds nothing yet. Rejected deposits are listed there
with their reason: a misplaced file does not vanish silently.

A client's colours and logos are not shipped with the product. They are placed
on the installation that needs them.

## Mapping the columns of the source files

Kovex presupposes no column name. Four CSV files are expected: identities,
applications, rights, entitlements. For each one, the configuration states
which column carries which identifier.

What must be filled in:

- identities: the person identifier column;
- rights: the right identifier column, and the owning application column;
- applications: the application identifier column;
- entitlements: the two columns linking a person to a right.

An unmapped column is not an error: the checks that depend on it are simply
declared unavailable, and the quality screen shows "—" rather than zero.

The separator and the encoding are set per file. When in doubt about a Windows
export, `;` and `utf-8` are the most common values.

**The simplest way is to declare everything at load time.** In the import
window, the "Check the files" button reads the beginning of each chosen file and
shows what it saw: the encoding that decodes it, the separator that splits it
regularly, the column names and a few rows. The lists then offer only columns
that actually exist, and your choice is written into the workspace
configuration.

A declared column the file does not contain makes the load **fail**, naming that
column, and the referential in place is not replaced. That was the costliest
defect: the loader only renames the columns it finds and says nothing about the
others, so a file of eleven thousand identities loaded without error and
displayed zero identities.

## Accounts and roles

Three roles, with fixed permissions:

| Role | Permissions |
|---|---|
| `admin` | read, write, delete, administer, mining, roles |
| `analyst` | read, write, mining, roles |
| `viewer` | read |

Three roles, but **a single account at installation**. The first start
creates `admin` and nothing else: the demonstration accounts and their
passwords were removed from the source, where they made every installation
computable offline. There is therefore no default password.

- In production, the initial password comes from the
  `PYGIA_BOOTSTRAP_ADMIN_PASSWORD` variable. Without it no account is created
  and nobody can log in: the installation stays closed rather than being
  opened by a credential everyone knows.
- In development, if the variable is absent, a random password is drawn and
  **logged once**, at startup, at warning level. It is never shown again.

If that password was lost — the line scrolls past quickly on a first start —
there is nothing to repair: delete `config/users.json`, set
`PYGIA_BOOTSTRAP_ADMIN_PASSWORD`, restart. The account is recreated with that
password. The file holds only hashes; deleting it loses no governance data.

Reading the **audit trail requires `admin`**. An account that can be audited
does not decide what the audit shows.

Access control works by **default deny**: a route not declared in the policy
is refused, not opened. Adding an endpoint without declaring it makes it
unreachable — that is the intended behaviour.

## Audit trail

The trail records governance decisions: role approval and rejection, mining
runs with their parameters, exports, configuration changes, workspace creation
and deletion.

Three properties to know:

- **It is never rewritten.** Each decision is an appended line. No API route
  allows one to be removed.
- **It is chained.** Each entry carries the fingerprint of the previous one.
  Modifying or deleting a line breaks the chain, and the screen reports it,
  naming the offending entry. That does not make forgery impossible — nothing
  can, on a file someone can reach — it makes it **detectable**.
- **It does not rotate.** It grows. Include it in the backup, and exclude it
  from any automatic cleanup.

Check its integrity periodically: the screen shows the verdict every time it
is opened, with no action from you.

## Backup

To back up:

- `workspaces/` — data, configuration and knowledge bases;
- the audit trail file;
- `config/` — accounts and translation catalogues;
- `.env` — **contains the signing key**. Losing it invalidates every token
  issued; disclosing it allows tokens to be forged.

Not to back up: `output/`, which can be regenerated.

## Troubleshooting

**The application answers 403 on a route.** The route is not declared in the
access policy, or the account lacks the permission. The server log names the
route to declare.

**Mining finds no role.** Check the number of usable entitlements in the
Quality tab first. An empty matrix produces zero roles without raising an
error.

**A quality check shows "—".** The matching column is not mapped in the
workspace configuration.

**Frontend changes do not take effect.** The browser is serving a cached
version. Resources carry a version number in their URL; a forced reload is
enough.

**The audit trail is reported as broken.** The file has been modified outside
the application. The screen names the entry from which the history can no
longer be relied on. Keep the file as it is: it is evidence.
