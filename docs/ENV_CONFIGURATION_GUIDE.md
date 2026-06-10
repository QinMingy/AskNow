# `.env` Third-Party Integration Guide

AskNow loads third-party integration information from the repository-root
`.env` file. This includes API keys, access tokens, App IDs, Resource IDs,
third-party API URLs, and provider model identifiers. Internal AskNow runtime
configuration in `.env` is ignored.

Third-party value priority:

```text
process/system value > repository .env value > code default
```

Provider selection, worker counts, timeouts, retry policies, buffer sizes, and
other internal runtime settings use code defaults.

## Local setup

The repository includes `.env.example`. Copy its values into the ignored
`.env` file and fill only the services you use:

```dotenv
DEEPSEEK_API_KEY=
HUGGINGFACE_API_KEY=
VOLCENGINE_ACCESS_TOKEN=
VOLCENGINE_APP_ID=
VOLCENGINE_RESOURCE_ID=volc.bigasr.sauc.duration
MODEL_API_KEY=
```

Run `start_demo.bat` normally after editing `.env`.

## Internal runtime configuration

Internal values such as `STREAM_PROCESSOR`, worker counts, backpressure
thresholds, and retry policies are not loaded from `.env`. They remain code
defaults so the local third-party configuration file stays focused.

## Security

- `.env` is ignored by Git and must remain local.
- `.env.example` contains third-party field names and non-secret defaults,
  never secret values.
- Never place real tokens in `.env.example`, documentation, commits, or chat.
- Cloud deployments should use the platform's secret/environment-variable
  manager instead of copying the local `.env` file.
