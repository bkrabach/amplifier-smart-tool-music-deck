# Registering your own Spotify app

music-deck ships no credentials. It runs under **your** Spotify app, using
**your** client ID, and stores only **your** token. This page is the whole
setup, in plain words.

It takes about ten minutes, and it needs two things you may not have yet: a
Spotify account with **Premium**, and a registered app in Spotify's developer
dashboard.

---

## What you are signing up for

A newly registered Spotify app lives in **Development Mode**, and it stays
there. Development Mode is Spotify's sandbox: deliberately small, and not a
foundation for anything that has to grow. Three facts decide whether music-deck
is usable for you at all.

1. **The app owner must hold Spotify Premium.** If your Premium lapses, the app
   stops working, and starts again when you resubscribe.
2. **Five authorised users, maximum.** Everyone who uses the app must be added
   to its allowlist by name. Someone who is not on the allowlist can still sign
   in — and then every request they make comes back `403`. That is the only
   signal you get.
3. **The quota is shared and it is not published.** Requests are grouped into
   buckets with limits Spotify does not disclose and reserves the right to
   change. Registering more apps does not buy you more room: since July 2026 the
   quota is counted per developer account, not per client ID.

There is no realistic path out of Development Mode for a personal tool. Extended
quota requires an organisation, a registered business, a launched service, and
roughly a quarter of a million monthly users.

---

## Step 1 — Have Premium

Sign in to Spotify and confirm the account you will own the app with has an
active Premium subscription. This is the account that owns the app, not
necessarily the account that listens.

## Step 2 — Register the app

1. Go to <https://developer.spotify.com/dashboard> and sign in.
2. Choose **Create app**.
3. Give it any name and description. Neither is shown to anyone but you.
4. For **Which API/SDKs are you planning to use**, tick **Web API**.
5. Set the redirect URI — see the next step, it is the part people get wrong.
6. Accept the terms and save.

## Step 3 — Set the redirect URI correctly

This is the one field that will silently cost you an afternoon.

Enter exactly:

```
http://127.0.0.1
```

Three rules are being obeyed there, all enforced by Spotify since 2025:

- **`localhost` is banned.** Spelling it `http://localhost:8080` is rejected,
  even though it means the same thing to your machine. Use the IP literal.
- **HTTP is only allowed for a loopback address.** `127.0.0.1` (or `[::1]` for
  IPv6) is a loopback address, so plain `http` is fine here and only here.
- **Leave the port off.** Registering a loopback literal with no port lets
  music-deck add a freshly-chosen port at sign-in time, which is exactly what it
  does — it never squats on a fixed port. This is supported *only* for loopback
  literals.

## Step 4 — Copy the client ID

Open the app's settings and copy the **Client ID**. It is not a secret in the
usual sense — PKCE is designed so that a public client can hold it — but it is
yours, and music-deck never bundles one.

Do **not** copy the client secret. music-deck never asks for one and never
stores one. If a tool asks you for a Spotify client secret, it is not doing
PKCE.

## Step 5 — Tell music-deck about it

Either set the environment variable:

```
export MUSIC_DECK_CLIENT_ID=<the client id you copied>
```

or write it once into your config file at
`~/.config/music-deck/config.json`:

```json
{"client_id": "<the client id you copied>"}
```

Then confirm music-deck can see it:

```
music-deck check
```

`check` reports what it found and exits 0 either way. Seeing
`"client_id": {"present": false, ...}` is a report, not a crash.

## Step 6 — Add yourself to the allowlist

In the dashboard, open **User Management** and add the Spotify account (name and
email) of every person who will use the tool — including yourself. Up to five.

Skipping this is the single most common cause of a `403` that looks like a bug
in the tool. music-deck reports it as `not_allowlisted`, and this page is the
remedy.

## Step 7 — Sign in

```
music-deck login
```

This opens your browser, you approve the scopes, and the token lands at
`~/.local/state/music-deck/token.json` with permissions `0600` — readable by
you and nobody else.

---

## What to expect afterwards

**You will have to sign in again, roughly twice a year.** Refresh tokens issued
to dashboard-registered apps last six months from the moment you authorised, and
refreshing an access token does *not* extend that. When the wall is hit,
music-deck refuses with `reauthorization_required` and names
`music-deck login` as the remedy. `music-deck check` reports how much of the six
months is left before you hit it.

**Access tokens last one hour** and music-deck refreshes them for you.

**Playback needs a device that is already playing.** music-deck produces no
audio of its own. Start something on your phone, your desktop app, or a speaker,
and music-deck can then pause it, skip it, change its volume, or move it
elsewhere. With nothing playing, playback verbs refuse with `no_active_device`.

**You cannot check for Premium in advance.** Spotify removed the field that used
to say whether an account is Premium, so music-deck learns it the same way you
would: a playback write comes back `403`, and it reports `premium_required`.

## Removing your data

```
music-deck disconnect
```

deletes the token and every locally cached byte of Spotify content, and reports
what it deleted. Revoke the app itself at
<https://www.spotify.com/account/apps/>.
