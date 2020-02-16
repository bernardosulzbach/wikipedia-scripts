# Wikipedia scripts

Some of my scripts for editing the Wikipedia.

## Open Watchlist

This Python 3 script logs in to Wikipedia and opens the first few unseen pages from your watchlist.

It uses the credentials from a `secrets.json` file with the following structure.

```json
{
  "username": "...",
  "password": "..."
}
```

It requires Firefox and [geckodriver](https://github.com/mozilla/geckodriver/releases) to work.
