# Frontend deployment

The frontend is deployed by GitHub Actions instead of building on the small server.

## Required GitHub secrets

Set these in GitHub repository settings: `Settings` -> `Secrets and variables` -> `Actions`.

- `SERVER_HOST`: server IP or domain, for example `101.43.51.64`
- `SERVER_USER`: SSH user, for example `ubuntu`
- `SERVER_SSH_KEY`: private key that can SSH into the server
- `SERVER_PORT`: SSH port, optional. Defaults to `22`

## SSH key setup

Create a deploy key on your local machine:

```bash
ssh-keygen -t ed25519 -C "github-actions-chatbot-deploy" -f ./chatbot_deploy_key
```

Add the public key to the server:

```bash
ssh-copy-id -i ./chatbot_deploy_key.pub ubuntu@101.43.51.64
```

Put the private key content into the GitHub secret:

```bash
cat ./chatbot_deploy_key
```

Use that output as `SERVER_SSH_KEY`.

## How it works

Pushing frontend changes to `yql_dev` triggers `.github/workflows/deploy-frontend.yml`.

The workflow:

1. Installs frontend dependencies with `npm ci`.
2. Builds `frontend/build` on GitHub-hosted runners.
3. Uploads the built files to `/srv/chatbot/frontend/build.next`.
4. Replaces `/srv/chatbot/frontend/build` only after `build.next/index.html` exists.
5. Verifies `http://SERVER_HOST/login`.

Nginx continues to serve `/srv/chatbot/frontend/build`, so the server no longer needs to run `npm run build`.
