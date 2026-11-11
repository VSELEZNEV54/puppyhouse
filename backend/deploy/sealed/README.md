# Sealed settings

`<NAME>.enc` here is a value for the server's `api.env`, encrypted with the server's public key
(`https://дом-щенков.рф/dsh-sealed-key.txt`): the repository is public, only this server can read it.
`deploy.sh` decrypts it into `/etc/domshchenkov/sealed.env`, which wins over `api.env`, recreates the API and the
worker and resends the notifications that failed in the last 24 hours. Allowed names and how to seal a value:
`backend/deploy/sealed.sh`. Remove a file to drop the value.
