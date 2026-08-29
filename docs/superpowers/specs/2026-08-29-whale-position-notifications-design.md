# Whale Position Notifications

## Goal

Show a native Windows system notification when a watched whale opens or closes
a Hyperliquid position discovered through Hyperdash.

## Scope

The feature applies only to Hyperdash `position` observations. It sends no
notification during the first successful refresh after the process starts;
that refresh establishes the baseline. Each later successful refresh can emit
one opening or closing notification per wallet and coin.

## Position observation and comparison

The Hyperdash adapter will maintain an in-memory snapshot keyed by
`(wallet_address, symbol)`. On every refresh it discovers qualifying wallets
as it does today, and also rechecks wallets that were active in its prior
snapshot. Rechecking those wallets prevents an absent delta result from being
mistaken for a closed position.

After a coin's wallet states have been fetched successfully, the adapter
compares the current non-zero positions with the prior snapshot:

- a key present only in the current snapshot is an `open` change;
- a key present only in the prior snapshot is a `close` change.

The first complete snapshot is retained without producing changes. A failed
or incomplete wallet request must not remove an existing position or create a
close notification. State is process-local: restarting the ingestion process
creates a fresh baseline, by design.

## Notifications

A small notification boundary receives normalized position changes from the
ingestion scheduler after the associated events have been stored. Its Windows
implementation sends a native toast on the local Windows desktop. Toasts
identify the action ("Whale opened position" or "Whale closed position"),
symbol, LONG/SHORT direction, USD position value, and a shortened wallet
address.

The notification implementation is optional at runtime. Unsupported platforms
or delivery errors are logged and do not interrupt ingestion or persistence.
No third-party account, credential, trading API, or order-placement capability
is introduced.

## Integration

`poll_once` continues to return the number of persisted records. After a
successful poll it consumes any position changes exposed by an adapter and
hands them to the notifier. Other adapters expose no changes and retain their
current behavior.

The normal `hello-coin ingest run` and combined `hello-coin run` commands
therefore enable the notifications automatically when run on Windows. The
dashboard remains read-only and does not create notifications.

## Error handling

- A first snapshot or empty successful snapshot emits no toast.
- Per-coin discovery failures remain isolated and leave that coin's existing
  snapshot unchanged.
- A failed previous-position recheck prevents closure detection for that
  wallet during that refresh.
- A failed toast is logged and does not retry or stop the polling loop.

## Testing and acceptance criteria

Offline tests cover the following behavior:

- the first successful refresh only establishes the baseline;
- a later newly observed position creates one opening notification;
- an observed prior position that is confirmed absent creates one closing
  notification;
- failed or incomplete reads cannot cause false closure notifications;
- notification content includes the action, coin, side, USD value, and
  abbreviated wallet;
- notifier errors and non-Windows execution leave ingestion running; and
- the existing offline suite remains green.
