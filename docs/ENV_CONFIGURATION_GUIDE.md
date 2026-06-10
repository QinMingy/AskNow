# `.env` Configuration Guide

AskNow loads local configuration from the repository-root `.env` file.
Operating-system, terminal, container, and cloud-platform environment variables
remain supported.

Configuration priority:

```text
process/system environment variable > repository .env > code default
```

This means a cloud deployment can inject secrets normally, while local
development can keep them together in one ignored file.

## Local setup

The repository includes `.env.example`. Copy its values into the ignored
`.env` file and fill only the providers you use:

```dotenv
DEEPSEEK_API_KEY=
HUGGINGFACE_API_KEY=

# Enable after filling the Volcengine credentials.
STREAM_PROCESSOR=volcengine
VOLCENGINE_APP_ID=
VOLCENGINE_ACCESS_TOKEN=
VOLCENGINE_RESOURCE_ID=volc.bigasr.sauc.duration
```

Run `start_demo.bat` normally after editing `.env`. No PowerShell `$env:...`
commands are required.

## Environment-variable compatibility

Existing variables are not overwritten by `.env`. For example:

```powershell
$env:STREAM_PROCESSOR="funasr"
.\start_demo.bat
```

Even if `.env` contains `STREAM_PROCESSOR=volcengine`, the terminal value
`funasr` wins for that process.

## Security

- `.env` is ignored by Git and must remain local.
- `.env.example` contains names and non-secret defaults only.
- Never place real tokens in `.env.example`, documentation, commits, or chat.
- Cloud deployments should use the platform's secret/environment-variable
  manager instead of copying the local `.env` file.
