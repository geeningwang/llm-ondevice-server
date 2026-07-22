# Model Weight Files (Not in Git)

The following weight files are served from the `www/` directory but excluded from the git repository due to their size. To recover the deployment on a new machine, download these files into the `www/` directory.

## Files

| Filename | Size | Description |
|----------|------|-------------|
| `gemma-4-E2B-it.litertlm` | 2.5 GB | Gemma 4 E2B Instruct (LiteRT LM format) |
| `gemma-4-E4B-it.litertlm` | 3.5 GB | Gemma 4 E4B Instruct (LiteRT LM format) |
| `gemma3-1b-it-int4.task` | 529 MB | Gemma 3 1B Instruct INT4 (MediaPipe task format) |

## Serving URLs

Once placed in `www/`, these files are available at:

- `https://<host>/gemma-4-E2B-it.litertlm`
- `https://<host>/gemma-4-E4B-it.litertlm`
- `https://<host>/gemma3-1b-it-int4.task`
